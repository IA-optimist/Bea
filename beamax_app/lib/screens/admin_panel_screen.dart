import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../theme/design_system.dart';

/// Admin Panel — opérateur view.
/// Mission stats, coût modèle, santé système, alertes.
class AdminPanelScreen extends StatefulWidget {
  const AdminPanelScreen({super.key});

  @override
  State<AdminPanelScreen> createState() => _AdminPanelScreenState();
}

class _AdminPanelScreenState extends State<AdminPanelScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  Future<void> _fetch() async {
    setState(() { _loading = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      final resp = await api.getJson('/api/v3/metrics/summary');
      if (resp['ok'] == true) {
        setState(() { _data = resp['data'] as Map<String, dynamic>?; _loading = false; });
      } else {
        setState(() { _error = resp['error']?.toString() ?? 'Erreur inconnue'; _loading = false; });
      }
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: CustomScrollView(slivers: [
          // ── Header ──
          SliverToBoxAdapter(child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
            child: Row(children: [
              const Text('Panneau Admin', style: TextStyle(
                fontSize: 22, fontWeight: FontWeight.w700,
                color: JDS.textPrimary, letterSpacing: -0.3,
              )),
              const Spacer(),
              GestureDetector(
                onTap: _fetch,
                child: Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: JDS.bgSurface,
                    borderRadius: BorderRadius.circular(JDS.radiusSm),
                    border: Border.all(color: JDS.borderSubtle),
                  ),
                  child: const Icon(Icons.refresh_rounded, size: 18, color: JDS.textMuted),
                ),
              ),
            ]),
          )),

          if (_loading)
            const SliverFillRemaining(child: Center(
              child: CircularProgressIndicator(color: JDS.blue),
            ))
          else if (_error != null)
            SliverFillRemaining(child: _ErrorState(error: _error!, onRetry: _fetch))
          else if (_data != null)
            ..._buildContent(_data!),

          const SliverToBoxAdapter(child: SizedBox(height: 100)),
        ]),
      ),
    );
  }

  List<Widget> _buildContent(Map<String, dynamic> d) {
    final health       = d['health'] as String? ?? 'unknown';
    final successRate  = (d['success_rate'] as num?)?.toDouble() ?? 0.0;
    final missions     = d['missions'] as Map<String, dynamic>? ?? {};
    final submitted    = missions['submitted'] as int? ?? 0;
    final completed    = missions['completed'] as int? ?? 0;
    final failed       = missions['failed']    as int? ?? 0;
    final costToday    = (d['cost_today_usd'] as num?)?.toDouble() ?? 0.0;
    final durationMs   = (d['duration_avg_ms'] as num?)?.toDouble() ?? 0.0;
    final toolRate     = (d['tool_reliability'] as num?)?.toDouble() ?? 1.0;
    final uptimeS      = (d['uptime_s'] as num?)?.toDouble() ?? 0.0;
    final models       = (d['active_models'] as List<dynamic>?) ?? [];
    final alerts       = (d['alerts'] as List<dynamic>?) ?? [];

    final healthColor = switch (health) {
      'healthy'  => JDS.green,
      'degraded' => JDS.amber,
      _          => JDS.red,
    };
    final healthLabel = switch (health) {
      'healthy'  => 'Système OK',
      'degraded' => 'Dégradé',
      _          => 'Critique',
    };

    return [
      // ── Health banner ──
      SliverToBoxAdapter(child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: healthColor.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(JDS.radiusMd),
            border: Border.all(color: healthColor.withValues(alpha: 0.25)),
          ),
          child: Row(children: [
            Container(
              width: 10, height: 10,
              decoration: BoxDecoration(
                color: healthColor,
                shape: BoxShape.circle,
                boxShadow: [BoxShadow(color: healthColor.withValues(alpha: 0.4), blurRadius: 6)],
              ),
            ),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(healthLabel, style: TextStyle(
                fontSize: 14, fontWeight: FontWeight.w700, color: healthColor,
              )),
              Text(
                'Uptime ${_formatUptime(uptimeS)}  ·  Taux succès ${(successRate * 100).round()}%',
                style: const TextStyle(fontSize: 12, color: JDS.textSecondary),
              ),
            ])),
            Text('${(successRate * 100).round()}%', style: TextStyle(
              fontSize: 22, fontWeight: FontWeight.w800, color: healthColor,
            )),
          ]),
        ),
      )),

      // ── Alerts ──
      if (alerts.isNotEmpty) ...[
        SliverToBoxAdapter(child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
          child: JSectionHeader(title: 'Alertes', count: '${alerts.length}'),
        )),
        SliverList(delegate: SliverChildBuilderDelegate(
          (_, i) {
            final a = alerts[i] as Map<String, dynamic>;
            final sev = a['severity'] as String? ?? 'info';
            final color = switch (sev) {
              'critical' => JDS.red,
              'warning'  => JDS.amber,
              _          => JDS.blue,
            };
            return Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 6),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.08),
                  borderRadius: BorderRadius.circular(JDS.radiusSm),
                  border: Border.all(color: color.withValues(alpha: 0.2)),
                ),
                child: Row(children: [
                  Icon(Icons.warning_amber_rounded, size: 16, color: color),
                  const SizedBox(width: 8),
                  Expanded(child: Text(
                    a['alert']?.toString() ?? '',
                    style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w500),
                  )),
                ]),
              ),
            );
          },
          childCount: alerts.length,
        )),
        const SliverToBoxAdapter(child: SizedBox(height: 8)),
      ],

      // ── Mission stats ──
      SliverToBoxAdapter(child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
        child: JSectionHeader(title: 'Missions'),
      )),
      SliverToBoxAdapter(child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: Row(children: [
          Expanded(child: _StatCard(value: '$submitted', label: 'Soumises', color: JDS.blue)),
          const SizedBox(width: 10),
          Expanded(child: _StatCard(value: '$completed', label: 'Réussies', color: JDS.green)),
          const SizedBox(width: 10),
          Expanded(child: _StatCard(value: '$failed', label: 'Échouées', color: JDS.red)),
        ]),
      )),
      const SliverToBoxAdapter(child: SizedBox(height: 16)),

      // ── Performance ──
      SliverToBoxAdapter(child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
        child: JSectionHeader(title: 'Performance'),
      )),
      SliverToBoxAdapter(child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: JCard(child: Column(children: [
          _MetricRow(
            icon: Icons.timer_outlined,
            label: 'Durée moyenne',
            value: durationMs >= 1000
                ? '${(durationMs / 1000).toStringAsFixed(1)}s'
                : '${durationMs.round()}ms',
            color: JDS.textSecondary,
          ),
          const Divider(height: 20),
          _MetricRow(
            icon: Icons.build_outlined,
            label: 'Fiabilité outils',
            value: '${(toolRate * 100).round()}%',
            color: toolRate >= 0.9 ? JDS.green : toolRate >= 0.7 ? JDS.amber : JDS.red,
          ),
        ])),
      )),
      const SliverToBoxAdapter(child: SizedBox(height: 16)),

      // ── Coût ──
      SliverToBoxAdapter(child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
        child: JSectionHeader(title: 'Coût modèles'),
      )),
      SliverToBoxAdapter(child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20),
        child: JCard(child: Column(children: [
          _MetricRow(
            icon: Icons.attach_money_rounded,
            label: 'Coût aujourd\'hui',
            value: '\$${costToday.toStringAsFixed(4)}',
            color: costToday < 0.5 ? JDS.green : costToday < 2.0 ? JDS.amber : JDS.red,
          ),
          if (models.isNotEmpty) ...[
            const Divider(height: 20),
            ...models.take(3).map<Widget>((m) {
              final name  = m['model'] as String? ?? '?';
              final calls = m['calls'] as int? ?? 0;
              final pct   = submitted > 0 ? calls / submitted : 0.0;
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(children: [
                  Container(
                    width: 8, height: 8,
                    decoration: const BoxDecoration(color: JDS.blue, shape: BoxShape.circle),
                  ),
                  const SizedBox(width: 10),
                  Expanded(child: Text(
                    name.length > 20 ? '${name.substring(0, 20)}…' : name,
                    style: const TextStyle(fontSize: 12, color: JDS.textSecondary),
                  )),
                  Text(
                    '$calls appels (${(pct * 100).round()}%)',
                    style: const TextStyle(fontSize: 11, color: JDS.textDim),
                  ),
                ]),
              );
            }),
          ],
        ])),
      )),
    ];
  }

  String _formatUptime(double secs) {
    if (secs < 60) return '${secs.round()}s';
    if (secs < 3600) return '${(secs / 60).floor()}min';
    if (secs < 86400) return '${(secs / 3600).floor()}h';
    return '${(secs / 86400).floor()}j';
  }
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

class _StatCard extends StatelessWidget {
  final String value;
  final String label;
  final Color color;
  const _StatCard({required this.value, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: color.withValues(alpha: 0.2)),
      ),
      child: Column(children: [
        Text(value, style: TextStyle(
          fontSize: 22, fontWeight: FontWeight.w800, color: color, height: 1,
        )),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(
          fontSize: 11, color: JDS.textMuted, fontWeight: FontWeight.w500,
        )),
      ]),
    );
  }
}

// ── Metric Row ────────────────────────────────────────────────────────────────

class _MetricRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;
  const _MetricRow({required this.icon, required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Icon(icon, size: 18, color: JDS.textMuted),
      const SizedBox(width: 12),
      Text(label, style: const TextStyle(fontSize: 14, color: JDS.textSecondary)),
      const Spacer(),
      Text(value, style: TextStyle(fontSize: 14, color: color, fontWeight: FontWeight.w600)),
    ]);
  }
}

// ── Error State ───────────────────────────────────────────────────────────────

class _ErrorState extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;
  const _ErrorState({required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(child: Column(mainAxisSize: MainAxisSize.min, children: [
      const Icon(Icons.error_outline_rounded, size: 48, color: JDS.red),
      const SizedBox(height: 12),
      Text(error, style: const TextStyle(color: JDS.textSecondary, fontSize: 13),
          textAlign: TextAlign.center),
      const SizedBox(height: 16),
      ElevatedButton(onPressed: onRetry, child: const Text('Réessayer')),
    ]));
  }
}
