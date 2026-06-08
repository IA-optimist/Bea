import { useEffect, useState } from 'react';
import { Database, Search, RefreshCw, FileText, HardDrive } from 'lucide-react';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { LoadingSpinner } from '../components/LoadingSpinner';
import { apiClient } from '../api/client';
import { formatDateTime } from '../utils/format';

export const MemoryMonitor = () => {
  const [memStats, setMemStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [querying, setQuerying] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [queryError, setQueryError] = useState<string | null>(null);

  useEffect(() => { load(); }, []);

  const load = async () => {
    setLoading(true);
    try {
      const stats = await apiClient.getMemoryStats();
      setMemStats(stats);
    } catch (err) {
      console.error('Failed to load memory stats:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleQuery = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setQuerying(true);
    setQueryError(null);
    setResults([]);
    try {
      const res = await apiClient.queryMemory(query);
      setResults(res?.results ?? res ?? []);
    } catch (err) {
      setQueryError(err instanceof Error ? err.message : 'Query failed');
    } finally {
      setQuerying(false);
    }
  };

  const stats = memStats?.data ?? memStats;

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Memory</h1>
          <p className="text-gray-600 dark:text-gray-400 mt-1">Vector memory store — indexed knowledge and RAG queries</p>
        </div>
        <Button onClick={load} className="gap-2"><RefreshCw className="w-4 h-4" />Refresh</Button>
      </div>

      {loading ? <LoadingSpinner /> : (
        <>
          {/* Stats cards */}
          {stats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: 'Indexed Files', value: stats.indexed_files ?? 0, icon: FileText },
                { label: 'Vectors', value: stats.vector_count ?? 0, icon: Database },
                { label: 'Backend', value: stats.store_backend ?? 'memory', icon: HardDrive },
                { label: 'Last Indexed', value: stats.last_indexed ? formatDateTime(stats.last_indexed) : 'Never', icon: RefreshCw },
              ].map(({ label, value, icon: Icon }) => (
                <Card key={label} className="text-center">
                  <Icon className="w-6 h-6 mx-auto mb-2 text-primary-500" />
                  <div className="text-xl font-bold text-gray-900 dark:text-white truncate">{value}</div>
                  <div className="text-sm text-gray-500 dark:text-gray-400">{label}</div>
                </Card>
              ))}
            </div>
          )}

          {/* RAG Query */}
          <Card>
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
              <Search className="w-4 h-4 text-primary-500" />Query Memory
            </h2>
            <form onSubmit={handleQuery} className="flex gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search knowledge base…"
                className="flex-1 px-3 py-2 bg-gray-50 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-900 dark:text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500"
              />
              <Button type="submit" loading={querying}><Search className="w-4 h-4" /></Button>
            </form>

            {queryError && (
              <p className="mt-2 text-sm text-red-600 dark:text-red-400">{queryError}</p>
            )}

            {results.length > 0 && (
              <div className="mt-4 space-y-2">
                {results.map((r: any, i: number) => (
                  <div key={i} className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                    <p className="text-sm text-gray-800 dark:text-gray-200">{r.content ?? r.text ?? r.chunk ?? JSON.stringify(r)}</p>
                    {r.score !== undefined && (
                      <p className="text-xs text-gray-400 mt-1">Score: {(r.score * 100).toFixed(1)}%</p>
                    )}
                  </div>
                ))}
              </div>
            )}

            {!querying && query && results.length === 0 && !queryError && (
              <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                {stats?.vector_count === 0
                  ? 'Memory is empty — index documents first.'
                  : 'No results found.'}
              </p>
            )}
          </Card>

          {/* Raw stats */}
          {stats && (
            <Card>
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Raw Stats</h2>
              <pre className="text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-3 overflow-x-auto">
                {JSON.stringify(stats, null, 2)}
              </pre>
            </Card>
          )}
        </>
      )}
    </div>
  );
};
