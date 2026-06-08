import { useEffect, useState } from 'react';
import { Cpu, CheckCircle, XCircle, RefreshCw, BookOpen, Shield, Zap } from 'lucide-react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Badge } from '../components/Badge';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';

export const McpSkills = () => {
  const [servers, setServers] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [skills, setSkills] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState<Set<string>>(new Set());
  const [tab, setTab] = useState<'mcp' | 'skills'>('mcp');

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
      if (currentStatus === 'enabled') {
        await apiClient.disableMcpServer(id);
      } else {
        await apiClient.enableMcpServer(id);
      }
      await load();
    } finally {
      setToggling((p) => { const n = new Set(p); n.delete(id); return n; });
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
        <Button onClick={load} className="gap-2"><RefreshCw className="w-4 h-4" />Refresh</Button>
      </div>

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
                </div>
              </div>
            </Card>
          ))}
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
                <div className="text-xs text-gray-400 flex-shrink-0">
                  {sk.use_count ?? 0}× used
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
};
