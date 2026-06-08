import { useEffect, useState } from 'react';
import { Sparkles, Play, CheckCircle, XCircle, Clock, AlertTriangle } from 'lucide-react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Badge } from '../components/Badge';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';
import { formatDateTime } from '../utils/format';

export const ImprovementLoop = () => {
  const [status, setStatus] = useState<any>(null);
  const [proposals, setProposals] = useState<any[]>([]);
  const [failures, setFailures] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [s, p, f, r] = await Promise.all([
        apiClient.getImprovementStatus(),
        apiClient.getImprovementProposals(),
        apiClient.getImprovementFailures(),
        apiClient.getImprovementReport(),
      ]);
      setStatus(s);
      setProposals(p?.proposals ?? p ?? []);
      setFailures(f?.failures ?? f ?? []);
      setReport(r);
    } catch (err) {
      console.error('Failed to load improvement data:', err);
    } finally {
      setLoading(false);
    }
  };

  const triggerRun = async () => {
    setRunning(true);
    try {
      await apiClient.triggerImprovementRun();
      setMessage({ type: 'success', text: 'Improvement cycle triggered' });
      setTimeout(() => setMessage(null), 4000);
      setTimeout(load, 2000);
    } catch (err) {
      setMessage({ type: 'error', text: 'Failed to trigger improvement cycle' });
      setTimeout(() => setMessage(null), 4000);
    } finally {
      setRunning(false);
    }
  };

  const severityVariant = (sev: string) => {
    if (sev === 'high' || sev === 'critical') return 'error';
    if (sev === 'medium') return 'warning';
    return 'info';
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Auto-Improve</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">Self-improvement loop — proposals, failures, reports</p>
        </div>
        <Button onClick={triggerRun} loading={running} className="gap-2">
          <Play className="w-4 h-4" />Run Cycle
        </Button>
      </div>

      {message && (
        <div className={`p-3 rounded border ${message.type === 'success' ? 'bg-green-50 border-green-300 text-green-800 dark:bg-green-900/20 dark:border-green-700 dark:text-green-200' : 'bg-red-50 border-red-300 text-red-800 dark:bg-red-900/20 dark:border-red-700 dark:text-red-200'}`}>
          {message.text}
        </div>
      )}

      {loading ? <LoadingSpinner /> : (
        <>
          {/* Gate status */}
          {status && (
            <Card>
              <div className="flex items-center gap-4">
                {status.allowed
                  ? <CheckCircle className="w-8 h-8 text-green-500 flex-shrink-0" />
                  : <XCircle className="w-8 h-8 text-red-500 flex-shrink-0" />}
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-900 dark:text-white">Gate</span>
                    <Badge variant={status.allowed ? 'success' : 'error'}>{status.reason}</Badge>
                  </div>
                  <div className="text-sm text-gray-500 dark:text-gray-400 mt-1 flex gap-4">
                    {status.last_improvement && <span><Clock className="w-3 h-3 inline mr-1" />Last: {formatDateTime(status.last_improvement)}</span>}
                    <span>Failures: {status.consecutive_failures ?? 0}</span>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Last report */}
          {report && report.data && (
            <Card>
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary-500" />Last Report
              </h2>
              <pre className="text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap bg-gray-50 dark:bg-gray-700 rounded p-3 max-h-48 overflow-y-auto">
                {typeof report.data === 'string' ? report.data : JSON.stringify(report.data, null, 2)}
              </pre>
            </Card>
          )}

          {/* Proposals */}
          <Card>
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Pending Proposals ({proposals.length})</h2>
            {proposals.length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">No pending proposals — run a cycle to generate them.</p>
            ) : proposals.map((p: any, i: number) => (
              <div key={p.id ?? i} className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 mb-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm text-gray-900 dark:text-white">{p.title ?? p.description ?? `Proposal ${i + 1}`}</span>
                  {p.status && <Badge>{p.status}</Badge>}
                </div>
                {p.file && <p className="text-xs text-gray-500 dark:text-gray-400 font-mono">{p.file}</p>}
              </div>
            ))}
          </Card>

          {/* Failures */}
          <Card>
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-yellow-500" />Detected Failures ({failures.length})
            </h2>
            {failures.length === 0 ? (
              <p className="text-sm text-gray-500 dark:text-gray-400">No failures detected.</p>
            ) : (
              <div className="space-y-2">
                {failures.slice(0, 20).map((f: any, i: number) => (
                  <div key={f.issue_id ?? i} className="flex items-start gap-3 border border-gray-200 dark:border-gray-700 rounded-lg p-3">
                    <span className="flex-shrink-0"><Badge variant={severityVariant(f.severity)}>{f.severity}</Badge></span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-white">{f.symptom}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{f.probable_root_cause}</p>
                      <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">{f.category} · {formatDateTime(f.timestamp)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
};
