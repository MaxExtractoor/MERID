import { useState, useEffect, useCallback } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Cell } from 'recharts';
import { Trophy, Star, Shield, Zap, Target, Award, TrendingUp, Users, RefreshCw, ChevronRight, Dices } from 'lucide-react';
import { API_ENDPOINTS, DEFAULTS, CHART_COLORS} from '../config/constants';

// ── Types ───────────────────────────────────────────────────────

interface LeaderboardEntry {
  user: string;
  xp: number;
}

interface QuestInfo {
  id: string;
  title: string;
  description: string;
  season: number;
  points: number;
  requirements: Record<string, string>;
}

interface RewardPool {
  base_emission: number;
  multiplier: number;
  current_emission: number;
  participation_rate: number;
}

interface SecuritySummary {
  quests: number;
  bug_reports: number;
  seasons: number;
  users: number;
}

interface X402Summary {
  available: boolean;
  total_payments?: number;
  total_amount_sats?: number;
  receipts_count?: number;
  resources_discovered?: number;
}

interface BettingMetrics {
  total_bets: number;
  wins: number;
  losses: number;
  win_rate: number;
  total_staked_usd: number;
  total_pnl_usd: number;
  roi: number;
  active_events: number;
  live_events: number;
  plans: { proposed: number; approved: number; executing: number; placed: number; settled: number };
}

interface RewardsSummary {
  gamification: {
    leaderboard: LeaderboardEntry[];
    total_users: number;
    total_events: number;
  };
  quests: {
    registered: number;
    quests: { id: string; title: string; season: number; points: number }[];
    progress_entries: number;
  };
  reward_pools: Record<string, RewardPool>;
  x402: X402Summary;
  security?: SecuritySummary;
}

// ── Helpers ─────────────────────────────────────────────────────

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function poolColor(pid: string): string {
  const map: Record<string, string> = {
    trading: 'from-green-500/20 to-green-600/10 border-green-500/30',
    security: 'from-red-500/20 to-red-600/10 border-red-500/30',
    governance: 'from-purple-500/20 to-purple-600/10 border-purple-500/30',
  };
  return map[pid] ?? 'from-slate-500/20 to-slate-600/10 border-slate-500/30';
}

function poolIcon(pid: string) {
  const map: Record<string, typeof TrendingUp> = {
    trading: TrendingUp,
    security: Shield,
    governance: Users,
  };
  return map[pid] ?? Star;
}

// ── Component ───────────────────────────────────────────────────

type Tab = 'overview' | 'quests' | 'leaderboard' | 'pools' | 'betting' | 'security';

export default function Rewards() {
  const [summary, setSummary] = useState<RewardsSummary | null>(null);
  const [quests, setQuests] = useState<QuestInfo[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [bettingMetrics, setBettingMetrics] = useState<BettingMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('overview');

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [sumRes, questRes, lbRes] = await Promise.all([
        fetch(API_ENDPOINTS.REWARDS_SUMMARY),
        fetch(`${API_ENDPOINTS.REWARDS_QUESTS}?season=1`),
        fetch(`${API_ENDPOINTS.REWARDS_LEADERBOARD}?limit=20`),
      ]);

      if (sumRes.ok) setSummary(await sumRes.json());
      if (questRes.ok) {
        const qd = await questRes.json();
        setQuests(qd.quests ?? []);
      }
      if (lbRes.ok) {
        const ld = await lbRes.json();
        setLeaderboard(ld.items ?? []);
      }

      try {
        const betRes = await fetch(API_ENDPOINTS.BETTING_CONSENSUS_METRICS);
        if (betRes.ok) setBettingMetrics(await betRes.json());
      } catch { /* betting metrics optional */ }
    } catch (e: unknown) {
      setError(e.message ?? 'Failed to load rewards data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, DEFAULTS.POLLING_INTERVALS.BACKGROUND);
    return () => clearInterval(interval);
  }, [fetchData]);

  // ── Tab bar ─────────────────────────────────────────────────

  const tabs: { key: Tab; label: string; icon: typeof Trophy }[] = [
    { key: 'overview', label: 'Overview', icon: Trophy },
    { key: 'quests', label: 'Quests', icon: Target },
    { key: 'leaderboard', label: 'Leaderboard', icon: Award },
    { key: 'pools', label: 'Reward Pools', icon: Zap },
    { key: 'betting', label: 'Sports Betting', icon: Dices },
    { key: 'security', label: 'Security', icon: Shield },
  ];

  // ── Render ──────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading rewards…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-6 text-red-300">
        <p className="font-semibold">Error loading rewards</p>
        <p className="text-sm mt-1 text-red-400">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Trophy className="w-7 h-7 text-yellow-400" />
            Rewards & Gamification
          </h1>
          <p className="text-sm text-slate-400 mt-1">XP, quests, reward pools, x402 payments, and security bounties</p>
        </div>
        <button type="button"
          onClick={() => { setLoading(true); fetchData(); }}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-slate-300 transition-colors"
        >
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-slate-800/50 rounded-lg p-1">
        {tabs.map(t => {
          const Icon = t.icon;
          const active = activeTab === t.key;
          return (
            <button type="button"
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                active
                  ? 'bg-slate-700 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/50'
              }`}
            >
              <Icon className="w-4 h-4" /> {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {activeTab === 'overview' && <OverviewTab summary={summary} />}
      {activeTab === 'quests' && <QuestsTab quests={quests} />}
      {activeTab === 'leaderboard' && <LeaderboardTab entries={leaderboard} />}
      {activeTab === 'pools' && <PoolsTab pools={summary?.reward_pools ?? {}} />}
      {activeTab === 'betting' && <BettingRewardsTab metrics={bettingMetrics} />}
      {activeTab === 'security' && <SecurityTab security={summary?.security ?? null} />}
    </div>
  );
}

// ── Overview Tab ────────────────────────────────────────────────

function OverviewTab({ summary }: { summary: RewardsSummary | null }) {
  if (!summary) return null;
  const g = summary.gamification;
  const q = summary.quests;
  const x = summary.x402;
  const s = summary.security;

  const stats = [
    { label: 'Total Users', value: formatNumber(g.total_users), icon: Users, color: 'text-blue-400' },
    { label: 'XP Events', value: formatNumber(g.total_events), icon: Star, color: 'text-yellow-400' },
    { label: 'Active Quests', value: q.registered.toString(), icon: Target, color: 'text-green-400' },
    { label: 'Quest Progress', value: q.progress_entries.toString(), icon: ChevronRight, color: 'text-purple-400' },
    { label: 'Reward Pools', value: Object.keys(summary.reward_pools).length.toString(), icon: Zap, color: 'text-orange-400' },
    { label: 'x402 Active', value: x.available ? 'Yes' : 'No', icon: TrendingUp, color: x.available ? 'text-emerald-400' : 'text-slate-500' },
  ];

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {stats.map(s => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <Icon className={`w-4 h-4 ${s.color}`} />
                <span className="text-xs text-slate-400">{s.label}</span>
              </div>
              <p className="text-xl font-bold text-white">{s.value}</p>
            </div>
          );
        })}
      </div>

      {/* Reward Pool Emission Chart */}
      {Object.keys(summary.reward_pools).length > 0 && (() => {
        const POOL_COLORS: Record<string, string> = {
          trading: CHART_COLORS.GREEN, security: CHART_COLORS.RED, governance: CHART_COLORS.PURPLE,
        };
        const poolData = Object.entries(summary.reward_pools).map(([pid, pool]) => ({
          name: pid.charAt(0).toUpperCase() + pid.slice(1),
          emission: pool.current_emission,
          base: pool.base_emission,
          fill: POOL_COLORS[pid] ?? CHART_COLORS.GRAY_500,
        }));
        return (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
              <Zap className="w-4 h-4 text-orange-400" /> Pool Emission Rates (tokens/day)
            </h3>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={poolData} layout="vertical" margin={{ left: 10, right: 20 }}>
                <XAxis type="number" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 12 }} width={90} />
                <RechartsTooltip
                  contentStyle={{ backgroundColor: CHART_COLORS.TOOLTIP_BG, border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: CHART_COLORS.AXIS_TICK }}
                  formatter={(value: number, name: string) => [
                    `${value.toFixed(0)} tokens/day`,
                    name === 'emission' ? 'Current' : 'Base',
                  ]}
                />
                <Bar dataKey="base" fill={CHART_COLORS.SLATE_500} radius={[0, 4, 4, 0]} barSize={14} name="Base" />
                <Bar dataKey="emission" radius={[0, 4, 4, 0]} barSize={14} name="Current">
                  {poolData.map((entry, idx) => (
                    <Cell key={idx} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        );
      })()}

      {/* XP Distribution (top 5 bar) */}
      {g.leaderboard.length > 0 && (() => {
        const xpData = g.leaderboard.slice(0, 8).map((e, i) => ({
          name: e.user.length > 12 ? e.user.slice(0, 12) + '…' : e.user,
          xp: e.xp,
          fill: i === 0 ? CHART_COLORS.YELLOW : i === 1 ? CHART_COLORS.AXIS_TICK : i === 2 ? CHART_COLORS.AMBER : CHART_COLORS.SLATE_400,
        }));
        return (
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
              <Award className="w-4 h-4 text-yellow-400" /> XP Distribution (Top 8)
            </h3>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={xpData} margin={{ left: 0, right: 10 }}>
                <XAxis dataKey="name" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 10 }} interval={0} angle={-20} textAnchor="end" height={50} />
                <YAxis tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 11 }} />
                <RechartsTooltip
                  contentStyle={{ backgroundColor: CHART_COLORS.TOOLTIP_BG, border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: CHART_COLORS.AXIS_TICK }}
                  formatter={(value: number) => [`${formatNumber(value)} XP`, 'XP']}
                />
                <Bar dataKey="xp" radius={[4, 4, 0, 0]} barSize={28}>
                  {xpData.map((entry, idx) => (
                    <Cell key={idx} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        );
      })()}

      {/* Top 5 leaderboard preview */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <Award className="w-4 h-4 text-yellow-400" /> Top 5 XP Leaders
          </h3>
          <div className="space-y-2">
            {g.leaderboard.slice(0, 5).map((entry, i) => (
              <div key={entry.user} className="flex items-center justify-between py-1.5 px-3 rounded-lg bg-slate-700/30">
                <div className="flex items-center gap-3">
                  <span className={`text-sm font-bold w-5 text-center ${i === 0 ? 'text-yellow-400' : i === 1 ? 'text-slate-300' : i === 2 ? 'text-amber-600' : 'text-slate-500'}`}>
                    {i + 1}
                  </span>
                  <span className="text-sm text-white font-medium truncate max-w-[180px]">{entry.user}</span>
                </div>
                <span className="text-sm font-semibold text-yellow-400">{formatNumber(entry.xp)} XP</span>
              </div>
            ))}
            {g.leaderboard.length === 0 && (
              <p className="text-sm text-slate-500 text-center py-4">No XP awarded yet</p>
            )}
          </div>
        </div>

        {/* Security summary */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <Shield className="w-4 h-4 text-red-400" /> Security Bounty Program
          </h3>
          {s ? (
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'Security Quests', value: s.quests, color: 'text-blue-400' },
                { label: 'Bug Reports', value: s.bug_reports, color: 'text-red-400' },
                { label: 'Active Seasons', value: s.seasons, color: 'text-green-400' },
                { label: 'Participants', value: s.users, color: 'text-purple-400' },
              ].map(item => (
                <div key={item.label} className="bg-slate-700/30 rounded-lg p-3">
                  <p className="text-xs text-slate-400">{item.label}</p>
                  <p className={`text-lg font-bold ${item.color}`}>{item.value}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-slate-500 text-center py-4">Security system not initialized</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Quests Tab ──────────────────────────────────────────────────

function QuestsTab({ quests }: { quests: QuestInfo[] }) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-white">Season 1 Quests</h2>
      {quests.length === 0 ? (
        <p className="text-slate-400 text-sm">No quests registered for this season.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {quests.map(q => (
            <div key={q.id} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 hover:border-blue-500/30 transition-colors">
              <div className="flex items-start justify-between mb-2">
                <h3 className="text-sm font-semibold text-white">{q.title}</h3>
                <span className="text-xs font-bold text-yellow-400 bg-yellow-400/10 px-2 py-0.5 rounded-full">
                  {q.points} pts
                </span>
              </div>
              <p className="text-xs text-slate-400 mb-3">{q.description}</p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(q.requirements).map(([k, v]) => (
                  <span key={k} className="text-[10px] bg-slate-700/50 text-slate-300 px-2 py-0.5 rounded">
                    {k}: {v}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Leaderboard Tab ─────────────────────────────────────────────

function LeaderboardTab({ entries }: { entries: LeaderboardEntry[] }) {
  const maxXp = entries.length > 0 ? entries[0].xp : 1;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-white">XP Leaderboard</h2>
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left text-xs text-slate-400 font-medium px-4 py-3 w-12">Rank</th>
              <th className="text-left text-xs text-slate-400 font-medium px-4 py-3">User / Agent</th>
              <th className="text-right text-xs text-slate-400 font-medium px-4 py-3 w-24">XP</th>
              <th className="text-left text-xs text-slate-400 font-medium px-4 py-3 w-48">Progress</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, i) => (
              <tr key={entry.user} className="border-b border-slate-700/20 hover:bg-slate-700/20 transition-colors">
                <td className="px-4 py-3">
                  <span className={`text-sm font-bold ${i === 0 ? 'text-yellow-400' : i === 1 ? 'text-slate-300' : i === 2 ? 'text-amber-600' : 'text-slate-500'}`}>
                    #{i + 1}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="text-sm text-white font-medium">{entry.user}</span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="text-sm font-semibold text-yellow-400">{formatNumber(entry.xp)}</span>
                </td>
                <td className="px-4 py-3">
                  <div className="w-full bg-slate-700/50 rounded-full h-2">
                    <div
                      className="bg-gradient-to-r from-blue-500 to-purple-500 h-2 rounded-full transition-all"
                      style={{ width: `${Math.max(5, (entry.xp / maxXp) * 100)}%` }}
                    />
                  </div>
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td colSpan={4} className="text-center text-slate-500 py-8 text-sm">
                  No leaderboard entries yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Pools Tab ───────────────────────────────────────────────────

function PoolsTab({ pools }: { pools: Record<string, RewardPool> }) {
  const entries = Object.entries(pools);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-white">Reward Pools</h2>
      {entries.length === 0 ? (
        <p className="text-slate-400 text-sm">No reward pools configured.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {entries.map(([pid, pool]) => {
            const Icon = poolIcon(pid);
            return (
              <div key={pid} className={`bg-gradient-to-br ${poolColor(pid)} border rounded-xl p-5`}>
                <div className="flex items-center gap-2 mb-4">
                  <Icon className="w-5 h-5 text-white" />
                  <h3 className="text-sm font-semibold text-white capitalize">{pid} Pool</h3>
                </div>
                <div className="space-y-3">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">Base Emission</span>
                    <span className="text-white font-medium">{pool.base_emission.toFixed(0)}/day</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">Multiplier</span>
                    <span className="text-white font-medium">{pool.multiplier.toFixed(2)}x</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">Current Emission</span>
                    <span className="text-emerald-400 font-semibold">{pool.current_emission.toFixed(0)}/day</span>
                  </div>
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-slate-400">Participation</span>
                      <span className="text-white">{(pool.participation_rate * 100).toFixed(1)}%</span>
                    </div>
                    <div className="w-full bg-slate-700/50 rounded-full h-1.5">
                      <div
                        className="bg-white/60 h-1.5 rounded-full transition-all"
                        style={{ width: `${Math.min(100, pool.participation_rate * 100)}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Betting Rewards Tab ─────────────────────────────────────────

function BettingRewardsTab({ metrics }: { metrics: BettingMetrics | null }) {
  if (!metrics) {
    return (
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-8 text-center">
        <Dices className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400">Sports betting metrics not available</p>
        <p className="text-xs text-slate-500 mt-1">Betting consensus system may not be initialized</p>
      </div>
    );
  }

  const pnlColor = metrics.total_pnl_usd >= 0 ? 'text-emerald-400' : 'text-red-400';
  const roiColor = metrics.roi >= 0 ? 'text-emerald-400' : 'text-red-400';

  const stats = [
    { label: 'Total Bets', value: metrics.total_bets.toString(), icon: Dices, color: 'text-blue-400' },
    { label: 'Win Rate', value: `${(metrics.win_rate * 100).toFixed(1)}%`, icon: Target, color: metrics.win_rate >= 0.5 ? 'text-emerald-400' : 'text-amber-400' },
    { label: 'Total PnL', value: `$${metrics.total_pnl_usd.toFixed(0)}`, icon: TrendingUp, color: pnlColor },
    { label: 'ROI', value: `${(metrics.roi * 100).toFixed(1)}%`, icon: Award, color: roiColor },
    { label: 'Active Events', value: metrics.active_events.toString(), icon: Star, color: 'text-purple-400' },
    { label: 'Live Events', value: metrics.live_events.toString(), icon: Zap, color: metrics.live_events > 0 ? 'text-orange-400' : 'text-slate-500' },
  ];

  const planData = [
    { label: 'Proposed', count: metrics.plans.proposed, color: 'bg-slate-500' },
    { label: 'Approved', count: metrics.plans.approved, color: 'bg-blue-500' },
    { label: 'Executing', count: metrics.plans.executing, color: 'bg-amber-500' },
    { label: 'Placed', count: metrics.plans.placed, color: 'bg-emerald-500' },
    { label: 'Settled', count: metrics.plans.settled, color: 'bg-purple-500' },
  ];
  const totalPlans = planData.reduce((s, p) => s + p.count, 0);

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-white flex items-center gap-2">
        <Dices className="w-5 h-5 text-blue-400" /> Sports Betting Performance
      </h2>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {stats.map(s => {
          const Icon = s.icon;
          return (
            <div key={s.label} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <Icon className={`w-4 h-4 ${s.color}`} />
                <span className="text-xs text-slate-400">{s.label}</span>
              </div>
              <p className={`text-xl font-bold ${s.color}`}>{s.value}</p>
            </div>
          );
        })}
      </div>

      {/* Win/Loss breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
            <Target className="w-4 h-4 text-emerald-400" /> Win / Loss Breakdown
          </h3>
          <div className="flex items-center gap-4 mb-3">
            <div className="flex-1">
              <div className="flex justify-between text-xs mb-1">
                <span className="text-emerald-400">Wins: {metrics.wins}</span>
                <span className="text-red-400">Losses: {metrics.losses}</span>
              </div>
              <div className="w-full bg-slate-700/50 rounded-full h-3 flex overflow-hidden">
                {metrics.total_bets > 0 && (
                  <>
                    <div className="bg-emerald-500 h-3 transition-all" style={{ width: `${(metrics.wins / metrics.total_bets) * 100}%` }} />
                    <div className="bg-red-500 h-3 transition-all" style={{ width: `${(metrics.losses / metrics.total_bets) * 100}%` }} />
                  </>
                )}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 mt-4">
            <div className="bg-slate-700/30 rounded-lg p-3">
              <p className="text-xs text-slate-400">Total Staked</p>
              <p className="text-lg font-bold text-white">${metrics.total_staked_usd.toFixed(0)}</p>
            </div>
            <div className="bg-slate-700/30 rounded-lg p-3">
              <p className="text-xs text-slate-400">Net PnL</p>
              <p className={`text-lg font-bold ${pnlColor}`}>
                {metrics.total_pnl_usd >= 0 ? '+' : ''}${metrics.total_pnl_usd.toFixed(0)}
              </p>
            </div>
          </div>
        </div>

        {/* Plan pipeline */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
            <ChevronRight className="w-4 h-4 text-blue-400" /> Betting Plan Pipeline
          </h3>
          <div className="space-y-3">
            {planData.map(p => (
              <div key={p.label} className="flex items-center gap-3">
                <span className="text-xs text-slate-400 w-20">{p.label}</span>
                <div className="flex-1 bg-slate-700/50 rounded-full h-2">
                  <div
                    className={`${p.color} h-2 rounded-full transition-all`}
                    style={{ width: totalPlans > 0 ? `${Math.max(4, (p.count / totalPlans) * 100)}%` : '0%' }}
                  />
                </div>
                <span className="text-xs text-white font-medium w-8 text-right">{p.count}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-slate-700/50 flex justify-between text-xs">
            <span className="text-slate-400">Total Plans</span>
            <span className="text-white font-semibold">{totalPlans}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Security Tab ────────────────────────────────────────────────

function SecurityTab({ security }: { security: SecuritySummary | null }) {
  if (!security) {
    return (
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-8 text-center">
        <Shield className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400">Security gamification system not initialized</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold text-white">Security Bounty Program</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Security Quests', value: security.quests, icon: Target, color: 'text-blue-400', bg: 'from-blue-500/20 to-blue-600/10 border-blue-500/30' },
          { label: 'Bug Reports', value: security.bug_reports, icon: Shield, color: 'text-red-400', bg: 'from-red-500/20 to-red-600/10 border-red-500/30' },
          { label: 'Active Seasons', value: security.seasons, icon: Trophy, color: 'text-green-400', bg: 'from-green-500/20 to-green-600/10 border-green-500/30' },
          { label: 'Participants', value: security.users, icon: Users, color: 'text-purple-400', bg: 'from-purple-500/20 to-purple-600/10 border-purple-500/30' },
        ].map(item => {
          const Icon = item.icon;
          return (
            <div key={item.label} className={`bg-gradient-to-br ${item.bg} border rounded-xl p-5`}>
              <Icon className={`w-6 h-6 ${item.color} mb-2`} />
              <p className="text-xs text-slate-400">{item.label}</p>
              <p className={`text-2xl font-bold ${item.color}`}>{item.value}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
