import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Secure session persistence for Bea.
///
/// Storage strategy:
///   - Access token → FlutterSecureStorage (encrypted keychain/keystore)
///   - Admin password → FlutterSecureStorage (only if remember_me = true)
///   - Login mode / username → SharedPreferences (non-sensitive)
///   - Remember me flag → SharedPreferences
///
/// Security:
///   - Tokens stored encrypted via OS keychain (iOS) / Android Keystore
///   - Password stored ONLY if user opts in via "Remember me"
///   - Logout wipes ALL secure storage entries
///   - Invalid stored data never crashes app
class SessionManager {
  static final SessionManager instance = SessionManager._();
  SessionManager._();

  final _secure = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  // Secure storage keys
  static const _keyToken = 'bea_auth_token';
  static const _keyPassword = 'bea_admin_password';

  // SharedPreferences keys (non-sensitive)
  static const _keyLoginMode = 'bea_login_mode';  // "admin" or "token"
  static const _keyUsername = 'bea_username';
  static const _keyRememberMe = 'bea_remember_me';
  static const _keyRole = 'bea_role';

  // ── Save ──

  /// Save session after successful login.
  Future<void> saveSession({
    required String token,
    required String loginMode,   // "admin" or "token"
    String? username,
    String? password,
    String? role,
    bool rememberMe = false,
  }) async {
    // Token always in secure storage
    await _secure.write(key: _keyToken, value: token);

    // Password only if remember_me AND admin mode
    if (rememberMe && loginMode == 'admin' && password != null) {
      await _secure.write(key: _keyPassword, value: password);
    } else {
      await _secure.delete(key: _keyPassword);
    }

    // Non-sensitive metadata in prefs
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyLoginMode, loginMode);
    await prefs.setBool(_keyRememberMe, rememberMe);
    if (username != null) await prefs.setString(_keyUsername, username);
    if (role != null) await prefs.setString(_keyRole, role);
  }

  // ── Restore ──

  /// Try restoring a saved session. Returns null if no valid session.
  Future<SavedSession?> restoreSession() async {
    try {
      final token = await _secure.read(key: _keyToken);
      if (token == null || token.isEmpty) return null;

      final prefs = await SharedPreferences.getInstance();
      return SavedSession(
        token: token,
        loginMode: prefs.getString(_keyLoginMode) ?? 'token',
        username: prefs.getString(_keyUsername) ?? '',
        role: prefs.getString(_keyRole) ?? 'user',
        rememberMe: prefs.getBool(_keyRememberMe) ?? false,
      );
    } catch (_) {
      return null;
    }
  }

  /// Get stored admin password (only if remember_me was on).
  Future<String?> getStoredPassword() async {
    try {
      return await _secure.read(key: _keyPassword);
    } catch (_) {
      return null;
    }
  }

  // ── Logout ──

  /// Clear all auth data. Wipes secure storage completely.
  Future<void> logout() async {
    await _secure.delete(key: _keyToken);
    await _secure.delete(key: _keyPassword);

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyLoginMode);
    await prefs.remove(_keyUsername);
    await prefs.remove(_keyRememberMe);
    await prefs.remove(_keyRole);

    // Also clear legacy keys
    await prefs.remove('jwt_token');
  }

  // ── Query ──

  Future<bool> hasSession() async {
    final token = await _secure.read(key: _keyToken);
    return token != null && token.isNotEmpty;
  }

  Future<String?> getToken() async {
    try {
      return await _secure.read(key: _keyToken);
    } catch (_) {
      return null;
    }
  }

  Future<String> getLoginMode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_keyLoginMode) ?? 'token';
  }

  Future<bool> getRememberMe() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getBool(_keyRememberMe) ?? false;
  }
}

/// Restored session data.
class SavedSession {
  final String token;
  final String loginMode;
  final String username;
  final String role;
  final bool rememberMe;

  SavedSession({
    required this.token,
    required this.loginMode,
    required this.username,
    required this.role,
    required this.rememberMe,
  });
}
