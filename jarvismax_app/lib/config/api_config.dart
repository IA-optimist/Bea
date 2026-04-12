import 'package:flutter/foundation.dart';
import 'hardcoded_config.dart';

/// ApiConfig — Fully hardcoded for Unity personal build.
/// No SharedPreferences, no migration, no domain guessing.
class ApiConfig extends ChangeNotifier {
  // All values come from HardcodedConfig — single source of truth.
  String get host    => HardcodedConfig.apiHost;
  int    get port    => HardcodedConfig.apiPort;
  String get baseUrl => 'http://${HardcodedConfig.apiHost}:${HardcodedConfig.apiPort}';

  // No-op update/reset — hardcoded build
  Future<void> update({String? host, int? port}) async {}
  Future<void> reset() async {}
}
