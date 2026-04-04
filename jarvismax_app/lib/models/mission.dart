import 'package:flutter/foundation.dart';

// ── Supporting models ─────────────────────────────────────────────────────────

class ReasoningStep {
  final String phase;
  final String content;
  final DateTime? timestamp;

  const ReasoningStep({
    required this.phase,
    required this.content,
    this.timestamp,
  });

  factory ReasoningStep.fromJson(Map<String, dynamic> json) => ReasoningStep(
        phase: json['phase'] as String? ?? 'unknown',
        content: json['content'] as String? ?? '',
        timestamp: json['timestamp'] != null
            ? DateTime.tryParse(json['timestamp'].toString())
            : null,
      );
}

class ActionStep {
  final String tool;
  final String status;
  final double? durationSeconds;
  final String? errorMessage;
  final Map<String, dynamic>? output;

  const ActionStep({
    required this.tool,
    required this.status,
    this.durationSeconds,
    this.errorMessage,
    this.output,
  });

  factory ActionStep.fromJson(Map<String, dynamic> json) => ActionStep(
        tool: json['tool'] as String? ?? 'unknown',
        status: json['status'] as String? ?? 'unknown',
        durationSeconds: (json['duration_seconds'] as num?)?.toDouble(),
        errorMessage: json['error'] as String?,
        output: json['output'] as Map<String, dynamic>?,
      );
}

// ── Mission ───────────────────────────────────────────────────────────────────

class Mission {
  final String id;
  final String userInput;
  final String intent;
  final String status;
  final String planSummary;
  final List<Map<String, dynamic>> planSteps;
  final double advisoryScore;
  final String advisoryDecision;
  final List<Map<String, dynamic>> advisoryIssues;
  final List<Map<String, dynamic>> advisoryRisks;
  final List<String> actionIds;
  final bool requiresValidation;
  final String createdAt;
  final String? completedAt;
  final String note;
  final Map<String, String>? agentOutputs;
  final String? approvalReason;
  final String finalOutput;

  // V1 — champs DQ v2
  final List<String> selectedAgents;
  final List<String> skippedAgents;
  final double confidenceScore;
  final int riskScore;
  final String complexity;
  final String finalOutputSource;
  final int fallbackLevelUsed;
  final String approvalDecision;

  // DQ v2 — champs decision_trace
  final String policyModeUsed;
  final String missionType;
  final bool knowledgeMatch;
  final bool planUsed;
  final String executionPolicyDecision;
  final String executionReason;

  // Phase 2 — observability fields
  final String? traceId;
  final List<ReasoningStep>? reasoningSteps;
  final List<ActionStep>? actionSteps;

  const Mission({
    required this.id,
    required this.userInput,
    required this.intent,
    required this.status,
    this.planSummary = '',
    this.planSteps = const [],
    this.advisoryScore = 0,
    this.advisoryDecision = 'UNKNOWN',
    this.advisoryIssues = const [],
    this.advisoryRisks = const [],
    this.actionIds = const [],
    this.requiresValidation = true,
    this.createdAt = '',
    this.completedAt,
    this.note = '',
    this.agentOutputs,
    this.approvalReason,
    this.finalOutput = '',
    this.selectedAgents = const [],
    this.skippedAgents = const [],
    this.confidenceScore = 0.0,
    this.riskScore = 0,
    this.complexity = '',
    this.finalOutputSource = '',
    this.fallbackLevelUsed = 0,
    this.approvalDecision = '',
    this.policyModeUsed = '',
    this.missionType = '',
    this.knowledgeMatch = false,
    this.planUsed = false,
    this.executionPolicyDecision = '',
    this.executionReason = '',
    this.traceId,
    this.reasoningSteps,
    this.actionSteps,
  });

  factory Mission.empty() => const Mission(
        id: '',
        userInput: '',
        intent: '',
        status: 'UNKNOWN',
      );

  factory Mission.fromJson(Map<String, dynamic> j) {
    try {
      final dt = j['decision_trace'] as Map?;
      return Mission(
        id: _s(j['id'] ?? j['mission_id']),
        // Canonical v3 uses 'goal'; legacy v1/v2 uses 'user_input'
        userInput: _s(j['user_input'] ?? j['goal']),
        intent: _s(j['intent'], 'OTHER'),
        // Normalize: canonical v3 returns 'COMPLETED'/'CANCELLED', app uses 'DONE'/'FAILED'
        status: _normalizeStatus(_s(j['status'], 'UNKNOWN')),
        planSummary: _s(j['plan_summary']),
        planSteps: _lmap(j['plan_steps']),
        advisoryScore: _d(j['advisory_score']),
        advisoryDecision: _s(j['advisory_decision'], 'UNKNOWN'),
        advisoryIssues: _lmap(j['advisory_issues']),
        advisoryRisks: _lmap(j['advisory_risks']),
        actionIds: _lstr(j['action_ids']),
        requiresValidation: _b(j['requires_validation'], d: true),
        createdAt: _s(j['created_at']),
        completedAt: j['completed_at']?.toString(),
        note: _s(j['note']),
        agentOutputs: _mstr(j['agent_outputs']),
        approvalReason: j['approval_reason']?.toString(),
        // Canonical v3 uses 'result'; legacy uses 'final_output' or 'output'
        finalOutput:
            j['final_output']?.toString() ?? j['result']?.toString() ?? j['output']?.toString() ?? '',
        // Canonical v3 returns agents as list under 'agents'; legacy uses 'agents_selected'
        selectedAgents: _lstr(j['agents_selected'] ?? j['agents']),
        skippedAgents: _lstr(j['skipped_agents']),
        confidenceScore: _d(j['confidence_score']),
        riskScore: _i(j['risk_score']),
        complexity: _s(j['complexity']),
        // Canonical v3 uses 'source_system' as a proxy for finalOutputSource
        finalOutputSource: _s(j['final_output_source'] ?? j['source_system']),
        fallbackLevelUsed: _i(j['fallback_level_used']),
        approvalDecision: _s(j['approval_decision']),
        policyModeUsed: _s(dt?['policy_mode_used']),
        missionType: _s(dt?['mission_type']),
        knowledgeMatch: _b(dt?['knowledge_match']),
        planUsed: _b(dt?['plan_used']),
        executionPolicyDecision: _s(dt?['execution_policy_decision']),
        executionReason: _s(dt?['execution_reason']),
        traceId: j['trace_id'] as String? ?? j['task_id']?.toString(),
        reasoningSteps: _parseReasoningSteps(j['reasoning_steps']),
        actionSteps: _parseActionSteps(j['action_steps']),
      );
    } catch (e) {
      debugPrint('Mission.fromJson error: $e');
      return Mission.empty();
    }
  }

  /// Normalize canonical API status to the vocabulary the app uses internally.
  /// Canonical v3 returns 'COMPLETED' and 'CANCELLED'; app was built around 'DONE'/'FAILED'.
  /// This maps them through so existing status checks (isDone, isTerminal) remain correct.
  static String _normalizeStatus(String raw) {
    switch (raw) {
      case 'COMPLETED': return 'DONE';
      case 'CANCELLED': return 'FAILED';
      default:          return raw;
    }
  }

  // ── Defensive helpers ──────────────────────────────────────────────────────
  static String _s(dynamic v, [String d = '']) => v?.toString() ?? d;
  static double _d(dynamic v, [double d = 0.0]) =>
      double.tryParse(v?.toString() ?? '') ?? d;
  static int _i(dynamic v, [int d = 0]) =>
      int.tryParse(v?.toString() ?? '') ?? d;
  static bool _b(dynamic v, {bool d = false}) =>
      v == true || v?.toString().toLowerCase() == 'true'
          ? true
          : (v == false ? false : d);
  static List<String> _lstr(dynamic v) {
    if (v is! List) return [];
    return v
        .map((e) => e?.toString() ?? '')
        .where((s) => s.isNotEmpty)
        .toList();
  }

  static List<Map<String, dynamic>> _lmap(dynamic v) {
    if (v is! List) return [];
    return v
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
  }

  static Map<String, String>? _mstr(dynamic v) {
    if (v is! Map || v.isEmpty) return null;
    return v.map((k, val) => MapEntry(k.toString(), val?.toString() ?? ''));
  }

  static List<ReasoningStep>? _parseReasoningSteps(dynamic v) {
    if (v is! List || v.isEmpty) return null;
    try {
      return v
          .whereType<Map>()
          .map((e) => ReasoningStep.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    } catch (_) {
      return null;
    }
  }

  static List<ActionStep>? _parseActionSteps(dynamic v) {
    if (v is! List || v.isEmpty) return null;
    try {
      return v
          .whereType<Map>()
          .map((e) => ActionStep.fromJson(Map<String, dynamic>.from(e)))
          .toList();
    } catch (_) {
      return null;
    }
  }

  /// Auto-generated display title from first ~60 chars of goal.
  String get displayTitle {
    if (userInput.isEmpty) return 'Mission ${id.substring(0, 8.clamp(0, id.length))}';
    return userInput.length > 60
        ? '${userInput.substring(0, 60)}…'
        : userInput;
  }

  String get statusLabel => status.replaceAll('_', ' ');
  bool get isPending => status == 'CREATED' || status == 'PLANNED';
  bool get isRunning => status == 'RUNNING' || status == 'REVIEW';
  bool get isApproved => status == 'PLANNED';
  bool get isDone => status == 'DONE';
  bool get isFailed => status == 'FAILED';
  bool get isRejected => status == 'REJECTED';
  bool get isExecuting => status == 'EXECUTING';
  bool get isActive =>
      status == 'RUNNING' || status == 'PLANNED' || status == 'REVIEW';
  bool get isTerminal =>
      status == 'DONE' || status == 'FAILED' || status == 'REJECTED';
}
