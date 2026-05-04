import '../config/hardcoded_config.dart';
import 'notification_service.dart';
import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';
import '../models/mission.dart';
import '../models/action_model.dart';
import '../models/autonomy_decision.dart';
import '../models/system_status.dart';
import 'websocket_service.dart';
import 'session_manager.dart';

class ApiResult<T> {
  final T? data;
  final String? error;
  bool get ok => error == null;

  const ApiResult.success(this.data) : error = null;
  const ApiResult.failure(this.error) : data = null;
}

class ApiService extends ChangeNotifier {
  ApiConfig? _config;
  WebSocketService? _wsService;
  StreamSubscription<Map<String, dynamic>>? _wsSubscription;

  // ── Secure storage for JWT ────────────────────────────────────────────────
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  static const _jwtKey = 'jarvis_jwt_token';

  String _jwtToken = '';
  String get jwtToken => _jwtToken;

  // Admin role: true when logged in via admin credentials (loginMode == 'admin')
  bool _isAdmin = false;
  bool get isAdmin => _isAdmin;

  List<Mission>     _missions = [];
  List<ActionModel> _actions  = [];
  SystemStatus      _status   = const SystemStatus();
  bool              _loading    = false;
  bool              _isChecking = true;
  String?           _lastError;
  Timer?            _refreshTimer;
  Timer?            _wsDebounceTimer;

  // ── Realtime state ────────────────────────────────────────────────────────
  Map<String, dynamic>? _lastWsEvent;
  Map<String, dynamic>? get lastWsEvent => _lastWsEvent;

  List<Mission>     get missions    => _missions;
  List<ActionModel> get actions     => _actions;
  SystemStatus      get status      => _status;
  bool              get loading     => _loading;
  bool              get isChecking  => _isChecking;
  String?           get lastError   => _lastError;
  List<ActionModel> get pendingActions =>
      _actions.where((a) => a.isPending).toList();

  void setConfig(ApiConfig config) {
    _config = config;
    config.addListener(_onConfigChanged);
    _loadJwt();
  }

  /// Wire WebSocket events into mission state updates.
  void setWebSocketService(WebSocketService ws) {
    _wsService = ws;
    _wsSubscription?.cancel();
    _wsSubscription = _wsService!.stream.listen(_handleWsEvent);
  }

  // ── Realtime event handler ────────────────────────────────────────────────

  void _handleWsEvent(Map<String, dynamic> event) {
    _lastWsEvent = event;
    final type = event['type']?.toString() ?? '';

    switch (type) {
      // WebSocket reconnected → full state resync
      case 'system':
        if (event['event'] == 'reconnected') {
          debugPrint('[API] WebSocket reconnected — resyncing state');
          refresh();
        } else if (event['event'] == 'auth_expired') {
          debugPrint('[API] WebSocket auth expired — refreshing token');
          _doTokenRefresh();
        }
        break;
      // Task/mission progress → refresh missions (debounced to avoid flooding)
      case 'task_progress':
      case 'mission_update':
      case 'mission_done':
        _debouncedMissionRefresh();
        try {
          final goal = event['goal']?.toString() ?? event['mission_id']?.toString() ?? 'Mission';
          final mid2 = event['mission_id']?.toString() ?? 'done';
          NotificationService.instance.showMissionDone(missionId: mid2, goal: goal, success: true);
        } catch (_) {}
        break;
      case 'mission_failed':
        _debouncedMissionRefresh();
        try {
          final goal = event['goal']?.toString() ?? 'Mission';
          final mid3 = event['mission_id']?.toString() ?? 'fail';
          NotificationService.instance.showMissionDone(missionId: mid3, goal: goal, success: false);
        } catch (_) {}
        break;

      // Action/approval change → refresh actions + notification
      case 'action_pending':
        _loadActions().catchError((_) {});
        // Fire local notification
        try {
          final action = event['action']?.toString() ?? 'Action requise';
          final risk = event['risk_level']?.toString();
          final mid = event['mission_id']?.toString() ?? 'unknown';
          NotificationService.instance.showApprovalRequired(
            missionId: mid, action: action, risk: risk);
        } catch (_) {}
        break;
      case 'action_approved':
      case 'action_rejected':
        _loadActions().catchError((_) {});
        break;

      // Agent thinking / token stream → notify listeners so UI can react
      case 'agent_thinking':
      case 'token_stream':
        notifyListeners();
        break;

      default:
        // Unknown event — still notify for potential consumers
        notifyListeners();
    }
  }

  /// Debounced mission refresh: at most one refresh per 4 seconds from WS events.
  void _debouncedMissionRefresh() {
    _wsDebounceTimer?.cancel();
    _wsDebounceTimer = Timer(const Duration(seconds: 4), () {
      _loadMissions().then((_) => _loadActions()).catchError((_) {});
    });
  }

  // ── JWT secure storage ────────────────────────────────────────────────────

  Future<void> _loadJwt() async {
    try {
      _jwtToken = await _storage.read(key: _jwtKey) ?? '';
    } catch (_) {
      _jwtToken = '';
    }
    // Auto-login: if JWT empty, use static API token (always valid)
    if (_jwtToken.isEmpty) {
      _jwtToken = HardcodedConfig.apiToken;
      _isAdmin = true;
    }
    // Restore admin role from persisted session (loginMode == 'admin').
    try {
      final session = await SessionManager.instance.restoreSession();
      if (session != null) _isAdmin = session.loginMode == 'admin';
    } catch (_) {}
    notifyListeners();
  }

  Future<void> saveJwt(String token) async {
    _jwtToken = token;
    await _storage.write(key: _jwtKey, value: token);
    notifyListeners();
  }

  /// Current token for external consumers.
  String get currentToken => _jwtToken;

  /// Login with a pre-existing token (e.g. from session storage).
  Future<bool> loginWithToken(String token) async {
    try {
      _jwtToken = token;
      // Validate with a quick status check
      final resp = await http.get(
        Uri.parse('$_base/api/v2/status'),
        headers: _authHeaders,
      ).timeout(const Duration(seconds: 5));
      if (resp.statusCode < 400) {
        await saveJwt(token);
        return true;
      }
      _jwtToken = '';
      return false;
    } catch (_) {
      _jwtToken = '';
      return false;
    }
  }

  /// Login with username/password credentials (admin path).
  Future<bool> loginWithCredentials(String username, String password) async {
    final result = await login(username, password);
    if (result.ok) {
      _isAdmin = true;  // credential login = admin role
      notifyListeners();
    }
    return result.ok;
  }

  Future<void> clearJwt() async {
    _jwtToken = '';
    _isAdmin = false;
    _tokenRefreshTimer?.cancel();
    _savedUsername = '';
    _savedPassword = '';
    await _storage.delete(key: _jwtKey);
    notifyListeners();
  }


  // ── JWT Auto-Refresh ────────────────────────────────────────────────────
  Timer? _tokenRefreshTimer;
  String _savedUsername = '';
  String _savedPassword = '';

  /// Schedule automatic token refresh 5 minutes before expiry.
  void _scheduleTokenRefresh({int expiresIn = 3600}) {
    _tokenRefreshTimer?.cancel();
    // Refresh 5 minutes before expiry (minimum 30s)
    final refreshIn = (expiresIn - 300).clamp(30, expiresIn);
    _tokenRefreshTimer = Timer(Duration(seconds: refreshIn), _doTokenRefresh);
    debugPrint('[JWT] Refresh scheduled in ${refreshIn}s');
  }

  /// Attempt silent token refresh.
  Future<void> _doTokenRefresh() async {

    debugPrint('[JWT] Attempting token refresh...');
    
    try {
      // Try /auth/refresh first
      final resp = await http.post(
        Uri.parse('\$_base/auth/refresh'),
        headers: {
          'Authorization': 'Bearer ${_jwtToken.isNotEmpty ? _jwtToken : HardcodedConfig.apiToken}',
          'Content-Type': 'application/json',
        },
      ).timeout(const Duration(seconds: 10));
      
      if (resp.statusCode == 200) {
        final json = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
        final newToken = json['access_token']?.toString() ?? '';
        final expiresIn = json['expires_in'] as int? ?? 3600;
        if (newToken.isNotEmpty) {
          await saveJwt(newToken);
          _scheduleTokenRefresh(expiresIn: expiresIn);
          debugPrint('[JWT] Token refreshed successfully');
          _wsService?.onTokenRefreshed();
          return;
        }
      }
      
      // Refresh failed — try re-login with saved credentials
      debugPrint('[JWT] Refresh failed (HTTP \${resp.statusCode}), trying re-login...');
      await _tryReLogin();
    } catch (e) {
      debugPrint('[JWT] Refresh error: \$e, trying re-login...');
      await _tryReLogin();
    }
  }

  /// Re-login with saved credentials as fallback.
  Future<void> _tryReLogin() async {
    if (_savedUsername.isEmpty || _savedPassword.isEmpty) {
      debugPrint('[JWT] No saved credentials, cannot re-login');
      return;
    }
    try {
      final result = await login(_savedUsername, _savedPassword);
      if (result.ok) {
        debugPrint('[JWT] Re-login successful');
        // _scheduleTokenRefresh is called inside login()
      } else {
        debugPrint('[JWT] Re-login failed: \${result.error}');
      }
    } catch (e) {
      debugPrint('[JWT] Re-login error: \$e');
    }
  }


  /// Validate stored JWT on startup. If valid, use it. If not, clear it.
  Future<void> autoLogin() async {

    try {
      final resp = await http.get(
        Uri.parse('\$_base/api/v2/agents'),
        headers: _authHeaders,
      ).timeout(const Duration(seconds: 5));
      if (resp.statusCode == 401) {
        // Token expired or invalid — clear it
        await clearJwt();
      } else if (resp.statusCode == 200) {
        // Token still valid — schedule refresh (assume ~50min remaining)
        _scheduleTokenRefresh(expiresIn: 3000);
      }
    } catch (_) {
      // Network error — keep token, might work later
    }
  }

  void _onConfigChanged() {
    refresh();
  }

  String get _base => _config?.baseUrl ?? 'http://10.0.2.2:8000';

  // ── HTTP helpers ──────────────────────────────────────────────────────────

  Map<String, String> get _authHeaders {
    final h = <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };
    final _effectiveToken = _jwtToken.isNotEmpty ? _jwtToken : HardcodedConfig.apiToken;
    if (_effectiveToken.isNotEmpty) {
      h['Authorization'] = 'Bearer $_effectiveToken';
    }
    return h;
  }

  Future<Map<String, dynamic>> _get(String path) async {
    final resp = await http.get(
      Uri.parse('$_base$path'),
      headers: _authHeaders,
    ).timeout(const Duration(seconds: 8));
    return _parse(resp);
  }

  Future<Map<String, dynamic>> _post(String path, [Map<String, dynamic>? body]) async {
    final resp = await http.post(
      Uri.parse('$_base$path'),
      headers: _authHeaders,
      body: body != null ? jsonEncode(body) : '{}',
    ).timeout(const Duration(seconds: 15));
    return _parse(resp);
  }

  // ── Public generic HTTP (used by ModulesScreen, etc.) ──

  /// Generic GET — returns parsed JSON map.
  Future<Map<String, dynamic>> getJson(String path) => _get(path);

  /// Generic POST — returns parsed JSON map.
  Future<Map<String, dynamic>> postJson(String path, [Map<String, dynamic>? body]) => _post(path, body);

  /// Generic DELETE — returns parsed JSON map.
  Future<Map<String, dynamic>> deleteJson(String path) async {
    final resp = await http.delete(
      Uri.parse('$_base$path'),
      headers: _authHeaders,
    ).timeout(const Duration(seconds: 8));
    return _parse(resp);
  }

  // ── Autonomy : multi-choice decisions ───────────────────────────────────
  // Mirror of /api/v3/autonomy/decisions and .../{id}/answer.

  /// Fetch the list of pending autonomy decisions awaiting operator input.
  Future<List<AutonomyDecision>> fetchPendingDecisions() async {
    try {
      final resp = await http.get(
        Uri.parse('$_base/api/v3/autonomy/decisions'),
        headers: _authHeaders,
      ).timeout(const Duration(seconds: 8));
      if (resp.statusCode != 200) return const [];
      final raw = jsonDecode(resp.body);
      if (raw is! List) return const [];
      return raw
          .whereType<Map<String, dynamic>>()
          .map(AutonomyDecision.fromJson)
          .toList();
    } catch (_) {
      return const [];
    }
  }

  /// Answer a pending decision. Returns true on success.
  Future<bool> answerDecision(String decisionId, int selectedIndex) async {
    try {
      final resp = await http.post(
        Uri.parse('$_base/api/v3/autonomy/decisions/$decisionId/answer'),
        headers: {..._authHeaders, 'Content-Type': 'application/json'},
        body: jsonEncode({'selected_index': selectedIndex}),
      ).timeout(const Duration(seconds: 8));
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Read-only autonomy daemon status.
  Future<Map<String, dynamic>> fetchAutonomyStatus() async {
    try {
      return await getJson('/api/v3/autonomy/status');
    } catch (_) {
      return {'running': false};
    }
  }

  Map<String, dynamic> _parse(http.Response resp) {
    try {
      final body = utf8.decode(resp.bodyBytes);
      final decoded = jsonDecode(body);
      final json = decoded is Map<String, dynamic>
          ? decoded
          : <String, dynamic>{'data': decoded};
      if (resp.statusCode >= 400) {
        throw Exception(
          json['error']?.toString() ??
          json['detail']?.toString() ??
          'HTTP ${resp.statusCode}',
        );
      }
      return json;
    } on FormatException {
      throw Exception('Réponse invalide du serveur (HTTP ${resp.statusCode})');
    }
  }

  // ── Public API calls ──────────────────────────────────────────────────────

  Future<ApiResult<Mission>> submitMission(String input, {String? conversationContext}) async {
    _setLoading(true);
    try {
      final body = <String, dynamic>{'goal': input};
      if (conversationContext != null && conversationContext.isNotEmpty) {
        body['context'] = conversationContext;
      }
      final raw = await _post('/api/v3/missions', body);
      final data = raw['data'];
      final Map<String, dynamic> missionJson = data is Map<String, dynamic>
          ? data
          : (data is Map ? Map<String, dynamic>.from(data) : {});
      final taskId = missionJson['task_id']?.toString() ??
          missionJson['mission_id']?.toString() ?? '';
      await _loadMissions();
      await _loadActions();
      Mission mission;
      if (taskId.isNotEmpty) {
        mission = _missions.firstWhere(
          (m) => m.id == taskId,
          orElse: () => Mission.fromJson({...missionJson, 'user_input': input}),
        );
      } else {
        mission = Mission.fromJson({...missionJson, 'user_input': input});
      }
      return ApiResult.success(mission);
    } catch (e) {
      _lastError = _friendly(e);
      notifyListeners();
      return ApiResult.failure(_lastError);
    } finally {
      _setLoading(false);
    }
  }

  Future<ApiResult<List<Mission>>> loadMissions() async {
    _setLoading(true);
    try {
      await _loadMissions();
      return ApiResult.success(_missions);
    } catch (e) {
      _lastError = _friendly(e);
      notifyListeners();
      return ApiResult.failure(_lastError);
    } finally {
      _setLoading(false);
    }
  }

  Future<ApiResult<Mission>> fetchMissionDetail(String id) async {
    try {
      final raw = await _get('/api/v3/missions/$id');
      final data = raw['data'];
      final Map<String, dynamic> missionJson = data is Map<String, dynamic>
          ? data
          : Map<String, dynamic>.from(data as Map);
      return ApiResult.success(Mission.fromJson(missionJson));
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<List<ActionModel>>> loadActions() async {
    _setLoading(true);
    try {
      await _loadActions();
      return ApiResult.success(_actions);
    } catch (e) {
      _lastError = _friendly(e);
      notifyListeners();
      return ApiResult.failure(_lastError);
    } finally {
      _setLoading(false);
    }
  }

  Future<ApiResult<void>> approveAction(String id) async {
    try {
      // v3 canonical: triggers MetaOrchestrator resumption + SQLite persist (3-step bridge)
      await _post('/api/v3/missions/$id/approve');
      await _loadActions();
      return const ApiResult.success(null);
    } catch (e) {
      try { await _loadActions(); } catch (_) {}
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<void>> rejectAction(String id, {String reason = ''}) async {
    try {
      // v3 canonical: triggers MetaOrchestrator rejection + CANCELLED state + SQLite persist
      await _post('/api/v3/missions/$id/reject', {'note': reason});
      await _loadActions();
      return const ApiResult.success(null);
    } catch (e) {
      try { await _loadActions(); } catch (_) {}
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<String>> login(String username, String password) async {
    try {
      final resp = await http.post(
        Uri.parse('$_base/auth/token'),
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'username=${Uri.encodeComponent(username)}&password=${Uri.encodeComponent(password)}',
      ).timeout(const Duration(seconds: 10));
      final json = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      if (resp.statusCode >= 400) {
        throw Exception(json['detail']?.toString() ?? 'HTTP ${resp.statusCode}');
      }
      final token = json['access_token']?.toString() ?? json['token']?.toString() ?? '';
      if (token.isNotEmpty) {
        await saveJwt(token);
        _savedUsername = username;
        _savedPassword = password;
        final expiresIn = json['expires_in'] as int? ?? 3600;
        _scheduleTokenRefresh(expiresIn: expiresIn);
      }
      return ApiResult.success(token);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<List<Map<String, dynamic>>>> getAgents() async {
    try {
      final raw = await _get('/api/v2/agents');
      final data = raw['data'];
      final List raw2 = data is Map && data.containsKey('agents')
          ? (data['agents'] as List? ?? [])
          : (data is List ? data : []);
      final list = raw2.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      return ApiResult.success(list);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<String>> getMode() async {
    try {
      final raw = await _get('/api/v2/status');
      final data = raw['data'];
      final String mode = data is Map
          ? (data['mode']?.toString() ?? 'AUTO')
          : 'AUTO';
      if (data is Map) {
        final missions = data['missions'];
        if (missions is Map) {
          final total = int.tryParse(missions['total']?.toString() ?? '') ?? 0;
          final byStatus = missions['by_status'];
          final done = byStatus is Map
              ? (int.tryParse(byStatus['DONE']?.toString() ?? '') ?? 0)
              : 0;
          _status = _status.copyWith(
            mode: mode,
            isOnline: true,
            totalMissions: total,
            doneMissions: done,
          );
          notifyListeners();
          return ApiResult.success(mode);
        }
      }
      _status = _status.copyWith(mode: mode, isOnline: true);
      notifyListeners();
      return ApiResult.success(mode);
    } catch (e) {
      final msg = e.toString();
      if (msg.contains('SocketException') ||
          msg.contains('Connection refused') ||
          msg.contains('TimeoutException')) {
        _status = _status.copyWith(isOnline: false);
      }
      notifyListeners();
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<void>> setMode(String mode) async {
    try {
      await _post('/api/system/mode', {'mode': mode});
      _status = _status.copyWith(mode: mode);
      notifyListeners();
      return const ApiResult.success(null);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<Map<String, dynamic>> setUncensoredMode(bool enabled) async {
    try {
      return await _post('/api/system/mode/uncensored', {'enabled': enabled});
    } catch (e) {
      return {'error': _friendly(e)};
    }
  }

  Future<Map<String, dynamic>> getUncensoredMode() async {
    try {
      return await _get('/api/system/mode/uncensored');
    } catch (e) {
      return {'uncensored': false, 'error': _friendly(e)};
    }
  }

  Future<ApiResult<Map<String, dynamic>>> getPolicyMode() async {
    try {
      final raw = await _get('/api/v2/system/policy-mode');
      final data = raw['data'];
      final Map<String, dynamic> result = data is Map<String, dynamic>
          ? data
          : (data is Map ? Map<String, dynamic>.from(data) : {});
      return ApiResult.success(result);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<Map<String, dynamic>>> setPolicyMode(String mode) async {
    try {
      final raw = await _post('/api/v2/system/policy-mode', {'policy_mode': mode});
      final data = raw['data'];
      final Map<String, dynamic> result = data is Map<String, dynamic>
          ? data
          : (data is Map ? Map<String, dynamic>.from(data) : {});
      return ApiResult.success(result);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<Map<String, dynamic>>> getCapabilities() async {
    try {
      final raw = await _get('/api/v2/system/capabilities');
      final data = raw['data'];
      final Map<String, dynamic> result = data is Map<String, dynamic>
          ? data
          : (data is Map ? Map<String, dynamic>.from(data) : {});
      return ApiResult.success(result);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  // AI OS dashboard
  Future<Map<String, dynamic>> getAiosStatus() async {
    final raw = await _get("/aios/status");
    return raw["data"] is Map<String, dynamic> ? raw["data"] : {};
  }

  Future<ApiResult<Map<String, dynamic>>> getRecentMetrics() async {
    try {
      final raw = await _get('/api/v2/metrics/recent');
      return ApiResult.success(raw);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  Future<ApiResult<List<Map<String, dynamic>>>> getSelfImprovementSuggestions() async {
    try {
      final raw = await _get('/api/v2/self-improvement/suggestions');
      final list = raw['suggestions'];
      if (list is List) {
        return ApiResult.success(
          list.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList(),
        );
      }
      return ApiResult.success([]);
    } catch (e) {
      return ApiResult.failure(_friendly(e));
    }
  }

  /// Stream real-time SSE events for a mission.
  Stream<Map<String, dynamic>> streamMissionLogs(
    String missionId, {
    int maxRetries = 5,
  }) async* {
    int attempt = 0;
    while (attempt <= maxRetries) {
      final client = http.Client();
      bool receivedDone = false;
      try {
        final req = http.Request(
          'GET',
          Uri.parse('$_base/api/v1/missions/$missionId/stream'),
        );
        req.headers['Accept'] = 'text/event-stream';
        req.headers['Cache-Control'] = 'no-cache';
        if (_jwtToken.isNotEmpty) {
          req.headers['Authorization'] = 'Bearer ${_jwtToken.isNotEmpty ? _jwtToken : HardcodedConfig.apiToken}';
        }
        final resp = await client.send(req);
        String buf = '';
        await for (final chunk
            in resp.stream.transform(utf8.decoder).transform(const LineSplitter())) {
          if (chunk.startsWith('data: ')) {
            buf = chunk.substring(6);
          } else if (chunk.isEmpty && buf.isNotEmpty) {
            try {
              final evt = jsonDecode(buf) as Map<String, dynamic>;
              yield evt;
              if (evt['event'] == 'done' || evt['event'] == 'timeout') {
                receivedDone = true;
                return;
              }
            } catch (_) {}
            buf = '';
          }
        }
      } catch (_) {
        // network error — will retry below
      } finally {
        client.close();
      }
      if (receivedDone) return;
      attempt++;
      if (attempt <= maxRetries) {
        await Future.delayed(const Duration(seconds: 2));
      }
    }
  }

  Future<bool> checkHealth() async {
    for (final path in ['/health', '/']) {
      try {
        final resp = await http.get(
          Uri.parse('$_base$path'),
          headers: _authHeaders,
        ).timeout(const Duration(seconds: 8));
        if (resp.statusCode >= 200 && resp.statusCode < 300) {
          _status = _status.copyWith(isOnline: true);
          _isChecking = false;
          notifyListeners();
          return true;
        }
      } catch (_) {
        continue;
      }
    }
    _status = _status.copyWith(isOnline: false);
    _isChecking = false;
    notifyListeners();
    return false;
  }

  Future<void> refresh() async {
    _setLoading(true);
    try {
      await checkHealth();
      await Future.wait([
        _loadMissions(),
        _loadActions(),
        _loadStats(),
        getMode(),
      ]);
    } catch (_) {
    } finally {
      _setLoading(false);
    }
  }

  int _offlineStreak = 0;

  void startAutoRefresh({Duration interval = const Duration(seconds: 30)}) {
    _refreshTimer?.cancel();
    _refreshTimer = Timer.periodic(interval, (_) async {
      // Adaptive: skip background refresh when persistently offline (saves battery/bandwidth)
      if (!_status.isOnline && _offlineStreak >= 3) {
        // Try a lightweight health-check every 3rd tick instead of full refresh
        final online = await checkHealth();
        if (!online) return;
      }
      await refresh();
      _offlineStreak = _status.isOnline ? 0 : _offlineStreak + 1;
    });
  }

  void stopAutoRefresh() {
    _refreshTimer?.cancel();
    _refreshTimer = null;
  }

  // ── Stats ─────────────────────────────────────────────────────────────────

  Future<void> _loadStats() async {
    try {
      final raw  = await _get('/api/v2/status');
      final data = raw['data'];
      if (data is Map) {
        final mode    = _status.mode;
        final missions = data['missions'] as Map? ?? {};
        final byStatus = missions['by_status'] as Map? ?? {};
        final total    = int.tryParse(missions['total']?.toString() ?? '') ?? 0;
        final done     = int.tryParse(byStatus['DONE']?.toString()     ?? '') ?? 0;
        final approved = int.tryParse(byStatus['APPROVED']?.toString() ?? '') ?? 0;
        _status = SystemStatus(
          isOnline:        true,
          mode:            mode,
          totalMissions:   total,
          doneMissions:    done,
          approvedMissions: approved,
        );
        notifyListeners();
      }
    } catch (_) {}
  }

  // ── Private helpers ───────────────────────────────────────────────────────

  Future<void> _loadMissions() async {
    final raw = await _get('/api/v3/missions');
    final data = raw['data'];
    final List<dynamic> list;
    if (data is Map && data.containsKey('missions')) {
      final v = data['missions'];
      list = v is List ? v : [];
    } else if (data is List) {
      list = data;
    } else {
      list = [];
    }
    _missions = list
        .whereType<Map>()
        .map((e) => Mission.fromJson(Map<String, dynamic>.from(e)))
        .toList();
    _status = _status.copyWith(totalMissions: _missions.length);
    notifyListeners();
  }

  Future<void> _loadActions() async {
    try {
      final raw = await _get('/api/v2/tasks');
      final data = raw['data'];
      final List<dynamic> list;
      if (data is Map && data.containsKey('actions')) {
        final v = data['actions'];
        list = v is List ? v : [];
      } else if (data is Map && data.containsKey('tasks')) {
        final v = data['tasks'];
        list = v is List ? v : [];
      } else if (data is List) {
        list = data;
      } else {
        list = [];
      }
      _actions = list
          .whereType<Map>()
          .map((raw) {
            final e = Map<String, dynamic>.from(raw);
            e['id']          ??= e['task_id'] ?? e['mission_id'] ?? '';
            e['description'] ??= e['plan_summary'] ?? e['user_input'] ?? '';
            if (e['status'] == 'DONE' || e['status'] == 'EXECUTING') {
              e['status'] = 'EXECUTED';
            }
            return ActionModel.fromJson(e);
          })
          .toList();
      _status = _status.copyWith(
        pendingActions: _actions.where((a) => a.isPending).length,
      );
      notifyListeners();
    } catch (_) {}
  }

  void _setLoading(bool v) {
    _loading = v;
    notifyListeners();
  }

  String _friendly(Object e) {
    final msg = e.toString();
    if (msg.contains('SocketException') || msg.contains('Connection refused')) {
      return 'Impossible de joindre le serveur Jarvis.\nVérifiez que l\'API tourne sur $_base';
    }
    if (msg.contains('TimeoutException')) {
      return 'Délai dépassé. Le serveur ne répond pas.';
    }
    return msg.replaceFirst('Exception: ', '');
  }

  @override
  void dispose() {
    stopAutoRefresh();
    _wsDebounceTimer?.cancel();
    _wsSubscription?.cancel();
    _config?.removeListener(_onConfigChanged);
    super.dispose();
  }
}
