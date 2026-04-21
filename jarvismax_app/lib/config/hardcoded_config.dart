/// JarvisMax — Configuration locale pour Flutter
/// App personnelle Unity — auto-login sans écran login
///
/// ⚠️ SÉCURITÉ ⚠️
/// Ce fichier contient des credentials. Pour empêcher la fuite via git :
///   1. Copier ce fichier en `hardcoded_config_local.dart` (non commité).
///   2. Remplacer les placeholders CHANGE_ME par les vraies valeurs.
///   3. Ou utiliser --dart-define au moment du build :
///        flutter build apk --dart-define=JARVIS_API_TOKEN=jv-xxxxx \
///                           --dart-define=JARVIS_API_HOST=77.42.40.146
///
/// Si un vrai token a été commité historiquement (cf commit e63a5c5 +
/// docs/SECURITY_AUDIT.md), il DOIT être révoqué côté serveur via l'API
/// /api/v2/tokens/{id}/revoke avant toute distribution d'APK.

class HardcodedConfig {
  // ══════════════════════════════════════════════
  // CREDENTIALS — NE PAS COMMITER EN CLAIR
  // Lues via --dart-define au build. Valeurs par défaut = placeholders
  // inoffensifs pour que le build ne casse pas en dev.
  // ══════════════════════════════════════════════
  static const String apiToken = String.fromEnvironment(
    'JARVIS_API_TOKEN',
    defaultValue: 'CHANGE_ME_via_--dart-define_or_local_override',
  );
  static const String apiHost = String.fromEnvironment(
    'JARVIS_API_HOST',
    defaultValue: '127.0.0.1',
  );
  static const int apiPort = int.fromEnvironment(
    'JARVIS_API_PORT',
    defaultValue: 8000,
  );
  static const String username = String.fromEnvironment(
    'JARVIS_USERNAME',
    defaultValue: 'admin',
  );

  /// Mode auto-login : true = bypass écran login, connexion directe.
  /// Seulement effectif si apiToken a été défini via --dart-define
  /// (sinon le placeholder déclenche un 401 au premier appel).
  static const bool autoLogin = bool.fromEnvironment(
    'JARVIS_AUTO_LOGIN',
    defaultValue: false,
  );
}
