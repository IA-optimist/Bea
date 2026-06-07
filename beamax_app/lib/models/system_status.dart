class SystemStatus {
  final String mode;
  final bool isOnline;
  final int pendingActions;
  final int totalMissions;
  // Mission breakdown
  final int doneMissions;
  final int approvedMissions;
  final int rejectedMissions;
  final int blockedMissions;
  final int pendingValidationMissions;
  // Action breakdown
  final int executedActions;
  final int failedActions;
  // Executor
  final bool executorRunning;
  final int executorTotal;

  const SystemStatus({
    this.mode = 'UNKNOWN',
    this.isOnline = false,
    this.pendingActions = 0,
    this.totalMissions = 0,
    this.doneMissions = 0,
    this.approvedMissions = 0,
    this.rejectedMissions = 0,
    this.blockedMissions = 0,
    this.pendingValidationMissions = 0,
    this.executedActions = 0,
    this.failedActions = 0,
    this.executorRunning = false,
    this.executorTotal = 0,
  });

  /// Reconstruit depuis le payload /api/stats
  factory SystemStatus.fromStats(Map<String, dynamic> stats) {
    final missions  = _m(stats['missions']);
    final actions   = _m(stats['actions']);
    final executor  = _m(stats['executor']);
    return SystemStatus(
      isOnline:                  true,
      totalMissions:             _i(missions['total']),
      doneMissions:              _i(missions['done']),
      approvedMissions:          _i(missions['in_progress']),
      rejectedMissions:          _i(missions['rejected']),
      blockedMissions:           _i(missions['blocked']),
      pendingValidationMissions: _i(missions['pending_validation']),
      pendingActions:            _i(actions['pending']),
      executedActions:           _i(actions['executed']),
      failedActions:             _i(actions['failed']),
      executorRunning:           executor['running'] == true,
      executorTotal:             _i(executor['executed_total']),
    );
  }

  factory SystemStatus.fromJson(Map<String, dynamic> j) => SystemStatus(
    mode:           _s(j['mode'], 'UNKNOWN'),
    isOnline:       true,
    pendingActions: _i(j['pending_actions']),
    totalMissions:  _i(j['total_missions']),
  );

  SystemStatus copyWith({
    String? mode,
    bool?   isOnline,
    int?    pendingActions,
    int?    totalMissions,
    int?    doneMissions,
    int?    approvedMissions,
    int?    rejectedMissions,
    int?    blockedMissions,
    int?    pendingValidationMissions,
    int?    executedActions,
    int?    failedActions,
    bool?   executorRunning,
    int?    executorTotal,
  }) => SystemStatus(
    mode:                      mode                      ?? this.mode,
    isOnline:                  isOnline                  ?? this.isOnline,
    pendingActions:            pendingActions            ?? this.pendingActions,
    totalMissions:             totalMissions             ?? this.totalMissions,
    doneMissions:              doneMissions              ?? this.doneMissions,
    approvedMissions:          approvedMissions          ?? this.approvedMissions,
    rejectedMissions:          rejectedMissions          ?? this.rejectedMissions,
    blockedMissions:           blockedMissions           ?? this.blockedMissions,
    pendingValidationMissions: pendingValidationMissions ?? this.pendingValidationMissions,
    executedActions:           executedActions           ?? this.executedActions,
    failedActions:             failedActions             ?? this.failedActions,
    executorRunning:           executorRunning           ?? this.executorRunning,
    executorTotal:             executorTotal             ?? this.executorTotal,
  );

  // ── Defensive helpers ────────────────────────────────────────────────────
  static String _s(dynamic v, [String d = '']) => v?.toString() ?? d;
  static int _i(dynamic v, [int d = 0]) =>
      int.tryParse(v?.toString() ?? '') ?? d;
  static Map<String, dynamic> _m(dynamic v) =>
      (v is Map) ? Map<String, dynamic>.from(v) : {};
}
