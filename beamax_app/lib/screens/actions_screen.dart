import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/action_model.dart';
import '../theme/design_system.dart';
import '../widgets/cyber_card.dart';
import '../widgets/status_badge.dart';

class ActionsScreen extends StatefulWidget {
  const ActionsScreen({super.key});

  @override
  State<ActionsScreen> createState() => _ActionsScreenState();
}

class _ActionsScreenState extends State<ActionsScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabs;

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 3, vsync: this);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      await context.read<ApiService>().loadActions();
      if (!mounted) return;
      final api = context.read<ApiService>();
      // Auto-switch vers EXÉCUTÉES si rien en attente (mode AUTO)
      if (api.pendingActions.isEmpty && api.actions.any((a) => a.isExecuted)) {
        _tabs.animateTo(1);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('ACTIONS'),
        bottom: TabBar(
          controller: _tabs,
          labelColor: JvColors.cyan,
          unselectedLabelColor: JvColors.textMut,
          indicatorColor: JvColors.cyan,
          indicatorWeight: 2,
          labelStyle: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.8),
          tabs: const [
            Tab(text: 'EN ATTENTE'),
            Tab(text: 'EXÉCUTÉES'),
            Tab(text: 'TOUTES'),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: JvColors.cyan),
            onPressed: () => context.read<ApiService>().loadActions(),
          ),
        ],
      ),
      body: Consumer<ApiService>(
        builder: (_, api, __) {
          if (api.loading && api.actions.isEmpty) {
            return const Center(child: CircularProgressIndicator());
          }
          final pending  = api.actions.where((a) => a.isPending).toList();
          final executed = api.actions.where((a) => a.isExecuted || a.isFailed).toList();

          return TabBarView(
            controller: _tabs,
            children: [
              _ActionList(
                actions: pending,
                showControls: true,
                emptyText: 'Aucune action en attente.\nEn mode AUTO, Bea exécute directement.\nVoir onglet EXÉCUTÉES.',
              ),
              _ActionList(
                actions: executed,
                showControls: false,
                emptyText: 'Aucune action exécutée pour l\'instant.',
              ),
              _ActionList(
                actions: api.actions,
                showControls: false,
                emptyText: 'Aucune action.',
              ),
            ],
          );
        },
      ),
    );
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }
}

class _ActionList extends StatelessWidget {
  final List<ActionModel> actions;
  final bool showControls;
  final String emptyText;

  const _ActionList({
    required this.actions,
    required this.showControls,
    this.emptyText = 'Aucune action',
  });

  @override
  Widget build(BuildContext context) {
    if (actions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.check_circle_outline, color: JvColors.textMut, size: 48),
              const SizedBox(height: 12),
              Text(
                emptyText,
                style: const TextStyle(color: JvColors.textMut, fontSize: 13),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      color: JvColors.cyan,
      backgroundColor: JvColors.card,
      onRefresh: () => context.read<ApiService>().loadActions(),
      child: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: actions.length,
        itemBuilder: (_, i) => _ActionCard(
          action: actions[i],
          showControls: showControls && actions[i].isPending,
        ),
      ),
    );
  }
}

class _ActionCard extends StatefulWidget {
  final ActionModel action;
  final bool showControls;

  const _ActionCard({required this.action, required this.showControls});

  @override
  State<_ActionCard> createState() => _ActionCardState();
}

class _ActionCardState extends State<_ActionCard> {
  bool _expanded = false;
  bool _acting   = false;

  ActionModel get a => widget.action;

  Color get _accentColor => switch (a.risk) {
    'CRITICAL' => const Color(0xFFAA00FF),
    'HIGH'     => JvColors.red,
    'MEDIUM'   => JvColors.orange,
    _          => JvColors.green,
  };

  @override
  Widget build(BuildContext context) {
    return CyberCard(
      accentColor: a.isPending ? _accentColor : null,
      onTap: () => setState(() => _expanded = !_expanded),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      a.description,
                      style: const TextStyle(
                        color: JvColors.textPrim, fontSize: 13, fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        StatusBadge.forRisk(a.risk),
                        const SizedBox(width: 6),
                        StatusBadge.forStatus(a.status),
                        if (a.target.isNotEmpty) ...[
                          const SizedBox(width: 6),
                          Flexible(
                            child: Text(
                              a.target,
                              style: const TextStyle(color: JvColors.textMut, fontSize: 10),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
              Icon(
                _expanded ? Icons.keyboard_arrow_up : Icons.keyboard_arrow_down,
                color: JvColors.textMut, size: 20,
              ),
            ],
          ),

          // Expanded details
          if (_expanded) ...[
            const SizedBox(height: 12),
            const Divider(height: 1),
            const SizedBox(height: 12),
            if (a.impact.isNotEmpty)
              _DetailRow('Impact', a.impact),
            if (a.diff.isNotEmpty)
              _DiffBlock(a.diff),
            if (a.rollback.isNotEmpty)
              _DetailRow('Rollback', a.rollback),
            if (a.result.isNotEmpty)
              _DetailRow('Résultat', a.result,
                  color: a.isFailed ? JvColors.red : JvColors.green),
            if (a.approvalReason != null && a.approvalReason!.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.info_outline, size: 12, color: JvColors.textMut),
                    const SizedBox(width: 5),
                    Expanded(
                      child: Text(
                        a.approvalReason!,
                        style: const TextStyle(
                          color: JvColors.textMut,
                          fontSize: 10,
                          fontStyle: FontStyle.italic,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],

          // Approve / Reject buttons
          if (widget.showControls) ...[
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: _acting
                      ? const Center(child: SizedBox(
                          width: 20, height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ))
                      : OutlinedButton.icon(
                          onPressed: () => _reject(context),
                          icon: const Icon(Icons.close, size: 16, color: JvColors.red),
                          label: const Text('REFUSER', style: TextStyle(color: JvColors.red)),
                          style: OutlinedButton.styleFrom(
                            side: const BorderSide(color: JvColors.red),
                          ),
                        ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _acting
                      ? const SizedBox.shrink()
                      : ElevatedButton.icon(
                          onPressed: () => _approve(context),
                          icon: const Icon(Icons.check, size: 16),
                          label: const Text('APPROUVER'),
                        ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _approve(BuildContext context) async {
    setState(() => _acting = true);
    final api = context.read<ApiService>();
    final messenger = ScaffoldMessenger.of(context);
    final result = await api.approveAction(a.id);
    if (!mounted) return;
    setState(() => _acting = false);
    _showFeedbackMsg(messenger, result.ok, result.ok ? 'Action approuvée' : result.error!);
  }

  Future<void> _reject(BuildContext context) async {
    final api = context.read<ApiService>();
    final messenger = ScaffoldMessenger.of(context);
    final reason = await _askReason(context);
    if (reason == null || !mounted) return;
    setState(() => _acting = true);
    final result = await api.rejectAction(a.id, reason: reason);
    if (!mounted) return;
    setState(() => _acting = false);
    _showFeedbackMsg(messenger, result.ok, result.ok ? 'Action refusée' : result.error!);
  }

  Future<String?> _askReason(BuildContext context) async {
    final ctrl = TextEditingController();
    return showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: JvColors.surface,
        title: const Text('Raison du refus', style: TextStyle(color: JvColors.textPrim)),
        content: TextField(
          controller: ctrl,
          decoration: const InputDecoration(hintText: 'Optionnel...'),
          style: const TextStyle(color: JvColors.textPrim),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, null),
            child: const Text('Annuler', style: TextStyle(color: JvColors.textMut)),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, ctrl.text),
            child: const Text('Confirmer'),
          ),
        ],
      ),
    );
  }

  void _showFeedbackMsg(ScaffoldMessengerState messenger, bool ok, String msg) {
    messenger.showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: ok
          ? JvColors.green.withValues(alpha:0.9)
          : JvColors.red.withValues(alpha:0.9),
    ));
  }
}

class _DetailRow extends StatelessWidget {
  final String label, value;
  final Color color;
  const _DetailRow(this.label, this.value, {this.color = JvColors.textSec});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 68,
            child: Text(
              label,
              style: const TextStyle(color: JvColors.textMut, fontSize: 10,
                  fontWeight: FontWeight.w700, letterSpacing: 0.5),
            ),
          ),
          Expanded(
            child: Text(value, style: TextStyle(color: color, fontSize: 12)),
          ),
        ],
      ),
    );
  }
}

class _DiffBlock extends StatelessWidget {
  final String diff;
  const _DiffBlock(this.diff);

  @override
  Widget build(BuildContext context) {
    if (diff.isEmpty) return const SizedBox.shrink();
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: JvColors.bg,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: JvColors.border),
      ),
      child: Text(
        diff,
        style: const TextStyle(
          color: JvColors.cyan, fontSize: 10, fontFamily: 'monospace', height: 1.4,
        ),
      ),
    );
  }
}
