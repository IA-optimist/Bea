import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/mission.dart';
import '../services/api_service.dart';
import '../widgets/cyber_card.dart';
import '../widgets/status_badge.dart';
import 'mission_detail_screen.dart';

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  /// null = ALL
  String? _filter;

  List<Mission> _applyFilter(List<Mission> missions) {
    // Tri : plus récentes en premier (created_at est un timestamp float en string)
    final sorted = [...missions]..sort((a, b) {
      final ta = double.tryParse(a.createdAt) ?? 0.0;
      final tb = double.tryParse(b.createdAt) ?? 0.0;
      return tb.compareTo(ta);
    });
    if (_filter == null || _filter == 'ALL') return sorted;
    return sorted.where((m) => m.status == _filter).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('HISTORIQUE'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: JvColors.cyan),
            onPressed: () => context.read<ApiService>().refresh(),
          ),
        ],
      ),
      body: Consumer<ApiService>(
        builder: (_, api, __) {
          final missions = _applyFilter(api.missions);

          return RefreshIndicator(
            color: JvColors.cyan,
            backgroundColor: JvColors.card,
            onRefresh: api.refresh,
            child: Column(
              children: [
                // ── Chip filters ─────────────────────────────────────────────
                _FilterBar(
                  selected: _filter ?? 'ALL',
                  onSelected: (f) => setState(() => _filter = f == 'ALL' ? null : f),
                ),
                const Divider(height: 1),
                // ── Liste ────────────────────────────────────────────────────
                Expanded(
                  child: api.loading && api.missions.isEmpty
                      ? const Center(child: CircularProgressIndicator())
                      : missions.isEmpty
                          ? _EmptyState(_filter)
                          : ListView.builder(
                              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                              itemCount: missions.length,
                              itemBuilder: (_, i) => _MissionItem(missions[i]),
                            ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

// ── Filter chips ─────────────────────────────────────────────────────────────

class _FilterBar extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onSelected;

  const _FilterBar({required this.selected, required this.onSelected});

  static const _labels = ['ALL', 'DONE', 'APPROVED', 'REJECTED', 'BLOCKED', 'PENDING_VALIDATION'];

  Color _chipColor(String f) => switch (f) {
        'DONE'               => JvColors.green,
        'BLOCKED'            => JvColors.red,
        'REJECTED'           => JvColors.orange,
        'APPROVED'           => JvColors.cyan,
        'PENDING_VALIDATION' => const Color(0xFFFFAA00),
        _                    => JvColors.textSec,
      };

  String _chipLabel(String f) => switch (f) {
        'PENDING_VALIDATION' => 'EN ATTENTE',
        'APPROVED'           => 'EN COURS',
        _                    => f,
      };

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Row(
        children: _labels.map((f) {
          final isSelected = f == selected;
          final color = _chipColor(f);
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: GestureDetector(
              onTap: () => onSelected(f),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                decoration: BoxDecoration(
                  color: isSelected ? color.withValues(alpha:0.18) : JvColors.card,
                  border: Border.all(
                    color: isSelected ? color : JvColors.border,
                    width: isSelected ? 1.5 : 1,
                  ),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  _chipLabel(f),
                  style: TextStyle(
                    color: isSelected ? color : JvColors.textSec,
                    fontSize: 12,
                    fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                    letterSpacing: 0.5,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

// ── Mission item avec ExpansionTile ──────────────────────────────────────────

class _MissionItem extends StatelessWidget {
  final Mission mission;

  const _MissionItem(this.mission);

  Color get _accentColor => switch (mission.status) {
        'DONE'     => JvColors.green,
        'BLOCKED'  => JvColors.red,
        'REJECTED' => JvColors.orange,
        'APPROVED' || 'EXECUTING' => JvColors.cyan,
        _          => JvColors.textMut,
      };

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 5),
      decoration: BoxDecoration(
        color: JvColors.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: JvColors.border),
        gradient: LinearGradient(
          begin: Alignment.centerLeft,
          end: Alignment.centerRight,
          colors: [_accentColor.withValues(alpha:0.07), JvColors.card],
        ),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Theme(
          // Supprime le trait ExpansionTile par défaut
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
            childrenPadding: const EdgeInsets.only(left: 14, right: 14, bottom: 14),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            // ── Header ────────────────────────────────────────────────────
            title: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Accent bar gauche
                Container(
                  width: 3,
                  height: 42,
                  margin: const EdgeInsets.only(right: 10),
                  decoration: BoxDecoration(
                    color: _accentColor,
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        mission.userInput,
                        style: const TextStyle(
                          color: JvColors.textPrim,
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 3),
                      Text(
                        mission.intent,
                        style: const TextStyle(
                          color: JvColors.textSec,
                          fontSize: 10,
                          letterSpacing: 0.5,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                StatusBadge.forStatus(mission.status),
              ],
            ),
            // ── Expanded body ──────────────────────────────────────────────
            children: [
              const Divider(color: JvColors.border, height: 12),

              // Score
              const Text(
                'SCORE ADVISORY',
                style: TextStyle(
                  color: JvColors.textMut,
                  fontSize: 9,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 1.5,
                ),
              ),
              const SizedBox(height: 6),
              ScoreBar(mission.advisoryScore),

              const SizedBox(height: 10),

              // Plan summary
              if (mission.planSummary.isNotEmpty) ...[
                const Text(
                  'PLAN',
                  style: TextStyle(
                    color: JvColors.textMut,
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.5,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  mission.planSummary,
                  style: const TextStyle(color: JvColors.textSec, fontSize: 12),
                ),
                const SizedBox(height: 10),
              ],

              // Plan steps
              if (mission.planSteps.isNotEmpty) ...[
                const Text(
                  'ÉTAPES',
                  style: TextStyle(
                    color: JvColors.textMut,
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.5,
                  ),
                ),
                const SizedBox(height: 6),
                ...mission.planSteps.asMap().entries.map(
                  (e) => _PlanStepRow(index: e.key, step: e.value),
                ),
                const SizedBox(height: 6),
              ],

              // Actions
              if (mission.actionIds.isNotEmpty) ...[
                const Text(
                  'ACTIONS',
                  style: TextStyle(
                    color: JvColors.textMut,
                    fontSize: 9,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1.5,
                  ),
                ),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: mission.actionIds
                      .map(
                        (id) => Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: JvColors.border,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            id.length > 12 ? '…${id.substring(id.length - 8)}' : id,
                            style: const TextStyle(
                              color: JvColors.textSec,
                              fontSize: 10,
                              fontFamily: 'monospace',
                            ),
                          ),
                        ),
                      )
                      .toList(),
                ),
                const SizedBox(height: 6),
              ],

              // Date
              if (mission.createdAt.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(
                  'Créée le ${_formatDate(mission.createdAt)}',
                  style: const TextStyle(color: JvColors.textMut, fontSize: 10),
                ),
              ],

              // Bouton détail
              const SizedBox(height: 10),
              Align(
                alignment: Alignment.centerRight,
                child: GestureDetector(
                  onTap: () => Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => MissionDetailScreen(mission: mission),
                    ),
                  ),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                    decoration: BoxDecoration(
                      border: Border.all(color: JvColors.cyan.withValues(alpha:0.5)),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Text(
                      'VOIR DÉTAIL →',
                      style: TextStyle(
                        color: JvColors.cyan,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.8,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PlanStepRow extends StatelessWidget {
  final int index;
  final Map<String, dynamic> step;

  const _PlanStepRow({required this.index, required this.step});

  @override
  Widget build(BuildContext context) {
    // Backend uses 'task' key — fallback on 'description' / 'action' for legacy
    final desc = (step['task'] ?? step['description'] ?? step['action'])
            ?.toString() ??
        step.values.firstOrNull?.toString() ??
        '—';
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 20,
            height: 20,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: JvColors.cyan.withValues(alpha:0.12),
              borderRadius: BorderRadius.circular(4),
              border: Border.all(color: JvColors.cyan.withValues(alpha:0.3)),
            ),
            child: Text(
              '${index + 1}',
              style: const TextStyle(
                color: JvColors.cyan,
                fontSize: 9,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  desc,
                  style: const TextStyle(color: JvColors.textSec, fontSize: 12),
                ),
                if (step['agent'] != null)
                  Text(
                    step['agent'].toString(),
                    style: const TextStyle(
                      color: JvColors.textMut,
                      fontSize: 10,
                      fontStyle: FontStyle.italic,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final String? filter;
  const _EmptyState(this.filter);

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.history_outlined, color: JvColors.textMut, size: 48),
          const SizedBox(height: 12),
          Text(
            filter != null && filter != 'ALL'
                ? 'Aucune mission avec le statut $filter'
                : 'Aucune mission dans l\'historique',
            style: const TextStyle(color: JvColors.textMut, fontSize: 13),
          ),
        ],
      ),
    );
  }
}

String _formatDate(String iso) {
  try {
    // Backend stores created_at as a Unix timestamp float (e.g. "1710854789.123")
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
