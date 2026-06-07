import '../theme/design_system.dart';
import 'package:flutter/material.dart';
import 'dart:convert';
import '../services/api_service.dart';
import '../widgets/cyber_card.dart';
import 'package:provider/provider.dart';

/// AI OS Dashboard — system introspection for Bea.
class AIOSDashboardScreen extends StatefulWidget {
  const AIOSDashboardScreen({super.key});

  @override
  State<AIOSDashboardScreen> createState() => _AIOSDashboardScreenState();
}

class _AIOSDashboardScreenState extends State<AIOSDashboardScreen> {
  Map<String, dynamic>? _status;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  Future<void> _loadStatus() async {
    setState(() { _loading = true; _error = null; });
    try {
      final api = context.read<ApiService>();
      final resp = await api.getAiosStatus();
      setState(() { _status = resp; _loading = false; });
    } catch (e) {
      setState(() { _error = e.toString(); _loading = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI OS'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: JvColors.cyan),
            onPressed: _loadStatus,
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: JvColors.cyan))
          : _error != null
              ? Center(child: Text(_error!, style: const TextStyle(color: JvColors.error)))
              : _buildDashboard(),
    );
  }

  Widget _buildDashboard() {
    final data = _status?['data'] ?? {};
    return RefreshIndicator(
      onRefresh: _loadStatus,
      child: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          _buildMissionsCard(data['missions']),
          const SizedBox(height: 8),
          _buildCapabilitiesCard(data['capabilities']),
          const SizedBox(height: 8),
          _buildToolsCard(data['tools']),
          const SizedBox(height: 8),
          _buildMemoryCard(data['memory'], data['vector_memory']),
          const SizedBox(height: 8),
          _buildPolicyCard(data['policy']),
          const SizedBox(height: 8),
          _buildSkillsCard(data['skills']),
          const SizedBox(height: 8),
          _buildSemanticCard(data['semantic_router']),
          const SizedBox(height: 8),
          _buildRecoveryCard(data['recovery']),
          const SizedBox(height: 8),
          _buildAgentsCard(data['agents']),
          const SizedBox(height: 8),
          _buildSafetyCard(data['self_improvement']),
          const SizedBox(height: 20),
        ],
      ),
    );
  }

  // ── Cards ──────────────────────────────────────────────────────

  Widget _buildMissionsCard(dynamic missions) {
    if (missions == null || missions['error'] != null) {
      return _errorCard('Missions', missions?['error'] ?? 'N/A');
    }
    final rate = ((missions['success_rate'] ?? 0) * 100).toInt();
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.rocket_launch, 'MISSIONS', '$rate% success'),
        const SizedBox(height: 8),
        _kvRow('Recent', '${missions['recent']}'),
        _kvRow('Done', '${missions['done']}'),
        _kvRow('Failed', '${missions['failed']}'),
      ]),
    );
  }

  Widget _buildCapabilitiesCard(dynamic caps) {
    if (caps == null || caps['error'] != null) {
      return _errorCard('Capabilities', caps?['error'] ?? 'N/A');
    }
    final names = (caps['capabilities'] as List?)?.cast<String>() ?? [];
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.hub, 'CAPABILITIES', '${caps['enabled']}/${caps['total']}'),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6, runSpacing: 4,
          children: names.map((n) => Chip(
            label: Text(n, style: const TextStyle(fontSize: 11, color: JvColors.text)),
            backgroundColor: JvColors.surface,
            padding: EdgeInsets.zero,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          )).toList(),
        ),
      ]),
    );
  }

  Widget _buildToolsCard(dynamic tools) {
    if (tools == null || tools['error'] != null) {
      return _errorCard('Tools', tools?['error'] ?? 'N/A');
    }
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.build, 'TOOLS', '${tools['total']} loaded'),
        const SizedBox(height: 8),
        Wrap(
          spacing: 6, runSpacing: 4,
          children: ((tools['names'] as List?) ?? []).map<Widget>((n) => Chip(
            label: Text(n.toString(), style: const TextStyle(fontSize: 10, color: JvColors.textSec)),
            backgroundColor: JvColors.bg,
            padding: EdgeInsets.zero,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
          )).toList(),
        ),
      ]),
    );
  }

  Widget _buildMemoryCard(dynamic mem, dynamic vec) {
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.memory, 'MEMORY', ''),
        const SizedBox(height: 8),
        if (mem != null && mem['error'] == null) ...[
          _kvRow('Types', '${mem['types_defined']}'),
          if (mem['by_type'] != null)
            ...((mem['by_type'] as Map).entries.map((e) =>
                _kvRow('  ${e.key}', '${e.value}'))),
        ] else
          Text('Structured: ${mem?['error'] ?? 'N/A'}', style: const TextStyle(color: JvColors.error, fontSize: 12)),
        const Divider(color: JvColors.surface),
        if (vec != null && vec['error'] == null) ...[
          _kvRow('Vectors', '${vec['total_vectors']}'),
          _kvRow('Collection', '${vec['collection']}'),
          _kvRow('Model', '${vec['embedding_model']}'),
        ] else
          Text('Vector: ${vec?['error'] ?? 'N/A'}', style: const TextStyle(color: JvColors.error, fontSize: 12)),
      ]),
    );
  }

  Widget _buildPolicyCard(dynamic policy) {
    if (policy == null || policy['error'] != null) {
      return _errorCard('Policy', policy?['error'] ?? 'N/A');
    }
    final active = policy['active'] ?? '?';
    Color profileColor = active == 'safe' ? JvColors.success
        : active == 'balanced' ? JvColors.cyan
        : JvColors.warning;
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.shield, 'POLICY', active.toString().toUpperCase()),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          decoration: BoxDecoration(
            color: profileColor.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: profileColor.withValues(alpha: 0.4)),
          ),
          child: Text('Active: $active',
              style: TextStyle(color: profileColor, fontWeight: FontWeight.bold)),
        ),
      ]),
    );
  }

  Widget _buildSkillsCard(dynamic skills) {
    if (skills == null || skills['error'] != null) {
      return _errorCard('Skills', skills?['error'] ?? 'N/A');
    }
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.psychology, 'SKILLS', '${skills['total_skills']} total'),
        const SizedBox(height: 8),
        _kvRow('Tracked', '${skills['tracked']}'),
        _kvRow('Disabled', '${skills['disabled']}'),
        _kvRow('Avg Score', '${skills['avg_score']}'),
      ]),
    );
  }

  Widget _buildSemanticCard(dynamic sr) {
    if (sr == null || sr['error'] != null) {
      return _errorCard('Semantic Router', sr?['error'] ?? 'N/A');
    }
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.route, 'SEMANTIC ROUTER', sr['embedding_model'] ?? ''),
        const SizedBox(height: 8),
        _kvRow('Embeddings', '${sr['capability_embeddings_loaded']}'),
        _kvRow('Cache Size', '${sr['cache']?['size'] ?? 0}'),
        _kvRow('Cache Hits', '${sr['cache']?['hits'] ?? 0}'),
        _kvRow('Threshold', '${sr['confidence_threshold']}'),
      ]),
    );
  }

  Widget _buildRecoveryCard(dynamic rec) {
    if (rec == null || rec['error'] != null) {
      return _errorCard('Recovery', rec?['error'] ?? 'N/A');
    }
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.healing, 'RECOVERY ENGINE', '${rec['total_strategies']} strategies'),
        const SizedBox(height: 8),
        _kvRow('Active Recoveries', '${rec['active_contexts']}'),
        _kvRow('Matrix Rules', '${rec['strategy_matrix_rules']}'),
        _kvRow('Tool Alternatives', '${rec['tool_alternatives']}'),
      ]),
    );
  }

  Widget _buildAgentsCard(dynamic agents) {
    if (agents == null || agents['error'] != null) {
      return _errorCard('Agents', agents?['error'] ?? 'N/A');
    }
    final roles = (agents['roles'] as List?)?.cast<Map>() ?? [];
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.groups, 'AGENTS', '${roles.length} roles'),
        const SizedBox(height: 8),
        ...roles.map((r) => Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            Icon(Icons.person, size: 14, color: JvColors.cyan),
            const SizedBox(width: 6),
            Text('${r['name'] ?? '?'}', style: const TextStyle(color: JvColors.text, fontSize: 12)),
            const Spacer(),
            Text('${r['agent_count'] ?? 0} agents',
                style: const TextStyle(color: JvColors.textSec, fontSize: 11)),
          ]),
        )),
      ]),
    );
  }

  Widget _buildSafetyCard(dynamic safety) {
    if (safety == null || safety['error'] != null) {
      return _errorCard('Self-Improvement', safety?['error'] ?? 'N/A');
    }
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.security, 'SELF-IMPROVEMENT', 'GUARDED'),
        const SizedBox(height: 8),
        _kvRow('Protected Files', '${safety['protected_files']}'),
        _kvRow('Allowed Scopes', '${safety['allowed_scopes']}'),
      ]),
    );
  }

  // ── Helpers ────────────────────────────────────────────────────

  Widget _header(IconData icon, String title, String subtitle) {
    return Row(children: [
      Icon(icon, color: JvColors.cyan, size: 18),
      const SizedBox(width: 8),
      Text(title, style: const TextStyle(
        color: JvColors.cyan, fontWeight: FontWeight.bold, fontSize: 14)),
      const Spacer(),
      Text(subtitle, style: const TextStyle(color: JvColors.textSec, fontSize: 12)),
    ]);
  }

  Widget _kvRow(String key, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(children: [
        Text(key, style: const TextStyle(color: JvColors.textSec, fontSize: 12)),
        const Spacer(),
        Text(value, style: const TextStyle(color: JvColors.text, fontSize: 12)),
      ]),
    );
  }

  Widget _errorCard(String title, String error) {
    return CyberCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _header(Icons.error_outline, title, 'ERROR'),
        const SizedBox(height: 4),
        Text(error, style: const TextStyle(color: JvColors.error, fontSize: 11)),
      ]),
    );
  }
}
