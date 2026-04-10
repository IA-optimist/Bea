import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ApiConfig extends ChangeNotifier {
  static const _keyHost = 'api_host';
  static const _keyPort = 'api_port';

  // Defaults
  static const defaultEmulatorHost = 'jarvis.jarvismaxapp.co.uk';
  /// Production domain with automatic TLS via Caddy.
  static const defaultProductionHost = 'jarvis.jarvismaxapp.co.uk';
  static const defaultLocalHost      = '192.168.1.100';
  /// Port 443 = HTTPS (no explicit port in URL); 8000 = plain HTTP for dev.
  static const defaultPort = 443;

  // Profils de connexion prédéfinis
  static const profiles = {
    'emulator':    ('10.0.2.2',                   8000), // Android emulator
    'local':       ('192.168.129.20',              8000), // LAN direct
    'tailscale':   ('100.109.1.124',               8000), // VPN direct
    'production': ('jarvis.jarvismaxapp.co.uk', 443), // Hetzner VPS
  };

  String _host = defaultProductionHost;
  int    _port = defaultPort;

  String get host => _host;
  int    get port => _port;

  /// Builds the base URL.
  /// Port 443 → https (no explicit port).
  /// Port 80  → http  (no explicit port).
  /// Other    → http  with explicit port (local/dev).
  String get baseUrl {
    if (_port == 443) return 'https://$_host';
    if (_port == 80)  return 'http://$_host';
    return 'http://$_host:$_port';
  }

  ApiConfig() {
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    String host = prefs.getString(_keyHost) ?? defaultProductionHost;
    int    port = prefs.getInt(_keyPort)    ?? defaultPort;
    // Migrate legacy/emulator hosts to HTTPS production domain.
    // Preserves Tailscale (100.x.x.x) and LAN (192.168.*) — those are
    // explicit developer choices.
    final bool isLegacyEmulator =
        host == '10.0.2.2' || host == '127.0.0.1' || host == 'localhost';
    // Also migrate the old raw-IP production entry (plain HTTP port 8000).
    final bool isOldRawIp = host == '77.42.40.146' && port == 8000;
    if (isLegacyEmulator || isOldRawIp) {
      host = defaultProductionHost;
      port = defaultPort;
      await prefs.setString(_keyHost, host);
      await prefs.setInt(_keyPort,    port);
    }
    _host = host;
    _port = port;
    notifyListeners();
  }

  Future<void> update({String? host, int? port}) async {
    if (host != null) _host = host;
    if (port != null) _port = port;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyHost, _host);
    await prefs.setInt(_keyPort, _port);
    notifyListeners();
  }

  Future<void> reset() async {
    await update(host: defaultEmulatorHost, port: defaultPort);
  }
}
