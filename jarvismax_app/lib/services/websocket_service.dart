import '../config/hardcoded_config.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart' show AppLifecycleState;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import '../config/api_config.dart';

/// Connection state machine.
/// UI can observe [connectionState] for explicit rendering.
enum WsConnectionState {
  /// Not connected, not trying to connect
  disconnected,

  /// Actively attempting to establish connection
  connecting,

  /// Connected and receiving messages
  connected,

  /// Was connected, now reconnecting (backoff active)
  reconnecting,

  /// Server rejected auth (401/4008) — needs token refresh or re-login
  authExpired,

  /// Network is completely unavailable
  offline,
}

/// Resilient WebSocket client with:
/// - Explicit connection state machine (6 states)
/// - Automatic reconnect on network transitions (WiFi ↔ 4G)
/// - Exponential backoff with jitter (1s, 2s, 5s, 10s, 20s ±20%)
/// - Heartbeat detection (35s timeout)
/// - Token reload before every reconnect
/// - 401 detection → auth_expired state → trigger token refresh
/// - Concurrent reconnect guard (single inflight attempt)
/// - State resync after reconnect
/// - App lifecycle awareness (sleep/wake)
class WebSocketService extends ChangeNotifier {
  ApiConfig? _config;
  WebSocket? _socket;
  Timer? _reconnectTimer;
  Timer? _heartbeatTimer;
  Timer? _heartbeatTimeout;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  final _controller = StreamController<Map<String, dynamic>>.broadcast();
  final _random = Random();

  // ── Connection state machine ────────────────────────────────────────────
  WsConnectionState _state = WsConnectionState.disconnected;
  bool _intentionalDisconnect = false;
  bool _connectInFlight = false; // Concurrent reconnect guard
  int _reconnectAttempts = 0;
  bool _wasConnectedBefore = false; // Track if this is a reconnect
  DateTime? _lastMessageAt;
  String _lastNetworkType = '';

  // ── Public getters ──────────────────────────────────────────────────────
  Stream<Map<String, dynamic>> get stream => _controller.stream;
  WsConnectionState get connectionState => _state;
  bool get isConnected => _state == WsConnectionState.connected;
  int get reconnectAttempts => _reconnectAttempts;

  // ── Backoff: 1s, 2s, 5s, 10s, 20s with ±20% jitter ───────────────────
  static const _backoffSchedule = [1, 2, 5, 10, 20];

  int get _nextDelayMs {
    final base = _reconnectAttempts < _backoffSchedule.length
        ? _backoffSchedule[_reconnectAttempts]
        : _backoffSchedule.last;
    final baseMs = base * 1000;
    // Add ±20% jitter to prevent thundering herd
    final jitter = (baseMs * 0.2 * (2 * _random.nextDouble() - 1)).round();
    return baseMs + jitter;
  }

  // ── Configuration ──────────────────────────────────────────────────────

  void setConfig(ApiConfig config) {
    _config = config;
  }

  // ── State transitions ──────────────────────────────────────────────────

  void _setState(WsConnectionState newState) {
    if (_state != newState) {
      debugPrint('[WS] State: ${_state.name} → ${newState.name}');
      _state = newState;
      notifyListeners();
    }
  }

  // ── Connect ────────────────────────────────────────────────────────────

  Future<void> connect() async {
    // Concurrent reconnect guard — only one connect() at a time
    if (_connectInFlight) {
      debugPrint('[WS] Connect already in-flight — skipping');
      return;
    }
    _connectInFlight = true;

    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _intentionalDisconnect = false;

    _setState(WsConnectionState.connecting);

    try {
      // 1. Reload token (may have been refreshed)
      final token = await _loadToken();
      if (token.isEmpty && _state != WsConnectionState.authExpired) {
        debugPrint('[WS] No token available — entering auth_expired');
        _setState(WsConnectionState.authExpired);
        _connectInFlight = false;
        return;
      }

      final baseUrl = _config?.baseUrl ?? 'http://10.0.2.2:8000';
      final wsUrl = baseUrl
          .replaceFirst('http://', 'ws://')
          .replaceFirst('https://', 'wss://');
      // NOTE: token is sent as a header, NOT as a query param.
      // The server removed ?token= support (it leaks into logs/Referer headers).
      final uri = '$wsUrl/ws/stream';
      final wsHeaders = token.isNotEmpty
          ? <String, dynamic>{'X-Jarvis-Token': token}
          : <String, dynamic>{};

      // 2. Close existing socket cleanly
      _closeSocket();

      debugPrint('[WS] Connecting (attempt ${_reconnectAttempts + 1})');

      _socket = await WebSocket.connect(uri, headers: wsHeaders)
          .timeout(const Duration(seconds: 8));

      _reconnectAttempts = 0;
      _lastMessageAt = DateTime.now();
      debugPrint('[WS] Connected successfully');

      _setState(WsConnectionState.connected);

      // 3. Start heartbeat monitor
      _startHeartbeatMonitor();

      // 4. Listen to connectivity changes (once)
      _startConnectivityMonitor();

      // 5. Listen to messages
      _socket!.listen(
        _onMessage,
        onDone: () => _onDisconnect('socket_done'),
        onError: (e) => _onDisconnect('socket_error: $e'),
        cancelOnError: false,
      );

      // 6. Emit reconnected event for UI resync (only on REconnect)
      if (_wasConnectedBefore) {
        _controller.add({
          'type': 'system',
          'event': 'reconnected',
          'message': 'WebSocket reconnected — syncing state',
        });
      }
      _wasConnectedBefore = true;
    } on WebSocketException catch (e) {
      // Check for auth rejection (close code 4008 or HTTP 401/403)
      final msg = e.toString().toLowerCase();
      if (msg.contains('401') || msg.contains('403') || msg.contains('unauthorized')) {
        debugPrint('[WS] Auth rejected — entering auth_expired');
        _setState(WsConnectionState.authExpired);
        _controller.add({
          'type': 'system',
          'event': 'auth_expired',
          'message': 'Token expired — attempting refresh',
        });
        // Don't auto-reconnect for auth failures — wait for token refresh
      } else {
        _onDisconnect('ws_exception: $e');
      }
    } catch (e) {
      debugPrint('[WS] Connect failed: $e');
      _onDisconnect('connect_failed: $e');
    } finally {
      _connectInFlight = false;
    }
  }

  // ── Message handler ────────────────────────────────────────────────────

  void _onMessage(dynamic data) {
    _lastMessageAt = DateTime.now();
    _resetHeartbeatTimeout();

    try {
      final json = jsonDecode(data as String) as Map<String, dynamic>;
      final type = json['type']?.toString() ?? '';

      // Handle auth rejection at message level
      if (type == 'error' && json['code'] == 4008) {
        debugPrint('[WS] Server sent auth_expired');
        _setState(WsConnectionState.authExpired);
        _controller.add({
          'type': 'system',
          'event': 'auth_expired',
          'message': 'Token expired during session',
        });
        return;
      }

      // Handle heartbeat/pong silently
      if (type == 'heartbeat' || type == 'pong') {
        return;
      }

      _controller.add(json);
    } catch (_) {
      // Malformed message — ignore
    }
  }

  // ── Heartbeat monitor ──────────────────────────────────────────────────

  void _startHeartbeatMonitor() {
    _heartbeatTimer?.cancel();
    _heartbeatTimeout?.cancel();

    // Send ping every 25s
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 25), (_) {
      if (_socket != null && _state == WsConnectionState.connected) {
        try {
          _socket!.add(jsonEncode({
            'type': 'ping',
            'ts': DateTime.now().millisecondsSinceEpoch,
          }));
        } catch (_) {
          _onDisconnect('ping_failed');
        }
      }
    });

    _resetHeartbeatTimeout();
  }

  void _resetHeartbeatTimeout() {
    _heartbeatTimeout?.cancel();
    // If no message in 35s, socket is dead
    _heartbeatTimeout = Timer(const Duration(seconds: 35), () {
      debugPrint('[WS] Heartbeat timeout — 35s without message');
      _onDisconnect('heartbeat_timeout');
    });
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _heartbeatTimeout?.cancel();
    _heartbeatTimeout = null;
  }

  // ── Connectivity monitoring ────────────────────────────────────────────

  void _startConnectivityMonitor() {
    if (_connectivitySub != null) return;

    _connectivitySub = Connectivity().onConnectivityChanged.listen(
      (results) {
        final newType = results.isNotEmpty ? results.first.name : 'none';
        debugPrint('[WS] Network: $_lastNetworkType → $newType');

        if (newType == 'none') {
          _setState(WsConnectionState.offline);
        } else if (_lastNetworkType == 'none' ||
                   (_lastNetworkType != newType && _lastNetworkType.isNotEmpty)) {
          // Network restored or switched — force immediate reconnect
          debugPrint('[WS] Network changed → forcing reconnect');
          _reconnectAttempts = 0;
          _scheduleReconnect(immediate: true);
        }

        _lastNetworkType = newType;
      },
      onError: (_) {},
    );
  }

  // ── App lifecycle ──────────────────────────────────────────────────────

  void onAppLifecycleChanged(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.resumed:
        debugPrint('[WS] App resumed — state=${_state.name}');
        if (_state == WsConnectionState.connected) {
          // Verify still alive
          try {
            _socket?.add(jsonEncode({'type': 'ping'}));
            _startHeartbeatMonitor(); // Restart after pause
          } catch (_) {
            _onDisconnect('resume_ping_failed');
          }
        } else if (!_intentionalDisconnect &&
                   _state != WsConnectionState.authExpired) {
          _reconnectAttempts = 0;
          connect();
        }
        break;
      case AppLifecycleState.paused:
        debugPrint('[WS] App paused — stopping heartbeat');
        _stopHeartbeat();
        break;
      default:
        break;
    }
  }

  // ── Disconnect + reconnect ─────────────────────────────────────────────

  void _onDisconnect(String reason) {
    final wasConnected = _state == WsConnectionState.connected;
    _closeSocket();
    _stopHeartbeat();

    if (wasConnected) {
      debugPrint('[WS] Disconnected: $reason');
    }

    // Don't reconnect on auth failures or intentional disconnect
    if (_intentionalDisconnect) {
      _setState(WsConnectionState.disconnected);
      return;
    }
    if (_state == WsConnectionState.authExpired) {
      return; // Stay in authExpired — wait for token refresh
    }

    _setState(WsConnectionState.reconnecting);
    _scheduleReconnect();
  }

  void _scheduleReconnect({bool immediate = false}) {
    _reconnectTimer?.cancel();

    if (immediate) {
      debugPrint('[WS] Immediate reconnect');
      connect();
      return;
    }

    final delayMs = _nextDelayMs;
    _reconnectAttempts++;
    debugPrint('[WS] Reconnecting in ${delayMs}ms (attempt $_reconnectAttempts)');
    _reconnectTimer = Timer(Duration(milliseconds: delayMs), connect);
  }

  void _closeSocket() {
    try {
      _socket?.close();
    } catch (_) {}
    _socket = null;
  }

  // ── Token management ───────────────────────────────────────────────────

  Future<String> _loadToken() async {
    // Always prefer the static API token (never expires) — avoids JWT expiry WS crash
    try {
      const staticToken = HardcodedConfig.apiToken;
      if (staticToken.isNotEmpty) return staticToken;
    } catch (_) {}
    // Fallback: JWT from secure storage
    try {
      const storage = FlutterSecureStorage(
        aOptions: AndroidOptions(encryptedSharedPreferences: true),
      );
      return await storage.read(key: 'jarvis_jwt_token') ?? '';
    } catch (_) {
      return '';
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────

  /// Intentional disconnect (user logout, settings change)
  void disconnect() {
    _intentionalDisconnect = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _stopHeartbeat();
    _connectivitySub?.cancel();
    _connectivitySub = null;
    _closeSocket();
    _setState(WsConnectionState.disconnected);
  }

  /// Call after successful token refresh to resume connection
  void onTokenRefreshed() {
    if (_state == WsConnectionState.authExpired ||
        _state == WsConnectionState.disconnected) {
      debugPrint('[WS] Token refreshed — reconnecting');
      _reconnectAttempts = 0;
      _intentionalDisconnect = false;
      connect();
    }
  }

  /// Force reconnect (e.g., after login)
  void forceReconnect() {
    _reconnectAttempts = 0;
    _intentionalDisconnect = false;
    _wasConnectedBefore = false;
    connect();
  }

  @override
  void dispose() {
    disconnect();
    _controller.close();
    super.dispose();
  }
}
