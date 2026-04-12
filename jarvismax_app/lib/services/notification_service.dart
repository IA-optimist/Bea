/// JarvisMax — Local notification service
/// Triggers Android notifications for approvals, mission completion, errors.
/// Uses flutter_local_notifications (no Firebase required).

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

class NotificationService {
  static final NotificationService _instance = NotificationService._();
  static NotificationService get instance => _instance;
  NotificationService._();

  final _plugin = FlutterLocalNotificationsPlugin();
  bool _initialized = false;

  static const _channelApproval = AndroidNotificationChannel(
    'jarvis_approval', 'Approbations',
    description: 'Jarvis demande votre validation',
    importance: Importance.max,
    playSound: true,
    enableVibration: true,
  );

  static const _channelMission = AndroidNotificationChannel(
    'jarvis_mission', 'Missions',
    description: 'Statut des missions Jarvis',
    importance: Importance.high,
  );

  static const _channelAlert = AndroidNotificationChannel(
    'jarvis_alert', 'Alertes',
    description: 'Alertes système Jarvis',
    importance: Importance.high,
  );

  Future<void> init() async {
    if (_initialized) return;
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    const settings = InitializationSettings(android: android);
    await _plugin.initialize(settings);

    final androidPlugin = _plugin
        .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
    await androidPlugin?.createNotificationChannel(_channelApproval);
    await androidPlugin?.createNotificationChannel(_channelMission);
    await androidPlugin?.createNotificationChannel(_channelAlert);
    await androidPlugin?.requestNotificationsPermission();

    _initialized = true;
    debugPrint('[Notif] Service initialized');
  }

  /// Show approval required notification (high priority, stays until dismissed)
  Future<void> showApprovalRequired({
    required String missionId,
    required String action,
    String? risk,
  }) async {
    await _ensureInit();
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'jarvis_approval', 'Approbations',
        importance: Importance.max,
        priority: Priority.high,
        fullScreenIntent: true,
        ongoing: false,
        autoCancel: true,
        styleInformation: BigTextStyleInformation(''),
      ),
    );
    await _plugin.show(
      missionId.hashCode,
      '⚠️ Jarvis demande votre approbation',
      '${action.length > 80 ? action.substring(0, 80) + '…' : action}'
      '${risk != null ? " [Risque: $risk]" : ""}',
      details,
    );
  }

  /// Show mission completed notification
  Future<void> showMissionDone({
    required String missionId,
    required String goal,
    bool success = true,
  }) async {
    await _ensureInit();
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'jarvis_mission', 'Missions',
        importance: Importance.high,
        priority: Priority.defaultPriority,
        autoCancel: true,
      ),
    );
    final short = goal.length > 60 ? goal.substring(0, 60) + '…' : goal;
    await _plugin.show(
      (missionId + '_done').hashCode,
      success ? '✅ Mission terminée' : '❌ Mission échouée',
      short,
      details,
    );
  }

  /// Show generic alert
  Future<void> showAlert(String title, String body) async {
    await _ensureInit();
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        'jarvis_alert', 'Alertes',
        importance: Importance.high,
        priority: Priority.high,
        autoCancel: true,
      ),
    );
    await _plugin.show(DateTime.now().millisecondsSinceEpoch ~/ 1000, title, body, details);
  }

  Future<void> _ensureInit() async {
    if (!_initialized) await init();
  }
}
