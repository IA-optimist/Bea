/// AutonomyDecision — model mirroring core.autonomy.multi_choice.Decision.
///
/// Represents a multi-choice question the autonomy daemon asks the
/// operator. The Flutter app fetches pending decisions from
/// `/api/v3/autonomy/decisions` and posts answers to
/// `/api/v3/autonomy/decisions/{id}/answer`.

class DecisionChoice {
  final int index;
  final String label;
  final String description;
  final String riskLevel;
  final double estimatedCostUsd;
  final double estimatedDurationS;
  final String rollbackPlan;

  DecisionChoice({
    required this.index,
    required this.label,
    this.description = '',
    this.riskLevel = 'low',
    this.estimatedCostUsd = 0.0,
    this.estimatedDurationS = 0.0,
    this.rollbackPlan = '',
  });

  factory DecisionChoice.fromJson(Map<String, dynamic> json) {
    final meta = (json['metadata'] as Map<String, dynamic>?) ?? const {};
    return DecisionChoice(
      index: (json['index'] as num?)?.toInt() ?? 0,
      label: (json['label'] ?? '').toString(),
      description: (json['description'] ?? '').toString(),
      riskLevel: (meta['risk_level'] ?? 'low').toString(),
      estimatedCostUsd: (meta['estimated_cost_usd'] as num?)?.toDouble() ?? 0.0,
      estimatedDurationS: (meta['estimated_duration_s'] as num?)?.toDouble() ?? 0.0,
      rollbackPlan: (meta['rollback_plan'] ?? '').toString(),
    );
  }
}

class AutonomyDecision {
  final String decisionId;
  final String name;
  final String question;
  final List<DecisionChoice> choices;
  final double timeoutS;
  final int defaultChoice;
  final double createdAt;
  final String status;
  final String maxRiskLevel;

  AutonomyDecision({
    required this.decisionId,
    required this.name,
    required this.question,
    required this.choices,
    this.timeoutS = 0.0,
    this.defaultChoice = -1,
    this.createdAt = 0.0,
    this.status = 'pending',
    this.maxRiskLevel = 'low',
  });

  factory AutonomyDecision.fromJson(Map<String, dynamic> json) {
    final rawChoices = (json['choices'] as List<dynamic>?) ?? const [];
    final meta = (json['metadata'] as Map<String, dynamic>?) ?? const {};
    return AutonomyDecision(
      decisionId: (json['decision_id'] ?? '').toString(),
      name: (json['name'] ?? '').toString(),
      question: (json['question'] ?? '').toString(),
      choices: rawChoices
          .whereType<Map<String, dynamic>>()
          .map(DecisionChoice.fromJson)
          .toList(),
      timeoutS: (json['timeout_s'] as num?)?.toDouble() ?? 0.0,
      defaultChoice: (json['default_choice'] as num?)?.toInt() ?? -1,
      createdAt: (json['created_at'] as num?)?.toDouble() ?? 0.0,
      status: (json['status'] ?? 'pending').toString(),
      maxRiskLevel: (meta['max_risk_level'] ?? 'low').toString(),
    );
  }

  bool get isPending => status == 'pending';
  Duration get age => Duration(
    milliseconds: ((DateTime.now().millisecondsSinceEpoch / 1000.0) - createdAt).toInt() * 1000,
  );
}
