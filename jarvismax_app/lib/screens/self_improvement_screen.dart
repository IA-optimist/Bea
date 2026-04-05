import '../theme/design_system.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../widgets/cyber_card.dart';

class SelfImprovementScreen extends StatefulWidget {
  const SelfImprovementScreen({super.key});

  @override
  State<SelfImprovementScreen> createState() => _SelfImprovementScreenState();
}

class _SelfImprovementScreenState extends State<SelfImprovementScreen> {
  List<Map<String, dynamic>> _suggestions = [];
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    final result =
        await context.read<ApiService>().getSelfImprovementSuggestions();
    if (!mounted) return;
    setState(() {
      _loading = false;
      if (result.ok && result.data != null) {
        _suggestions = result.data!;
      } else {
        _error = result.error;
      }
    });
  }

  void _dismiss(int index) {
    setState(() => _suggestions.removeAt(index));
  }

  Future<void> _approve(int index) async {
    final s = _suggestions[index];
    final text = s['suggested_change']?.toString() ??
        s['problem_type']?.toString() ?? 'self-improve';
    setState(() => _suggestions.removeAt(index));
    if (!mounted) return;
    await context.read<ApiService>().submitMission(
        '[AUTO-AMÉLIORATION] $text');
  }

  Color _priorityColor(double score) {
    if (score >= 0.7) return JvColors.red;
    if (score >= 0.4) return JvColors.orange;
    return JvColors.green;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AUTO-AMÉLIORATION'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: JvColors.cyan),
            onPressed: _load,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      _error!,
                      style: const TextStyle(color: JvColors.textMut),
                      textAlign: TextAlign.center,
                    ),
                  ),
                )
              : RefreshIndicator(
                  color: JvColors.cyan,
                  backgroundColor: JvColors.card,
                  onRefresh: _load,
                  child: _suggestions.isEmpty
                      ? ListView(
                          padding: const EdgeInsets.all(24),
                          children: const [
                            Center(
                              child: Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(Icons.auto_awesome,
                                      size: 48, color: JvColors.textMut),
                                  SizedBox(height: 16),
                                  Text(
                                    'Aucune suggestion — continuez à utiliser '
                                    'Jarvis pour générer des données.',
                                    style: TextStyle(color: JvColors.textMut),
                                    textAlign: TextAlign.center,
                                  ),
                                ],
                              ),
                            ),
                          ],
                        )
                      : ListView.builder(
                          padding: const EdgeInsets.all(16),
                          itemCount: _suggestions.length,
                          itemBuilder: (context, index) {
                            final s = _suggestions[index];
                            return _SuggestionCard(
                              data: s,
                              priorityColor: _priorityColor,
                              onApprove: () => _approve(index),
                              onDismiss: () => _dismiss(index),
                            );
                          },
                        ),
                ),
    );
  }
}

class _SuggestionCard extends StatelessWidget {
  final Map<String, dynamic> data;
  final Color Function(double) priorityColor;
  final VoidCallback onApprove;
  final VoidCallback onDismiss;

  const _SuggestionCard({
    required this.data,
    required this.priorityColor,
    required this.onApprove,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    final problemType = data['problem_type']?.toString() ?? 'unknown';
    final missionType = data['mission_type']?.toString() ?? '';
    final frequency = int.tryParse(data['frequency']?.toString() ?? '0') ?? 0;
    final priorityScore =
        (data['priority_score'] as num?)?.toDouble() ?? 0.0;
    final impactEstimate = data['impact_estimate']?.toString() ?? '';
    final riskEstimate = data['risk_estimate']?.toString() ?? '';
    final suggestedChange = data['suggested_change']?.toString() ?? '';
    final affectedFilesRaw = data['affected_files'];
    final affectedFiles = affectedFilesRaw is List
        ? affectedFilesRaw.map((e) => e.toString()).toList()
        : <String>[];

    final pColor = priorityColor(priorityScore);

    return CyberCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            children: [
              Expanded(
                child: Text(
                  problemType,
                  style: const TextStyle(
                    color: JvColors.textPrim,
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              if (missionType.isNotEmpty)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: JvColors.border,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    missionType,
                    style: const TextStyle(
                        color: JvColors.textSec, fontSize: 10),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 4),
          // Frequency
          Text(
            'Fréquence : $frequency occurrences',
            style: const TextStyle(color: JvColors.textMut, fontSize: 11),
          ),
          const SizedBox(height: 8),
          // Priority bar
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text('Priorité',
                      style:
                          TextStyle(color: JvColors.textMut, fontSize: 11)),
                  Text(
                    '${(priorityScore * 100).toStringAsFixed(0)}%',
                    style: TextStyle(
                        color: pColor,
                        fontSize: 11,
                        fontWeight: FontWeight.w700),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: priorityScore.clamp(0.0, 1.0),
                  backgroundColor: JvColors.border,
                  valueColor: AlwaysStoppedAnimation<Color>(pColor),
                  minHeight: 6,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          // Impact + Risk chips
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              if (impactEstimate.isNotEmpty)
                _Chip(
                    label: 'impact: $impactEstimate',
                    color: JvColors.cyan.withValues(alpha: 0.12),
                    textColor: JvColors.cyan),
              if (riskEstimate.isNotEmpty)
                _Chip(
                    label: 'risk: $riskEstimate',
                    color: JvColors.orange.withValues(alpha: 0.12),
                    textColor: JvColors.orange),
            ],
          ),
          if (suggestedChange.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text(
              'Changement suggéré',
              style: TextStyle(color: JvColors.textMut, fontSize: 11),
            ),
            const SizedBox(height: 3),
            Text(
              suggestedChange,
              style:
                  const TextStyle(color: JvColors.textSec, fontSize: 12),
            ),
          ],
          if (affectedFiles.isNotEmpty) ...[
            const SizedBox(height: 8),
            const Text(
              'Fichiers concernés',
              style: TextStyle(color: JvColors.textMut, fontSize: 11),
            ),
            const SizedBox(height: 3),
            ...affectedFiles.map((f) => Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Text(
                    '• $f',
                    style: const TextStyle(
                        color: JvColors.textMut,
                        fontSize: 11,
                        fontFamily: 'monospace'),
                  ),
                )),
          ],
          const SizedBox(height: 12),
          // Buttons
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: onApprove,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: JvColors.green,
                    side: const BorderSide(color: JvColors.green),
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  child: const Text('Approuver',
                      style: TextStyle(fontSize: 12)),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: OutlinedButton(
                  onPressed: onDismiss,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: JvColors.textMut,
                    side: const BorderSide(color: JvColors.textMut),
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  child:
                      const Text('Ignorer', style: TextStyle(fontSize: 12)),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  final String label;
  final Color color;
  final Color textColor;
  const _Chip(
      {required this.label, required this.color, required this.textColor});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
      decoration:
          BoxDecoration(color: color, borderRadius: BorderRadius.circular(4)),
      child: Text(label, style: TextStyle(color: textColor, fontSize: 11)),
    );
  }
}
