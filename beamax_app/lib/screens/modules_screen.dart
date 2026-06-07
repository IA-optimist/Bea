import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../theme/design_system.dart';

/// Modules — browse, search, test, enable/disable agents, skills, connectors,
/// MCP, catalog, and health. All data from real /api/v3/ endpoints.
class ModulesScreen extends StatefulWidget {
  const ModulesScreen({super.key});

  @override
  State<ModulesScreen> createState() => _ModulesScreenState();
}

class _ModulesScreenState extends State<ModulesScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  final _tabs = [
    _TabDef('Agents', Icons.smart_toy_outlined, '/api/v3/agents', 'agents'),
    _TabDef('Skills', Icons.extension_outlined, '/api/v3/skills', 'skills'),
    _TabDef('Connectors', Icons.cable_outlined, '/api/v3/connectors', 'connectors'),
    _TabDef('MCP', Icons.hub_outlined, '/api/v3/mcp', 'mcp'),
    _TabDef('Health', Icons.monitor_heart_outlined, '/api/v3/modules/health', 'health'),
  ];

  List<dynamic> _items = [];
  Map<String, dynamic>? _healthData;
  bool _loading = false;
  String _error = '';
  String _search = '';
  String _userRole = 'admin'; // default: single-operator system
  late final ApiService _api;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _tabs.length, vsync: this);
    _tabController.addListener(() {
      if (!_tabController.indexIsChanging) _load();
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _api = context.read<ApiService>();
    _loadRole();
    _load();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  _TabDef get _current => _tabs[_tabController.index];
  bool get _isAdmin => _userRole == 'admin';

  Future<void> _loadRole() async {
    try {
      final d = await _api.getJson('/auth/me');
      final role = d['role']?.toString();
      if (role != null && mounted) {
        setState(() => _userRole = role);
      }
    } catch (_) {
      // Default to admin for single-operator setups
    }
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = ''; });
    try {
      if (_current.key == 'health') {
        final d = await _api.getJson(_current.endpoint);
        setState(() { _healthData = d; _items = []; });
      } else {
        final d = await _api.getJson(_current.endpoint);
        setState(() => _items = List<dynamic>.from(
          d[_current.key] ?? d['items'] ?? [],
        ));
      }
    } catch (e) {
      setState(() => _error = e.toString().replaceFirst('Exception: ', ''));
    }
    setState(() => _loading = false);
  }

  List<dynamic> get _filtered {
    if (_search.isEmpty) return _items;
    final q = _search.toLowerCase();
    return _items.where((i) {
      final name = (i['name'] ?? i['id'] ?? '').toString().toLowerCase();
      final desc = (i['description'] ?? i['purpose'] ?? '').toString().toLowerCase();
      return name.contains(q) || desc.contains(q);
    }).toList();
  }

  // ── Actions ──

  Future<void> _toggle(String id) async {
    try {
      await _api.postJson('/api/v3/${_current.key}/$id/toggle', {});
      _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Toggle failed: ${e.toString().replaceFirst("Exception: ", "")}')),
        );
      }
    }
  }

  Future<void> _test(String id) async {
    try {
      final d = await _api.postJson('/api/v3/${_current.key}/$id/test', {});
      if (!mounted) return;
      final status = d['status'] ?? d['health']?['status'] ?? 'done';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Test result: $status')),
      );
      _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Test failed: ${e.toString().replaceFirst("Exception: ", "")}')),
        );
      }
    }
  }

  // ── Build ──

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Modules'),
        bottom: TabBar(
          controller: _tabController,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: _tabs.map((t) => Tab(
            icon: Icon(t.icon, size: 18),
            text: t.label,
          )).toList(),
          labelColor: JDS.blue,
          unselectedLabelColor: JDS.textMuted,
          indicatorColor: JDS.blue,
          indicatorSize: TabBarIndicatorSize.label,
        ),
      ),
      body: Column(children: [
        // Search bar (not for health tab)
        if (_current.key != 'health')
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: Row(children: [
              Expanded(child: TextField(
                onChanged: (v) => setState(() => _search = v),
                decoration: InputDecoration(
                  hintText: 'Search ${_current.label.toLowerCase()}…',
                  prefixIcon: const Icon(Icons.search, size: 20),
                  isDense: true,
                  contentPadding: const EdgeInsets.symmetric(vertical: 10),
                ),
              )),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.refresh_rounded, size: 20),
                onPressed: _load,
              ),
            ]),
          ),
        // Content
        Expanded(child: _buildContent()),
      ]),
    );
  }

  Widget _buildContent() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error.isNotEmpty) {
      return Center(child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.error_outline_rounded, size: 48, color: JDS.red),
          const SizedBox(height: 12),
          Text(_error, style: const TextStyle(color: JDS.textMuted, fontSize: 14),
              textAlign: TextAlign.center),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _load,
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('Retry'),
          ),
        ]),
      ));
    }
    if (_current.key == 'health') return _buildHealth();

    final items = _filtered;
    if (items.isEmpty) {
      return JEmptyState(
        icon: _current.icon,
        title: 'No ${_current.label.toLowerCase()} found',
        subtitle: _search.isNotEmpty
            ? 'Try a different search term'
            : 'None registered yet',
      );
    }

    return RefreshIndicator(
      onRefresh: _load,
      color: JDS.blue,
      backgroundColor: JDS.bgElevated,
      child: ListView.builder(
        itemCount: items.length,
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 80),
        itemBuilder: (_, i) => _buildModuleCard(items[i]),
      ),
    );
  }

  Widget _buildModuleCard(dynamic item) {
    final name = item['name']?.toString() ?? item['id']?.toString() ?? '?';
    final desc = item['description']?.toString() ?? item['purpose']?.toString() ?? '';
    final status = item['status']?.toString() ?? 'unknown';
    final isCore = item['source'] == 'core';

    final statusColor = switch (status) {
      'enabled' || 'active' => JDS.green,
      'disabled' => JDS.textDim,
      'error' => JDS.red,
      'pending' => JDS.amber,
      _ => JDS.textMuted,
    };

    final statusLabel = switch (status) {
      'enabled' => 'Ready',
      'disabled' => 'Disabled',
      'error' => 'Error',
      'pending' => 'Needs setup',
      _ => status,
    };

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: JCard(
        padding: const EdgeInsets.all(14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          // Name + status
          Row(children: [
            Expanded(child: Text(name, style: const TextStyle(
              fontWeight: FontWeight.w600, fontSize: 15, color: JDS.textPrimary,
            ))),
            JStatusBadge(label: statusLabel, color: statusColor),
            if (isCore) ...[
              const SizedBox(width: 6),
              JStatusBadge(label: 'CORE', color: JDS.blue),
            ],
          ]),

          // Description
          if (desc.isNotEmpty) Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(desc, style: const TextStyle(
              color: JDS.textMuted, fontSize: 13, height: 1.4,
            ), maxLines: 2, overflow: TextOverflow.ellipsis),
          ),

          // Metadata badges
          if (item['provider'] != null || item['model'] != null || item['transport'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Wrap(spacing: 6, runSpacing: 4, children: [
                if (item['provider'] != null) _metaBadge(item['provider']),
                if (item['model'] != null) _metaBadge(item['model']),
                if (item['transport'] != null) _metaBadge(item['transport']),
              ]),
            ),

          // Actions (only for non-core items)
          if (!isCore)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Row(children: [
                _actionBtn('Test', Icons.play_arrow_rounded, () => _test(item['id'] ?? name)),
                const SizedBox(width: 12),
                _actionBtn(
                  status == 'enabled' ? 'Disable' : 'Enable',
                  status == 'enabled' ? Icons.pause_circle_outlined : Icons.play_circle_outline,
                  () => _toggle(item['id'] ?? name),
                ),
              ]),
            ),
        ]),
      ),
    );
  }

  Widget _buildHealth() {
    if (_healthData == null) {
      return const JEmptyState(
        icon: Icons.monitor_heart_outlined,
        title: 'No health data',
        subtitle: 'Could not load module health status',
      );
    }

    final agents = _healthData!['agents'] as Map? ?? {};
    final connectors = _healthData!['connectors'] as Map? ?? {};
    final mcp = _healthData!['mcp'] as Map? ?? {};
    final skills = _healthData!['skills'] as Map? ?? {};

    return RefreshIndicator(
      onRefresh: _load,
      color: JDS.blue,
      backgroundColor: JDS.bgElevated,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        _healthTile('Agents', '${agents['ready'] ?? 0}/${agents['total'] ?? 0} ready',
            Icons.smart_toy_outlined, JDS.blue),
        _healthTile('Connectors', '${connectors['connected'] ?? 0}/${connectors['total'] ?? 0} connected',
            Icons.cable_outlined, JDS.green),
        _healthTile('MCP', '${mcp['connected'] ?? 0}/${mcp['total'] ?? 0} connected',
            Icons.hub_outlined, JDS.violet),
        _healthTile('Skills', '${skills['enabled'] ?? 0} enabled',
            Icons.extension_outlined, JDS.amber),

        if ((connectors['failing'] ?? 0) > 0)
          _healthTile('Failing', '${connectors['failing']} connectors',
              Icons.warning_amber_rounded, JDS.red),

        const SizedBox(height: 80),
      ]),
    );
  }

  Widget _healthTile(String label, String value, IconData icon, Color color) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: JCard(
        padding: const EdgeInsets.all(16),
        child: Row(children: [
          Icon(icon, color: color, size: 22),
          const SizedBox(width: 14),
          Expanded(child: Text(label, style: const TextStyle(
            fontSize: 15, color: JDS.textPrimary, fontWeight: FontWeight.w500,
          ))),
          Text(value, style: TextStyle(
            fontSize: 14, color: color, fontWeight: FontWeight.w600,
          )),
        ]),
      ),
    );
  }

  Widget _metaBadge(String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: JDS.blueSoft,
        borderRadius: BorderRadius.circular(JDS.radiusXl),
      ),
      child: Text(text, style: const TextStyle(
        color: JDS.blue, fontSize: 11, fontWeight: FontWeight.w500,
      )),
    );
  }

  Widget _actionBtn(String label, IconData icon, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(JDS.radiusSm),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 16, color: JDS.textSecondary),
          const SizedBox(width: 4),
          Text(label, style: const TextStyle(
            fontSize: 12, color: JDS.textSecondary, fontWeight: FontWeight.w500,
          )),
        ]),
      ),
    );
  }
}

class _TabDef {
  final String label;
  final IconData icon;
  final String endpoint;
  final String key;
  const _TabDef(this.label, this.icon, this.endpoint, this.key);
}
