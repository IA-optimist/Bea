import { useEffect, useRef, useState } from 'react';
import { Radio, Activity, ChevronRight, XCircle } from 'lucide-react';
import { Card } from '../components/Card';
import { Badge } from '../components/Badge';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';

const WS_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/^http/, 'ws');
const TOKEN = localStorage.getItem('bea_token') || '';

interface LogEntry {
  id: number;
  ts: string;
  source?: string;
  type?: string;
  content?: string;
  raw: any;
}

const statusVariant = (s: string) => {
  if (s === 'completed' || s === 'done' || s === 'success') return 'success';
  if (s === 'failed' || s === 'error') return 'error';
  if (s === 'running') return 'warning';
  return 'default';
};

export const MissionLogs = () => {
  const [missions, setMissions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<any | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [wsState, setWsState] = useState<'idle' | 'connecting' | 'open' | 'closed' | 'error'>('idle');
  const wsRef = useRef<WebSocket | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const logIdRef = useRef(0);

  useEffect(() => { loadMissions(); }, []);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const loadMissions = async () => {
    setLoading(true);
    try {
      const data = await apiClient.listMissions({ limit: 50 });
      setMissions(data);
    } catch (err) {
      console.error('Failed to load missions:', err);
    } finally {
      setLoading(false);
    }
  };

  const connectWs = (mission: any) => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setSelected(mission);
    setLogs([]);
    setWsState('connecting');

    const ws = new WebSocket(`${WS_BASE}/api/v3/mission/${mission.mission_id || mission.id}/stream`);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsState('open');
      // Browser WS can't set headers — send token as first message for auth
      const t = TOKEN || localStorage.getItem('bea_token') || '';
      if (t) ws.send(t);
      // Keepalive ping every 25s
      const ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
        else clearInterval(ping);
      }, 25000);
    };

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === 'pong') return;
        const id = ++logIdRef.current;
        const ts = data.timestamp || data.ts || new Date().toISOString();
        setLogs((prev) => [...prev, { id, ts, source: data.source, type: data.type, content: extractContent(data), raw: data }]);
      } catch {
        // Not JSON — plain text line
        const id = ++logIdRef.current;
        setLogs((prev) => [...prev, { id, ts: new Date().toISOString(), content: evt.data, raw: evt.data }]);
      }
    };

    ws.onerror = () => setWsState('error');
    ws.onclose = () => setWsState((s) => s === 'open' ? 'closed' : s);
  };

  const disconnect = () => {
    wsRef.current?.close();
    wsRef.current = null;
    setWsState('closed');
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Mission Logs</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">Live WebSocket stream per mission</p>
        </div>
        <div className="flex items-center gap-2">
          <WsIndicator state={wsState} />
          {wsState === 'open' && (
            <button onClick={disconnect} className="text-xs text-gray-500 hover:text-red-500 flex items-center gap-1">
              <XCircle className="w-4 h-4" />Disconnect
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Mission list */}
        <div className="md:col-span-1">
          <Card className="p-0 overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700">
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">Missions ({missions.length})</span>
            </div>
            {loading ? (
              <div className="p-4"><LoadingSpinner /></div>
            ) : missions.length === 0 ? (
              <div className="p-4 text-sm text-gray-500 dark:text-gray-400 text-center">No missions yet</div>
            ) : (
              <div className="divide-y divide-gray-100 dark:divide-gray-700 max-h-[70vh] overflow-y-auto">
                {missions.map((m: any) => {
                  const mId = m.mission_id || m.id;
                  const isActive = selected && (selected.mission_id || selected.id) === mId;
                  return (
                    <button
                      key={mId}
                      onClick={() => connectWs(m)}
                      className={`w-full text-left px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${isActive ? 'bg-primary-50 dark:bg-primary-900/20' : ''}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-gray-900 dark:text-white truncate flex-1">
                          {m.goal || m.title || mId}
                        </span>
                        <ChevronRight className={`w-4 h-4 flex-shrink-0 ${isActive ? 'text-primary-500' : 'text-gray-400'}`} />
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge variant={statusVariant(m.status || '')}>{m.status || 'unknown'}</Badge>
                        <span className="text-xs text-gray-400">{mId.slice(0, 8)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </Card>
        </div>

        {/* Log viewer */}
        <div className="md:col-span-2">
          <Card className="p-0 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700">
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                {selected ? `Logs — ${(selected.goal || selected.title || selected.mission_id || '').slice(0, 40)}` : 'Select a mission'}
              </span>
              {logs.length > 0 && <span className="text-xs text-gray-400">{logs.length} events</span>}
            </div>
            <div className="bg-gray-950 min-h-[400px] max-h-[65vh] overflow-y-auto p-4 font-mono text-xs">
              {wsState === 'connecting' && (
                <div className="text-yellow-400 animate-pulse">Connecting…</div>
              )}
              {wsState === 'error' && (
                <div className="text-red-400">Connection error. Mission may be inactive or token invalid.</div>
              )}
              {wsState === 'closed' && logs.length === 0 && (
                <div className="text-gray-500">Disconnected — no events received. Mission may be inactive.</div>
              )}
              {logs.length === 0 && wsState === 'idle' && (
                <div className="text-gray-600">← Select a mission to stream its logs</div>
              )}
              {logs.map((entry) => (
                <LogLine key={entry.id} entry={entry} />
              ))}
              <div ref={logsEndRef} />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
};

const LogLine = ({ entry }: { entry: LogEntry }) => {
  const [expanded, setExpanded] = useState(false);
  const ts = entry.ts ? new Date(entry.ts).toLocaleTimeString() : '';
  const color = logColor(entry.type, entry.source);

  return (
    <div className="mb-1">
      <div
        className={`flex gap-2 cursor-pointer hover:bg-gray-800 rounded px-1 py-0.5 ${color}`}
        onClick={() => setExpanded((x) => !x)}
      >
        <span className="text-gray-600 flex-shrink-0 select-none">{ts}</span>
        {entry.source && <span className="text-blue-400 flex-shrink-0">[{entry.source}]</span>}
        {entry.type && <span className="text-purple-400 flex-shrink-0">{entry.type}</span>}
        <span className="break-all">{entry.content || JSON.stringify(entry.raw).slice(0, 200)}</span>
      </div>
      {expanded && (
        <pre className="text-gray-400 text-xs pl-4 mt-0.5 whitespace-pre-wrap break-all">
          {JSON.stringify(entry.raw, null, 2)}
        </pre>
      )}
    </div>
  );
};

const WsIndicator = ({ state }: { state: string }) => {
  const colors: Record<string, string> = {
    idle: 'text-gray-400',
    connecting: 'text-yellow-500 animate-pulse',
    open: 'text-green-500 animate-pulse',
    closed: 'text-gray-500',
    error: 'text-red-500',
  };
  const labels: Record<string, string> = {
    idle: 'Idle', connecting: 'Connecting', open: 'Live', closed: 'Closed', error: 'Error',
  };
  return (
    <div className={`flex items-center gap-1.5 text-xs font-medium ${colors[state] || 'text-gray-400'}`}>
      {state === 'open' ? <Activity className="w-4 h-4" /> : <Radio className="w-4 h-4" />}
      {labels[state] || state}
    </div>
  );
};

function extractContent(data: any): string {
  if (data.content) return String(data.content).slice(0, 500);
  if (data.message) return String(data.message).slice(0, 500);
  if (data.output) return String(data.output).slice(0, 500);
  if (data.text) return String(data.text).slice(0, 500);
  if (data.result) return String(data.result).slice(0, 500);
  return '';
}

function logColor(type?: string, source?: string): string {
  if (type === 'error' || source === 'error') return 'text-red-400';
  if (type === 'warning') return 'text-yellow-400';
  if (type === 'tool_call' || type === 'tool_result') return 'text-cyan-400';
  if (type === 'reasoning' || type === 'thought') return 'text-purple-300';
  if (type === 'done' || type === 'completed') return 'text-green-400';
  return 'text-gray-300';
}
