import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/autonomy_decision.dart';
import '../services/api_service.dart';

/// DecisionsScreen — pending multi-choice decisions from the autonomy
/// daemon. Each card shows the question + N choices ; tapping a choice
/// answers the decision and removes it from the list.
///
/// The screen polls /api/v3/autonomy/decisions every 5 s when visible.
/// In a future version this can switch to WebSocket events on the
/// `decision.created` topic.
class DecisionsScreen extends StatefulWidget {
  const DecisionsScreen({super.key});

  @override
  State<DecisionsScreen> createState() => _DecisionsScreenState();
}

class _DecisionsScreenState extends State<DecisionsScreen> {
  List<AutonomyDecision> _decisions = const [];
  bool _loading = true;
  String? _error;
  Timer? _pollTimer;
  final Set<String> _answering = <String>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _refresh();
      _pollTimer = Timer.periodic(
        const Duration(seconds: 5),
        (_) => _refresh(silent: true),
      );
    });
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  Future<void> _refresh({bool silent = false}) async {
    if (!mounted) return;
    if (!silent) setState(() => _loading = true);
    try {
      final api = context.read<ApiService>();
      final list = await api.fetchPendingDecisions();
      if (!mounted) return;
      setState(() {
        _decisions = list;
        _error = null;
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

  Future<void> _answer(AutonomyDecision d, int index) async {
    setState(() => _answering.add(d.decisionId));
    final api = context.read<ApiService>();
    final ok = await api.answerDecision(d.decisionId, index);
    if (!mounted) return;
    setState(() => _answering.remove(d.decisionId));
    if (ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text("Décision « ${d.name} » envoyée — choix : ${d.choices[index].label}")),
      );
      await _refresh();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Échec de l'envoi de la décision. Réessayer ?")),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Décisions en attente'),
        actions: [
          IconButton(
            tooltip: 'Rafraîchir',
            icon: const Icon(Icons.refresh),
            onPressed: _refresh,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_loading && _decisions.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null && _decisions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 48, color: Colors.redAccent),
              const SizedBox(height: 12),
              Text("Erreur de chargement : $_error",
                  textAlign: TextAlign.center),
              const SizedBox(height: 16),
              ElevatedButton(onPressed: _refresh, child: const Text('Réessayer')),
            ],
          ),
        ),
      );
    }
    if (_decisions.isEmpty) {
      return RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          children: const [
            SizedBox(height: 120),
            Center(
              child: Padding(
                padding: EdgeInsets.symmetric(horizontal: 32),
                child: Column(
                  children: [
                    Icon(Icons.check_circle_outline, size: 64, color: Colors.green),
                    SizedBox(height: 16),
                    Text(
                      'Aucune décision en attente.',
                      style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                    ),
                    SizedBox(height: 8),
                    Text(
                      "Le daemon d'autonomie ne sollicite ton choix sur rien actuellement.",
                      textAlign: TextAlign.center,
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: _decisions.length,
        separatorBuilder: (_, __) => const SizedBox(height: 16),
        itemBuilder: (_, i) => _DecisionCard(
          decision: _decisions[i],
          isAnswering: _answering.contains(_decisions[i].decisionId),
          onChoose: (idx) => _answer(_decisions[i], idx),
        ),
      ),
    );
  }
}

class _DecisionCard extends StatelessWidget {
  final AutonomyDecision decision;
  final bool isAnswering;
  final void Function(int) onChoose;

  const _DecisionCard({
    required this.decision,
    required this.isAnswering,
    required this.onChoose,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header : name + risk badge
            Row(
              children: [
                Expanded(
                  child: Text(
                    decision.name,
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 16,
                    ),
                  ),
                ),
                _RiskBadge(level: decision.maxRiskLevel),
              ],
            ),
            const SizedBox(height: 8),
            Text(decision.question),
            const SizedBox(height: 16),
            const Text('Choisis une stratégie :',
                style: TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            ...List.generate(
              decision.choices.length,
              (i) => _ChoiceTile(
                choice: decision.choices[i],
                disabled: isAnswering,
                onTap: () => onChoose(i),
              ),
            ),
            if (isAnswering) ...[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
            ],
          ],
        ),
      ),
    );
  }
}

class _ChoiceTile extends StatelessWidget {
  final DecisionChoice choice;
  final bool disabled;
  final VoidCallback onTap;

  const _ChoiceTile({
    required this.choice,
    required this.disabled,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      decoration: BoxDecoration(
        border: Border.all(color: Colors.grey.shade300),
        borderRadius: BorderRadius.circular(8),
      ),
      child: ListTile(
        onTap: disabled ? null : onTap,
        title: Row(
          children: [
            Expanded(
              child: Text(choice.label,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            _RiskBadge(level: choice.riskLevel, compact: true),
          ],
        ),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (choice.description.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(choice.description),
              ),
            if (choice.estimatedCostUsd > 0 || choice.estimatedDurationS > 0)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  _meta(choice),
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                ),
              ),
          ],
        ),
        trailing: const Icon(Icons.chevron_right),
      ),
    );
  }

  String _meta(DecisionChoice c) {
    final parts = <String>[];
    if (c.estimatedCostUsd > 0) {
      parts.add('~\$${c.estimatedCostUsd.toStringAsFixed(2)}');
    }
    if (c.estimatedDurationS > 0) {
      final d = c.estimatedDurationS;
      parts.add(d > 120 ? '~${(d / 60).toStringAsFixed(1)} min' : '~${d.toInt()} s');
    }
    if (c.rollbackPlan.isNotEmpty) parts.add('rollback : ${c.rollbackPlan}');
    return parts.join(' • ');
  }
}

class _RiskBadge extends StatelessWidget {
  final String level;
  final bool compact;

  const _RiskBadge({required this.level, this.compact = false});

  @override
  Widget build(BuildContext context) {
    Color bg;
    Color fg = Colors.white;
    switch (level) {
      case 'critical':
        bg = Colors.red.shade900;
      case 'high':
        bg = Colors.red.shade400;
      case 'medium':
        bg = Colors.orange.shade400;
      case 'low':
      default:
        bg = Colors.green.shade400;
    }
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 6 : 10,
        vertical: compact ? 2 : 4,
      ),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(compact ? 4 : 6),
      ),
      child: Text(
        level.toUpperCase(),
        style: TextStyle(
          color: fg,
          fontSize: compact ? 10 : 12,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }
}
