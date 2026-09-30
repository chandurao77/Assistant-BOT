import { useEffect, useState } from 'react';

const API_BASE = '/api';

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem('assistant_bot_auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface FeedbackStats {
  total_ratings: number;
  positive: number;
  negative: number;
  satisfaction_rate: number;
  recent_7d_positive: number;
  recent_7d_negative: number;
  reason_breakdown?: Record<string, number>;
}

interface QueryMetrics {
  total_queries: number;
  total_conversations: number;
  queries_last_24h: number;
  no_answer_count: number;
  no_answer_rate: number;
  avg_sources_per_answered_query: number;
}

interface AdminStats {
  system: {
    components: Record<string, string>;
    database_type: string;
    all_healthy: boolean;
  };
  vector_store: {
    total_chunks: number;
    indexed_spaces: { space_key: string; space_name: string }[];
    space_count: number;
  };
  ingestion: {
    running: boolean;
    start_time: string | null;
    end_time: string | null;
    source: string | null;
    current_page: number;
    total_pages: number;
    percent: number;
    last_result: {
      pages_processed: number;
      pages_skipped: number;
      chunks_indexed: number;
      errors: string[];
    } | null;
  };
  users: {
    total: number;
    list: { id: string; name: string; email: string; role: string; created_at: string }[];
  };
  analytics: {
    top_questions: { question: string; count: number }[];
    unanswered_questions: { question: string; count: number }[];
    usage_trend: { date: string; count: number }[];
    peak_hours: { hour: number; count: number }[];
    recent_activity: { question: string; sources_found: number; answered: boolean; response_ms: number | null; user_id: string | null; created_at: string }[];
    response_time: { avg_ms: number; min_ms: number; max_ms: number };
    space_usage: { space_keys: string; count: number }[];
    per_user_usage: { user_id: string; count: number }[];
    active_users_24h: number;
  };
  cache: {
    hits: number;
    misses: number;
    total_lookups: number;
    hit_rate: number;
  };
}

function StatCard({ label, value, sub, color = 'blue', icon }: { label: string; value: string | number; sub?: string; color?: string; icon?: React.ReactNode }) {
  const colors: Record<string, { card: string; accent: string; icon: string; value: string }> = {
    blue:   { card: 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700', accent: 'bg-blue-500',   icon: 'text-blue-500 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/30',   value: 'text-gray-900 dark:text-white' },
    green:  { card: 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700', accent: 'bg-emerald-500', icon: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30', value: 'text-gray-900 dark:text-white' },
    red:    { card: 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700', accent: 'bg-red-500',    icon: 'text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-900/30',    value: 'text-gray-900 dark:text-white' },
    amber:  { card: 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700', accent: 'bg-amber-500',  icon: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30',  value: 'text-gray-900 dark:text-white' },
    purple: { card: 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700', accent: 'bg-purple-500', icon: 'text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-900/30', value: 'text-gray-900 dark:text-white' },
    cyan:   { card: 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700', accent: 'bg-cyan-500',   icon: 'text-cyan-600 dark:text-cyan-400 bg-cyan-50 dark:bg-cyan-900/30',   value: 'text-gray-900 dark:text-white' },
  };
  const c = colors[color] || colors.blue;
  return (
    <div className={`rounded-xl border ${c.card} overflow-hidden shadow-sm hover:shadow-md transition-shadow duration-200`}>
      <div className={`h-1 ${c.accent}`} />
      <div className="p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wide font-medium">{label}</p>
          {icon && <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${c.icon}`}>{icon}</div>}
        </div>
        <p className={`text-2xl font-bold ${c.value} mt-1`}>{value}</p>
        {sub && <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{sub}</p>}
      </div>
    </div>
  );
}

function SatisfactionBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct >= 80 ? 'from-emerald-400 to-emerald-600' : pct >= 50 ? 'from-amber-400 to-amber-600' : 'from-red-400 to-red-600';
  const textColor = pct >= 80 ? 'text-emerald-600 dark:text-emerald-400' : pct >= 50 ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400';
  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs mb-2">
        <span className="text-gray-500 dark:text-gray-400 font-medium">Satisfaction Rate</span>
        <span className={`font-bold ${textColor}`}>{pct}%</span>
      </div>
      <div className="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-3 overflow-hidden">
        <div className={`bg-gradient-to-r ${color} h-3 rounded-full transition-all duration-700 ease-out shadow-sm`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function SectionHeader({ title, color = 'blue', icon }: { title: string; color?: string; icon?: React.ReactNode }) {
  const accents: Record<string, string> = {
    blue: 'border-blue-500', green: 'border-emerald-500', red: 'border-red-500',
    amber: 'border-amber-500', purple: 'border-purple-500', cyan: 'border-cyan-500', indigo: 'border-indigo-500',
  };
  return (
    <h3 className={`text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3 uppercase tracking-wide 
                     flex items-center gap-2 pl-3 border-l-[3px] ${accents[color] || accents.blue}`}>
      {icon}
      {title}
    </h3>
  );
}

export function FeedbackDashboard({ onBack }: { onBack: () => void }) {
  const [feedback, setFeedback] = useState<FeedbackStats | null>(null);
  const [metrics, setMetrics] = useState<QueryMetrics | null>(null);
  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [fbRes, mRes, asRes] = await Promise.all([
          fetch(`${API_BASE}/feedback/stats`, { headers: { ...getAuthHeaders() } }),
          fetch(`${API_BASE}/health/metrics`, { headers: { ...getAuthHeaders() } }),
          fetch(`${API_BASE}/health/admin-stats`, { headers: { ...getAuthHeaders() } }),
        ]);
        if (fbRes.ok) setFeedback(await fbRes.json());
        if (mRes.ok) setMetrics(await mRes.json());
        if (asRes.ok) setAdminStats(await asRes.json());
      } catch { /* ignore */ }
      setLoading(false);
    };
    load();
  }, []);

  if (loading) {
    return (
      <div className="h-full overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6 animate-pulse">
          {/* Skeleton header */}
          <div className="flex items-center justify-between">
            <div>
              <div className="h-6 w-48 bg-gray-200 dark:bg-gray-700 rounded-lg" />
              <div className="h-4 w-32 bg-gray-200 dark:bg-gray-700 rounded mt-2" />
            </div>
            <div className="h-8 w-28 bg-gray-200 dark:bg-gray-700 rounded-lg" />
          </div>
          {/* Skeleton stat cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="h-3 w-20 bg-gray-200 dark:bg-gray-700 rounded mb-2" />
                <div className="h-7 w-16 bg-gray-200 dark:bg-gray-700 rounded" />
              </div>
            ))}
          </div>
          {/* Skeleton chart */}
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <div className="h-3 w-32 bg-gray-200 dark:bg-gray-700 rounded mb-3" />
            <div className="flex items-end gap-1 h-32">
              {[55, 70, 40, 85, 50, 75, 60].map((h, i) => (
                <div key={i} className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-t" style={{ height: `${h}%` }} />
              ))}
            </div>
          </div>
          {/* Skeleton table */}
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="h-8 bg-gray-100 dark:bg-gray-700/50" />
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex gap-4 px-4 py-3 border-t border-gray-100 dark:border-gray-700">
                <div className="h-4 flex-1 bg-gray-200 dark:bg-gray-700 rounded" />
                <div className="h-4 w-12 bg-gray-200 dark:bg-gray-700 rounded" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50/50 dark:bg-gray-900/50">
      {/* Gradient Header Banner */}
      <div className="bg-gradient-to-r from-confluence-blue via-blue-600 to-indigo-600 dark:from-gray-800 dark:via-gray-800 dark:to-gray-900 px-6 py-6">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2.5">
              <svg className="w-6 h-6 text-blue-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              Analytics Dashboard
            </h2>
            <p className="text-sm text-blue-100 dark:text-gray-400 mt-1">Real-time insights into queries, feedback & system performance</p>
          </div>
          <button
            onClick={onBack}
            className="px-4 py-2 text-sm bg-white/15 hover:bg-white/25 backdrop-blur-sm text-white border border-white/20
                       rounded-lg transition-all duration-150 font-medium"
          >
            ← Back to Chat
          </button>
        </div>
      </div>

      <div className="px-6 py-6">
      <div className="max-w-5xl mx-auto">

        {/* Query Metrics */}
        {metrics && (
          <section className="mb-8">
            <SectionHeader title="Query Analytics" color="blue" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" /></svg>
            } />
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <StatCard label="Total Queries" value={metrics.total_queries} color="blue" />
              <StatCard label="Conversations" value={metrics.total_conversations} color="purple" />
              <StatCard label="Last 24h" value={metrics.queries_last_24h} color="blue" />
              <StatCard
                label="No-Answer Rate"
                value={`${Math.round(metrics.no_answer_rate * 100)}%`}
                sub={`${metrics.no_answer_count} unanswered`}
                color={metrics.no_answer_rate > 0.2 ? 'red' : 'green'}
              />
              <StatCard
                label="Avg Sources / Query"
                value={metrics.avg_sources_per_answered_query.toFixed(1)}
                color="amber"
              />
            </div>
          </section>
        )}

        {/* Feedback Metrics */}
        {feedback && (
          <section className="mb-8">
            <SectionHeader title="User Feedback" color="green" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 10h4.764a2 2 0 011.789 2.894l-3.5 7A2 2 0 0115.263 21h-4.017c-.163 0-.326-.02-.485-.06L7 20m7-10V5a2 2 0 00-2-2h-.095c-.5 0-.905.405-.905.905 0 .714-.211 1.412-.608 2.006L7 11v9m7-10h-2M7 20H5a2 2 0 01-2-2v-6a2 2 0 012-2h2.5" /></svg>
            } />
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <StatCard label="Total Ratings" value={feedback.total_ratings} color="blue" />
              <StatCard
                label="Thumbs Up"
                value={feedback.positive}
                sub={`${feedback.recent_7d_positive} this week`}
                color="green"
              />
              <StatCard
                label="Thumbs Down"
                value={feedback.negative}
                sub={`${feedback.recent_7d_negative} this week`}
                color="red"
              />
            </div>
            <div className="mt-4 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
              <SatisfactionBar rate={feedback.satisfaction_rate} />
            </div>

            {/* Negative feedback reason breakdown */}
            {feedback.reason_breakdown && Object.keys(feedback.reason_breakdown).length > 0 && (
              <div className="mt-4 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
                  Thumbs-Down Reasons
                </p>
                <div className="space-y-2">
                  {Object.entries(feedback.reason_breakdown)
                    .sort(([, a], [, b]) => b - a)
                    .map(([reason, count]) => {
                      const total = Object.values(feedback.reason_breakdown!).reduce((s, v) => s + v, 0);
                      const pct = total > 0 ? Math.round((count / total) * 100) : 0;
                      const labels: Record<string, string> = {
                        outdated_information: 'Outdated information',
                        wrong_answer: 'Wrong answer',
                        incomplete_answer: 'Incomplete answer',
                        not_relevant: 'Not relevant',
                        other: 'Other',
                        unspecified: 'No reason given',
                      };
                      return (
                        <div key={reason} className="flex items-center gap-3">
                          <span className="text-xs text-gray-600 dark:text-gray-400 w-36 truncate">
                            {labels[reason] || reason}
                          </span>
                          <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded-full h-2 overflow-hidden">
                            <div
                              className="bg-red-400 dark:bg-red-500 h-2 rounded-full transition-all duration-500"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 w-14 text-right">
                            {count} ({pct}%)
                          </span>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}
          </section>
        )}

        {/* System Health */}
        {adminStats && (
          <section className="mb-8">
            <SectionHeader title="System Health" color="green" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" /></svg>
            } />
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {Object.entries(adminStats.system.components).map(([name, status]) => (
                <div key={name} className={`rounded-xl border p-4 overflow-hidden relative ${status === 'ok' ? 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700' : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700'}`}>
                  <div className={`absolute top-0 left-0 right-0 h-1 ${status === 'ok' ? 'bg-emerald-500' : 'bg-red-500'}`} />
                  <div className="flex items-center gap-2">
                    <div className={`w-2.5 h-2.5 rounded-full ${status === 'ok' ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-red-500 shadow-sm shadow-red-500/50'} animate-pulse`} />
                    <p className="text-sm font-medium text-gray-900 dark:text-white capitalize">{name.replace(/_/g, ' ')}</p>
                  </div>
                  <p className={`text-xs mt-1.5 font-medium ${status === 'ok' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                    {status === 'ok' ? '● Operational' : `● ${status}`}
                  </p>
                </div>
              ))}
              <StatCard label="Database" value={adminStats.system.database_type.toUpperCase()} color="purple" />
            </div>
          </section>
        )}

        {/* Indexed Sources */}
        {adminStats && (
          <section className="mb-8">
            <SectionHeader title="Indexed Sources" color="purple" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" /></svg>
            } />
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <StatCard label="Total Chunks" value={adminStats.vector_store.total_chunks.toLocaleString()} color="blue" />
              <StatCard label="Indexed Spaces" value={adminStats.vector_store.space_count} color="purple" />
            </div>
            <div className="mt-3 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50">
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Space Key</th>
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Space Name</th>
                  </tr>
                </thead>
                <tbody>
                  {adminStats.vector_store.indexed_spaces.map((s) => (
                    <tr key={s.space_key} className="border-t border-gray-100 dark:border-gray-700 hover:bg-blue-50/50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2 font-mono text-xs text-gray-600 dark:text-gray-300">{s.space_key}</td>
                      <td className="px-4 py-2 text-gray-900 dark:text-white">{s.space_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Last Ingestion */}
        {adminStats && (
          <section className="mb-8">
            <SectionHeader title="Ingestion Status" color="amber" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
            } />
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <StatCard
                label="Status"
                value={adminStats.ingestion.running ? 'Running' : (adminStats.ingestion.end_time ? 'Completed' : 'Idle')}
                color={adminStats.ingestion.running ? 'amber' : 'green'}
              />
              {adminStats.ingestion.last_result && (
                <>
                  <StatCard label="Pages Processed" value={adminStats.ingestion.last_result.pages_processed} color="blue" />
                  <StatCard label="Pages Skipped" value={adminStats.ingestion.last_result.pages_skipped} color="purple" />
                  <StatCard label="Chunks Indexed" value={adminStats.ingestion.last_result.chunks_indexed} color="blue" />
                  <StatCard
                    label="Errors"
                    value={adminStats.ingestion.last_result.errors.length}
                    color={adminStats.ingestion.last_result.errors.length > 0 ? 'red' : 'green'}
                  />
                </>
              )}
              {adminStats.ingestion.end_time && (
                <StatCard
                  label="Last Run"
                  value={new Date(adminStats.ingestion.end_time).toLocaleDateString()}
                  sub={new Date(adminStats.ingestion.end_time).toLocaleTimeString()}
                  color="blue"
                />
              )}
            </div>
            {adminStats.ingestion.running && adminStats.ingestion.percent > 0 && (
              <div className="mt-3 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
                  <span>{adminStats.ingestion.source}: {adminStats.ingestion.current_page}/{adminStats.ingestion.total_pages} pages</span>
                  <span>{adminStats.ingestion.percent}%</span>
                </div>
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
                  <div className="bg-confluence-blue h-2.5 rounded-full transition-all" style={{ width: `${adminStats.ingestion.percent}%` }} />
                </div>
              </div>
            )}
          </section>
        )}

        {/* Users */}
        {adminStats && adminStats.users.total > 0 && (
          <section className="mb-8">
            <SectionHeader title={`Registered Users (${adminStats.users.total})`} color="indigo" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" /></svg>
            } />
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50">
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Name</th>
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Email</th>
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Role</th>
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {adminStats.users.list.map((u) => (
                    <tr key={u.id} className="border-t border-gray-100 dark:border-gray-700 hover:bg-blue-50/50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2 text-gray-900 dark:text-white">{u.name}</td>
                      <td className="px-4 py-2 text-gray-600 dark:text-gray-300 text-xs">{u.email}</td>
                      <td className="px-4 py-2">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${u.role === 'admin' ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'}`}>
                          {u.role}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-gray-500 dark:text-gray-400 text-xs">{u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Top Questions */}
        {adminStats && (adminStats.analytics?.top_questions?.length ?? 0) > 0 && (
          <section className="mb-8">
            <SectionHeader title="Top Questions" color="blue" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            } />
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50">
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">#</th>
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Question</th>
                    <th className="text-right px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {adminStats.analytics!.top_questions.map((q, i) => (
                    <tr key={i} className="border-t border-gray-100 dark:border-gray-700 hover:bg-blue-50/50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2 text-gray-400 text-xs">{i + 1}</td>
                      <td className="px-4 py-2 text-gray-900 dark:text-white">{q.question}</td>
                      <td className="px-4 py-2 text-right font-mono text-gray-600 dark:text-gray-300">{q.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Unanswered Questions (Content Gaps) */}
        {adminStats && (adminStats.analytics?.unanswered_questions?.length ?? 0) > 0 && (
          <section className="mb-8">
            <SectionHeader title="Unanswered Questions (Content Gaps)" color="red" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
            } />
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50">
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Question</th>
                    <th className="text-right px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Times Asked</th>
                  </tr>
                </thead>
                <tbody>
                  {adminStats.analytics!.unanswered_questions.map((q, i) => (
                    <tr key={i} className="border-t border-gray-100 dark:border-gray-700 hover:bg-blue-50/50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2 text-gray-900 dark:text-white">{q.question}</td>
                      <td className="px-4 py-2 text-right font-mono text-red-600 dark:text-red-400">{q.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Usage Trend + Peak Hours — side by side on desktop */}
        {adminStats && ((adminStats.analytics?.usage_trend?.length ?? 0) > 0 || (adminStats.analytics?.peak_hours?.length ?? 0) > 0) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            {/* Usage Trend (7-day) */}
            {(adminStats.analytics?.usage_trend?.length ?? 0) > 0 && (
              <section>
                <SectionHeader title="Usage Trend (Last 7 Days)" color="blue" icon={
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" /></svg>
                } />
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                  <div className="flex items-end gap-1 h-32">
                    {(() => {
                      const trend = adminStats.analytics!.usage_trend;
                      const maxCount = Math.max(...trend.map(d => d.count), 1);
                      return trend.map((d, i) => {
                        const pctHeight = (d.count / maxCount) * 100;
                        return (
                          <div key={i} className="flex-1 flex flex-col items-center gap-1 group cursor-default">
                            <span className="text-xs text-gray-500 dark:text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">{d.count}</span>
                            <div
                              className="w-full bg-gradient-to-t from-confluence-blue to-blue-400 dark:from-blue-600 dark:to-blue-400 hover:from-blue-600 hover:to-blue-300 rounded-t min-h-[4px] transition-all duration-200 shadow-sm"
                              style={{ height: `${pctHeight}%` }}
                              aria-label={`${d.date}: ${d.count} queries`}
                            />
                            <span className="text-xs text-gray-400 dark:text-gray-500 truncate w-full text-center">
                              {d.date.slice(5)}
                            </span>
                          </div>
                        );
                      });
                    })()}
                  </div>
                </div>
              </section>
            )}

            {/* Peak Usage Hours */}
            {(adminStats.analytics?.peak_hours?.length ?? 0) > 0 && (
              <section>
                <SectionHeader title="Peak Usage Hours (UTC)" color="amber" icon={
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                } />
                <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
                  <div className="flex items-end gap-0.5 h-32">
                    {(() => {
                      const hours = adminStats.analytics!.peak_hours;
                      const hourMap = new Map(hours.map(h => [h.hour, h.count]));
                      const maxCount = Math.max(...hours.map(h => h.count), 1);
                      return Array.from({ length: 24 }, (_, h) => {
                        const count = hourMap.get(h) || 0;
                        return (
                          <div key={h} className="flex-1 flex flex-col items-center gap-0.5 group cursor-default"
                               aria-label={`${h}:00 — ${count} queries`}>
                            <span className="text-xs text-gray-500 dark:text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">
                              {count > 0 ? count : ''}
                            </span>
                            <div
                              className={`w-full rounded-t min-h-[2px] transition-all duration-200 ${count > 0 ? 'bg-gradient-to-t from-amber-500 to-orange-400 dark:from-amber-600 dark:to-amber-400 hover:from-amber-600 hover:to-orange-300 shadow-sm' : 'bg-gray-200 dark:bg-gray-700'}`}
                              style={{ height: count > 0 ? `${(count / maxCount) * 100}%` : '2px' }}
                            />
                            {h % 4 === 0 && (
                              <span className="text-xs text-gray-400 dark:text-gray-500">{h}</span>
                            )}
                          </div>
                        );
                      });
                    })()}
                  </div>
                </div>
              </section>
            )}
          </div>
        )}

        {/* Response Time + Cache — side by side on desktop */}
        {adminStats && (
          (adminStats.analytics?.response_time?.avg_ms ?? 0) > 0 || (adminStats.cache?.total_lookups ?? 0) > 0
        ) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            {/* Response Time */}
            {adminStats.analytics?.response_time && adminStats.analytics.response_time.avg_ms > 0 && (
              <section>
                <SectionHeader title="Response Time" color="cyan" icon={
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                } />
                <div className="grid grid-cols-3 gap-3">
                  <StatCard
                    label="Average"
                    value={adminStats.analytics.response_time.avg_ms > 1000
                      ? `${(adminStats.analytics.response_time.avg_ms / 1000).toFixed(1)}s`
                      : `${adminStats.analytics.response_time.avg_ms}ms`}
                    color={adminStats.analytics.response_time.avg_ms < 3000 ? 'green' : 'amber'}
                  />
                  <StatCard
                    label="Fastest"
                    value={adminStats.analytics.response_time.min_ms > 1000
                      ? `${(adminStats.analytics.response_time.min_ms / 1000).toFixed(1)}s`
                      : `${adminStats.analytics.response_time.min_ms}ms`}
                    color="green"
                  />
                  <StatCard
                    label="Slowest"
                    value={adminStats.analytics.response_time.max_ms > 1000
                      ? `${(adminStats.analytics.response_time.max_ms / 1000).toFixed(1)}s`
                      : `${adminStats.analytics.response_time.max_ms}ms`}
                    color={adminStats.analytics.response_time.max_ms > 10000 ? 'red' : 'amber'}
                  />
                </div>
              </section>
            )}

            {/* Cache Hit Rate */}
            {adminStats.cache && adminStats.cache.total_lookups > 0 && (
              <section>
                <SectionHeader title="Semantic Cache" color="purple" icon={
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" /></svg>
                } />
                <div className="grid grid-cols-2 gap-3">
                  <StatCard label="Total Lookups" value={adminStats.cache.total_lookups} color="blue" />
                  <StatCard label="Hits" value={adminStats.cache.hits} color="green" />
                  <StatCard label="Misses" value={adminStats.cache.misses} color="amber" />
                  <StatCard
                    label="Hit Rate"
                    value={`${Math.round(adminStats.cache.hit_rate * 100)}%`}
                    color={adminStats.cache.hit_rate >= 0.3 ? 'green' : 'amber'}
                  />
                </div>
              </section>
            )}
          </div>
        )}

        {/* Space Usage Breakdown */}
        {adminStats && (adminStats.analytics?.space_usage?.length ?? 0) > 0 && (
          <section className="mb-8">
            <SectionHeader title="Space Usage Breakdown" color="indigo" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>
            } />
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50">
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Space(s)</th>
                    <th className="text-right px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Queries</th>
                  </tr>
                </thead>
                <tbody>
                  {adminStats.analytics!.space_usage.map((s, i) => (
                    <tr key={i} className="border-t border-gray-100 dark:border-gray-700 hover:bg-blue-50/50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2 font-mono text-xs text-gray-600 dark:text-gray-300">{s.space_keys}</td>
                      <td className="px-4 py-2 text-right font-mono text-gray-900 dark:text-white">{s.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Per-User Usage */}
        {adminStats && (adminStats.analytics?.per_user_usage?.length ?? 0) > 0 && (
          <section className="mb-8">
            <SectionHeader title={`Top Users ${(adminStats.analytics!.active_users_24h ?? 0) > 0 ? `(${adminStats.analytics!.active_users_24h} active in 24h)` : ''}`} color="indigo" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>
            } />
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50">
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">User</th>
                    <th className="text-right px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Queries</th>
                  </tr>
                </thead>
                <tbody>
                  {adminStats.analytics!.per_user_usage.map((u, i) => (
                    <tr key={i} className="border-t border-gray-100 dark:border-gray-700 hover:bg-blue-50/50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2 text-gray-900 dark:text-white text-xs">{u.user_id}</td>
                      <td className="px-4 py-2 text-right font-mono text-gray-600 dark:text-gray-300">{u.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Recent Activity Feed */}
        {adminStats && (adminStats.analytics?.recent_activity?.length ?? 0) > 0 && (
          <section className="mb-8">
            <SectionHeader title="Recent Activity" color="cyan" icon={
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            } />
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50">
                    <th className="text-left px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Question</th>
                    <th className="text-center px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</th>
                    <th className="text-right px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Sources</th>
                    <th className="text-right px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Time</th>
                    <th className="text-right px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">When</th>
                  </tr>
                </thead>
                <tbody>
                  {adminStats.analytics!.recent_activity.map((a, i) => (
                    <tr key={i} className="border-t border-gray-100 dark:border-gray-700 hover:bg-blue-50/50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2 text-gray-900 dark:text-white text-xs max-w-[200px] truncate" title={a.question}>{a.question}</td>
                      <td className="px-4 py-2 text-center">
                        <span className={`inline-block w-2 h-2 rounded-full ${a.answered ? 'bg-green-500' : 'bg-red-500'}`} title={a.answered ? 'Answered' : 'No answer'} />
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-xs text-gray-600 dark:text-gray-300">{a.sources_found}</td>
                      <td className="px-4 py-2 text-right font-mono text-xs text-gray-500 dark:text-gray-400">
                        {a.response_ms != null ? (a.response_ms > 1000 ? `${(a.response_ms / 1000).toFixed(1)}s` : `${a.response_ms}ms`) : '—'}
                      </td>
                      <td className="px-4 py-2 text-right text-xs text-gray-400 dark:text-gray-500">{new Date(a.created_at).toLocaleTimeString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {!feedback && !metrics && !adminStats && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            <svg className="w-12 h-12 mx-auto mb-3 text-gray-300 dark:text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <p className="font-medium">No analytics data available yet.</p>
            <p className="text-sm mt-1">Start chatting and providing feedback to see metrics here.</p>
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
