class ActionModel {
  final String id;
  final String description;
  final String risk;
  final String target;
  final String impact;
  final String diff;
  final String rollback;
  final String missionId;
  final String status;
  final double createdAt;
  final double? approvedAt;
  final double? rejectedAt;
  final double? executedAt;
  final String result;
  final String note;
  final String? approvalReason;

  const ActionModel({
    required this.id,
    required this.description,
    required this.risk,
    required this.target,
    required this.impact,
    this.diff = '',
    this.rollback = '',
    this.missionId = '',
    required this.status,
    this.createdAt = 0,
    this.approvedAt,
    this.rejectedAt,
    this.executedAt,
    this.result = '',
    this.note = '',
    this.approvalReason,
  });

  factory ActionModel.fromJson(Map<String, dynamic> j) => ActionModel(
    id:             _s(j['id']),
    description:    _s(j['description']),
    risk:           _s(j['risk'], 'LOW'),
    target:         _s(j['target']),
    impact:         _s(j['impact']),
    diff:           _s(j['diff']),
    rollback:       _s(j['rollback']),
    missionId:      _s(j['mission_id']),
    status:         _s(j['status'], 'PENDING'),
    createdAt:      _d(j['created_at']),
    approvedAt:     j['approved_at'] != null ? _d(j['approved_at']) : null,
    rejectedAt:     j['rejected_at'] != null ? _d(j['rejected_at']) : null,
    executedAt:     j['executed_at'] != null ? _d(j['executed_at']) : null,
    result:         _s(j['result']),
    note:           _s(j['note']),
    approvalReason: j['approval_reason']?.toString(),
  );

  // ── Defensive helpers ────────────────────────────────────────────────────
  static String _s(dynamic v, [String d = '']) => v?.toString() ?? d;
  static double _d(dynamic v, [double d = 0.0]) =>
      double.tryParse(v?.toString() ?? '') ?? d;

  bool get isPending  => status == 'PENDING';
  bool get isApproved => status == 'APPROVED';
  bool get isRejected => status == 'REJECTED';
  bool get isExecuted => status == 'EXECUTED';
  bool get isFailed   => status == 'FAILED';
}
