import 'package:flutter/foundation.dart';
import 'api_service.dart';

/// Gère l'état global du mode uncensored.
/// - Démarre toujours à false (reset à chaque lancement de l'app)
/// - Synchronise avec le backend via ApiService
/// - Notifie les widgets via ChangeNotifier / Provider
class UncensoredModeNotifier extends ChangeNotifier {
  bool _isUncensored = false;

  bool get isUncensored => _isUncensored;

  final ApiService _api;

  UncensoredModeNotifier(this._api);

  /// Appelé au démarrage pour synchroniser avec le serveur.
  Future<void> init() async {
    try {
      final raw = await _api.getUncensoredMode();
      _isUncensored = raw['uncensored'] == true;
      notifyListeners();
    } catch (_) {
      // Serveur injoignable — on reste à false
    }
  }

  /// Active ou désactive le mode uncensored via l'API.
  Future<void> setUncensored(bool enabled) async {
    await _api.setUncensoredMode(enabled);
    _isUncensored = enabled;
    notifyListeners();
  }
}
