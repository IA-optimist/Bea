import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_service.dart';
import '../theme/design_system.dart';

/// Capabilities — real backend data from /api/v2/system/capabilities
class CapabilitiesScreen extends StatefulWidget {
  const CapabilitiesScreen({super.key});

  @override
  State<CapabilitiesScreen> createState() => _CapabilitiesScreenState();
}

class _CapabilitiesScreenState extends State<CapabilitiesScreen> {
  Map<String, dynamic> _data = {};
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() { _loading = true; _error = null; });
    try {
      final result = await context.read<ApiService>().getCapabilities();
      if (!mounted) return;
      if (result.ok && result.data != null) {
        setState(() { _data = result.data!; _loading = false; });
      } else {
        setState(() { _error = result.error ?? 'Unknown error'; _loading = false; });
      }
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  Color _statusColor(String status) {
    switch (status.toLowerCase()) {
      case 'active': return JDS.green;
      case 'planned': return JDS.amber;
      case 'degraded': return JDS.amber;
      case 'disabled': return JDS.textDim;
      default: return JDS.textMuted;
    }
  }

  IconData _modalityIcon(String key) {
    switch (key) {
      case 'text': return Icons.text_fields_rounded;
      case 'image': return Icons.image_outlined;
      case 'audio': return Icons.mic_outlined;
      case 'document': return Icons.description_outlined;
      case 'screenshot': return Icons.screenshot_outlined;
      default: return Icons.category_outlined;
    }
  }

  @override
  Widget build(BuildContext context) {
    final agentsMap = (_data['agents'] as Map?)?.cast<String, dynamic>() ?? {};
    final modalities = (_data['modalities'] as Map?)?.cast<String, dynamic>() ?? {};
    final roles = (_data['roles'] as List?)?.cast<String>() ?? [];
    final summary = (_data['summary'] as Map?)?.cast<String, dynamic>() ?? {};
    final version = _data['version']?.toString() ?? '';
    final phase = _data['phase']?.toString() ?? '';

    final activeAgents = agentsMap.values
        .where((v) => v is Map && v['status'] == 'active').length;
    final plannedAgents = agentsMap.values
        .where((v) => v is Map && v['status'] == 'planned').length;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Capabilities'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh_rounded), onPressed: _load),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Padding(
                  padding: const EdgeInsets.all(32),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const Icon(Icons.error_outline_rounded, color: JDS.red, size: 48),
                    const SizedBox(height: 16),
                    Text(_error!, style: const TextStyle(color: JDS.textMuted, fontSize: 14),
                        textAlign: TextAlign.center),
                    const SizedBox(height: 20),
                    ElevatedButton.icon(
                      onPressed: _load,
                      icon: const Icon(Icons.refresh, size: 16),
                      label: const Text('Retry'),
                    ),
                  ]),
                ))
              : RefreshIndicator(
                  onRefresh: _load,
                  color: JDS.blue,
                  backgroundColor: JDS.bgElevated,
                  child: ListView(padding: const EdgeInsets.all(20), children: [
                    // ── Summary card ──
                    if (version.isNotEmpty || phase.isNotEmpty)
                      JCard(child: Row(children: [
                        const Icon(Icons.info_outline_rounded, size: 18, color: JDS.blue),
                        const SizedBox(width: 10),
                        if (version.isNotEmpty)
                          Text('v$version', style: const TextStyle(
                            color: JDS.textPrimary, fontSize: 13, fontWeight: FontWeight.w600,
                          )),
                        if (phase.isNotEmpty) ...[
                          const SizedBox(width: 8),
                          Text('Phase $phase', style: const TextStyle(
                            color: JDS.textMuted, fontSize: 12,
                          )),
                        ],
                        const Spacer(),
                        JStatusBadge(
                          label: '$activeAgents ACTIVE',
                          color: JDS.green,
                        ),
                        if (plannedAgents > 0) ...[
                          const SizedBox(width: 6),
                          JStatusBadge(
                            label: '$plannedAgents PLANNED',
                            color: JDS.amber,
                          ),
                        ],
                      ])),
                    const SizedBox(height: 20),

                    // ── Agents ──
                    JSectionHeader(title: 'Agents', count: '${agentsMap.length}'),
                    ...agentsMap.entries.map((e) {
                      final info = e.value is Map
                          ? Map<String, dynamic>.from(e.value)
                          : <String, dynamic>{};
                      final status = info['status']?.toString() ?? 'unknown';
                      final role = info['role']?.toString() ?? '';
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: JCard(
                          padding: const EdgeInsets.all(14),
                          child: Row(children: [
                            Icon(Icons.smart_toy_outlined, size: 18,
                                color: _statusColor(status)),
                            const SizedBox(width: 12),
                            Expanded(child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(e.key, style: const TextStyle(
                                  color: JDS.textPrimary, fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                )),
                                if (role.isNotEmpty)
                                  Text(role, style: const TextStyle(
                                    color: JDS.textMuted, fontSize: 12,
                                  )),
                              ],
                            )),
                            JStatusBadge(
                              label: status.toUpperCase(),
                              color: _statusColor(status),
                            ),
                          ]),
                        ),
                      );
                    }),
                    const SizedBox(height: 20),

                    // ── Modalities ──
                    JSectionHeader(title: 'Modalities', count: '${modalities.length}'),
                    ...modalities.entries.map((e) {
                      final info = e.value is Map
                          ? Map<String, dynamic>.from(e.value)
                          : <String, dynamic>{};
                      final status = info['status']?.toString() ?? 'unknown';
                      final desc = info['description']?.toString() ?? '';
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: JCard(
                          padding: const EdgeInsets.all(14),
                          child: Row(children: [
                            Icon(_modalityIcon(e.key), size: 18,
                                color: _statusColor(status)),
                            const SizedBox(width: 12),
                            Expanded(child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(e.key.toUpperCase(), style: const TextStyle(
                                  color: JDS.textPrimary, fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                )),
                                if (desc.isNotEmpty)
                                  Text(desc, style: const TextStyle(
                                    color: JDS.textMuted, fontSize: 12,
                                  ), maxLines: 2, overflow: TextOverflow.ellipsis),
                              ],
                            )),
                            JStatusBadge(
                              label: status.toUpperCase(),
                              color: _statusColor(status),
                            ),
                          ]),
                        ),
                      );
                    }),
                    const SizedBox(height: 20),

                    // ── Roles ──
                    JSectionHeader(title: 'Roles', count: '${roles.length}'),
                    Wrap(spacing: 8, runSpacing: 6, children: roles.map((r) =>
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(
                          color: JDS.bgElevated,
                          borderRadius: BorderRadius.circular(JDS.radiusXl),
                          border: Border.all(color: JDS.borderDefault),
                        ),
                        child: Text(r, style: const TextStyle(
                          color: JDS.textPrimary, fontSize: 12, fontWeight: FontWeight.w500,
                        )),
                      ),
                    ).toList()),

                    const SizedBox(height: 80),
                  ]),
                ),
    );
  }
}
