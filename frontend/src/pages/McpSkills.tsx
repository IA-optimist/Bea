import { useEffect, useState } from 'react';
import { Cpu, CheckCircle, XCircle, RefreshCw, BookOpen, Shield, Zap, Plus, Trash2, X } from 'lucide-react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Badge } from '../components/Badge';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';

const EMPTY_FORM = {
  id: '', name: '', description: '',
  command: '', args: '', transport: 'stdio',
  endpoint: '', category: 'engineering',
  trust_level: 'community', risk_level: 'medium',
  required_secrets: '', source: '', source_url: '',
};

export const McpSkills = () => {
  const [servers, setServers] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [skills, setSkills] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<'mcp' | 'skills'>('mcp');
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [mcpRes, statsRes, skillsRes] = await Promise.all([
        apiClient.getMcpServers(),
        apiClient.getMcpStats(),
        apiClient.getLearnedSkills(),
      ]);
      setServers(mcpRes);
      setStats(statsRes);
      setSkills(skillsRes);
    } catch (err) {
      console.error('Failed to load MCP/Skills:', err);
    } finally {
      setLoading(false);
    }
  };

  const toggleServer = async (id: string, currentStatus: string) => {
    setToggling((p) => new Set(p).add(id));
    try {
      if (currentStatus === 'enabled') await apiClient.disableMcpServer(id);
      else await apiClient.enableMcpServer(id);
      await load();
    } finally {
      setToggling((p) => { const n = new Set(p); n.delete(id); return n; });
    }
  };

  const deleteServer = async (id: string) => {
    if (!confirm(`Remove MCP server "${id}" ?`)) return;
    setDeleting((p) => new Set(p).add(id));
    try {
      await apiClient.deleteMcpServer(id);
      setMsg({ type: 'success', text: `Server "${id}" removed` });
      setTimeout(() => setMsg(null), 4000);
      await load();
    } catch (err: any) {
      setMsg({ type: 'error', text: err?.response?.data?.detail || 'Delete failed' });
      setTimeout(() => setMsg(null), 4000);
    } finally {
      setDeleting((p) => { const n = new Set(p); n.delete(id); return n; });
    }
  };

  const slugify = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

  const handleAdd = async () => {
    if (!form.id || !form.name) return;
    setSaving(true);
    try {
      await apiClient.addMcpServer({
        ...form,
        args: form.args.trim() ? form.args.trim().split(/\s+/) : [],
        required_secrets: form.required_secrets.trim() ? form.required_secrets.trim().split(/[\s,]+/) : [],
      });
      setMsg({ type: 'success', text: `Server "${form.name}" registered` });
      setTimeout(() => setMsg(null), 4000);
      setShowAdd(false);
      setForm({ ...EMPTY_FORM });
      await load();
    } catch (err: any) {
      setMsg({ type: 'error', text: err?.response?.data?.detail || 'Failed to add server' });
      setTimeout(() => setMsg(null), 5000);
    } finally {
      setSaving(false);
    }
  };

  const trustColor = (trust: string) => {
    if (trust === 'official') return 'success';
    if (trust === 'managed') return 'info';
    return 'warning';
  };

  const riskColor = (risk: string) => {
    if (risk === 'high') return 'error';
    if (risk === 'medium') return 'warning';
    return 'success';
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">MCP &amp; Skills</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">Manage MCP servers and learned skills</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={load} className="gap-2"><RefreshCw className="w-4 h-4" />Refresh</Button>
          <Button onClick={() => setShowAdd(true)} className="gap-2"><Plus className="w-4 h-4" />Add Server</Button>
        </div>
      </div>

      {msg && (
        <div className={`p-3 rounded border text-sm ${msg.type === 'success' ? 'bg-green-50 border-green-300 text-green-800 dark:bg-green-900/20 dark:border-green-700 dark:text-green-200' : 'bg-red-50 border-red-300 text-red-800 dark:bg-red-900/20 dark:border-red-700 dark:text-red-200'}`}>
          {msg.text}
        </div>
      )}

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Servers', value: stats.total_servers, icon: Cpu },
            { label: 'Total Tools', value: stats.total_tools, icon: Zap },
            { label: 'Official', value: stats.by_trust?.official ?? 0, icon: Shield },
            { label: 'Community', value: stats.by_trust?.community ?? 0, icon: BookOpen },
          ].map(({ label, value, icon: Icon }) => (
            <Card key={label} className="text-center">
              <Icon className="w-6 h-6 mx-auto mb-2 text-primary-500" />
              <div className="text-2xl font-bold text-gray-900 dark:text-white">{value}</div>
              <div className="text-sm text-gray-500 dark:text-gray-400">{label}</div>
            </Card>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-gray-200 dark:border-gray-700">
        {(['mcp', 'skills'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${tab === t ? 'border-primary-500 text-primary-600 dark:text-primary-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}>
            {t === 'mcp' ? 'MCP Servers' : 'Learned Skills'}
          </button>
        ))}
      </div>

      {loading ? <LoadingSpinner /> : tab === 'mcp' ? (
        <div className="space-y-3">
          {servers.map((srv) => (
            <Card key={srv.id}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-gray-900 dark:text-white">{srv.name}</span>
                    <Badge variant={trustColor(srv.trust)}>{srv.trust}</Badge>
                    {srv.risk && <Badge variant={riskColor(srv.risk)}>risk:{srv.risk}</Badge>}
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 truncate">{srv.description}</p>
                  <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 dark:text-gray-400">
                    <span>{srv.tools_count ?? 0} tools</span>
                    <span>{srv.transport}</span>
                    {srv.source && <span className="truncate max-w-[200px]">{srv.source}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {srv.status === 'enabled'
                    ? <CheckCircle className="w-4 h-4 text-green-500" />
                    : <XCircle className="w-4 h-4 text-gray-400" />}
                  <Button size="sm" variant={srv.status === 'enabled' ? 'secondary' : 'primary'}
                    loading={toggling.has(srv.id)} onClick={() => toggleServer(srv.id, srv.status)}>
                    {srv.status === 'enabled' ? 'Disable' : 'Enable'}
                  </Button>
                  <button
                    disabled={deleting.has(srv.id)}
                    onClick={() => deleteServer(srv.id)}
                    className="p-1.5 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-40"
                    title="Remove server"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </Card>
          ))}
          {servers.length === 0 && (
            <Card><div className="text-center py-8 text-gray-500 dark:text-gray-400">No MCP servers registered. Add one with the button above.</div></Card>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {skills.length === 0 ? (
            <Card><div className="text-center py-8 text-gray-500 dark:text-gray-400">No learned skills yet — run missions to build the skill library.</div></Card>
          ) : skills.map((sk: any) => (
            <Card key={sk.skill_id ?? sk.id}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-gray-900 dark:text-white text-sm">{sk.name}</span>
                    {sk.confidence !== undefined && (
                      <Badge variant={sk.confidence > 0.7 ? 'success' : 'warning'}>{(sk.confidence * 100).toFixed(0)}%</Badge>
                    )}
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mt-1 line-clamp-2">{sk.description}</p>
                </div>
                <div className="text-xs text-gray-400 flex-shrink-0">{sk.use_count ?? 0}× used</div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Add MCP Server Modal */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-gray-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Add MCP Server</h2>
              <button onClick={() => setShowAdd(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              {/* Name → auto-slug id */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Name *</label>
                  <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    value={form.name}
                    onChange={(e) => setForm((f) => ({ ...f, name: e.target.value, id: f.id || slugify(e.target.value) }))}
                    placeholder="My MCP Server" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">ID *</label>
                  <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    value={form.id}
                    onChange={(e) => setForm((f) => ({ ...f, id: e.target.value }))}
                    placeholder="my-mcp-server" />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="What does this server do?" />
              </div>

              {/* Transport selector */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Transport</label>
                  <select className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    value={form.transport}
                    onChange={(e) => setForm((f) => ({ ...f, transport: e.target.value }))}>
                    <option value="stdio">stdio</option>
                    <option value="http">http</option>
                    <option value="sse">sse</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Category</label>
                  <select className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    value={form.category}
                    onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}>
                    <option value="engineering">Engineering</option>
                    <option value="security">Security</option>
                    <option value="data">Data</option>
                    <option value="infra">Infra</option>
                    <option value="managed">Managed</option>
                    <option value="community">Community</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Risk</label>
                  <select className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    value={form.risk_level}
                    onChange={(e) => setForm((f) => ({ ...f, risk_level: e.target.value }))}>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </div>
              </div>

              {form.transport === 'stdio' ? (
                <>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Command</label>
                    <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono"
                      value={form.command}
                      onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))}
                      placeholder="npx" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Args (space-separated)</label>
                    <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono"
                      value={form.args}
                      onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))}
                      placeholder="-y @modelcontextprotocol/server-filesystem /path" />
                  </div>
                </>
              ) : (
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Endpoint URL</label>
                  <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono"
                    value={form.endpoint}
                    onChange={(e) => setForm((f) => ({ ...f, endpoint: e.target.value }))}
                    placeholder="http://localhost:3100/mcp" />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Trust Level</label>
                  <select className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    value={form.trust_level}
                    onChange={(e) => setForm((f) => ({ ...f, trust_level: e.target.value }))}>
                    <option value="official">Official</option>
                    <option value="vendor">Vendor</option>
                    <option value="managed">Managed</option>
                    <option value="community">Community</option>
                    <option value="untrusted">Untrusted</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Required Secrets (comma-sep)</label>
                  <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500 font-mono"
                    value={form.required_secrets}
                    onChange={(e) => setForm((f) => ({ ...f, required_secrets: e.target.value }))}
                    placeholder="GITHUB_TOKEN,API_KEY" />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Source (optional)</label>
                <input className="w-full px-3 py-2 text-sm bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  value={form.source}
                  onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}
                  placeholder="modelcontextprotocol/servers" />
              </div>
            </div>
            <div className="flex justify-end gap-3 p-6 border-t border-gray-200 dark:border-gray-700">
              <Button variant="secondary" onClick={() => { setShowAdd(false); setForm({ ...EMPTY_FORM }); }}>Cancel</Button>
              <Button onClick={handleAdd} loading={saving} disabled={!form.id || !form.name}>
                Register Server
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
