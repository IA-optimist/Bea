import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../theme/design_system.dart';

/// HexStrike V2 security tools — list, availability, stats.
class SecurityScreen extends StatefulWidget {
  const SecurityScreen({super.key});

  @override
  State<SecurityScreen> createState() => _SecurityScreenState();
}

class _SecurityScreenState extends State<SecurityScreen> {
  List<Map<String, dynamic>> _tools = [];
  Map<String, dynamic>? _stats;
  bool _loading = true;
  String? _error;
  String? _filterCategory;
  bool _availableOnly = false;

  static const _categories = ['recon', 'scanning', 'web', 'exploitation'];
  static const _riskColors = {
    'low':    JDS.green,
    'medium': JDS.amber,
    'high':   JDS.red,
  };

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
        api.getJson('/api/v3/security/tools'),
        api.getJson('/api/v3/security/tools/stats'),
      ]);
      final rawTools = (results[0]['data'] ?? results[0]) as List? ?? [];
      setState(() {
        _tools = rawTools.whereType<Map<String, dynamic>>().toList();
        _stats = (results[1]['data'] ?? results[1]) as Map<String, dynamic>?;
        _loading = false;
      });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  List<Map<String, dynamic>> get _filtered {
    return _tools.where((t) {
      if (_filterCategory != null && t['category'] != _filterCategory) return false;
      if (_availableOnly && t['available'] != true) return false;
      return true;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: JDS.bgBase,
      appBar: AppBar(
        backgroundColor: JDS.bgSurface,
        foregroundColor: JDS.textPrimary,
        elevation: 0,
        title: const Text('Sécurité HexStrike',
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
              : CustomScrollView(slivers: [

                  // ── Stats banner ──
                  if (_stats != null)
                    SliverToBoxAdapter(child: _StatsBanner(stats: _stats!)),

                  // ── Filters ──
                  SliverToBoxAdapter(child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(children: [
                        _Chip(
                          label: 'Tous',
                          selected: _filterCategory == null,
                          onTap: () => setState(() => _filterCategory = null),
                        ),
                        for (final cat in _categories)
                          _Chip(
                            label: cat[0].toUpperCase() + cat.substring(1),
                            selected: _filterCategory == cat,
                            onTap: () => setState(() => _filterCategory = cat),
                          ),
                        const SizedBox(width: 8),
                        FilterChip(
                          label: const Text('Installés',
                              style: TextStyle(fontSize: 12, color: JDS.textPrimary)),
                          selected: _availableOnly,
                          onSelected: (v) => setState(() => _availableOnly = v),
                          backgroundColor: JDS.bgElevated,
                          selectedColor: JDS.blueSoft,
                          checkmarkColor: JDS.blue,
                          side: BorderSide(
                            color: _availableOnly ? JDS.blue : JDS.borderDefault,
                          ),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(20)),
                        ),
                      ]),
                    ),
                  )),

                  // ── Tool list ──
                  SliverList(delegate: SliverChildBuilderDelegate(
                    (ctx, i) => _ToolTile(tool: _filtered[i]),
                    childCount: _filtered.length,
                  )),

                  if (_filtered.isEmpty)
                    const SliverToBoxAdapter(
                      child: Padding(
                        padding: EdgeInsets.all(40),
                        child: Center(child: Text(
                          'Aucun outil dans ce filtre.',
                          style: TextStyle(color: JDS.textMuted),
                        )),
                      ),
                    ),

                  const SliverToBoxAdapter(child: SizedBox(height: 40)),
                ]),
    );
  }
}

class _StatsBanner extends StatelessWidget {
  final Map<String, dynamic> stats;
  const _StatsBanner({required this.stats});

  @override
  Widget build(BuildContext context) {
    final total  = stats['total_tools'] ?? 0;
    final avail  = stats['available_count'] ?? 0;
    final needApproval = stats['requires_approval_count'] ?? 0;
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 14, 16, 0),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: JDS.bgElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: JDS.borderDefault),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          _Stat(label: 'Total', value: '$total'),
          _Stat(label: 'Installés', value: '$avail', color: JDS.green),
          _Stat(label: 'Approval', value: '$needApproval', color: JDS.amber),
        ],
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  final String label;
  final String value;
  final Color color;
  const _Stat({required this.label, required this.value, this.color = JDS.textPrimary});

  @override
  Widget build(BuildContext context) => Column(
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(value, style: TextStyle(
        fontSize: 22, fontWeight: FontWeight.w700, color: color)),
      const SizedBox(height: 2),
      Text(label, style: const TextStyle(fontSize: 11, color: JDS.textMuted)),
    ],
  );
}

class _ToolTile extends StatelessWidget {
  final Map<String, dynamic> tool;
  const _ToolTile({required this.tool});

  @override
  Widget build(BuildContext context) {
    const riskColors = {
      'low': JDS.green, 'medium': JDS.amber, 'high': JDS.red,
    };
    final risk = tool['risk_level'] as String? ?? 'low';
    final riskColor = riskColors[risk] ?? JDS.textMuted;
    final available = tool['available'] == true;
    final approvalNeeded = tool['requires_approval'] == true;
    final name = tool['name'] as String? ?? '?';
    final desc = tool['description'] as String? ?? '';
    final cat  = tool['category'] as String? ?? '';

    return Container(
      margin: const EdgeInsets.fromLTRB(16, 6, 16, 0),
      decoration: BoxDecoration(
        color: JDS.bgElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border(left: BorderSide(color: riskColor, width: 3)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(children: [
          Expanded(child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Text(name, style: const TextStyle(
                  fontSize: 14, fontWeight: FontWeight.w600,
                  color: JDS.textPrimary)),
                const SizedBox(width: 6),
                _Tag(label: cat, color: JDS.blue),
              ]),
              if (desc.isNotEmpty) ...[
                const SizedBox(height: 3),
                Text(desc, style: const TextStyle(
                  fontSize: 12, color: JDS.textMuted), maxLines: 2,
                  overflow: TextOverflow.ellipsis),
              ],
              const SizedBox(height: 6),
              Row(children: [
                _Tag(label: risk, color: riskColor),
                if (approvalNeeded) ...[
                  const SizedBox(width: 6),
                  const _Tag(label: 'approbation', color: JDS.amber),
                ],
              ]),
            ],
          )),
          const SizedBox(width: 10),
          Icon(
            available ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded,
            size: 20,
            color: available ? JDS.green : JDS.textDim,
          ),
        ]),
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  final String label;
  final Color color;
  const _Tag({required this.label, required this.color});

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(5),
      border: Border.all(color: color.withValues(alpha: 0.4)),
    ),
    child: Text(label, style: TextStyle(
      fontSize: 10, fontWeight: FontWeight.w600, color: color)),
  );
}

class _Chip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;
  const _Chip({required this.label, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(right: 6),
    child: GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? JDS.blue.withValues(alpha: 0.18) : JDS.bgElevated,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: selected ? JDS.blue : JDS.borderDefault,
          ),
        ),
        child: Text(label, style: TextStyle(
          fontSize: 12,
          fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
          color: selected ? JDS.blue : JDS.textSecondary,
        )),
      ),
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
        ElevatedButton(onPressed: onRetry,
            child: const Text('Réessayer')),
      ]),
    ),
  );
}
