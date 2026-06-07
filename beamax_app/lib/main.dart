import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import 'config/api_config.dart';
import 'models/app_mode.dart';
import 'services/api_service.dart';
import 'services/uncensored_notifier.dart';
import 'services/websocket_service.dart';
import 'theme/design_system.dart';
import 'screens/home_screen.dart';
import 'screens/mission_screen.dart';
import 'screens/approvals_screen.dart';
import 'screens/history_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/modules_screen.dart';
import 'screens/login_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: JDS.bgSurface,
    systemNavigationBarIconBrightness: Brightness.light,
  ));

  runApp(const BeaApp());
}

/// Root application widget.
class BeaApp extends StatelessWidget {
  const BeaApp({super.key});

  @override
  Widget build(BuildContext context) {
    final apiConfig          = ApiConfig();
    final apiService         = ApiService();
    final wsService          = WebSocketService();
    final uncensoredNotifier = UncensoredModeNotifier(apiService);
    apiService.setConfig(apiConfig);
    wsService.setConfig(apiConfig);
    apiService.setWebSocketService(wsService);

    return MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: apiConfig),
        ChangeNotifierProvider.value(value: apiService),
        ChangeNotifierProvider.value(value: uncensoredNotifier),
        ChangeNotifierProvider.value(value: wsService),
      ],
      child: MaterialApp(
        title: 'Bea',
        debugShowCheckedModeBanner: false,
        theme: BeaTheme.dark,
        home: const _AppEntry(),
      ),
    );
  }
}

// ─── App Entry — Auth gate ───────────────────────────────────────────────────

class _AppEntry extends StatefulWidget {
  const _AppEntry();

  @override
  State<_AppEntry> createState() => _AppEntryState();
}

class _AppEntryState extends State<_AppEntry> {
  bool _loggedIn = false;
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _checkSession();
  }

  Future<void> _checkSession() async {
    final api = context.read<ApiService>();
    await Future.delayed(const Duration(milliseconds: 300));
    if (api.jwtToken.isNotEmpty) {
      try {
        final ok = await api.checkHealth();
        if (mounted) setState(() { _loggedIn = ok; _checking = false; });
      } catch (_) {
        if (mounted) setState(() { _checking = false; });
      }
    } else {
      if (mounted) setState(() { _checking = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_checking) {
      return Scaffold(
        backgroundColor: JDS.bgBase,
        body: Center(child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Brand mark
            Container(
              width: 56, height: 56,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                gradient: const LinearGradient(
                  colors: [JDS.blue, JDS.violet],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: const Center(child: Text('J', style: TextStyle(
                fontSize: 24, fontWeight: FontWeight.w700, color: Colors.white,
              ))),
            ),
            const SizedBox(height: 20),
            const Text('Bea', style: TextStyle(
              fontSize: 24, fontWeight: FontWeight.w700,
              color: JDS.textPrimary, letterSpacing: -0.5,
            )),
            const SizedBox(height: 6),
            const Text('AI Operating System', style: TextStyle(
              fontSize: 12, fontWeight: FontWeight.w500,
              color: JDS.textMuted, letterSpacing: 1,
            )),
            const SizedBox(height: 32),
            const SizedBox(
              width: 24, height: 24,
              child: CircularProgressIndicator(strokeWidth: 2, color: JDS.blue),
            ),
          ],
        )),
      );
    }

    // Also react to api.clearJwt() — logout from SettingsScreen
    final apiToken = context.watch<ApiService>().jwtToken;
    if (!_loggedIn || apiToken.isEmpty) {
      return LoginScreen(
        onLoginSuccess: () => setState(() => _loggedIn = true),
      );
    }
    return const _AppShell();
  }
}

// ─── Tab navigation notifier — allows child screens to switch tabs ────────────

/// Shared notifier for programmatic tab switching.
/// Set [tabNotifier.value] from any screen to switch tabs.
final ValueNotifier<int> tabNotifier = ValueNotifier<int>(0);

// ─── App Shell — Tab navigation ──────────────────────────────────────────────

class _AppShell extends StatefulWidget {
  const _AppShell({super.key});

  @override
  State<_AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<_AppShell> with WidgetsBindingObserver {
  int _tab = 0;

  // 5 core tabs — clean and focused
  static const _tabs = <Widget>[
    HomeScreen(),        // 0: Home — status, recents, quick action
    MissionScreen(),     // 1: Missions — chat AI interface
    ApprovalsScreen(),   // 2: Approvals
    HistoryScreen(),     // 3: History
    SettingsScreen(),    // 4: Settings + advanced
  ];

  void _onTabNotifier() {
    final target = tabNotifier.value;
    if (target != _tab && target >= 0 && target < _tabs.length) {
      setState(() => _tab = target);
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    tabNotifier.addListener(_onTabNotifier);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final api = context.read<ApiService>();
      api.checkHealth();
      api.refresh();
      api.startAutoRefresh();
      context.read<UncensoredModeNotifier>().init();
      context.read<WebSocketService>().connect();
    });
  }

  @override
  Widget build(BuildContext context) {
    final pendingCount = context.watch<ApiService>().pendingActions.length;

    return Scaffold(
      body: IndexedStack(index: _tab, children: _tabs),
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          border: Border(top: BorderSide(color: JDS.borderSubtle, width: 0.5)),
        ),
        child: BottomNavigationBar(
          currentIndex: _tab,
          onTap: (i) {
            setState(() => _tab = i);
            tabNotifier.value = i;
          },
          type: BottomNavigationBarType.fixed,
          items: [
            const BottomNavigationBarItem(
              icon: Icon(Icons.home_rounded),
              activeIcon: Icon(Icons.home_rounded),
              label: 'Accueil',
            ),
            const BottomNavigationBarItem(
              icon: Icon(Icons.rocket_launch_outlined),
              activeIcon: Icon(Icons.rocket_launch_rounded),
              label: 'Missions',
            ),
            BottomNavigationBarItem(
              icon: Badge(
                isLabelVisible: pendingCount > 0,
                label: Text('$pendingCount',
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                backgroundColor: JDS.amber,
                child: const Icon(Icons.check_circle_outline_rounded),
              ),
              activeIcon: Badge(
                isLabelVisible: pendingCount > 0,
                label: Text('$pendingCount',
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700)),
                backgroundColor: JDS.amber,
                child: const Icon(Icons.check_circle_rounded),
              ),
              label: 'Approbations',
            ),
            const BottomNavigationBarItem(
              icon: Icon(Icons.history_rounded),
              activeIcon: Icon(Icons.history_rounded),
              label: 'Historique',
            ),
            const BottomNavigationBarItem(
              icon: Icon(Icons.settings_outlined),
              activeIcon: Icon(Icons.settings),
              label: 'Paramètres',
            ),
          ],
        ),
      ),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    try {
      context.read<WebSocketService>().onAppLifecycleChanged(state);
    } catch (_) {}
    if (state == AppLifecycleState.resumed) {
      try { context.read<ApiService>().refresh(); } catch (_) {}
    }
  }

  @override
  void dispose() {
    tabNotifier.removeListener(_onTabNotifier);
    WidgetsBinding.instance.removeObserver(this);
    context.read<ApiService>().stopAutoRefresh();
    context.read<WebSocketService>().disconnect();
    super.dispose();
  }
}

