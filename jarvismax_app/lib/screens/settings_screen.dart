import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../services/session_manager.dart';
import '../services/websocket_service.dart';
import '../config/api_config.dart';
import '../theme/design_system.dart';
import 'modules_screen.dart';
import 'self_improvement_screen.dart';
import 'health_screen.dart';
import 'capabilities_screen.dart';
import 'aios_dashboard_screen.dart';
import 'admin_panel_screen.dart';

/// Settings — configuration + advanced access point.
/// Normal: server, account, logout.
/// Advanced section: Modules, System, Capabilities, Self-Improvement, AI OS.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final api    = context.watch<ApiService>();
    final ws     = context.watch<WebSocketService>();
    final config = context.watch<ApiConfig>();
    final isAdmin = api.isAdmin;

    return Scaffold(
      body: SafeArea(
        child: CustomScrollView(slivers: [
          // ── Header ──
          SliverToBoxAdapter(child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
            child: const Text('Paramètres', style: TextStyle(
              fontSize: 22, fontWeight: FontWeight.w700,
              color: JDS.textPrimary, letterSpacing: -0.3,
            )),
          )),

          // ── Connection status ──
          SliverToBoxAdapter(child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 0),
            child: JCard(child: Column(children: [
              _StatusRow(
                icon: Icons.cloud_outlined,
                label: 'Serveur',
                value: api.status.isOnline ? 'Connecté' : 'Hors ligne',
                color: api.status.isOnline ? JDS.green : JDS.red,
              ),
              const Divider(height: 20),
              _StatusRow(
                icon: Icons.sync_alt_rounded,
                label: 'WebSocket',
                value: ws.isConnected ? 'Actif' : 'Déconnecté',
                color: ws.isConnected ? JDS.green : JDS.textDim,
              ),
              const Divider(height: 20),
              _StatusRow(
                icon: Icons.dns_outlined,
                label: 'Adresse',
                value: config.baseUrl.replaceFirst('http://', '').replaceFirst('https://', ''),
                color: JDS.textSecondary,
              ),
            ])),
          )),

          // ── Account ──
          SliverToBoxAdapter(child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
            child: JSectionHeader(title: 'Compte'),
          )),
          SliverToBoxAdapter(child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: JCard(child: Column(children: [
              // Role indicator
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Row(children: [
                  Icon(
                    isAdmin ? Icons.shield_outlined : Icons.person_outline,
                    size: 18,
                    color: isAdmin ? JDS.blue : JDS.textSecondary,
                  ),
                  const SizedBox(width: 10),
                  Text(
                    isAdmin ? 'Administrateur' : 'Utilisateur',
                    style: TextStyle(
                      color: isAdmin ? JDS.blue : JDS.textSecondary,
                      fontSize: 14, fontWeight: FontWeight.w500,
                    ),
                  ),
                  const Spacer(),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: (isAdmin ? JDS.blue : JDS.textDim).withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      isAdmin ? 'ADMIN' : 'USER',
                      style: TextStyle(
                        fontSize: 10, fontWeight: FontWeight.w700,
                        color: isAdmin ? JDS.blue : JDS.textDim,
                        letterSpacing: 0.5,
                      ),
                    ),
                  ),
                ]),
              ),
              const Divider(height: 12),
              _SettingsItem(
                icon: Icons.logout_rounded,
                label: 'Se déconnecter',
                color: JDS.red,
                onTap: () => _logout(context),
              ),
            ])),
          )),

          // ── Advanced (admin only) ──
          if (isAdmin) ...[
            SliverToBoxAdapter(child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 0),
              child: JSectionHeader(title: 'Avancé'),
            )),
            SliverToBoxAdapter(child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 0),
              child: JCard(padding: EdgeInsets.zero, child: Column(children: [
                _NavItem(
                  icon: Icons.dashboard_outlined,
                  label: 'Panneau Admin',
                  subtitle: 'Métriques, coût modèles, alertes',
                  onTap: () => _push(context, const AdminPanelScreen()),
                ),
                const Divider(height: 1, indent: 52),
                _NavItem(
                  icon: Icons.extension_rounded,
                  label: 'Modules',
                  subtitle: 'Agents, compétences, connecteurs, MCP',
                  onTap: () => _push(context, const ModulesScreen()),
                ),
                const Divider(height: 1, indent: 52),
                _NavItem(
                  icon: Icons.memory_rounded,
                  label: 'Tableau de bord',
                  subtitle: 'Vue système et diagnostics',
                  onTap: () => _push(context, const AIOSDashboardScreen()),
                ),
                const Divider(height: 1, indent: 52),
                _NavItem(
                  icon: Icons.category_rounded,
                  label: 'Capacités',
                  subtitle: 'Outils disponibles et routage',
                  onTap: () => _push(context, const CapabilitiesScreen()),
                ),
                const Divider(height: 1, indent: 52),
                _NavItem(
                  icon: Icons.auto_fix_high_rounded,
                  label: 'Auto-amélioration',
                  subtitle: 'Patchs autonomes et apprentissage',
                  onTap: () => _push(context, const SelfImprovementScreen()),
                ),
                const Divider(height: 1, indent: 52),
                _NavItem(
                  icon: Icons.monitor_heart_outlined,
                  label: 'Santé système',
                  subtitle: 'Métriques, disponibilité, ressources',
                  onTap: () => _push(context, const HealthScreen()),
                ),
              ])),
            )),
          ],

          // ── Version ──
          SliverToBoxAdapter(child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 24, 20, 0),
            child: Column(children: [
              Center(child: Text('Bea AI OS • v2.0.0', style: TextStyle(
                fontSize: 12, color: JDS.textDim,
              ))),
              const SizedBox(height: 4),
              Center(child: Text(
                'Backend: ${config.baseUrl.replaceFirst("https://", "").replaceFirst("http://", "")}',
                style: TextStyle(fontSize: 10, color: JDS.textDim),
              )),
            ]),
          )),

          const SliverToBoxAdapter(child: SizedBox(height: 100)),
        ]),
      ),
    );
  }

  void _push(BuildContext ctx, Widget screen) {
    Navigator.push(ctx, MaterialPageRoute(builder: (_) => screen));
  }

  Future<void> _logout(BuildContext ctx) async {
    final confirmed = await showDialog<bool>(
      context: ctx,
      builder: (c) => AlertDialog(
        backgroundColor: JDS.bgElevated,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(JDS.radiusLg)),
        title: const Text('Se déconnecter ?', style: TextStyle(color: JDS.textPrimary)),
        content: const Text('Vous devrez vous reconnecter.',
            style: TextStyle(color: JDS.textSecondary)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false),
              child: const Text('Annuler')),
          TextButton(onPressed: () => Navigator.pop(c, true),
              style: TextButton.styleFrom(foregroundColor: JDS.red),
              child: const Text('Déconnecter')),
        ],
      ),
    );
    if (confirmed != true) return;
    await SessionManager.instance.logout();
    // clearJwt() calls notifyListeners() → _AppState watches jwtToken → shows LoginScreen
    if (ctx.mounted) await ctx.read<ApiService>().clearJwt();
  }
}

// ── Status Row ───────────────────────────────────────────────────────────────

class _StatusRow extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const _StatusRow({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Row(children: [
      Icon(icon, size: 18, color: JDS.textMuted),
      const SizedBox(width: 12),
      Text(label, style: const TextStyle(fontSize: 14, color: JDS.textSecondary)),
      const Spacer(),
      Container(
        width: 7, height: 7,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 8),
      Text(value, style: TextStyle(fontSize: 13, color: color, fontWeight: FontWeight.w500)),
    ]);
  }
}

// ── Settings Item ────────────────────────────────────────────────────────────

class _SettingsItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _SettingsItem({
    required this.icon,
    required this.label,
    this.color = JDS.textPrimary,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Row(children: [
        Icon(icon, size: 18, color: color),
        const SizedBox(width: 12),
        Text(label, style: TextStyle(fontSize: 14, color: color, fontWeight: FontWeight.w500)),
        const Spacer(),
        Icon(Icons.chevron_right_rounded, size: 18, color: JDS.textDim),
      ]),
    );
  }
}

// ── Navigation Item ──────────────────────────────────────────────────────────

class _NavItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final String subtitle;
  final VoidCallback onTap;

  const _NavItem({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(children: [
          Container(
            width: 36, height: 36,
            decoration: BoxDecoration(
              color: JDS.bgOverlay,
              borderRadius: BorderRadius.circular(JDS.radiusSm),
            ),
            child: Icon(icon, size: 18, color: JDS.textSecondary),
          ),
          const SizedBox(width: 12),
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: const TextStyle(
                fontSize: 14, fontWeight: FontWeight.w500, color: JDS.textPrimary,
              )),
              Text(subtitle, style: const TextStyle(
                fontSize: 12, color: JDS.textMuted,
              )),
            ],
          )),
          const Icon(Icons.chevron_right_rounded, size: 18, color: JDS.textDim),
        ]),
      ),
    );
  }
}
