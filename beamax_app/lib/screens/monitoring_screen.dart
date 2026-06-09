import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_service.dart';
import '../theme/design_system.dart';
import '../widgets/cyber_card.dart';

/// MonitoringScreen — observabilité LLM (coût / erreurs / latence / par modèle).
/// Consomme GET /api/v3/metrics/llm (LLMTracer.stats()). Rafraîchit toutes les 15 s.
class MonitoringScreen extends StatefulWidget {
  const MonitoringScreen({super.key});

  @override
  State<MonitoringScreen> createState() => _MonitoringScreenState();
}

class _MonitoringScreenState extends State<MonitoringScreen> {
  Map<String, dynamic> _stats = {};
  bool _loading = true;
  String _error = '';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await context.read<ApiService>().getJson('/api/v3/metrics/llm');
      if (!mounted) return;
      setState(() {
        _stats = d;
        _error = '';
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final calls = (_stats['calls'] ?? 0).toString();
    final cost = (_stats['cost_usd'] ?? 0).toString();
    final tokens = (_stats['total_tokens'] ?? 0).toString();
    final errRate = _stats['error_rate'] is num
        ? '${((_stats['error_rate'] as num) * 100).toStringAsFixed(1)}%'
        : '—';
    final byModel = (_stats['by_model'] is Map)
        ? Map<String, dynamic>.from(_stats['by_model'] as Map)
        : <String, dynamic>{};

    return Scaffold(
      appBar: AppBar(
        title: const Text('MONITORING'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: JDS.blue),
            onPressed: _load,
          ),
        ],
      ),
      body: _loading
          ? const Center(
              child: CircularProgressIndicator(color: JDS.blue, strokeWidth: 2))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  if (_error.isNotEmpty)
                    Container(
                      margin: const EdgeInsets.only(bottom: 12),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: JDS.red.withValues(alpha: 0.07),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: JDS.red.withValues(alpha: 0.3)),
                      ),
                      child: Text('Métriques indisponibles: $_error',
                          style: const TextStyle(color: JDS.red, fontSize: 12)),
                    ),
                  Row(
                    children: [
                      _MetricTile(label: 'Appels LLM', value: calls, color: JDS.blue),
                      const SizedBox(width: 10),
                      _MetricTile(label: 'Coût (USD)', value: cost, color: JDS.green),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      _MetricTile(label: "Taux d'erreur", value: errRate, color: JDS.amber),
                      const SizedBox(width: 10),
                      _MetricTile(label: 'Tokens', value: tokens, color: JDS.textSecondary),
                    ],
                  ),
                  const SizedBox(height: 16),
                  const Text('PAR MODÈLE',
                      style: TextStyle(
                        color: JDS.textMuted,
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1.2,
                      )),
                  const SizedBox(height: 8),
                  if (byModel.isEmpty)
                    CyberCard(
                      child: const Text('Aucun appel tracé pour le moment.',
                          style: TextStyle(color: JDS.textMuted, fontSize: 12)),
                    )
                  else
                    ...byModel.entries.map((e) {
                      final m = e.value is Map
                          ? Map<String, dynamic>.from(e.value as Map)
                          : <String, dynamic>{};
                      return CyberCard(
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Expanded(
                              child: Text(e.key,
                                  style: const TextStyle(
                                    color: JDS.textPrimary,
                                    fontSize: 13,
                                    fontFamily: 'monospace',
                                  )),
                            ),
                            Text('${m['calls'] ?? 0} appels',
                                style: const TextStyle(
                                    color: JDS.textSecondary, fontSize: 12)),
                            const SizedBox(width: 12),
                            Text('\$${m['cost_usd'] ?? 0}',
                                style: const TextStyle(
                                    color: JDS.green, fontSize: 12)),
                          ],
                        ),
                      );
                    }),
                ],
              ),
            ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _MetricTile(
      {required this.label, required this.value, required this.color});

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: JDS.bgSurface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withValues(alpha: 0.3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: const TextStyle(color: JDS.textMuted, fontSize: 11)),
            const SizedBox(height: 6),
            Text(value,
                style: TextStyle(
                    color: color, fontSize: 20, fontWeight: FontWeight.w800)),
          ],
        ),
      ),
    );
  }
}
