import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../config/task_types.dart';
import '../services/api_service.dart';
import '../services/uncensored_notifier.dart';
import '../services/websocket_service.dart';
import '../models/mission.dart';
import '../theme/design_system.dart';

// ─── Chat message model ───────────────────────────────────────────────────────

enum _MsgType { user, working, bea }

class _ChatMsg {
  final String localId;
  final _MsgType type;
  final String text;
  final Mission? mission;
  final String? missionId;
  final List<String> steps;
  final DateTime ts;

  _ChatMsg({
    required this.localId,
    required this.type,
    required this.text,
    this.mission,
    this.missionId,
    List<String>? steps,
    DateTime? ts,
  })  : steps = steps != null ? List.unmodifiable(steps) : const [],
        ts = ts ?? DateTime.now();

  _ChatMsg copyWith({
    String? text,
    _MsgType? type,
    Mission? mission,
    List<String>? steps,
  }) =>
      _ChatMsg(
        localId: localId,
        type: type ?? this.type,
        text: text ?? this.text,
        mission: mission ?? this.mission,
        missionId: missionId,
        steps: steps ?? List<String>.from(this.steps),
        ts: ts,
      );
}

// ─── Mission Screen ───────────────────────────────────────────────────────────

class MissionScreen extends StatefulWidget {
  const MissionScreen({super.key});

  @override
  State<MissionScreen> createState() => _MissionScreenState();
}

class _MissionScreenState extends State<MissionScreen> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  final _controller  = TextEditingController();
  final _focus       = FocusNode();
  final _scrollCtrl  = ScrollController();
  final List<_ChatMsg> _messages = [];

  String? _activeMid;
  bool    _sending = false;
  String  _selectedTaskKey = 'libre';

  StreamSubscription<Map<String, dynamic>>? _wsSub;
  StreamSubscription<Map<String, dynamic>>? _sseSub;
  Timer? _pollTimer;

  int _msgCounter = 0;
  String _nextId() => 'msg_${_msgCounter++}';

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _subscribeWs();
      _loadHistory();
    });
  }

  @override
  void dispose() {
    _wsSub?.cancel();
    _sseSub?.cancel();
    _pollTimer?.cancel();
    _controller.dispose();
    _focus.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  // ── Load chat history ─────────────────────────────────────────────────────

  void _loadHistory() {
    if (!mounted) return;
    final api = context.read<ApiService>();
    final sorted = [...api.missions]
      ..sort((a, b) => a.createdAt.compareTo(b.createdAt));
    final recent = sorted.length > 30
        ? sorted.sublist(sorted.length - 30)
        : sorted;

    final msgs = <_ChatMsg>[];
    for (final m in recent) {
      // User bubble
      msgs.add(_ChatMsg(
        localId: _nextId(),
        type: _MsgType.user,
        text: m.userInput,
        missionId: m.id,
        ts: _parseTs(m.createdAt),
      ));
      // Response bubble
      if (m.isTerminal) {
        final output = m.finalOutput.isNotEmpty
            ? m.finalOutput
            : m.planSummary.isNotEmpty
                ? m.planSummary
                : m.isFailed
                    ? '❌ Mission échouée'
                    : '✓ Mission terminée';
        msgs.add(_ChatMsg(
          localId: _nextId(),
          type: _MsgType.bea,
          text: output,
          mission: m,
          missionId: m.id,
          ts: _parseTs(m.completedAt ?? m.createdAt),
        ));
      } else if (m.isActive) {
        msgs.add(_ChatMsg(
          localId: _nextId(),
          type: _MsgType.working,
          text: 'Bea travaille...',
          missionId: m.id,
          ts: _parseTs(m.createdAt),
        ));
        // Track first active mission
        _activeMid ??= m.id;
      }
    }

    if (msgs.isNotEmpty) {
      setState(() => _messages.addAll(msgs));
      _scrollToBottom(instant: true);
    }

    // Resume tracking active mission from history
    if (_activeMid != null) {
      _startLiveTracking(_activeMid!);
    }
  }

  // ── WebSocket subscription ────────────────────────────────────────────────

  void _subscribeWs() {
    if (!mounted) return;
    final ws = context.read<WebSocketService>();
    _wsSub = ws.stream.listen(_onWsEvent, onError: (_) {});
  }

  void _onWsEvent(Map<String, dynamic> event) {
    final type = event['type']?.toString() ?? '';
    final mid  = event['mission_id']?.toString()
        ?? event['id']?.toString()
        ?? '';
    if (mid.isEmpty || mid != _activeMid) return;

    switch (type) {
      case 'mission_update':
      case 'task_progress':
      case 'agent_thinking':
        final step = event['step']?.toString()
            ?? event['message']?.toString()
            ?? event['phase']?.toString()
            ?? event['agent']?.toString()
            ?? '';
        if (step.isNotEmpty) _addLiveStep(mid, step);
      case 'mission_done':
        _fetchAndFinalize(mid);
      case 'mission_failed':
        _onMissionFailed(mid, event['error']?.toString());
    }
  }

  void _addLiveStep(String mid, String step) {
    if (!mounted) return;
    final idx = _messages.indexWhere(
        (m) => m.missionId == mid && m.type == _MsgType.working);
    if (idx < 0) return;
    final cur  = _messages[idx];
    final next = cur.copyWith(steps: [...cur.steps, step]);
    setState(() => _messages[idx] = next);
    _scrollToBottom();
  }

  // ── Send mission ──────────────────────────────────────────────────────────

  Future<void> _send() async {
    final input = _controller.text.trim();
    if (input.isEmpty || _sending || _activeMid != null) return;

    final goal = (_selectedTaskKey != 'libre')
        ? '[$_selectedTaskKey] $input'
        : input;

    _controller.clear();
    _focus.unfocus();
    setState(() => _sending = true);

    // Add user bubble immediately
    final userBubble = _ChatMsg(
      localId: _nextId(),
      type: _MsgType.user,
      text: input,
    );
    setState(() => _messages.add(userBubble));
    _scrollToBottom();

    final api = context.read<ApiService>();
    // Build conversation context from recent messages
    String _convCtx = '';
    final _recentMsgs = _messages.where((m) => m.type != _MsgType.working).toList();
    if (_recentMsgs.length > 1) {
      _convCtx = _recentMsgs.reversed.take(6).toList().reversed
        .map((m) => m.type == _MsgType.user ? 'User: ${m.text}' : 'Bea: ${m.text.length > 200 ? m.text.substring(0, 200) : m.text}')
        .join('\n');
    }
    final result = await api.submitMission(goal, conversationContext: _convCtx.isNotEmpty ? _convCtx : null);
    if (!mounted) return;

    if (result.ok && result.data != null) {
      final m = result.data!;
      final workBubble = _ChatMsg(
        localId: _nextId(),
        type: _MsgType.working,
        text: 'Bea travaille...',
        missionId: m.id,
      );
      setState(() {
        _messages.add(workBubble);
        _activeMid = m.id;
        _sending = false;
      });
      _scrollToBottom();
      _startLiveTracking(m.id);
    } else {
      final errBubble = _ChatMsg(
        localId: _nextId(),
        type: _MsgType.bea,
        text: '❌ ${result.error ?? 'Erreur lors de la soumission de la mission.'}',
      );
      setState(() {
        _messages.add(errBubble);
        _sending = false;
      });
      _scrollToBottom();
    }
  }

  // ── Live tracking ─────────────────────────────────────────────────────────

  void _startLiveTracking(String mid) {
    _sseSub?.cancel();
    _pollTimer?.cancel();

    final api = context.read<ApiService>();

    // SSE stream for real-time steps
    _sseSub = api.streamMissionLogs(mid).listen(
      (event) {
        if (!mounted) return;
        // Extract step label
        final step = event['step']?.toString()
            ?? event['message']?.toString()
            ?? event['phase']?.toString()
            ?? '';
        if (step.isNotEmpty) _addLiveStep(mid, step);

        // Terminal event from SSE
        final evtType = event['event']?.toString() ?? '';
        if (evtType == 'done' || evtType == 'completed') {
          _sseSub?.cancel();
          _fetchAndFinalize(mid);
        } else if (evtType == 'failed' || evtType == 'error') {
          _sseSub?.cancel();
          _onMissionFailed(mid, event['error']?.toString());
        }
      },
      onError: (_) {/* SSE failed — polling handles it */},
      onDone: () {
        // SSE stream closed — confirm via poll
        if (_activeMid == mid) _pollForCompletion(mid);
      },
    );

    // Polling fallback every 8s
    _pollTimer = Timer.periodic(const Duration(seconds: 8), (_) {
      if (_activeMid == mid) _pollForCompletion(mid);
    });
  }

  Future<void> _pollForCompletion(String mid) async {
    if (!mounted) return;
    final api = context.read<ApiService>();
    final result = await api.fetchMissionDetail(mid);
    if (!mounted) return;
    if (result.ok && result.data != null) {
      final m = result.data!;
      if (m.isTerminal) {
        _pollTimer?.cancel();
        _sseSub?.cancel();
        if (m.isDone) {
          _onMissionCompleted(m);
        } else {
          _onMissionFailed(mid,
              m.finalOutput.isNotEmpty ? m.finalOutput : null);
        }
      }
    }
  }

  Future<void> _fetchAndFinalize(String mid) async {
    _pollTimer?.cancel();
    _sseSub?.cancel();
    if (!mounted) return;
    final api = context.read<ApiService>();
    final result = await api.fetchMissionDetail(mid);
    if (!mounted) return;
    if (result.ok && result.data != null) {
      final m = result.data!;
      if (m.isDone) {
        _onMissionCompleted(m);
      } else if (m.isFailed || m.isRejected) {
        _onMissionFailed(mid,
            m.finalOutput.isNotEmpty ? m.finalOutput : m.status);
      } else {
        // Still running — restart polling
        _pollTimer = Timer.periodic(const Duration(seconds: 8), (_) {
          if (_activeMid == mid) _pollForCompletion(mid);
        });
      }
    }
  }

  void _onMissionCompleted(Mission m) {
    if (!mounted) return;
    final idx = _messages.indexWhere(
        (msg) => msg.missionId == m.id && msg.type == _MsgType.working);
    if (idx < 0) return;

    final output = m.finalOutput.isNotEmpty
        ? m.finalOutput
        : m.planSummary.isNotEmpty
            ? m.planSummary
            : '✓ Mission terminée';

    final beaBubble = _ChatMsg(
      localId: _messages[idx].localId,
      type: _MsgType.bea,
      text: output,
      mission: m,
      missionId: m.id,
      steps: _messages[idx].steps,
      ts: _messages[idx].ts,
    );

    setState(() {
      _messages[idx] = beaBubble;
      _activeMid = null;
    });
    _scrollToBottom();
  }

  void _onMissionFailed(String mid, String? errorMsg) {
    if (!mounted) return;
    final idx = _messages.indexWhere(
        (m) => m.missionId == mid && m.type == _MsgType.working);
    if (idx < 0) return;

    final errBubble = _messages[idx].copyWith(
      type: _MsgType.bea,
      text: '❌ ${errorMsg ?? 'La mission a échoué.'}',
    );
    setState(() {
      _messages[idx] = errBubble;
      _activeMid = null;
    });
    _pollTimer?.cancel();
    _sseSub?.cancel();
    _scrollToBottom();
  }

  // ── New mission ───────────────────────────────────────────────────────────

  void _newMission() {
    showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: JvColors.card,
        title: const Text('Nouvelle conversation',
            style: TextStyle(color: JvColors.textPrim, fontSize: 16, fontWeight: FontWeight.w700)),
        content: const Text(
          'Démarrer une nouvelle conversation effacera l\'affichage actuel.\nL\'historique complet reste disponible dans l\'onglet Historique.',
          style: TextStyle(color: JvColors.textSec, fontSize: 13, height: 1.5),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Annuler', style: TextStyle(color: JvColors.textMut)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: JvColors.cyan,
              foregroundColor: Colors.black,
            ),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Nouvelle mission'),
          ),
        ],
      ),
    ).then((confirmed) {
      if (confirmed == true && mounted) {
        _pollTimer?.cancel();
        _sseSub?.cancel();
        setState(() {
          _messages.clear();
          _activeMid = null;
          _selectedTaskKey = 'libre';
        });
      }
    });
  }

  // ── Open a specific mission from drawer ────────────────────────────────────

  void _openMissionInChat(Mission m) {
    // Close drawer
    _scaffoldKey.currentState?.closeDrawer();

    // Clear current chat and show this mission
    _pollTimer?.cancel();
    _sseSub?.cancel();

    final msgs = <_ChatMsg>[];
    // User bubble
    msgs.add(_ChatMsg(
      localId: _nextId(),
      type: _MsgType.user,
      text: m.userInput,
      missionId: m.id,
      ts: _parseTs(m.createdAt),
    ));
    // Response bubble
    if (m.isTerminal) {
      final output = m.finalOutput.isNotEmpty
          ? m.finalOutput
          : m.planSummary.isNotEmpty
              ? m.planSummary
              : m.isFailed
                  ? '❌ Mission échouée'
                  : '✓ Mission terminée';
      msgs.add(_ChatMsg(
        localId: _nextId(),
        type: _MsgType.bea,
        text: output,
        mission: m,
        missionId: m.id,
        ts: _parseTs(m.completedAt ?? m.createdAt),
      ));
    } else if (m.isActive) {
      msgs.add(_ChatMsg(
        localId: _nextId(),
        type: _MsgType.working,
        text: 'Bea travaille...',
        missionId: m.id,
        ts: _parseTs(m.createdAt),
      ));
    }

    setState(() {
      _messages
        ..clear()
        ..addAll(msgs);
      _activeMid = m.isActive ? m.id : null;
      _selectedTaskKey = 'libre';
    });

    if (_activeMid != null) {
      _startLiveTracking(_activeMid!);
    }
    _scrollToBottom(instant: true);
  }

  // ── Scroll helpers ────────────────────────────────────────────────────────

  void _scrollToBottom({bool instant = false}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollCtrl.hasClients) return;
      final target = _scrollCtrl.position.maxScrollExtent;
      if (instant) {
        _scrollCtrl.jumpTo(target);
      } else {
        _scrollCtrl.animateTo(
          target,
          duration: const Duration(milliseconds: 280),
          curve: Curves.easeOut,
        );
      }
    });
  }

  // ── Build ─────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final isUncensored = context.watch<UncensoredModeNotifier>().isUncensored;
    final ws = context.watch<WebSocketService>();
    final locked = _sending || _activeMid != null;
    final hint = (kTaskTypes.firstWhere(
          (t) => t['key'] == _selectedTaskKey,
          orElse: () => kTaskTypes.first,
        )['hint'] as String);

    return Scaffold(
      key: _scaffoldKey,
      drawer: _MissionHistoryDrawer(
        missions: context.watch<ApiService>().missions,
        activeMissionId: _activeMid,
        onSelectMission: _openMissionInChat,
        onNewMission: _newMission,
      ),
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.menu_rounded, size: 22),
          tooltip: 'Historique',
          onPressed: () => _scaffoldKey.currentState?.openDrawer(),
        ),
        title: const Text('BEA'),
        actions: [
          _WsDot(state: ws.connectionState),
          const SizedBox(width: 2),
          IconButton(
            icon: const Icon(Icons.add_circle_outline, size: 22),
            tooltip: 'Nouvelle mission',
            onPressed: _newMission,
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: Column(
        children: [
          // Uncensored banner
          if (isUncensored)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              color: const Color(0xFFf43f5e).withValues(alpha: 0.12),
              child: const Row(children: [
                Text('🔓', style: TextStyle(fontSize: 11)),
                SizedBox(width: 6),
                Text('Uncensored · Local only',
                    style: TextStyle(
                        color: Color(0xFFf43f5e),
                        fontSize: 11,
                        fontWeight: FontWeight.w700)),
              ]),
            ),

          // Chat messages
          Expanded(
            child: _messages.isEmpty
                ? const _EmptyHint()
                : ListView.builder(
                    controller: _scrollCtrl,
                    padding: const EdgeInsets.only(
                        top: 16, bottom: 8, left: 12, right: 12),
                    itemCount: _messages.length,
                    itemBuilder: (ctx, i) {
                      final msg = _messages[i];
                      return switch (msg.type) {
                        _MsgType.user    => _UserBubble(msg: msg),
                        _MsgType.working => _WorkingBubble(msg: msg, key: ValueKey(msg.localId)),
                        _MsgType.bea  => _BeaBubble(msg: msg, key: ValueKey(msg.localId)),
                      };
                    },
                  ),
          ),

          // Mission type selector
          _MissionTypeBar(
            selected: _selectedTaskKey,
            onSelect: (k) => setState(() => _selectedTaskKey = k),
          ),

          // Chat input
          _ChatInput(
            controller: _controller,
            focus: _focus,
            locked: locked,
            isUncensored: isUncensored,
            hint: locked ? 'Bea travaille...' : hint,
            onSend: _send,
          ),
        ],
      ),
    );
  }
}

// ─── User bubble ──────────────────────────────────────────────────────────────

class _UserBubble extends StatelessWidget {
  final _ChatMsg msg;
  const _UserBubble({required this.msg, super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12, left: 48),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.end,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Flexible(
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: JvColors.cyan.withValues(alpha: 0.12),
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(16),
                  topRight: Radius.circular(16),
                  bottomLeft: Radius.circular(16),
                  bottomRight: Radius.circular(4),
                ),
                border:
                    Border.all(color: JvColors.cyan.withValues(alpha: 0.28)),
              ),
              child: SelectableText(
                msg.text,
                style: const TextStyle(
                    color: JvColors.textPrim, fontSize: 14, height: 1.5),
              ),
            ),
          ),
          const SizedBox(width: 8),
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: JvColors.cyan.withValues(alpha: 0.18),
              shape: BoxShape.circle,
              border: Border.all(color: JvColors.cyan.withValues(alpha: 0.4)),
            ),
            child: const Icon(Icons.person, size: 16, color: JvColors.cyan),
          ),
        ],
      ),
    );
  }
}

// ─── Working bubble (animated) ────────────────────────────────────────────────

class _WorkingBubble extends StatefulWidget {
  final _ChatMsg msg;
  const _WorkingBubble({required this.msg, super.key});

  @override
  State<_WorkingBubble> createState() => _WorkingBubbleState();
}

class _WorkingBubbleState extends State<_WorkingBubble>
    with SingleTickerProviderStateMixin {
  late final AnimationController _anim;
  bool _stepsExpanded = true;

  @override
  void initState() {
    super.initState();
    _anim = AnimationController(
        vsync: this, duration: const Duration(milliseconds: 900))
      ..repeat(reverse: true);
  }

  @override
  void dispose() {
    _anim.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final steps = widget.msg.steps;
    return Padding(
      padding: const EdgeInsets.only(bottom: 12, right: 48),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _BeaAvatar(),
          const SizedBox(width: 8),
          Flexible(
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: JvColors.card,
                borderRadius: const BorderRadius.only(
                  topLeft: Radius.circular(4),
                  topRight: Radius.circular(16),
                  bottomLeft: Radius.circular(16),
                  bottomRight: Radius.circular(16),
                ),
                border: Border.all(color: JvColors.border),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Animated dots + label
                  Row(children: [
                    AnimatedBuilder(
                      animation: _anim,
                      builder: (_, __) => Row(
                        children: List.generate(3, (i) {
                          final phase = (i * 0.3);
                          final v = (_anim.value - phase).clamp(0.0, 1.0);
                          return Padding(
                            padding: const EdgeInsets.only(right: 4),
                            child: Opacity(
                              opacity: 0.25 + v * 0.75,
                              child: Container(
                                width: 7,
                                height: 7,
                                decoration: const BoxDecoration(
                                  color: JvColors.cyan,
                                  shape: BoxShape.circle,
                                ),
                              ),
                            ),
                          );
                        }),
                      ),
                    ),
                    const SizedBox(width: 8),
                    const Text('Bea travaille...',
                        style: TextStyle(
                            color: JvColors.cyan,
                            fontSize: 12,
                            fontWeight: FontWeight.w600)),
                  ]),

                  // Live steps
                  if (steps.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    GestureDetector(
                      onTap: () =>
                          setState(() => _stepsExpanded = !_stepsExpanded),
                      child: Row(children: [
                        Text(
                          '${steps.length} étape${steps.length > 1 ? "s" : ""}',
                          style: const TextStyle(
                              color: JvColors.textMut, fontSize: 11),
                        ),
                        const SizedBox(width: 4),
                        Icon(
                          _stepsExpanded
                              ? Icons.expand_less
                              : Icons.expand_more,
                          size: 14,
                          color: JvColors.textMut,
                        ),
                      ]),
                    ),
                    if (_stepsExpanded) ...[
                      const SizedBox(height: 6),
                      ...steps.map((s) => Padding(
                            padding: const EdgeInsets.only(bottom: 3),
                            child: Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  const Text('▸ ',
                                      style: TextStyle(
                                          color: JvColors.cyan, fontSize: 10)),
                                  Expanded(
                                    child: Text(s,
                                        style: const TextStyle(
                                            color: JvColors.textSec,
                                            fontSize: 11,
                                            height: 1.4)),
                                  ),
                                ]),
                          )),
                    ],
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Bea response bubble ───────────────────────────────────────────────────

class _BeaBubble extends StatefulWidget {
  final _ChatMsg msg;
  const _BeaBubble({required this.msg, super.key});

  @override
  State<_BeaBubble> createState() => _BeaBubbleState();
}

class _BeaBubbleState extends State<_BeaBubble> {
  bool _stepsExpanded = false;
  bool _copied = false;

  @override
  Widget build(BuildContext context) {
    final m = widget.msg;
    final mission = m.mission;
    final isError = m.text.startsWith('❌');
    final accentColor = isError ? JvColors.red : JvColors.cyan;
    final hasProcess = m.steps.isNotEmpty ||
        (mission != null && mission.planSteps.isNotEmpty);

    return Padding(
      padding: const EdgeInsets.only(bottom: 16, right: 48),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _BeaAvatar(),
          const SizedBox(width: 8),
          Flexible(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Main bubble
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: JvColors.card,
                    borderRadius: const BorderRadius.only(
                      topLeft: Radius.circular(4),
                      topRight: Radius.circular(16),
                      bottomLeft: Radius.circular(16),
                      bottomRight: Radius.circular(16),
                    ),
                    border: Border.all(
                        color: accentColor.withValues(alpha: 0.22)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Response text — no truncation, fully selectable
                      SelectableText(
                        m.text,
                        style: TextStyle(
                          color: isError ? JvColors.red : JvColors.textPrim,
                          fontSize: 14,
                          height: 1.65,
                        ),
                      ),

                      // Collapsible process section
                      if (hasProcess) ...[
                        const SizedBox(height: 10),
                        Divider(
                            height: 1,
                            color: JvColors.border.withValues(alpha: 0.6)),
                        const SizedBox(height: 8),
                        GestureDetector(
                          onTap: () => setState(
                              () => _stepsExpanded = !_stepsExpanded),
                          child: Row(children: [
                            Icon(Icons.account_tree_outlined,
                                size: 12, color: JvColors.textMut),
                            const SizedBox(width: 5),
                            Text(
                              _stepsExpanded
                                  ? 'Masquer le processus'
                                  : 'Voir le processus',
                              style: const TextStyle(
                                  color: JvColors.textMut, fontSize: 11),
                            ),
                            const SizedBox(width: 4),
                            Icon(
                              _stepsExpanded
                                  ? Icons.expand_less
                                  : Icons.expand_more,
                              size: 13,
                              color: JvColors.textMut,
                            ),
                          ]),
                        ),
                        if (_stepsExpanded) ...[
                          const SizedBox(height: 8),
                          // Live execution steps
                          if (m.steps.isNotEmpty)
                            ...m.steps.map((s) => Padding(
                                  padding: const EdgeInsets.only(bottom: 3),
                                  child: Row(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        const Text('▸ ',
                                            style: TextStyle(
                                                color: JvColors.cyan,
                                                fontSize: 10)),
                                        Expanded(
                                          child: Text(s,
                                              style: const TextStyle(
                                                  color: JvColors.textSec,
                                                  fontSize: 11,
                                                  height: 1.4)),
                                        ),
                                      ]),
                                )),
                          // Plan steps from mission object
                          if (mission != null &&
                              mission.planSteps.isNotEmpty) ...[
                            if (m.steps.isNotEmpty)
                              const SizedBox(height: 4),
                            ...mission.planSteps.asMap().entries.map((e) {
                              final i = e.key + 1;
                              final step = e.value;
                              final task = step['task']?.toString() ??
                                  step['description']?.toString() ??
                                  step['name']?.toString() ??
                                  'Étape $i';
                              final agent =
                                  step['agent']?.toString() ?? '';
                              return Padding(
                                padding: const EdgeInsets.only(bottom: 5),
                                child: Row(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Container(
                                        width: 17,
                                        height: 17,
                                        decoration: BoxDecoration(
                                          color: JvColors.cyan
                                              .withValues(alpha: 0.14),
                                          shape: BoxShape.circle,
                                        ),
                                        child: Center(
                                          child: Text('$i',
                                              style: const TextStyle(
                                                  color: JvColors.cyan,
                                                  fontSize: 9,
                                                  fontWeight:
                                                      FontWeight.w800)),
                                        ),
                                      ),
                                      const SizedBox(width: 6),
                                      Expanded(
                                        child: Column(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              Text(task,
                                                  style: const TextStyle(
                                                      color: JvColors.textSec,
                                                      fontSize: 11,
                                                      height: 1.4)),
                                              if (agent.isNotEmpty)
                                                Text(agent,
                                                    style: const TextStyle(
                                                        color: JvColors.textMut,
                                                        fontSize: 10)),
                                            ]),
                                      ),
                                    ]),
                              );
                            }),
                          ],
                        ],
                      ],
                    ],
                  ),
                ),

                // Meta row: time + copy button + status
                const SizedBox(height: 4),
                Row(children: [
                  const SizedBox(width: 4),
                  Text(_fmtTime(m.ts),
                      style: const TextStyle(
                          color: JvColors.textMut, fontSize: 10)),
                  if (mission != null) ...[
                    const SizedBox(width: 8),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: accentColor.withValues(alpha: 0.08),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(mission.status,
                          style: TextStyle(
                              color: accentColor.withValues(alpha: 0.7),
                              fontSize: 9,
                              fontWeight: FontWeight.w600)),
                    ),
                  ],
                  const Spacer(),
                  if (!isError)
                    GestureDetector(
                      onTap: () async {
                        await Clipboard.setData(
                            ClipboardData(text: m.text));
                        if (mounted) {
                          setState(() => _copied = true);
                          Future.delayed(const Duration(seconds: 2),
                              () {
                            if (mounted) setState(() => _copied = false);
                          });
                        }
                      },
                      child: Row(children: [
                        Icon(
                          _copied ? Icons.check_circle_outline : Icons.copy_outlined,
                          size: 13,
                          color: _copied ? JvColors.green : JvColors.textMut,
                        ),
                        const SizedBox(width: 3),
                        Text(
                          _copied ? 'Copié' : 'Copier',
                          style: TextStyle(
                              color: _copied
                                  ? JvColors.green
                                  : JvColors.textMut,
                              fontSize: 10),
                        ),
                        const SizedBox(width: 4),
                      ]),
                    ),
                ]),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Bea avatar ────────────────────────────────────────────────────────────

class _BeaAvatar extends StatelessWidget {
  const _BeaAvatar();

  @override
  Widget build(BuildContext context) => Container(
        width: 28,
        height: 28,
        decoration: BoxDecoration(
          color: JvColors.cyan.withValues(alpha: 0.1),
          shape: BoxShape.circle,
          border: Border.all(color: JvColors.cyan.withValues(alpha: 0.35)),
        ),
        child: const Center(
          child: Text('B',
              style: TextStyle(
                  color: JvColors.cyan,
                  fontSize: 13,
                  fontWeight: FontWeight.w800)),
        ),
      );
}

// ─── Chat input ───────────────────────────────────────────────────────────────

class _ChatInput extends StatelessWidget {
  final TextEditingController controller;
  final FocusNode focus;
  final bool locked;
  final bool isUncensored;
  final String hint;
  final VoidCallback onSend;

  const _ChatInput({
    required this.controller,
    required this.focus,
    required this.locked,
    required this.isUncensored,
    required this.hint,
    required this.onSend,
  });

  @override
  Widget build(BuildContext context) {
    final accentColor =
        isUncensored ? const Color(0xFFf43f5e) : JvColors.cyan;

    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
      decoration: BoxDecoration(
        color: JvColors.bg,
        border: Border(
            top: BorderSide(color: JvColors.border.withValues(alpha: 0.6))),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Container(
              constraints: const BoxConstraints(maxHeight: 130),
              decoration: BoxDecoration(
                color: JvColors.card,
                borderRadius: BorderRadius.circular(22),
                border: Border.all(
                  color: locked
                      ? JvColors.border
                      : accentColor.withValues(alpha: 0.35),
                  width: locked ? 1.0 : 1.3,
                ),
              ),
              child: TextField(
                controller: controller,
                focusNode: focus,
                maxLines: null,
                enabled: !locked,
                style: const TextStyle(
                    color: JvColors.textPrim, fontSize: 14, height: 1.5),
                decoration: InputDecoration(
                  contentPadding: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 10),
                  border: InputBorder.none,
                  hintText: hint,
                  hintStyle: const TextStyle(
                      color: JvColors.textMut, fontSize: 13),
                ),
                textInputAction: TextInputAction.newline,
              ),
            ),
          ),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: locked ? null : onSend,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: locked ? JvColors.border : accentColor,
                shape: BoxShape.circle,
              ),
              child: locked
                  ? const Padding(
                      padding: EdgeInsets.all(10),
                      child: CircularProgressIndicator(
                          strokeWidth: 2.5, color: JvColors.textMut),
                    )
                  : const Icon(Icons.send_rounded,
                      size: 19, color: Colors.black),
            ),
          ),
        ],
      ),
    );
  }
}

// ─── Empty hint ───────────────────────────────────────────────────────────────

class _EmptyHint extends StatelessWidget {
  const _EmptyHint();

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 72,
                height: 72,
                decoration: BoxDecoration(
                  color: JvColors.cyan.withValues(alpha: 0.08),
                  shape: BoxShape.circle,
                  border:
                      Border.all(color: JvColors.cyan.withValues(alpha: 0.25)),
                ),
                child: const Center(
                  child: Text('B',
                      style: TextStyle(
                          color: JvColors.cyan,
                          fontSize: 30,
                          fontWeight: FontWeight.w800)),
                ),
              ),
              const SizedBox(height: 18),
              const Text('Bea',
                  style: TextStyle(
                      color: JvColors.textPrim,
                      fontSize: 20,
                      fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              const Text('Votre assistant IA autonome',
                  style:
                      TextStyle(color: JvColors.textSec, fontSize: 13)),
              const SizedBox(height: 4),
              const Text('Posez une question ou lancez une mission',
                  style:
                      TextStyle(color: JvColors.textMut, fontSize: 12)),
            ],
          ),
        ),
      );
}

// ─── WS dot indicator ─────────────────────────────────────────────────────────

class _WsDot extends StatelessWidget {
  final WsConnectionState state;
  const _WsDot({required this.state, super.key});

  @override
  Widget build(BuildContext context) {
    final Color dotColor;
    final String label;
    switch (state) {
      case WsConnectionState.connected:
        dotColor = JvColors.green;
        label = 'WS';
      case WsConnectionState.connecting:
      case WsConnectionState.reconnecting:
        dotColor = JvColors.orange;
        label = 'WS…';
      case WsConnectionState.authExpired:
        dotColor = JvColors.orange;
        label = 'AUTH';
      case WsConnectionState.offline:
        dotColor = JvColors.textMut;
        label = 'OFF';
      case WsConnectionState.disconnected:
        dotColor = JvColors.textMut;
        label = 'WS';
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 4),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
            width: 7,
            height: 7,
            decoration:
                BoxDecoration(shape: BoxShape.circle, color: dotColor)),
        const SizedBox(width: 4),
        Text(label,
            style: TextStyle(
                fontSize: 9,
                color: dotColor,
                fontWeight: FontWeight.w700)),
      ]),
    );
  }
}

// ─── Mission type bar ─────────────────────────────────────────────────────────

class _MissionTypeBar extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onSelect;
  const _MissionTypeBar(
      {required this.selected, required this.onSelect, super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 40,
      decoration: BoxDecoration(
        color: JvColors.bg,
        border: Border(
            top: BorderSide(color: JvColors.border.withValues(alpha: 0.4))),
      ),
      child: ListView.builder(
        scrollDirection: Axis.horizontal,
        padding:
            const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        itemCount: kTaskTypes.length,
        itemBuilder: (ctx, i) {
          final t = kTaskTypes[i];
          final key = t['key'] as String;
          final label = t['label'] as String;
          final code = t['icon'] as int;
          final sel = key == selected;
          return Padding(
            padding: const EdgeInsets.only(right: 6),
            child: GestureDetector(
              onTap: () => onSelect(key),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 150),
                padding: const EdgeInsets.symmetric(
                    horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: sel
                      ? JvColors.cyan.withValues(alpha: 0.1)
                      : Colors.transparent,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: sel ? JvColors.cyan : JvColors.border,
                    width: sel ? 1.4 : 1,
                  ),
                ),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(
                    IconData(code, fontFamily: 'MaterialIcons'),
                    size: 12,
                    color: sel ? JvColors.cyan : JvColors.textMut,
                  ),
                  const SizedBox(width: 4),
                  Text(label,
                      style: TextStyle(
                          fontSize: 11,
                          fontWeight: sel
                              ? FontWeight.w600
                              : FontWeight.w400,
                          color: sel ? JvColors.cyan : JvColors.textSec)),
                ]),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ─── Mission History Drawer ────────────────────────────────────────────────────

class _MissionHistoryDrawer extends StatefulWidget {
  final List<Mission> missions;
  final String? activeMissionId;
  final void Function(Mission) onSelectMission;
  final VoidCallback onNewMission;

  const _MissionHistoryDrawer({
    required this.missions,
    required this.activeMissionId,
    required this.onSelectMission,
    required this.onNewMission,
  });

  @override
  State<_MissionHistoryDrawer> createState() => _MissionHistoryDrawerState();
}

class _MissionHistoryDrawerState extends State<_MissionHistoryDrawer> {
  String _search = '';

  @override
  Widget build(BuildContext context) {
    // Sort by creation date descending
    final sorted = [...widget.missions]
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));

    // Filter by search
    final filtered = _search.isEmpty
        ? sorted
        : sorted.where((m) =>
            m.userInput.toLowerCase().contains(_search.toLowerCase())).toList();

    // Group by date
    final grouped = <String, List<Mission>>{};
    for (final m in filtered) {
      final dt = DateTime.tryParse(m.createdAt);
      final key = dt != null ? _dateLabel(dt) : 'Autre';
      grouped.putIfAbsent(key, () => []).add(m);
    }

    return Drawer(
      backgroundColor: JDS.bgBase,
      child: SafeArea(
        child: Column(children: [
          // Header
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Row(children: [
              const Expanded(child: Text('Historique', style: TextStyle(
                fontSize: 18, fontWeight: FontWeight.w700, color: JDS.textPrimary,
              ))),
              IconButton(
                icon: const Icon(Icons.add_circle_outline, color: JDS.blue, size: 22),
                onPressed: () {
                  Navigator.pop(context); // close drawer
                  widget.onNewMission();
                },
                tooltip: 'Nouvelle mission',
              ),
            ]),
          ),

          // Search
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: TextField(
              style: const TextStyle(color: JDS.textPrimary, fontSize: 13),
              decoration: InputDecoration(
                hintText: 'Rechercher…',
                hintStyle: const TextStyle(color: JDS.textDim, fontSize: 13),
                prefixIcon: const Icon(Icons.search, size: 18, color: JDS.textMuted),
                filled: true,
                fillColor: JDS.bgElevated,
                contentPadding: const EdgeInsets.symmetric(vertical: 8),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(JDS.radiusMd),
                  borderSide: BorderSide(color: JDS.borderSubtle),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(JDS.radiusMd),
                  borderSide: BorderSide(color: JDS.borderSubtle),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(JDS.radiusMd),
                  borderSide: BorderSide(color: JDS.blue),
                ),
              ),
              onChanged: (v) => setState(() => _search = v),
            ),
          ),

          // Mission list
          Expanded(
            child: filtered.isEmpty
                ? Center(child: Text(
                    _search.isEmpty ? 'Aucune mission' : 'Aucun résultat',
                    style: const TextStyle(color: JDS.textMuted, fontSize: 13),
                  ))
                : ListView(
                    padding: const EdgeInsets.only(bottom: 20),
                    children: grouped.entries.expand((entry) => [
                      // Date header
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
                        child: Text(entry.key, style: const TextStyle(
                          fontSize: 11, fontWeight: FontWeight.w600,
                          color: JDS.textDim, letterSpacing: 0.5,
                        )),
                      ),
                      // Mission items
                      ...entry.value.map((m) => _HistoryItem(
                        mission: m,
                        isActive: m.id == widget.activeMissionId,
                        onTap: () => widget.onSelectMission(m),
                      )),
                    ]).toList(),
                  ),
          ),
        ]),
      ),
    );
  }

  String _dateLabel(DateTime dt) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final mDay = DateTime(dt.year, dt.month, dt.day);
    final diff = today.difference(mDay).inDays;
    if (diff == 0) return "Aujourd'hui";
    if (diff == 1) return 'Hier';
    if (diff < 7) return 'Cette semaine';
    if (diff < 30) return 'Ce mois';
    return 'Plus ancien';
  }
}

class _HistoryItem extends StatelessWidget {
  final Mission mission;
  final bool isActive;
  final VoidCallback onTap;

  const _HistoryItem({
    required this.mission,
    required this.isActive,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final title = mission.userInput.isNotEmpty
        ? mission.userInput
        : mission.id;
    final status = mission.status.toLowerCase();

    final Color dotColor;
    final String statusText;
    if (mission.isActive) {
      dotColor = JDS.blue;
      statusText = 'En cours';
    } else if (mission.isDone) {
      dotColor = JDS.green;
      statusText = 'Terminé';
    } else if (mission.isFailed) {
      dotColor = JDS.red;
      statusText = 'Échoué';
    } else if (status.contains('approval') || status.contains('pending')) {
      dotColor = JDS.amber;
      statusText = 'En attente';
    } else {
      dotColor = JDS.textDim;
      statusText = mission.statusLabel;
    }

    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        decoration: BoxDecoration(
          color: isActive ? JDS.blueSoft : Colors.transparent,
          border: Border(
            left: BorderSide(
              color: isActive ? JDS.blue : Colors.transparent,
              width: 2,
            ),
          ),
        ),
        child: Row(children: [
          // Status dot
          Container(
            width: 8, height: 8,
            decoration: BoxDecoration(
              color: dotColor,
              shape: BoxShape.circle,
              boxShadow: mission.isActive
                  ? [BoxShadow(color: dotColor.withValues(alpha: 0.4), blurRadius: 4)]
                  : null,
            ),
          ),
          const SizedBox(width: 12),
          // Title + meta
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
                  color: isActive ? JDS.textPrimary : JDS.textSecondary,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 2),
              Text(
                statusText,
                style: TextStyle(fontSize: 10, color: dotColor),
              ),
            ],
          )),
        ]),
      ),
    );
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

String _fmtTime(DateTime dt) {
  final h = dt.hour.toString().padLeft(2, '0');
  final m = dt.minute.toString().padLeft(2, '0');
  return '$h:$m';
}

DateTime _parseTs(String? s) {
  if (s == null || s.isEmpty) return DateTime.now();
  return DateTime.tryParse(s) ?? DateTime.now();
}
