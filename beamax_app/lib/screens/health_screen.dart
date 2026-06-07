import '../theme/design_system.dart';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../widgets/cyber_card.dart';
import 'package:provider/provider.dart';

/// Bea Health — Live system observability dashboard
class HealthScreen extends StatefulWidget {
  const HealthScreen({super.key});

  @override
  State<HealthScreen> createState() => _HealthScreenState();
}

class _HealthScreenState extends State<HealthScreen> {
  Map<String, dynamic>? _summary;
  Map<String, dynamic>? _routing;
  Map<String, dynamic>? _tools;
  Map<String, dynamic>? _improvement;
  Map<String, dynamic>? _failures;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchAll();
  }

  Future<void> _fetchAll() async {
    setState(() { _loading = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      final results = await Future.wait([
        api.getJson('/api/v3/metrics/summary'),
        api.getJson('/api/v3/metrics/routing'),
        api.getJson('/api/v3/metrics/tools'),
        api.getJson('/api/v3/metrics/improvement'),
        api.getJson('/api/v3/metrics/failures'),
      ]);
      setState(() {
        _summary = results[0]['data'];
        _routing = results[1]['data'];
        _tools = results[2]['data'];
        _improvement = results[3]['data'];
        _failures = results[4]['data'];
        _loading = false;
      });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BEA HEALTH'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: JvColors.cyan),
            onPressed: _fetchAll,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.error_outline, color: JvColors.red, size: 48),
                    const SizedBox(height: 12),
                    Text(_error!, style: TextStyle(color: JvColors.textSec)),
                    const SizedBox(height: 16),
                    ElevatedButton(onPressed: _fetchAll, child: const Text('Retry')),
                  ],
                ))
              : RefreshIndicator(
                  color: JvColors.cyan,
                  backgroundColor: JvColors.card,
                  onRefresh: _fetchAll,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      _buildHealthBanner(),
                      const SizedBox(height: 12),
                      _buildStatsRow(),
                      const SizedBox(height: 16),
                      _sectionTitle('Active Models'),
                      _buildModelList(),
                      const SizedBox(height: 16),
                      _sectionTitle('Tool Reliability'),
                      _buildToolList(),
                      const SizedBox(height: 16),
                      _sectionTitle('Self-Improvement'),
                      _buildImprovementCard(),
                      const SizedBox(height: 16),
                      if (_failures != null && (_failures!['total_1h'] ?? 0) > 0) ...[
                        _sectionTitle('Failures (1h)'),
                        _buildFailureCard(),
                        const SizedBox(height: 16),
                      ],
                      if (_summary?['alerts'] != null &&
                          (_summary!['alerts'] as List).isNotEmpty) ...[
                        _sectionTitle('Alerts'),
                        _buildAlerts(),
                      ],
                    ],
                  ),
                ),
    );
  }

  Widget _sectionTitle(String title) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Text(title, style: const TextStyle(
      fontSize: 16, fontWeight: FontWeight.w600, color: JvColors.textSec)),
  );

  Widget _buildHealthBanner() {
    final health = _summary?['health'] ?? 'unknown';
    final Color color;
    final IconData icon;
    switch (health) {
      case 'healthy':
        color = JvColors.green; icon = Icons.check_circle; break;
      case 'degraded':
        color = JvColors.orange; icon = Icons.warning; break;
      case 'critical':
        color = JvColors.red; icon = Icons.error; break;
      default:
        color = JvColors.textSec; icon = Icons.help_outline;
    }

    return CyberCard(
      accentColor: color,
      child: Row(
        children: [
          Icon(icon, color: color, size: 36),
          const SizedBox(width: 12),
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('System ${health.toString().toUpperCase()}',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: color)),
              Text('Uptime: ${_formatDuration(_summary?['uptime_s'] ?? 0)}',
                style: const TextStyle(color: JvColors.textSec)),
            ],
          )),
        ],
      ),
    );
  }

  Widget _buildStatsRow() {
    final s = _summary ?? {};
    final missions = s['missions'] ?? {};
    return Row(
      children: [
        _statTile('Success', '${((s['success_rate'] ?? 0) * 100).toStringAsFixed(0)}%',
            (s['success_rate'] ?? 0) >= 0.7 ? JvColors.green : JvColors.red),
        const SizedBox(width: 8),
        _statTile('Missions', '${missions['completed'] ?? 0}/${missions['submitted'] ?? 0}',
            JvColors.cyan),
        const SizedBox(width: 8),
        _statTile('Tools', '${((s['tool_reliability'] ?? 0) * 100).toStringAsFixed(0)}%',
            (s['tool_reliability'] ?? 0) >= 0.8 ? JvColors.green : JvColors.orange),
        const SizedBox(width: 8),
        _statTile('Cost', '\$${(s['cost_today_usd'] ?? 0).toStringAsFixed(3)}',
            JvColors.textSec),
      ],
    );
  }

  Widget _statTile(String label, String value, Color color) => Expanded(
    child: CyberCard(child: Column(
      children: [
        Text(value, style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: color)),
        const SizedBox(height: 2),
        Text(label, style: const TextStyle(fontSize: 11, color: JvColors.textSec)),
      ],
    )),
  );

  Widget _buildModelList() {
    final models = _routing?['models'] as List? ?? [];
    if (models.isEmpty) {
      return CyberCard(child: Text('No model data yet', style: TextStyle(color: JvColors.textSec)));
    }
    return CyberCard(child: Column(
      children: models.take(5).map((m) {
        final name = (m['model'] ?? '').toString().split('/').last;
        final rate = (m['success_rate'] ?? 1.0) as num;
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            children: [
              Expanded(child: Text(name, style: const TextStyle(color: JvColors.textPrim, fontSize: 13),
                overflow: TextOverflow.ellipsis)),
              Text('${m['calls']}', style: const TextStyle(color: JvColors.textSec, fontSize: 12)),
              const SizedBox(width: 8),
              Container(
                width: 50,
                alignment: Alignment.center,
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: rate >= 0.9 ? JvColors.green.withValues(alpha: 0.15) :
                         rate >= 0.7 ? JvColors.orange.withValues(alpha: 0.15) :
                                       JvColors.red.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text('${(rate * 100).toStringAsFixed(0)}%',
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.bold,
                    color: rate >= 0.9 ? JvColors.green : rate >= 0.7 ? JvColors.orange : JvColors.red)),
              ),
            ],
          ),
        );
      }).toList(),
    ));
  }

  Widget _buildToolList() {
    final tools = _tools?['tools'] as List? ?? [];
    if (tools.isEmpty) {
      return CyberCard(child: Text('No tool data yet', style: TextStyle(color: JvColors.textSec)));
    }
    return CyberCard(child: Column(
      children: tools.take(6).map((t) {
        final rate = (t['success_rate'] ?? 1.0) as num;
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            children: [
              Icon(rate >= 0.9 ? Icons.check_circle_outline : Icons.warning_amber,
                size: 14, color: rate >= 0.9 ? JvColors.green : JvColors.orange),
              const SizedBox(width: 6),
              Expanded(child: Text(t['tool'] ?? '', style: const TextStyle(fontSize: 13, color: JvColors.textPrim))),
              Text('${t['calls']}', style: const TextStyle(fontSize: 12, color: JvColors.textSec)),
              const SizedBox(width: 8),
              Text('${(t['avg_latency_ms'] ?? 0).toStringAsFixed(0)}ms',
                style: const TextStyle(fontSize: 11, color: JvColors.textMut)),
            ],
          ),
        );
      }).toList(),
    ));
  }

  Widget _buildImprovementCard() {
    final imp = _improvement ?? {};
    final exp = imp['experiments'] ?? {};
    return CyberCard(child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            _miniStat('Started', '${exp['started'] ?? 0}', JvColors.cyan),
            _miniStat('Promoted', '${exp['promoted'] ?? 0}', JvColors.green),
            _miniStat('Rejected', '${exp['rejected'] ?? 0}', JvColors.red),
            _miniStat('Lessons', '${imp['lessons_learned'] ?? 0}', JvColors.textSec),
          ],
        ),
        if (imp['daemon'] != null && imp['daemon']['running'] == true)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Row(
              children: [
                Icon(Icons.play_circle_fill, size: 14, color: JvColors.green),
                const SizedBox(width: 4),
                Text('Daemon active · ${imp['daemon']['cycles_completed'] ?? 0} cycles',
                  style: const TextStyle(fontSize: 11, color: JvColors.green)),
              ],
            ),
          ),
      ],
    ));
  }

  Widget _miniStat(String label, String value, Color color) => Column(
    children: [
      Text(value, style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: color)),
      Text(label, style: const TextStyle(fontSize: 10, color: JvColors.textMut)),
    ],
  );

  Widget _buildFailureCard() {
    final cats = _failures?['by_category'] as Map? ?? {};
    if (cats.isEmpty) return const SizedBox.shrink();
    return CyberCard(accentColor: JvColors.red, child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: cats.entries.map((e) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            Icon(Icons.error_outline, size: 14, color: JvColors.red),
            const SizedBox(width: 6),
            Expanded(child: Text(e.key, style: const TextStyle(fontSize: 13, color: JvColors.textPrim))),
            Text('${e.value}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold, color: JvColors.red)),
          ],
        ),
      )).toList(),
    ));
  }

  Widget _buildAlerts() {
    final alerts = _summary?['alerts'] as List? ?? [];
    return Column(
      children: alerts.map((a) {
        final sev = a['severity'] ?? 'warning';
        final color = sev == 'critical' ? JvColors.red : JvColors.orange;
        return CyberCard(accentColor: color, child: Row(
          children: [
            Icon(sev == 'critical' ? Icons.error : Icons.warning, color: color, size: 20),
            const SizedBox(width: 8),
            Expanded(child: Text((a['alert'] ?? '').replaceAll('_', ' '),
              style: TextStyle(color: color, fontWeight: FontWeight.w500))),
            Text('${a['current']}', style: TextStyle(color: color, fontWeight: FontWeight.bold)),
          ],
        ));
      }).toList(),
    );
  }

  String _formatDuration(num seconds) {
    final s = seconds.toInt();
    if (s < 60) return '${s}s';
    if (s < 3600) return '${s ~/ 60}m';
    return '${s ~/ 3600}h ${(s % 3600) ~/ 60}m';
  }
}
