import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/task_types.dart';
import '../services/api_service.dart';
import '../services/websocket_service.dart';
import '../models/mission.dart';
import '../theme/design_system.dart';
import 'mission_detail_screen.dart';

/// Home — the primary Jarvis interface.
/// Shows: greeting, quick input, system status, approvals, recent missions.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _controller = TextEditingController();
  final _focus = FocusNode();
  bool _sending = false;
  String? _feedback;
  bool _feedbackIsError = false;
  String _selectedTaskKey = 'libre';

  @override
  Widget build(BuildContext context) {
    final ws = context.watch<WebSocketService>();
    final api = context.watch<ApiService>();

    return Scaffold(
      body: SafeArea(
        child: GestureDetector(
          onTap: () => _focus.unfocus(),
          child: RefreshIndicator(
            onRefresh: api.refresh,
            color: JDS.blue,
            backgroundColor: JDS.bgElevated,
            child: CustomScrollView(slivers: [
              // ── Header ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                child: Row(children: [
                  // Brand
                  Container(
                    width: 34, height: 34,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(10),
                      gradient: const LinearGradient(
                        colors: [JDS.blue, JDS.violet],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                    ),
                    child: const Center(child: Text('J', style: TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700, color: Colors.white,
                    ))),
                  ),
                  const SizedBox(width: 10),
                  const Text('Jarvis', style: TextStyle(
                    fontSize: 22, fontWeight: FontWeight.w700,
                    color: JDS.textPrimary, letterSpacing: -0.5,
                  )),
                  const Spacer(),
                  _ConnectionIndicator(connected: ws.isConnected),
                ]),
              )),

              // ── Greeting ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(_dateString(), style: const TextStyle(
                    fontSize: 12, fontWeight: FontWeight.w500, color: JDS.textMuted,
                  )),
                  const SizedBox(height: 4),
                  Text(_greetingText(), style: const TextStyle(
                    fontSize: 26, fontWeight: FontWeight.w700,
                    color: JDS.textPrimary, letterSpacing: -0.5, height: 1.2,
                  )),
                ]),
              )),

              // ── Approval Alert ──
              if (api.pendingActions.isNotEmpty)
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
                  child: _ApprovalAlert(count: api.pendingActions.length),
                )),

              // ── Task Type Selector ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(0, 0, 0, 12),
                child: _TaskTypeBar(
                  selected: _selectedTaskKey,
                  onSelect: (key) => setState(() => _selectedTaskKey = key),
                ),
              )),

              // ── Composer ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: _Composer(
                  controller: _controller,
                  focus: _focus,
                  sending: _sending,
                  onSend: _send,
                  hintText: _currentHint,
                  selectedLabel: _selectedTaskKey == 'libre' ? null : _currentLabel,
                  onClearType: () => setState(() => _selectedTaskKey = 'libre'),
                ),
              )),

              // ── Feedback ──
              if (_feedback != null)
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
                  child: _FeedbackBanner(
                    message: _feedback!,
                    isError: _feedbackIsError,
                    onDismiss: () => setState(() => _feedback = null),
                  ),
                )),

              // ── Stats ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                child: _StatsRow(api: api),
              )),

              // ── Recent Missions ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 24, 20, 12),
                child: JSectionHeader(
                  title: 'Missions récentes',
                  count: '${api.missions.length}',
                  action: TextButton(
                    onPressed: () => api.refresh(),
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    child: const Text('Actualiser', style: TextStyle(
                      fontSize: 12, color: JDS.textMuted,
                    )),
                  ),
                ),
              )),

              // Mission list or empty
              if (api.loading && api.missions.isEmpty)
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Column(children: List.generate(3, (_) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _MissionSkeleton(),
                  ))),
                ))
              else if (api.missions.isEmpty)
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: JEmptyState(
                    icon: Icons.rocket_launch_outlined,
                    title: 'Aucune mission',
                    subtitle: 'Décrivez une tâche ci-dessus pour commencer',
                  ),
                ))
              else
                SliverList(delegate: SliverChildBuilderDelegate(
                  (_, i) {
                    final m = api.missions[i];
                    return Padding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                      child: _MissionCard(mission: m, onTap: () => _openMission(m)),
                    );
                  },
                  childCount: api.missions.take(10).length,
                )),

              const SliverToBoxAdapter(child: SizedBox(height: 100)),
            ]),
          ),
        ),
      ),
    );
  }

  Map<String, dynamic> get _currentTypeData =>
      kTaskTypes.firstWhere((t) => t['key'] == _selectedTaskKey,
          orElse: () => kTaskTypes.first);

  String get _currentHint => _currentTypeData['hint'] as String;
  String get _currentLabel => _currentTypeData['label'] as String;

  String _dateString() {
    final now = DateTime.now();
    final weekdays = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
    final months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
    return '${weekdays[now.weekday - 1]} ${now.day} ${months[now.month - 1]}';
  }

  String _greetingText() {
    final h = DateTime.now().hour;
    if (h < 6) return 'Vous travaillez tard ?';
    if (h < 12) return 'Bonjour.';
    if (h < 18) return 'Bon après-midi.';
    return 'Bonsoir.';
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;

    // Prefix the domain skill key so the backend can route to the right skill
    final goal = (_selectedTaskKey != 'libre')
        ? '[$_selectedTaskKey] $text'
        : text;

    setState(() { _sending = true; _feedback = null; });

    try {
      final api = context.read<ApiService>();
      final result = await api.submitMission(goal);
      if (!mounted) return;

      if (result != null) {
        setState(() {
          _sending = false;
          _feedback = '✓ Mission lancée';
          _feedbackIsError = false;
          _selectedTaskKey = 'libre'; // reset type after send
        });
        _controller.clear();
        await api.refresh();
      } else {
        setState(() {
          _sending = false;
          _feedback = 'Échec d\'envoi de la mission';
          _feedbackIsError = true;
        });
      }
    } catch (e) {
      if (mounted) setState(() {
        _sending = false;
        _feedback = 'Erreur de connexion';
        _feedbackIsError = true;
      });
    }
  }

  void _openMission(Mission m) {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => MissionDetailScreen(mission: m),
    ));
  }

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }
}

// ── Connection Indicator ─────────────────────────────────────────────────────

class _ConnectionIndicator extends StatelessWidget {
  final bool connected;
  const _ConnectionIndicator({required this.connected});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: JDS.bgElevated,
        borderRadius: BorderRadius.circular(JDS.radiusSm),
        border: Border.all(color: JDS.borderSubtle),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
          width: 7, height: 7,
          decoration: BoxDecoration(
            color: connected ? JDS.green : JDS.textDim,
            shape: BoxShape.circle,
            boxShadow: connected
                ? [BoxShadow(color: JDS.green.withValues(alpha: 0.4), blurRadius: 4)]
                : null,
          ),
        ),
        const SizedBox(width: 6),
        Text(connected ? 'En ligne' : 'Hors ligne', style: TextStyle(
          fontSize: 11, fontWeight: FontWeight.w500,
          color: connected ? JDS.textSecondary : JDS.textDim,
        )),
      ]),
    );
  }
}

// ── Approval Alert ───────────────────────────────────────────────────────────

class _ApprovalAlert extends StatelessWidget {
  final int count;
  const _ApprovalAlert({required this.count});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.amberSoft,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: JDS.amber.withValues(alpha: 0.2)),
      ),
      child: Row(children: [
        const Icon(Icons.pending_actions_rounded, size: 20, color: JDS.amber),
        const SizedBox(width: 12),
        Expanded(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$count élément${count > 1 ? 's' : ''} attend${count == 1 ? '' : 'ent'} votre décision',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: JDS.amber)),
            const Text('Jarvis attend votre validation avant de continuer',
                style: TextStyle(fontSize: 12, color: JDS.textSecondary)),
          ],
        )),
        const Icon(Icons.chevron_right_rounded, color: JDS.amber, size: 20),
      ]),
    );
  }
}

// ── Composer ──────────────────────────────────────────────────────────────────

class _Composer extends StatelessWidget {
  final TextEditingController controller;
  final FocusNode focus;
  final bool sending;
  final VoidCallback onSend;
  final String hintText;
  final String? selectedLabel;
  final VoidCallback? onClearType;

  const _Composer({
    required this.controller,
    required this.focus,
    required this.sending,
    required this.onSend,
    this.hintText = 'Que voulez-vous faire ? Recherche, analyse, code, automatisation…',
    this.selectedLabel,
    this.onClearType,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusLg),
        border: Border.all(
          color: selectedLabel != null
              ? JDS.blue.withValues(alpha: 0.4)
              : JDS.borderDefault,
        ),
      ),
      child: Column(children: [
        // ── Selected category badge ──
        if (selectedLabel != null) ...[
          Row(children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: JDS.blue.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: JDS.blue.withValues(alpha: 0.3)),
              ),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.category_rounded, size: 11, color: JDS.blue),
                const SizedBox(width: 4),
                Text(selectedLabel!, style: const TextStyle(
                  fontSize: 11, color: JDS.blue, fontWeight: FontWeight.w600,
                )),
              ]),
            ),
            const SizedBox(width: 6),
            GestureDetector(
              onTap: onClearType,
              child: const Icon(Icons.close_rounded, size: 14, color: JDS.textDim),
            ),
          ]),
          const SizedBox(height: 10),
        ],
        TextField(
          controller: controller,
          focusNode: focus,
          maxLines: 3,
          minLines: 2,
          style: const TextStyle(color: JDS.textPrimary, fontSize: 15, height: 1.5),
          decoration: InputDecoration(
            hintText: hintText,
            border: InputBorder.none,
            enabledBorder: InputBorder.none,
            focusedBorder: InputBorder.none,
            filled: false,
            contentPadding: EdgeInsets.zero,
          ),
        ),
        const Divider(height: 24),
        Row(children: [
          const Text('Jarvis s\'occupe du reste', style: TextStyle(
            fontSize: 12, color: JDS.textDim,
          )),
          const Spacer(),
          SizedBox(
            height: 36,
            child: ElevatedButton(
              onPressed: sending ? null : onSend,
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.symmetric(horizontal: 20),
              ),
              child: sending
                  ? const SizedBox(width: 16, height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(Icons.play_arrow_rounded, size: 16),
                      SizedBox(width: 4),
                      Text('Lancer'),
                    ]),
            ),
          ),
        ]),
      ]),
    );
  }
}

// ── Task Type Bar ─────────────────────────────────────────────────────────────

class _TaskTypeBar extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onSelect;

  const _TaskTypeBar({required this.selected, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        children: kTaskTypes.map((t) {
          final key = t['key'] as String;
          final label = t['label'] as String;
          final iconCode = t['icon'] as int;
          final isSelected = key == selected;

          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: GestureDetector(
              onTap: () => onSelect(key),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                decoration: BoxDecoration(
                  color: isSelected
                      ? JDS.blue.withValues(alpha: 0.15)
                      : JDS.bgSurface,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: isSelected ? JDS.blue : JDS.borderSubtle,
                    width: isSelected ? 1.5 : 1,
                  ),
                ),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(
                    IconData(iconCode, fontFamily: 'MaterialIcons'),
                    size: 13,
                    color: isSelected ? JDS.blue : JDS.textMuted,
                  ),
                  const SizedBox(width: 5),
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
                      color: isSelected ? JDS.blue : JDS.textSecondary,
                    ),
                  ),
                ]),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

// ── Feedback Banner ──────────────────────────────────────────────────────────

class _FeedbackBanner extends StatelessWidget {
  final String message;
  final bool isError;
  final VoidCallback onDismiss;

  const _FeedbackBanner({
    required this.message,
    required this.isError,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    final color = isError ? JDS.red : JDS.green;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(JDS.radiusSm),
        border: Border.all(color: color.withValues(alpha: 0.2)),
      ),
      child: Row(children: [
        Text(message, style: TextStyle(fontSize: 13, color: color, fontWeight: FontWeight.w500)),
        const Spacer(),
        GestureDetector(
          onTap: onDismiss,
          child: Icon(Icons.close_rounded, size: 16, color: color),
        ),
      ]),
    );
  }
}

// ── Stats Row ────────────────────────────────────────────────────────────────

class _StatsRow extends StatelessWidget {
  final ApiService api;
  const _StatsRow({required this.api});

  @override
  Widget build(BuildContext context) {
    final running = api.missions.where((m) =>
        m.status.toLowerCase() == 'running' || m.status.toLowerCase() == 'executing').length;
    final done = api.missions.where((m) =>
        m.status.toLowerCase() == 'completed' || m.status.toLowerCase() == 'done').length;
    final failed = api.missions.where((m) =>
        m.status.toLowerCase() == 'failed').length;

    return Row(children: [
      Expanded(child: _StatTile(value: '$running', label: 'Actif', color: JDS.blue)),
      const SizedBox(width: 10),
      Expanded(child: _StatTile(value: '$done', label: 'Terminé', color: JDS.green)),
      const SizedBox(width: 10),
      Expanded(child: _StatTile(value: '$failed', label: 'Échoué', color: JDS.red)),
      const SizedBox(width: 10),
      Expanded(child: _StatTile(
        value: api.status.isOnline ? '✓' : '—',
        label: 'Système',
        color: api.status.isOnline ? JDS.green : JDS.textDim,
      )),
    ]);
  }
}

class _StatTile extends StatelessWidget {
  final String value;
  final String label;
  final Color color;
  const _StatTile({required this.value, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: JDS.borderSubtle),
      ),
      child: Column(children: [
        Text(value, style: TextStyle(
          fontSize: 20, fontWeight: FontWeight.w700, color: color, height: 1,
        )),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(
          fontSize: 11, color: JDS.textMuted, fontWeight: FontWeight.w500,
        )),
      ]),
    );
  }
}

// ── Mission Card ─────────────────────────────────────────────────────────────

class _MissionCard extends StatelessWidget {
  final Mission mission;
  final VoidCallback onTap;
  const _MissionCard({required this.mission, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final status = mission.status.toLowerCase();

    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: JDS.bgSurface,
          borderRadius: BorderRadius.circular(JDS.radiusMd),
          border: Border.all(color: JDS.borderSubtle),
        ),
        child: Row(children: [
          JStatusDot(status: status),
          const SizedBox(width: 12),
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                mission.userInput.isNotEmpty ? mission.userInput : mission.id,
                style: const TextStyle(fontSize: 14, color: JDS.textPrimary, fontWeight: FontWeight.w500),
                maxLines: 1, overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 2),
              Text(_missionMeta(mission), style: const TextStyle(
                fontSize: 12, color: JDS.textDim,
              )),
            ],
          )),
          const SizedBox(width: 8),
          JStatusBadge.fromStatus(status),
        ]),
      ),
    );
  }

  String _missionMeta(Mission m) {
    final parts = <String>[];
    if (m.createdAt.isNotEmpty) {
      final dt = DateTime.tryParse(m.createdAt);
      if (dt != null) parts.add(_timeAgo(dt));
    }
    return parts.join(' · ');
  }

  String _timeAgo(DateTime dt) {
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 1) return 'à l\'instant';
    if (diff.inMinutes < 60) return 'il y a ${diff.inMinutes}min';
    if (diff.inHours < 24) return 'il y a ${diff.inHours}h';
    return 'il y a ${diff.inDays}j';
  }
}

// ── Mission Skeleton ─────────────────────────────────────────────────────────

class _MissionSkeleton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: JDS.borderSubtle),
      ),
      child: Row(children: [
        Container(
          width: 8, height: 8,
          decoration: BoxDecoration(
            color: JDS.bgOverlay,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 12),
        Expanded(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(height: 14, width: 200, decoration: BoxDecoration(
              color: JDS.bgOverlay, borderRadius: BorderRadius.circular(4),
            )),
            const SizedBox(height: 6),
            Container(height: 10, width: 80, decoration: BoxDecoration(
              color: JDS.bgOverlay, borderRadius: BorderRadius.circular(4),
            )),
          ],
        )),
      ]),
    );
  }
}

