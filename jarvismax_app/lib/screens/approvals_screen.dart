import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../models/action_model.dart';
import '../theme/design_system.dart';
import 'decisions_screen.dart';

/// Approvals — premium, touch-friendly approval flow.
/// Each card: what Bea wants to do, why, risk, impact, approve/deny.
class ApprovalsScreen extends StatefulWidget {
  const ApprovalsScreen({super.key});

  @override
  State<ApprovalsScreen> createState() => _ApprovalsScreenState();
}

class _ApprovalsScreenState extends State<ApprovalsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ApiService>().loadActions();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Consumer<ApiService>(
          builder: (_, api, __) {
            final pending = api.actions.where((a) => a.isPending).toList();
            final recent = api.actions
                .where((a) => a.isExecuted || a.isFailed)
                .take(8).toList();

            return RefreshIndicator(
              onRefresh: api.loadActions,
              color: JDS.blue,
              backgroundColor: JDS.bgElevated,
              child: CustomScrollView(slivers: [
                // ── Header ──
                SliverToBoxAdapter(child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 20, 20, 8),
                  child: Row(children: [
                    const Text('Approbations', style: TextStyle(
                      fontSize: 22, fontWeight: FontWeight.w700,
                      color: JDS.textPrimary, letterSpacing: -0.3,
                    )),
                    const Spacer(),
                    if (pending.isNotEmpty)
                      JStatusBadge(
                        label: '${pending.length} EN ATTENTE',
                        color: JDS.amber,
                      ),
                    // ── Autonomy decisions shortcut ──
                    IconButton(
                      tooltip: 'Décisions autonomy',
                      icon: const Icon(Icons.checklist_rtl, color: JDS.textSecondary),
                      onPressed: () {
                        Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => const DecisionsScreen(),
                          ),
                        );
                      },
                    ),
                  ]),
                )),

                // ── Empty state ──
                if (pending.isEmpty && recent.isEmpty)
                  SliverFillRemaining(child: JEmptyState(
                    icon: Icons.check_circle_outline_rounded,
                    title: 'Tout est bon',
                    subtitle: 'Aucune approbation requise pour l\'instant.\nBea gère tout automatiquement.',
                  )),

                // ── Pending section ──
                if (pending.isNotEmpty) ...[
                  SliverToBoxAdapter(child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 16, 20, 12),
                    child: JSectionHeader(title: 'Décision requise', count: '${pending.length}'),
                  )),
                  SliverList(delegate: SliverChildBuilderDelegate(
                    (_, i) => Padding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
                      child: _ApprovalCard(action: pending[i]),
                    ),
                    childCount: pending.length,
                  )),
                ],

                // ── Recent section ──
                if (recent.isNotEmpty) ...[
                  SliverToBoxAdapter(child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 20, 20, 12),
                    child: JSectionHeader(title: 'Récemment résolues', count: '${recent.length}'),
                  )),
                  SliverList(delegate: SliverChildBuilderDelegate(
                    (_, i) => Padding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                      child: _ResolvedCard(action: recent[i]),
                    ),
                    childCount: recent.length,
                  )),
                ],

                const SliverToBoxAdapter(child: SizedBox(height: 100)),
              ]),
            );
          },
        ),
      ),
    );
  }
}

// ── Approval Card ────────────────────────────────────────────────────────────

class _ApprovalCard extends StatefulWidget {
  final ActionModel action;
  const _ApprovalCard({required this.action});

  @override
  State<_ApprovalCard> createState() => _ApprovalCardState();
}

class _ApprovalCardState extends State<_ApprovalCard> {
  bool _acting = false;
  bool _showFeedback = false;
  final _feedbackCtrl = TextEditingController();

  ActionModel get a => widget.action;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusLg),
        border: Border.all(color: JDS.riskColor(a.risk).withValues(alpha: 0.25)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // Risk + provider
        Row(children: [
          JRiskBadge(risk: a.risk),
          const Spacer(),
          if (a.missionId != null)
            Text(a.missionId!.substring(0, 8), style: const TextStyle(
              fontSize: 11, color: JDS.textDim, fontFamily: 'monospace',
            )),
        ]),

        const SizedBox(height: 14),

        // What
        const Text('Bea veut :', style: TextStyle(
          fontSize: 11, fontWeight: FontWeight.w600, color: JDS.textMuted,
          letterSpacing: 0.5,
        )),
        const SizedBox(height: 4),
        Text(a.description, style: const TextStyle(
          fontSize: 15, fontWeight: FontWeight.w500, color: JDS.textPrimary, height: 1.5,
        )),

        // Why
        if (a.approvalReason != null && a.approvalReason!.isNotEmpty) ...[
          const SizedBox(height: 10),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.lightbulb_outline_rounded, size: 14, color: JDS.textMuted),
            const SizedBox(width: 6),
            Expanded(child: Text(a.approvalReason!, style: const TextStyle(
              fontSize: 13, color: JDS.textSecondary, height: 1.4,
            ))),
          ]),
        ],

        // Impact
        if (a.impact.isNotEmpty) ...[
          const SizedBox(height: 8),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            const Icon(Icons.trending_up_rounded, size: 14, color: JDS.textMuted),
            const SizedBox(width: 6),
            Expanded(child: Text('Impact : ${a.impact}', style: const TextStyle(
              fontSize: 13, color: JDS.textSecondary,
            ))),
          ]),
        ],

        // Consequence hints
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: JDS.bgOverlay,
            borderRadius: BorderRadius.circular(JDS.radiusSm),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Container(width: 4, height: 4, decoration: BoxDecoration(
                color: JDS.green, shape: BoxShape.circle,
              )),
              const SizedBox(width: 8),
              const Text('Si approuvé : ', style: TextStyle(fontSize: 12, color: JDS.green, fontWeight: FontWeight.w500)),
              const Expanded(child: Text('Bea exécute cette action', style: TextStyle(
                fontSize: 12, color: JDS.textSecondary,
              ))),
            ]),
            const SizedBox(height: 4),
            Row(children: [
              Container(width: 4, height: 4, decoration: BoxDecoration(
                color: JDS.textDim, shape: BoxShape.circle,
              )),
              const SizedBox(width: 8),
              const Text('Si refusé : ', style: TextStyle(fontSize: 12, color: JDS.textDim, fontWeight: FontWeight.w500)),
              const Expanded(child: Text('Action ignorée, mission continue', style: TextStyle(
                fontSize: 12, color: JDS.textSecondary,
              ))),
            ]),
          ]),
        ),

        // Optional feedback
        if (_showFeedback) ...[
          const SizedBox(height: 12),
          TextField(
            controller: _feedbackCtrl,
            maxLines: 2,
            style: const TextStyle(fontSize: 13, color: JDS.textPrimary),
            decoration: const InputDecoration(
              hintText: 'Optionnel : ajouter une note…',
              contentPadding: EdgeInsets.all(12),
            ),
          ),
        ],

        const SizedBox(height: 16),

        // Actions
        if (_acting)
          const Center(child: SizedBox(width: 24, height: 24,
              child: CircularProgressIndicator(strokeWidth: 2)))
        else
          Row(children: [
            // Feedback toggle
            GestureDetector(
              onTap: () => setState(() => _showFeedback = !_showFeedback),
              child: Icon(_showFeedback ? Icons.comment : Icons.comment_outlined,
                  size: 18, color: JDS.textDim),
            ),
            const Spacer(),
            // Deny
            SizedBox(
              height: 40,
              child: OutlinedButton(
                onPressed: () => _deny(context),
                style: OutlinedButton.styleFrom(
                  foregroundColor: JDS.red,
                  side: const BorderSide(color: JDS.red),
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                ),
                child: const Text('Refuser'),
              ),
            ),
            const SizedBox(width: 10),
            // Approve
            SizedBox(
              height: 40,
              child: ElevatedButton(
                onPressed: () => _approve(context),
                style: ElevatedButton.styleFrom(
                  backgroundColor: JDS.green,
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                ),
                child: const Text('Approuver', style: TextStyle(fontWeight: FontWeight.w600)),
              ),
            ),
          ]),
      ]),
    );
  }

  Future<void> _approve(BuildContext ctx) async {
    setState(() => _acting = true);
    final result = await ctx.read<ApiService>().approveAction(a.id);
    if (!mounted) return;
    setState(() => _acting = false);
    _showResult(ctx, result.ok, result.ok ? 'Approuvé' : (result.error ?? 'Erreur'));
  }

  Future<void> _deny(BuildContext ctx) async {
    setState(() => _acting = true);
    final result = await ctx.read<ApiService>().rejectAction(a.id);
    if (!mounted) return;
    setState(() => _acting = false);
    _showResult(ctx, result.ok, result.ok ? 'Refusé' : (result.error ?? 'Erreur'));
  }

  void _showResult(BuildContext ctx, bool ok, String msg) {
    ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: ok ? JDS.bgElevated : JDS.red,
    ));
  }

  @override
  void dispose() {
    _feedbackCtrl.dispose();
    super.dispose();
  }
}

// ── Resolved Card ────────────────────────────────────────────────────────────

// ── Risk label helper ─────────────────────────────────────────
/// Human-friendly risk labels for approval cards.
String _riskLabel(String risk) {
  switch (risk.toLowerCase()) {
    case 'high':     return 'Risque élevé';
    case 'medium':   return 'Risque moyen';
    case 'critical': return 'Risque critique';
    default:         return 'Risque faible';
  }
}

class _ResolvedCard extends StatelessWidget {
  final ActionModel action;
  const _ResolvedCard({required this.action});

  @override
  Widget build(BuildContext context) {
    final ok = action.isExecuted;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.bgSurface,
        borderRadius: BorderRadius.circular(JDS.radiusMd),
        border: Border.all(color: JDS.borderSubtle),
      ),
      child: Row(children: [
        Icon(ok ? Icons.check_circle_rounded : Icons.cancel_rounded,
             color: ok ? JDS.green : JDS.red, size: 18),
        const SizedBox(width: 10),
        Expanded(child: Text(action.description, style: const TextStyle(
          fontSize: 13, color: JDS.textPrimary,
        ), maxLines: 2, overflow: TextOverflow.ellipsis)),
        JStatusBadge(
          label: ok ? 'FAIT' : 'REFUSÉ',
          color: ok ? JDS.green : JDS.textDim,
        ),
      ]),
    );
  }
}
