import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../main.dart' show tabNotifier;
import '../services/api_service.dart';
import '../services/websocket_service.dart';
import '../models/mission.dart';
import '../theme/design_system.dart';
import 'mission_detail_screen.dart';

/// Home — the primary Jarvis interface.
/// Shows: greeting, quick input, system status, approvals, recent missions.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {

  @override
  Widget build(BuildContext context) {
    final ws = context.watch<WebSocketService>();
    final api = context.watch<ApiService>();

    return Scaffold(
      body: SafeArea(
        child: GestureDetector(
          onTap: () => _focus.unfocus(),
          child: RefreshIndicator(
            onRefresh: api.refresh,
            color: JDS.blue,
            backgroundColor: JDS.bgElevated,
            child: CustomScrollView(slivers: [
              // ── Header ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                child: Row(children: [
                  // Brand
                  Container(
                    width: 34, height: 34,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(10),
                      gradient: const LinearGradient(
                        colors: [JDS.blue, JDS.violet],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                    ),
                    child: const Center(child: Text('J', style: TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w700, color: Colors.white,
                    ))),
                  ),
                  const SizedBox(width: 10),
                  const Text('Jarvis', style: TextStyle(
                    fontSize: 22, fontWeight: FontWeight.w700,
                    color: JDS.textPrimary, letterSpacing: -0.5,
                  )),
                  const Spacer(),
                  _ConnectionIndicator(connected: ws.isConnected),
                ]),
              )),

              // ── Greeting ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(_dateString(), style: const TextStyle(
                    fontSize: 12, fontWeight: FontWeight.w500, color: JDS.textMuted,
                  )),
                  const SizedBox(height: 4),
                  Text(_greetingText(), style: const TextStyle(
                    fontSize: 26, fontWeight: FontWeight.w700,
                    color: JDS.textPrimary, letterSpacing: -0.5, height: 1.2,
                  )),
                ]),
              )),

              // ── Approval Alert ──
              if (api.pendingActions.isNotEmpty)
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 16),
                  child: _ApprovalAlert(count: api.pendingActions.length),
                )),

              // ── Quick Action — navigate to Missions chat ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                child: _QuickMissionButton(onTap: () {
                  _navigateToMissions(context);
                }),
              )),

              // ── Stats ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                child: _StatsRow(api: api),
              )),

              // ── Recent Missions ──
              SliverToBoxAdapter(child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 24, 20, 12),
                child: JSectionHeader(
                  title: 'Missions récentes',
                  count: '${api.missions.length}',
                  action: TextButton(
                    onPressed: () => api.refresh(),
                    style: TextButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    child: const Text('Actualiser', style: TextStyle(
                      fontSize: 12, color: JDS.textMuted,
                    )),
                  ),
                ),
              )),

              // Mission list or empty
              if (api.loading && api.missions.isEmpty)
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Column(children: List.generate(3, (_) => Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: _MissionSkeleton(),
                  ))),
                ))
              else if (api.missions.isEmpty)
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: JEmptyState(
                    icon: Icons.rocket_launch_outlined,
                    title: 'Aucune mission',
                    subtitle: 'Lancez une mission depuis l'onglet Missions',
                  ),
                ))
              else
                SliverList(delegate: SliverChildBuilderDelegate(
                  (_, i) {
                    final m = api.missions[i];
                    return Padding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                      child: _MissionCard(mission: m, onTap: () => _openMission(m)),
                    );
                  },
                  childCount: api.missions.take(10).length,
                )),

              const SliverToBoxAdapter(child: SizedBox(height: 100)),
            ]),
          ),
        ),
      ),
    );
  }

  void _navigateToMissions(BuildContext ctx) {
    // Switch to Missions tab (index 1) via shared notifier
    tabNotifier.value = 1;
  }

  String _dateString() {
    final now = DateTime.now();
    final weekdays = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
    final months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                    'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
    return '${weekdays[now.weekday - 1]} ${now.day} ${months[now.month - 1]}';
  }

  String _greetingText() {
    final h = DateTime.now().hour;
    if (h < 6) return 'Vous travaillez tard ?';
    if (h < 12) return 'Bonjour.';
    if (h < 18) return 'Bon après-midi.';
    return 'Bonsoir.';
  }

  void _openMission(Mission m) {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => MissionDetailScreen(mission: m),
    ));
  }

  @override
  void dispose() {
    super.dispose();
  }
}

// ── Connection Indicator ─────────────────────────────────────────────────────

class _ConnectionIndicator extends StatelessWidget {
  final bool connected;
  const _ConnectionIndicator({required this.connected});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: JDS.bgElevated,
        borderRadius: BorderRadius.circular(JDS.radiusSm),
        border: Border.all(color: JDS.borderSubtle),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Container(
          width: 7, height: 7,
          decoration: BoxDecoration(
            color: connected ? JDS.green : JDS.textDim,
            shape: BoxShape.circle,
            boxShadow: connected
                ? [BoxShadow(color: JDS.green.withValues(alpha: 0.4), blurRadius: 4)]
                : null,
          ),
        ),
        const SizedBox(width: 6),
        Text(connected ? 'En ligne' : 'Hors ligne', style: TextStyle(
          fontSize: 11, fontWeight: FontWeight.w500,
          color: connected ? JDS.textSecondary : JDS.textDim,
        )),
      ]),
    );
  }
}

// ── Approval Alert ───────────────────────────────────────────────────────────

class _ApprovalAlert extends StatelessWidget {
  final int count;
  const _ApprovalAlert({required this.count});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.amberSoft,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: JDS.amber.withValues(alpha: 0.2)),
      ),
      child: Row(children: [
        const Icon(Icons.pending_actions_rounded, size: 20, color: JDS.amber),
        const SizedBox(width: 12),
        Expanded(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('$count élément${count > 1 ? 's' : ''} attend${count == 1 ? '' : 'ent'} votre décision',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: JDS.amber)),
            const Text('Jarvis attend votre validation avant de continuer',
                style: TextStyle(fontSize: 12, color: JDS.textSecondary)),
          ],
        )),
        const Icon(Icons.chevron_right_rounded, color: JDS.amber, size: 20),
      ]),
    );
  }
}

// ── Quick Mission Button ─────────────────────────────────────────────────────

class _QuickMissionButton extends StatelessWidget {
  final VoidCallback onTap;
  const _QuickMissionButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: JDS.bgSurface,
          borderRadius: BorderRadius.circular(JDS.radiusLg),
          border: Border.all(color: JDS.borderDefault),
        ),
        child: Row(children: [
          Container(
            width: 40, height: 40,
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [JDS.blue, JDS.violet],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(JDS.radiusMd),
            ),
            child: const Icon(Icons.chat_bubble_outline_rounded, size: 18, color: Colors.white),
          ),
          const SizedBox(width: 14),
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: const [
              Text('Nouvelle mission', style: TextStyle(
                fontSize: 15, fontWeight: FontWeight.w600, color: JDS.textPrimary,
              )),
              SizedBox(height: 2),
              Text('Recherche, analyse, code, stratégie…', style: TextStyle(
                fontSize: 13, color: JDS.textMuted,
              )),
            ],
          )),
          const Icon(Icons.arrow_forward_ios_rounded, size: 14, color: JDS.textDim),
        ]),
      ),
    );
  }
}

// ── Stats Row ────────────────────────────────────────────────────────────────

class _StatsRow extends StatelessWidget {
  final ApiService api;
  const _StatsRow({required this.api});

  @override
  Widget build(BuildContext context) {
    final running = api.missions.where((m) =>
        m.status.toLowerCase() == 'running' || m.status.toLowerCase() == 'executing').length;
    final done = api.missions.where((m) =>
        m.status.toLowerCase() == 'completed' || m.status.toLowerCase() == 'done').length;
    final failed = api.missions.where((m) =>
        m.status.toLowerCase() == 'failed').length;

    return Row(children: [
      Expanded(child: _StatTile(value: '$running', label: 'Actif', color: JDS.blue)),
      const SizedBox(width: 10),
      Expanded(child: _StatTile(value: '$done', label: 'Terminé', color: JDS.green)),
      const SizedBox(width: 10),
      Expanded(child: _StatTile(value: '$failed', label: 'Échoué', color: JDS.red)),
      const SizedBox(width: 10),
      Expanded(child: _StatTile(
        value: api.status.isOnline ? '✓' : '—',
        label: 'Système',
        color: api.status.isOnline ? JDS.green : JDS.textDim,
      )),
    ]);
  }
}

class _StatTile extends StatelessWidget {
  final String value;
  final String label;
  final Color color;
  const _StatTile({required this.value, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 12),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: JDS.borderSubtle),
      ),
      child: Column(children: [
        Text(value, style: TextStyle(
          fontSize: 20, fontWeight: FontWeight.w700, color: color, height: 1,
        )),
        const SizedBox(height: 4),
        Text(label, style: const TextStyle(
          fontSize: 11, color: JDS.textMuted, fontWeight: FontWeight.w500,
        )),
      ]),
    );
  }
}

// ── Mission Card ─────────────────────────────────────────────────────────────

class _MissionCard extends StatelessWidget {
  final Mission mission;
  final VoidCallback onTap;
  const _MissionCard({required this.mission, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final status = mission.status.toLowerCase();

    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: JDS.bgSurface,
          borderRadius: BorderRadius.circular(JDS.radiusMd),
          border: Border.all(color: JDS.borderSubtle),
        ),
        child: Row(children: [
          JStatusDot(status: status),
          const SizedBox(width: 12),
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                mission.userInput.isNotEmpty ? mission.userInput : mission.id,
                style: const TextStyle(fontSize: 14, color: JDS.textPrimary, fontWeight: FontWeight.w500),
                maxLines: 1, overflow: TextOverflow.ellipsis,
              ),
              const SizedBox(height: 2),
              Text(_missionMeta(mission), style: const TextStyle(
                fontSize: 12, color: JDS.textDim,
              )),
            ],
          )),
          const SizedBox(width: 8),
          JStatusBadge.fromStatus(status),
        ]),
      ),
    );
  }

  String _missionMeta(Mission m) {
    final parts = <String>[];
    if (m.createdAt.isNotEmpty) {
      final dt = DateTime.tryParse(m.createdAt);
      if (dt != null) parts.add(_timeAgo(dt));
    }
    return parts.join(' · ');
  }

  String _timeAgo(DateTime dt) {
    final diff = DateTime.now().difference(dt);
    if (diff.inMinutes < 1) return 'à l\'instant';
    if (diff.inMinutes < 60) return 'il y a ${diff.inMinutes}min';
    if (diff.inHours < 24) return 'il y a ${diff.inHours}h';
    return 'il y a ${diff.inDays}j';
  }
}

// ── Mission Skeleton ─────────────────────────────────────────────────────────

class _MissionSkeleton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: JDS.borderSubtle),
      ),
      child: Row(children: [
        Container(
          width: 8, height: 8,
          decoration: BoxDecoration(
            color: JDS.bgOverlay,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 12),
        Expanded(child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(height: 14, width: 200, decoration: BoxDecoration(
              color: JDS.bgOverlay, borderRadius: BorderRadius.circular(4),
            )),
            const SizedBox(height: 6),
            Container(height: 10, width: 80, decoration: BoxDecoration(
              color: JDS.bgOverlay, borderRadius: BorderRadius.circular(4),
            )),
          ],
        )),
      ]),
    );
  }
}

