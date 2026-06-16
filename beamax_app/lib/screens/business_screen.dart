import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../theme/design_system.dart';

/// Business overview — ventures, actions, economic metrics.
class BusinessScreen extends StatefulWidget {
  const BusinessScreen({super.key});

  @override
  State<BusinessScreen> createState() => _BusinessScreenState();
}

class _BusinessScreenState extends State<BusinessScreen> {
  Map<String, dynamic>? _ventures;
  Map<String, dynamic>? _actions;
  Map<String, dynamic>? _economic;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _fetchAll();
  }

  Future<void> _fetchAll() async {
    setState(() { _loading = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      final results = await Future.wait([
        api.getJson('/api/v3/venture').catchError((_) => <String, dynamic>{}),
        api.getJson('/api/v3/business-actions').catchError((_) => <String, dynamic>{}),
        api.getJson('/api/v3/economic').catchError((_) => <String, dynamic>{}),
      ]);
      setState(() {
        _ventures = results[0];
        _actions  = results[1];
        _economic = results[2];
        _loading  = false;
      });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: JDS.bgBase,
      appBar: AppBar(
        backgroundColor: JDS.bgSurface,
        foregroundColor: JDS.textPrimary,
        elevation: 0,
        title: const Text('Business',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded, size: 20),
            onPressed: _fetchAll,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: JDS.blue))
          : _error != null
              ? _ErrorView(message: _error!, onRetry: _fetchAll)
              : RefreshIndicator(
                  onRefresh: _fetchAll,
                  color: JDS.blue,
                  backgroundColor: JDS.bgElevated,
                  child: CustomScrollView(slivers: [

                    // ── Economic summary ──
                    if (_economic != null) ...[
                      const SliverToBoxAdapter(child: _SectionHeader(title: 'Vue économique')),
                      SliverToBoxAdapter(child: _EconomicPanel(data: _economic!)),
                    ],

                    // ── Ventures ──
                    const SliverToBoxAdapter(child: _SectionHeader(title: 'Ventures')),
                    _VentureSliver(data: _ventures),

                    // ── Business actions ──
                    const SliverToBoxAdapter(child: _SectionHeader(title: 'Actions business')),
                    _ActionsSliver(data: _actions),

                    const SliverToBoxAdapter(child: SizedBox(height: 40)),
                  ]),
                ),
    );
  }
}

// ── Section header ────────────────────────────────────────────────────────────

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(20, 20, 20, 6),
    child: Text(title, style: const TextStyle(
      fontSize: 11, fontWeight: FontWeight.w700,
      color: JDS.textMuted, letterSpacing: 0.8)),
  );
}

// ── Economic panel ─────────────────────────────────────────────────────────────

class _EconomicPanel extends StatelessWidget {
  final Map<String, dynamic> data;
  const _EconomicPanel({required this.data});

  @override
  Widget build(BuildContext context) {
    final d = (data['data'] ?? data) as Map<String, dynamic>;
    final keys = ['revenue', 'cost', 'margin', 'roi', 'balance']
        .where((k) => d.containsKey(k)).toList();

    if (keys.isEmpty) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: JDS.bgElevated,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: JDS.borderDefault),
          ),
          child: Text(
            d.entries.take(6).map((e) => '${e.key}: ${e.value}').join('\n'),
            style: const TextStyle(fontSize: 12, color: JDS.textSecondary),
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: JDS.bgElevated,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: JDS.borderDefault),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceAround,
          children: keys.map((k) => Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('${d[k]}', style: const TextStyle(
                fontSize: 16, fontWeight: FontWeight.w700, color: JDS.textPrimary)),
              const SizedBox(height: 2),
              Text(k, style: const TextStyle(fontSize: 10, color: JDS.textMuted)),
            ],
          )).toList(),
        ),
      ),
    );
  }
}

// ── Ventures sliver ────────────────────────────────────────────────────────────

class _VentureSliver extends StatelessWidget {
  final Map<String, dynamic>? data;
  const _VentureSliver({this.data});

  @override
  Widget build(BuildContext context) {
    if (data == null) return const _NoneSliver(message: 'Données non disponibles.');
    final items = (data!['ventures'] ?? data!['data'] ??
        (data is List ? data : null)) as List? ?? [];
    if (items.isEmpty) return const _NoneSliver(message: 'Aucun venture configuré.');
    return SliverList(
      delegate: SliverChildBuilderDelegate(
        (ctx, i) => _VentureTile(v: items[i] as Map<String, dynamic>),
        childCount: items.length,
      ),
    );
  }
}

class _VentureTile extends StatelessWidget {
  final Map<String, dynamic> v;
  const _VentureTile({required this.v});

  @override
  Widget build(BuildContext context) {
    final name   = v['name'] as String? ?? v['id'] as String? ?? '?';
    final status = (v['status'] as String? ?? 'unknown').toLowerCase();
    final desc   = v['description'] as String? ?? '';
    final rev    = v['revenue_estimate'];
    final stColor = _statusColor(status);
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 0),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.bgElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: JDS.borderDefault),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(name, style: const TextStyle(
            fontSize: 14, fontWeight: FontWeight.w600, color: JDS.textPrimary))),
          _StatusBadge(label: status, color: stColor),
        ]),
        if (desc.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(desc, style: const TextStyle(fontSize: 12, color: JDS.textMuted),
              maxLines: 2, overflow: TextOverflow.ellipsis),
        ],
        if (rev != null) ...[
          const SizedBox(height: 6),
          Row(children: [
            const Icon(Icons.attach_money, size: 13, color: JDS.green),
            const SizedBox(width: 4),
            Text('$rev', style: const TextStyle(fontSize: 12, color: JDS.green)),
          ]),
        ],
      ]),
    );
  }

  Color _statusColor(String s) {
    if (s == 'active' || s == 'live' || s == 'production') return JDS.green;
    if (s == 'paused' || s == 'pending') return JDS.amber;
    if (s == 'failed' || s == 'archived') return JDS.textDim;
    return JDS.blue;
  }
}

// ── Business actions sliver ───────────────────────────────────────────────────

class _ActionsSliver extends StatelessWidget {
  final Map<String, dynamic>? data;
  const _ActionsSliver({this.data});

  @override
  Widget build(BuildContext context) {
    if (data == null) return const _NoneSliver(message: 'Données non disponibles.');
    final items = (data!['actions'] ?? data!['data'] ?? []) as List? ?? [];
    if (items.isEmpty) return const _NoneSliver(message: 'Aucune action business.');
    return SliverList(
      delegate: SliverChildBuilderDelegate(
        (ctx, i) {
          final a = items[i] as Map<String, dynamic>;
          final name   = a['name'] as String? ?? a['id'] as String? ?? '?';
          final status = (a['status'] as String? ?? 'unknown').toLowerCase();
          return Container(
            margin: const EdgeInsets.fromLTRB(16, 4, 16, 0),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: JDS.bgElevated,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: JDS.borderDefault),
            ),
            child: Row(children: [
              Expanded(child: Text(name, style: const TextStyle(
                fontSize: 13, fontWeight: FontWeight.w500, color: JDS.textPrimary))),
              _StatusBadge(label: status),
            ]),
          );
        },
        childCount: items.length,
      ),
    );
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

class _StatusBadge extends StatelessWidget {
  final String label;
  final Color? color;
  const _StatusBadge({required this.label, this.color});

  @override
  Widget build(BuildContext context) {
    final c = color ?? _defaultColor(label);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: c.withValues(alpha: 0.4)),
      ),
      child: Text(label.toUpperCase(),
          style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: c)),
    );
  }

  Color _defaultColor(String s) {
    if (s == 'active' || s == 'live' || s == 'production' || s == 'completed') return JDS.green;
    if (s == 'pending' || s == 'running') return JDS.blue;
    if (s == 'paused' || s == 'waiting') return JDS.amber;
    if (s == 'failed' || s == 'cancelled') return JDS.red;
    return JDS.textMuted;
  }
}

class _NoneSliver extends StatelessWidget {
  final String message;
  const _NoneSliver({required this.message});

  @override
  Widget build(BuildContext context) => SliverToBoxAdapter(
    child: Padding(
      padding: const EdgeInsets.fromLTRB(20, 4, 20, 0),
      child: Text(message, style: const TextStyle(color: JDS.textMuted, fontSize: 13)),
    ),
  );
}

class _ErrorView extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _ErrorView({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.error_outline, color: JDS.red, size: 40),
        const SizedBox(height: 12),
        Text(message, style: const TextStyle(color: JDS.textMuted, fontSize: 13),
            textAlign: TextAlign.center),
        const SizedBox(height: 16),
        ElevatedButton(onPressed: onRetry, child: const Text('Réessayer')),
      ]),
    ),
  );
}
