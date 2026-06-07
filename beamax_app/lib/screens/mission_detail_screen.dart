import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../models/mission.dart';
import '../services/api_service.dart';
import '../theme/design_system.dart';
import '../widgets/cyber_card.dart';
import '../widgets/mission_status_theme.dart';
import '../widgets/status_badge.dart';
import 'actions_screen.dart';

// ── Timeline constants ────────────────────────────────────────────────────────

const List<String> _kTimelineKeys = [
  'CREATED',
  'PLANNED',
  'RUNNING',
  'REVIEW',
  'DONE',
];

const List<String> _kTimelineLabels = [
  'Créé',
  'Planifié',
  'En cours',
  'Révision',
  'Terminé',
];

// ── Screen ────────────────────────────────────────────────────────────────────

class MissionDetailScreen extends StatefulWidget {
  final Mission mission;

  const MissionDetailScreen({super.key, required this.mission});

  @override
  State<MissionDetailScreen> createState() => _MissionDetailScreenState();
}

class _MissionDetailScreenState extends State<MissionDetailScreen> {
  Mission? _detail;
  bool _loadingDetail = false;
  bool _showOutputs = true;
  ApiService? _api;

  // ── Phase 7: polling & elapsed timer ──────────────────────────────────────
  Timer? _pollTimer;
  Timer? _elapsedTick;

  @override
  void initState() {
    super.initState();
    _fetchDetail();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _api = context.read<ApiService>();
      _api!.addListener(_onApiChanged);
    });
  }

  void _onApiChanged() {
    if (!mounted || _loadingDetail) return;
    final liveMission = _api?.missions.cast<Mission?>().firstWhere(
          (m) => m?.id == widget.mission.id,
          orElse: () => null,
        );
    if (liveMission == null) return;
    final currentStatus = _detail?.status ?? widget.mission.status;
    if (liveMission.status != currentStatus) {
      _fetchDetail();
    }
  }

  Future<void> _fetchDetail() async {
    setState(() => _loadingDetail = true);
    final api = context.read<ApiService>();
    final result = await api.fetchMissionDetail(widget.mission.id);
    if (mounted) {
      setState(() {
        if (result.ok) _detail = result.data;
        _loadingDetail = false;
      });
      _updatePolling();
    }
  }

  void _updatePolling() {
    if (_mission.isTerminal) {
      _pollTimer?.cancel();
      _pollTimer = null;
      _elapsedTick?.cancel();
      _elapsedTick = null;
      return;
    }
    if (!_mission.isActive) return;

    _pollTimer ??= Timer.periodic(const Duration(seconds: 3), (_) {
      if (!mounted || _mission.isTerminal) {
        _pollTimer?.cancel();
        _pollTimer = null;
        return;
      }
      _fetchDetail();
    });

    _elapsedTick ??= Timer.periodic(const Duration(seconds: 1), (_) {
      if (!mounted) {
        _elapsedTick?.cancel();
        _elapsedTick = null;
        return;
      }
      setState(() {});
    });
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _elapsedTick?.cancel();
    _api?.removeListener(_onApiChanged);
    super.dispose();
  }

  Mission get _mission => _detail ?? widget.mission;

  Color get _accentColor {
    switch (_mission.status) {
      case 'DONE':
        return JDS.green;
      case 'FAILED':
        return JDS.red;
      case 'REJECTED':
        return const Color(0xFF9C27B0);
      case 'RUNNING':
        return JDS.green;
      case 'REVIEW':
        return JDS.amber;
      case 'PLANNED':
        return const Color(0xFF2196F3);
      case 'BLOCKED':
        return JDS.red;
      case 'APPROVED':
      case 'EXECUTING':
        return JDS.blue;
      default:
        return JDS.textMuted;
    }
  }

  // ── Elapsed time display ──────────────────────────────────────────────────

  String get _elapsedDisplay {
    if (_mission.createdAt.isEmpty) return '';
    try {
      final ts = double.tryParse(_mission.createdAt);
      final start = ts != null
          ? DateTime.fromMillisecondsSinceEpoch((ts * 1000).toInt())
          : DateTime.parse(_mission.createdAt);
      final elapsed = DateTime.now().difference(start).inSeconds;
      if (elapsed < 60) return 'En cours depuis ${elapsed}s...';
      final mins = elapsed ~/ 60;
      final secs = elapsed % 60;
      return 'En cours depuis ${mins}m ${secs.toString().padLeft(2, '0')}s...';
    } catch (_) {
      return '';
    }
  }

  // ── Phase 5: Timeline widget ──────────────────────────────────────────────

  int get _timelineIndex {
    switch (_mission.status) {
      case 'CREATED':
        return 0;
      case 'PLANNED':
        return 1;
      case 'RUNNING':
        return 2;
      case 'REVIEW':
        return 3;
      case 'DONE':
      case 'FAILED':
      case 'REJECTED':
        return 4;
      default:
        return 0;
    }
  }

  Widget _buildTimeline() {
    final currentIdx = _timelineIndex;
    final isFailed = _mission.isFailed || _mission.isRejected;

    final items = <Widget>[];
    for (var i = 0; i < _kTimelineKeys.length; i++) {
      final completed = currentIdx > i;
      final current = currentIdx == i;
      final isFailedNode = isFailed && i == 4;

      Color nodeColor;
      Widget nodeChild;

      if (isFailedNode) {
        nodeColor = JDS.red;
        nodeChild = const Icon(Icons.close, size: 11, color: Colors.white);
      } else if (completed) {
        nodeColor = JDS.blue;
        nodeChild =
            const Icon(Icons.check, size: 11, color: Colors.black);
      } else if (current && _mission.status == 'RUNNING') {
        nodeColor = JDS.green;
        nodeChild = const SizedBox(
          width: 11,
          height: 11,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: Colors.black,
          ),
        );
      } else if (current) {
        nodeColor = MissionStatusTheme.colorFor(_mission.status);
        nodeChild = const DecoratedBox(
          decoration: BoxDecoration(
            color: Colors.black,
            shape: BoxShape.circle,
          ),
          child: SizedBox(width: 8, height: 8),
        );
      } else {
        nodeColor = Colors.transparent;
        nodeChild = const SizedBox.shrink();
      }

      items.add(
        Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 26,
              height: 26,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: (completed || current || isFailedNode)
                    ? nodeColor
                    : Colors.transparent,
                border: Border.all(
                  color: (completed || current || isFailedNode)
                      ? nodeColor
                      : JDS.borderDefault,
                  width: current ? 2 : 1,
                ),
                shape: BoxShape.circle,
              ),
              child: nodeChild,
            ),
            const SizedBox(height: 4),
            Text(
              _kTimelineLabels[i],
              style: TextStyle(
                fontSize: 8,
                color: (completed || current)
                    ? JDS.textSecondary
                    : JDS.textMuted,
                fontWeight:
                    current ? FontWeight.w700 : FontWeight.normal,
              ),
            ),
          ],
        ),
      );

      if (i < _kTimelineKeys.length - 1) {
        items.add(
          Expanded(
            child: Container(
              height: 2,
              margin: const EdgeInsets.only(bottom: 18),
              color: currentIdx > i
                  ? JDS.blue.withValues(alpha: 0.5)
                  : JDS.borderDefault,
            ),
          ),
        );
      }
    }

    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: items,
      ),
    );
  }

  // ── Phase 6: Stats row ───────────────────────────────────────────────────

  Widget _buildStatsRow() {
    String? duration;
    if (_mission.completedAt != null &&
        _mission.completedAt!.isNotEmpty &&
        _mission.createdAt.isNotEmpty) {
      try {
        final tsStart = double.tryParse(_mission.createdAt);
        final tsEnd = double.tryParse(_mission.completedAt!);
        final start = tsStart != null
            ? DateTime.fromMillisecondsSinceEpoch((tsStart * 1000).toInt())
            : DateTime.parse(_mission.createdAt);
        final end = tsEnd != null
            ? DateTime.fromMillisecondsSinceEpoch((tsEnd * 1000).toInt())
            : DateTime.parse(_mission.completedAt!);
        final secs = end.difference(start).inSeconds;
        duration = secs < 60 ? '${secs}s' : '${secs ~/ 60}m ${secs % 60}s';
      } catch (_) {}
    }

    final toolCount = _mission.actionSteps?.length ?? 0;
    final traceShort = _mission.traceId != null && _mission.traceId!.length >= 8
        ? _mission.traceId!.substring(0, 8)
        : _mission.traceId;

    if (duration == null && toolCount == 0 && traceShort == null) {
      return const SizedBox.shrink();
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 4),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: JDS.borderDefault),
      ),
      child: Row(
        children: [
          if (duration != null) ...[
            const Icon(Icons.timer_outlined, size: 13, color: JDS.textMuted),
            const SizedBox(width: 4),
            Text(
              'Durée: $duration',
              style: const TextStyle(color: JDS.textSecondary, fontSize: 11),
            ),
            const SizedBox(width: 16),
          ],
          if (toolCount > 0) ...[
            const Icon(Icons.build_outlined, size: 13, color: JDS.textMuted),
            const SizedBox(width: 4),
            Text(
              'Outils: $toolCount',
              style: const TextStyle(color: JDS.textSecondary, fontSize: 11),
            ),
            const SizedBox(width: 16),
          ],
          if (traceShort != null) ...[
            const Icon(Icons.location_on_outlined,
                size: 13, color: JDS.textMuted),
            const SizedBox(width: 4),
            GestureDetector(
              onTap: () {
                Clipboard.setData(
                    ClipboardData(text: _mission.traceId ?? traceShort));
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Trace ID copié'),
                    duration: Duration(seconds: 2),
                  ),
                );
              },
              child: Text(
                'Trace: $traceShort',
                style: const TextStyle(
                  color: JDS.blue,
                  fontSize: 11,
                  decoration: TextDecoration.underline,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  // ── Phase 4: Reasoning section ───────────────────────────────────────────

  Color _reasoningPhaseColor(String phase) {
    switch (phase.toLowerCase()) {
      case 'classify':
        return const Color(0xFF2196F3);
      case 'plan':
        return const Color(0xFF009688);
      case 'reflect':
        return JDS.amber;
      case 'decision':
        return const Color(0xFF9C27B0);
      default:
        return JDS.textMuted;
    }
  }

  Widget _buildReasoningSection() {
    final steps = _mission.reasoningSteps;
    if (steps == null || steps.isEmpty) return const SizedBox.shrink();

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: JDS.borderDefault),
      ),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
        childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
        leading: const Icon(Icons.psychology_outlined,
            color: JDS.blue, size: 18),
        title: Text(
          'Raisonnement (${steps.length} étapes)',
          style: const TextStyle(
            color: JDS.textPrimary,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
        initiallyExpanded: false,
        iconColor: JDS.textMuted,
        collapsedIconColor: JDS.textMuted,
        children: steps.map((step) {
          final phaseColor = _reasoningPhaseColor(step.phase);
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: phaseColor.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(4),
                    border:
                        Border.all(color: phaseColor.withValues(alpha: 0.4)),
                  ),
                  child: Text(
                    step.phase.toUpperCase(),
                    style: TextStyle(
                      color: phaseColor,
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    step.content,
                    style: const TextStyle(
                        color: JDS.textSecondary, fontSize: 12, height: 1.4),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  // ── Phase 4: Actions executed section ───────────────────────────────────

  Color _actionStatusColor(String status) {
    switch (status.toLowerCase()) {
      case 'success':
        return JDS.green;
      case 'failed':
        return JDS.red;
      case 'approval_required':
        return JDS.amber;
      case 'blocked':
        return const Color(0xFF9C27B0);
      default:
        return JDS.textMuted;
    }
  }

  Widget _buildActionsSection() {
    final steps = _mission.actionSteps;
    if (steps == null || steps.isEmpty) return const SizedBox.shrink();

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: JDS.borderDefault),
      ),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
        childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
        leading: const Icon(Icons.terminal_outlined,
            color: JDS.blue, size: 18),
        title: Text(
          'Actions exécutées (${steps.length})',
          style: const TextStyle(
            color: JDS.textPrimary,
            fontSize: 13,
            fontWeight: FontWeight.w600,
          ),
        ),
        initiallyExpanded: false,
        iconColor: JDS.textMuted,
        collapsedIconColor: JDS.textMuted,
        children: steps.map((action) {
          final statusColor = _actionStatusColor(action.status);
          return Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.code, size: 13, color: JDS.textMuted),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        action.tool,
                        style: const TextStyle(
                          color: JDS.textPrimary,
                          fontSize: 12,
                          fontFamily: 'monospace',
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 7, vertical: 2),
                      decoration: BoxDecoration(
                        color: statusColor.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(4),
                        border: Border.all(
                            color: statusColor.withValues(alpha: 0.4)),
                      ),
                      child: Text(
                        action.status.toUpperCase().replaceAll('_', ' '),
                        style: TextStyle(
                          color: statusColor,
                          fontSize: 9,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    if (action.durationSeconds != null) ...[
                      const SizedBox(width: 6),
                      Text(
                        '${action.durationSeconds!.toStringAsFixed(1)}s',
                        style: const TextStyle(
                            color: JDS.textMuted, fontSize: 10),
                      ),
                    ],
                  ],
                ),
                if (action.errorMessage != null &&
                    action.errorMessage!.isNotEmpty)
                  Container(
                    margin: const EdgeInsets.only(top: 5),
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: JDS.red.withValues(alpha: 0.07),
                      borderRadius: BorderRadius.circular(6),
                      border: Border.all(
                          color: JDS.red.withValues(alpha: 0.25)),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.error_outline,
                            size: 12, color: JDS.red),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            action.errorMessage!,
                            style: const TextStyle(
                                color: JDS.red,
                                fontSize: 11,
                                height: 1.3),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  // ── Phase 4: Error section (for FAILED missions) ─────────────────────────

  Widget _buildErrorSection() {
    if (!_mission.isFailed) return const SizedBox.shrink();

    String? errorMessage;
    String? failedPhase;

    // Try to extract from finalOutput
    if (_mission.finalOutput.isNotEmpty) {
      errorMessage = _mission.finalOutput;
    }

    // Try to extract from executionReason
    if (_mission.executionReason.isNotEmpty) {
      errorMessage ??= _mission.executionReason;
    }

    // Try to get failed phase from executionPolicyDecision
    if (_mission.executionPolicyDecision.isNotEmpty) {
      failedPhase = _mission.executionPolicyDecision;
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.red.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: JDS.red.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.error_outline, color: JDS.red, size: 16),
              SizedBox(width: 8),
              Text(
                'MISSION ÉCHOUÉE',
                style: TextStyle(
                  color: JDS.red,
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1,
                ),
              ),
            ],
          ),
          if (failedPhase != null && failedPhase.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              'Phase échouée: $failedPhase',
              style: const TextStyle(color: JDS.textSecondary, fontSize: 12),
            ),
          ],
          if (errorMessage != null && errorMessage.isNotEmpty) ...[
            const SizedBox(height: 8),
            SelectableText(
              errorMessage,
              style: const TextStyle(
                  color: JDS.textSecondary, fontSize: 12, height: 1.4),
            ),
          ],
          const SizedBox(height: 10),
          const Text(
            '→ Réessayez avec une description plus précise',
            style: TextStyle(
              color: JDS.amber,
              fontSize: 11,
              fontStyle: FontStyle.italic,
            ),
          ),
        ],
      ),
    );
  }

  // ── Build ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final outputs = _mission.agentOutputs;
    final showProgress = _mission.isActive || _loadingDetail;
    final elapsed = _mission.isActive ? _elapsedDisplay : '';

    return Scaffold(
      appBar: AppBar(
        title: const Text('DÉTAIL MISSION'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: JDS.blue),
          onPressed: () => Navigator.pop(context),
        ),
      ),
      body: Column(
        children: [
          // ── Phase 7: Progress indicator ─────────────────────────────────
          if (showProgress)
            LinearProgressIndicator(
              backgroundColor: JDS.borderDefault,
              color: _accentColor,
            ),
          if (elapsed.isNotEmpty)
            Container(
              width: double.infinity,
              color: JDS.bgSurface,
              padding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
              child: Row(
                children: [
                  const Icon(Icons.hourglass_top,
                      size: 12, color: JDS.textMuted),
                  const SizedBox(width: 6),
                  Text(
                    elapsed,
                    style: const TextStyle(
                        color: JDS.textMuted, fontSize: 11),
                  ),
                ],
              ),
            ),
          // ── Content ─────────────────────────────────────────────────────
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                // ── Header card ───────────────────────────────────────────
                CyberCard(
                  accentColor: _accentColor,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(
                            child: Text(
                              _mission.userInput,
                              style: const TextStyle(
                                color: JDS.textPrimary,
                                fontSize: 15,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          StatusBadge.forStatus(_mission.status, fontSize: 11),
                        ],
                      ),
                      const SizedBox(height: 8),
                      _InfoRow('Intention', _mission.intent),
                      if (_mission.createdAt.isNotEmpty)
                        _InfoRow('Créée le',
                            _formatDate(_mission.createdAt)),
                      if (_mission.completedAt != null &&
                          _mission.completedAt!.isNotEmpty)
                        _InfoRow('Terminée le',
                            _formatDate(_mission.completedAt!)),
                    ],
                  ),
                ),

                // ── Phase 5: Timeline ───────────────────────────────────
                _buildTimeline(),

                // ── Phase 6: Stats row ──────────────────────────────────
                _buildStatsRow(),

                // ── Phase 4: Error section ──────────────────────────────
                _buildErrorSection(),

                // ── Réponse Bea ──────────────────────────────────────
                if (_mission.isDone || _mission.finalOutput.isNotEmpty) ...[
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Row(
                      children: [
                        const Text('Réponse de Bea', style: TextStyle(
                          color: JDS.textMuted, fontSize: 10,
                          fontWeight: FontWeight.w700, letterSpacing: 1.2,
                        )),
                        const Spacer(),
                        if (_mission.finalOutput.isNotEmpty) ...[
                          GestureDetector(
                            onTap: () {
                              Clipboard.setData(ClipboardData(text: _mission.finalOutput));
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text('Résultat copié'),
                                  duration: Duration(seconds: 2),
                                ),
                              );
                            },
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                              decoration: BoxDecoration(
                                color: JDS.blue.withValues(alpha: 0.1),
                                borderRadius: BorderRadius.circular(6),
                                border: Border.all(color: JDS.blue.withValues(alpha: 0.3)),
                              ),
                              child: const Row(mainAxisSize: MainAxisSize.min, children: [
                                Icon(Icons.copy_outlined, size: 12, color: JDS.blue),
                                SizedBox(width: 4),
                                Text('Copier', style: TextStyle(
                                  color: JDS.blue, fontSize: 11, fontWeight: FontWeight.w600,
                                )),
                              ]),
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  Container(
                    margin: const EdgeInsets.only(bottom: 12),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: JDS.blue.withValues(alpha: 0.06),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                          color: JDS.blue.withValues(alpha: 0.25)),
                    ),
                    child: SelectableText(
                      _mission.finalOutput.isNotEmpty
                          ? _mission.finalOutput
                          : 'Aucune réponse disponible pour cette mission.',
                      style: TextStyle(
                        color: _mission.finalOutput.isNotEmpty
                            ? JDS.textPrimary
                            : JDS.textMuted,
                        fontSize: 14,
                        height: 1.55,
                      ),
                    ),
                  ),
                ],

                // ── Phase 4: Reasoning section ──────────────────────────
                if (_mission.reasoningSteps != null &&
                    _mission.reasoningSteps!.isNotEmpty) ...[
                  const SectionLabel('Raisonnement'),
                  _buildReasoningSection(),
                ],

                // ── Phase 4: Actions section ────────────────────────────
                if (_mission.actionSteps != null &&
                    _mission.actionSteps!.isNotEmpty) ...[
                  const SectionLabel('Actions exécutées'),
                  _buildActionsSection(),
                ],

                // ── Score ───────────────────────────────────────────────
                const SectionLabel('Score Advisory'),
                CyberCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            'Décision : ${_mission.advisoryDecision}',
                            style: const TextStyle(
                              color: JDS.textSecondary,
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          _ScoreBadge(_mission.advisoryScore),
                        ],
                      ),
                      const SizedBox(height: 10),
                      ScoreBar(_mission.advisoryScore, height: 10),
                    ],
                  ),
                ),

                // ── Décision ────────────────────────────────────────────
                if (_mission.complexity.isNotEmpty ||
                    _mission.riskScore > 0 ||
                    _mission.confidenceScore > 0.0) ...[
                  const SectionLabel('Décision'),
                  CyberCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            if (_mission.complexity.isNotEmpty)
                              _DecisionChip(
                                  'Complexité',
                                  _mission.complexity.toUpperCase(),
                                  JDS.textSecondary),
                            if (_mission.complexity.isNotEmpty)
                              const SizedBox(width: 8),
                            _DecisionChip(
                                'Risque',
                                '${_mission.riskScore}/10',
                                _riskColor(_mission.riskScore)),
                            const SizedBox(width: 8),
                            _DecisionChip(
                                'Confiance',
                                '${(_mission.confidenceScore * 100).toStringAsFixed(0)}%',
                                _confidenceColor(_mission.confidenceScore)),
                          ],
                        ),
                        if (_mission.missionType.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          _InfoRow('Type', _mission.missionType),
                        ],
                        if (_mission.policyModeUsed.isNotEmpty) ...[
                          const SizedBox(height: 2),
                          _InfoRow('Policy', _mission.policyModeUsed),
                        ],
                        if (_mission.executionPolicyDecision.isNotEmpty) ...[
                          const SizedBox(height: 2),
                          _InfoRow(
                              'Exécution', _mission.executionPolicyDecision),
                        ],
                        if (_mission.knowledgeMatch) ...[
                          const SizedBox(height: 2),
                          const _InfoRow('Mémoire', 'Oui'),
                        ],
                        if (_mission.planUsed) ...[
                          const SizedBox(height: 2),
                          const _InfoRow('Plan', 'Actif'),
                        ],
                        if (_mission.approvalDecision.isNotEmpty) ...[
                          const SizedBox(height: 8),
                          _InfoRow('Approbation', _mission.approvalDecision),
                        ],
                        if (_mission.approvalReason != null &&
                            _mission.approvalReason!.isNotEmpty) ...[
                          const SizedBox(height: 2),
                          _InfoRow('Raison', _mission.approvalReason!),
                        ],
                        if (_mission.finalOutputSource.isNotEmpty &&
                            _mission.finalOutputSource != 'unknown') ...[
                          const SizedBox(height: 8),
                          _InfoRow('Source', _mission.finalOutputSource),
                        ],
                        if (_mission.fallbackLevelUsed > 0) ...[
                          const SizedBox(height: 2),
                          _InfoRow(
                              'Fallback', 'Niveau ${_mission.fallbackLevelUsed}'),
                        ],
                      ],
                    ),
                  ),
                ],

                // ── Agents sélectionnés ──────────────────────────────────
                if (_mission.selectedAgents.isNotEmpty) ...[
                  const SectionLabel('Agents sélectionnés'),
                  CyberCard(
                    child: Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      children: _mission.selectedAgents
                          .map((a) => _AgentChip(a, JDS.blue))
                          .toList(),
                    ),
                  ),
                  if (_mission.skippedAgents.isNotEmpty) ...[
                    Padding(
                      padding: const EdgeInsets.only(top: 4, bottom: 2),
                      child: Text(
                        'Agents ignorés (${_mission.skippedAgents.length})',
                        style: const TextStyle(
                            color: JDS.textMuted, fontSize: 11),
                      ),
                    ),
                    Wrap(
                      spacing: 6,
                      runSpacing: 4,
                      children: _mission.skippedAgents
                          .map((a) => _AgentChip(a, JDS.textMuted))
                          .toList(),
                    ),
                    const SizedBox(height: 8),
                  ],
                ],

                // ── Plan summary ─────────────────────────────────────────
                if (_mission.planSummary.isNotEmpty) ...[
                  const SectionLabel('Résumé du Plan'),
                  CyberCard(
                    child: Text(
                      _mission.planSummary,
                      style: const TextStyle(
                          color: JDS.textSecondary, fontSize: 13),
                    ),
                  ),
                ],

                // ── Plan steps ───────────────────────────────────────────
                if (_mission.planSteps.isNotEmpty) ...[
                  const SectionLabel('Étapes du Plan'),
                  ..._mission.planSteps.asMap().entries.map(
                        (e) =>
                            _PlanStepCard(index: e.key, step: e.value),
                      ),
                ],

                // ── Issues ───────────────────────────────────────────────
                if (_mission.advisoryIssues.isNotEmpty) ...[
                  const SectionLabel('Problèmes'),
                  ..._mission.advisoryIssues.map((issue) => _IssueCard(issue)),
                ],

                // ── Risks ────────────────────────────────────────────────
                if (_mission.advisoryRisks.isNotEmpty) ...[
                  const SectionLabel('Risques'),
                  ..._mission.advisoryRisks.map((risk) => _RiskCard(risk)),
                ],

                // ── Actions ──────────────────────────────────────────────
                if (_mission.actionIds.isNotEmpty) ...[
                  const SectionLabel('Actions associées'),
                  CyberCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (_mission.approvalReason != null &&
                            _mission.approvalReason!.isNotEmpty)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 10),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                const Icon(Icons.info_outline,
                                    size: 13, color: JDS.textMuted),
                                const SizedBox(width: 6),
                                Expanded(
                                  child: Text(
                                    _mission.approvalReason!,
                                    style: const TextStyle(
                                      color: JDS.textMuted,
                                      fontSize: 11,
                                      fontStyle: FontStyle.italic,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        Text(
                          '${_mission.actionIds.length} action(s)',
                          style: const TextStyle(
                            color: JDS.textSecondary,
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 6,
                          runSpacing: 6,
                          children: _mission.actionIds
                              .map((id) => Container(
                                    padding: const EdgeInsets.symmetric(
                                      horizontal: 10,
                                      vertical: 4,
                                    ),
                                    decoration: BoxDecoration(
                                      color: JDS.borderDefault,
                                      borderRadius:
                                          BorderRadius.circular(4),
                                      border: Border.all(
                                          color: JDS.blue
                                              .withValues(alpha: 0.2)),
                                    ),
                                    child: Text(
                                      id,
                                      style: const TextStyle(
                                        color: JDS.blue,
                                        fontSize: 10,
                                        fontFamily: 'monospace',
                                      ),
                                    ),
                                  ))
                              .toList(),
                        ),
                        const SizedBox(height: 12),
                        SizedBox(
                          width: double.infinity,
                          child: OutlinedButton.icon(
                            icon: const Icon(Icons.check_circle_outline,
                                size: 16),
                            label: const Text('VOIR LES ACTIONS'),
                            style: OutlinedButton.styleFrom(
                              foregroundColor: JDS.blue,
                              side:
                                  const BorderSide(color: JDS.blue),
                              padding: const EdgeInsets.symmetric(
                                  vertical: 12),
                            ),
                            onPressed: () {
                              Navigator.of(context).pop();
                              Navigator.of(context).push(
                                MaterialPageRoute(
                                  builder: (_) => const ActionsScreen(),
                                ),
                              );
                            },
                          ),
                        ),
                      ],
                    ),
                  ),
                ],

                // ── Note ─────────────────────────────────────────────────
                if (_mission.note.isNotEmpty) ...[
                  const SectionLabel('Note'),
                  CyberCard(
                    child: Text(
                      _mission.note,
                      style: const TextStyle(
                          color: JDS.textSecondary, fontSize: 12),
                    ),
                  ),
                ],

                // ── Agent Outputs ─────────────────────────────────────────
                const SectionLabel('Réponses Agents'),
                if (_loadingDetail)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: Center(
                      child: SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: JDS.blue,
                        ),
                      ),
                    ),
                  )
                else ...[
                  CyberCard(
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'Afficher les réponses complètes',
                          style: TextStyle(
                              color: JDS.textSecondary, fontSize: 13),
                        ),
                        Switch(
                          value: _showOutputs,
                          onChanged: (v) =>
                              setState(() => _showOutputs = v),
                          activeColor: JDS.blue,
                        ),
                      ],
                    ),
                  ),
                  if (_showOutputs) ...[
                    if (outputs == null || outputs.isEmpty)
                      Container(
                        margin: const EdgeInsets.only(bottom: 8),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: JDS.bgSurface,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: JDS.borderDefault),
                        ),
                        child: const Text(
                          'Aucune réponse disponible pour cette mission.',
                          style: TextStyle(
                              color: JDS.textMuted, fontSize: 12),
                        ),
                      )
                    else
                      ...outputs.entries.map(
                        (e) => _AgentOutputTile(
                            agentId: e.key, output: e.value),
                      ),
                  ],
                ],

                const SizedBox(height: 40),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Sub-widgets ───────────────────────────────────────────────────────────────

class _InfoRow extends StatelessWidget {
  final String label;
  final String value;

  const _InfoRow(this.label, this.value);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text(
              label,
              style: const TextStyle(
                color: JDS.textMuted,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(color: JDS.textSecondary, fontSize: 11),
            ),
          ),
        ],
      ),
    );
  }
}

class _ScoreBadge extends StatelessWidget {
  final double score;
  const _ScoreBadge(this.score);

  @override
  Widget build(BuildContext context) {
    final color = score >= 7.5
        ? JDS.green
        : score >= 4.0
            ? JDS.amber
            : JDS.red;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(
        '${score.toStringAsFixed(1)}/10',
        style: TextStyle(
          color: color,
          fontSize: 14,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _PlanStepCard extends StatelessWidget {
  final int index;
  final Map<String, dynamic> step;

  const _PlanStepCard({required this.index, required this.step});

  @override
  Widget build(BuildContext context) {
    final desc = step['task'] as String? ??
        step['description'] as String? ??
        step['action'] as String? ??
        step.toString();
    final status = step['status'] as String?;

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: JDS.borderDefault),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: JDS.blue.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: JDS.blue.withValues(alpha: 0.4)),
            ),
            child: Text(
              '${index + 1}',
              style: const TextStyle(
                color: JDS.blue,
                fontSize: 11,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  desc,
                  style: const TextStyle(
                    color: JDS.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                if (status != null && status.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  StatusBadge.forStatus(status, fontSize: 9),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _IssueCard extends StatelessWidget {
  final Map<String, dynamic> issue;
  const _IssueCard(this.issue);

  @override
  Widget build(BuildContext context) {
    final msg = issue['message'] as String? ??
        issue['description'] as String? ??
        issue.toString();
    final type = issue['type'] as String? ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: JDS.amber.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: JDS.amber.withValues(alpha: 0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.warning_amber_outlined,
              color: JDS.amber, size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (type.isNotEmpty)
                  Text(type,
                      style: const TextStyle(
                        color: JDS.amber,
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                      )),
                Text(msg,
                    style:
                        const TextStyle(color: JDS.textSecondary, fontSize: 12)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RiskCard extends StatelessWidget {
  final Map<String, dynamic> risk;
  const _RiskCard(this.risk);

  @override
  Widget build(BuildContext context) {
    final desc = risk['description'] as String? ??
        risk['message'] as String? ??
        risk.toString();
    final level =
        risk['level'] as String? ?? risk['severity'] as String? ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: JDS.red.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: JDS.red.withValues(alpha: 0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.shield_outlined, color: JDS.red, size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (level.isNotEmpty) StatusBadge.forRisk(level, fontSize: 9),
                const SizedBox(height: 2),
                Text(desc,
                    style:
                        const TextStyle(color: JDS.textSecondary, fontSize: 12)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AgentOutputTile extends StatelessWidget {
  final String agentId;
  final String output;

  const _AgentOutputTile({required this.agentId, required this.output});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: JDS.borderDefault),
      ),
      child: ExpansionTile(
        tilePadding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
        childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
        leading: const Icon(Icons.smart_toy_outlined,
            color: JDS.blue, size: 18),
        title: Text(
          agentId,
          style: const TextStyle(
            color: JDS.blue,
            fontSize: 13,
            fontWeight: FontWeight.w700,
            fontFamily: 'monospace',
          ),
        ),
        iconColor: JDS.textMuted,
        collapsedIconColor: JDS.textMuted,
        children: [
          SelectableText(
            output,
            style: const TextStyle(
              color: JDS.textSecondary,
              fontSize: 12,
              height: 1.5,
            ),
          ),
        ],
      ),
    );
  }
}

class _DecisionChip extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _DecisionChip(this.label, this.value, this.color);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Column(
        children: [
          Text(label,
              style: const TextStyle(color: JDS.textMuted, fontSize: 9)),
          const SizedBox(height: 2),
          Text(value,
              style: TextStyle(
                  color: color,
                  fontSize: 12,
                  fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _AgentChip extends StatelessWidget {
  final String name;
  final Color color;
  const _AgentChip(this.name, this.color);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Text(
        name,
        style:
            TextStyle(color: color, fontSize: 10, fontFamily: 'monospace'),
      ),
    );
  }
}

Color _riskColor(int score) {
  if (score <= 3) return JDS.green;
  if (score <= 6) return JDS.amber;
  return JDS.red;
}

Color _confidenceColor(double score) {
  if (score >= 0.70) return JDS.green;
  if (score >= 0.40) return JDS.amber;
  return JDS.red;
}

// ── Utils ─────────────────────────────────────────────────────────────────────

String _formatDate(String iso) {
  try {
    final ts = double.tryParse(iso);
    final dt = ts != null
        ? DateTime.fromMillisecondsSinceEpoch((ts * 1000).toInt()).toLocal()
        : DateTime.parse(iso).toLocal();
    return '${dt.day.toString().padLeft(2, '0')}/${dt.month.toString().padLeft(2, '0')}/${dt.year}'
        '  ${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  } catch (_) {
    return iso;
  }
}
