import { useState } from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import ErrorBar from './ErrorBar';
import { TrendingUp, ChevronUp, Zap, Target, Trophy, DollarSign } from '../ui/icons';

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
    ...(headers ?? {}),
  };
}

interface LadderTier {
  level: number;
  name: string;
  seed_usd: number;
  profit_target_pct: number;
  max_drawdown_pct: number;
  min_trades: number;
  min_win_rate_pct: number;
  description: string;
}

interface NextGoal {
  status: string;
  message?: string;
  remaining?: string[];
  next_tier?: string;
  next_seed_usd?: number;
}

interface PortfolioProgress {
  portfolio_id: string;
  current_tier: number;
  seed_balance: number;
  current_equity: number;
  high_water_mark: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_pct: number;
  roi_pct: number;
  drawdown_pct: number;
  tier_name: string;
  next_goal: NextGoal;
}

interface LadderStatus {
  tiers: LadderTier[];
  portfolios: Record<string, PortfolioProgress>;
  total_portfolios: number;
}

const TIER_COLORS: Record<number, { bg: string; border: string; text: string }> = {
  0: { bg: 'bg-slate-800/60', border: 'border-slate-600/40', text: 'text-slate-300' },
  1: { bg: 'bg-green-900/30', border: 'border-green-600/40', text: 'text-green-400' },
  2: { bg: 'bg-blue-900/30', border: 'border-blue-600/40', text: 'text-blue-400' },
  3: { bg: 'bg-purple-900/30', border: 'border-purple-600/40', text: 'text-purple-400' },
  4: { bg: 'bg-amber-900/30', border: 'border-amber-500/40', text: 'text-amber-400' },
};

function TierBadge({ level, name }: { level: number; name: string }) {
  const c = TIER_COLORS[level] ?? TIER_COLORS[0];
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold ${c.bg} ${c.text} border ${c.border}`}>
      T{level} {name}
    </span>
  );
}

function ProgressBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  return (
    <div className="w-full h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function PaperLadderCard() {
  const { data, error, refetch } = useApiData<LadderStatus>(API_ENDPOINTS.PAPER_LADDER_STATUS, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });
  const [seeding, setSeeding] = useState(false);

  const portfolios = data?.portfolios ? Object.values(data.portfolios) : [];
  const tiers = data?.tiers ?? [];

  const handleSeedAll = async () => {
    setSeeding(true);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.PAPER_LADDER_SEED_ALL}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await refetch();
    } finally {
      setSeeding(false);
    }
  };

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-slate-200">Paper Trading Ladder</h3>
          {data && (
            <span className="text-[10px] text-slate-500">{portfolios.length} portfolios</span>
          )}
        </div>
        {portfolios.length === 0 && (
          <button
            type="button"
            onClick={handleSeedAll}
            disabled={seeding}
            className="text-[10px] font-bold px-2 py-1 rounded bg-amber-600/20 text-amber-400 border border-amber-600/40 hover:bg-amber-600/30 disabled:opacity-50"
          >
            {seeding ? 'Seeding...' : '🌱 Seed All Agents'}
          </button>
        )}
      </div>

      <ErrorBar label="Paper Ladder" error={error} />

      {/* Tier ladder visualization */}
      {tiers.length > 0 && portfolios.length === 0 && (
        <div className="mb-4">
          <div className="flex items-center gap-1">
            {tiers.map((t, i) => (
              <div key={t.level} className="flex items-center">
                <div className={`px-2 py-1 rounded text-[9px] font-bold ${TIER_COLORS[i]?.bg ?? ''} ${TIER_COLORS[i]?.text ?? ''} border ${TIER_COLORS[i]?.border ?? ''}`}>
                  ${(t.seed_usd ?? 0).toLocaleString()}
                </div>
                {i < tiers.length - 1 && <ChevronUp className="w-3 h-3 text-slate-600 rotate-90" />}
              </div>
            ))}
          </div>
          <p className="text-[10px] text-slate-500 mt-2 italic">No portfolios seeded yet — click "Seed All Agents" to start</p>
        </div>
      )}

      {/* Portfolio grid */}
      {portfolios.length > 0 && (
        <div className="space-y-2 max-h-[400px] overflow-y-auto">
          {portfolios.map(p => {
            const tier = tiers.find(t => t.level === p.current_tier);
            const profitTarget = tier?.profit_target_pct ?? 0;
            const ddLimit = tier?.max_drawdown_pct ?? 0;

            return (
              <div key={p.portfolio_id} className="bg-slate-800/40 border border-slate-700/40 rounded-lg p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-slate-300">{p.portfolio_id}</span>
                    <TierBadge level={p.current_tier} name={p.tier_name} />
                  </div>
                  <span className={`text-xs font-bold ${p.roi_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {(p.roi_pct ?? 0) >= 0 ? '+' : ''}{(p.roi_pct ?? 0).toFixed(1)}%
                  </span>
                </div>

                {/* Stats row */}
                <div className="grid grid-cols-4 gap-2 mb-2">
                  <div className="text-center">
                    <div className="text-[9px] text-slate-500 uppercase">Equity</div>
                    <div className="text-[11px] font-bold text-slate-200">${(p.current_equity ?? 0).toLocaleString()}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-[9px] text-slate-500 uppercase">Trades</div>
                    <div className="text-[11px] font-bold text-slate-200">{p.total_trades}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-[9px] text-slate-500 uppercase">Win Rate</div>
                    <div className={`text-[11px] font-bold ${p.win_rate_pct >= 50 ? 'text-emerald-400' : 'text-slate-300'}`}>
                      {(p.win_rate_pct ?? 0).toFixed(0)}%
                    </div>
                  </div>
                  <div className="text-center">
                    <div className="text-[9px] text-slate-500 uppercase">Drawdown</div>
                    <div className={`text-[11px] font-bold ${p.drawdown_pct > ddLimit * 0.7 ? 'text-red-400' : 'text-slate-300'}`}>
                      {(p.drawdown_pct ?? 0).toFixed(1)}%
                    </div>
                  </div>
                </div>

                {/* Progress bars */}
                {profitTarget > 0 && (
                  <div className="mb-1">
                    <div className="flex items-center justify-between text-[9px] text-slate-500 mb-0.5">
                      <span className="flex items-center gap-1"><Target className="w-2.5 h-2.5" /> Profit</span>
                      <span>{Math.max(0, p.roi_pct ?? 0).toFixed(1)}% / {profitTarget}%</span>
                    </div>
                    <ProgressBar value={Math.max(0, p.roi_pct)} max={profitTarget} color="bg-emerald-500" />
                  </div>
                )}
                {tier && tier.min_trades > 0 && (
                  <div className="mb-1">
                    <div className="flex items-center justify-between text-[9px] text-slate-500 mb-0.5">
                      <span className="flex items-center gap-1"><Zap className="w-2.5 h-2.5" /> Trades</span>
                      <span>{p.total_trades} / {tier.min_trades}</span>
                    </div>
                    <ProgressBar value={p.total_trades} max={tier.min_trades} color="bg-blue-500" />
                  </div>
                )}

                {/* Next goal */}
                {p.next_goal && p.next_goal.status === 'in_progress' && p.next_goal.remaining && (
                  <div className="mt-2 flex items-start gap-1.5">
                    <Trophy className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                    <div className="text-[9px] text-slate-400">
                      <span className="font-semibold text-amber-400">Next: {p.next_goal.next_tier}</span>
                      {' '}(${p.next_goal.next_seed_usd?.toLocaleString()})
                      <div className="mt-0.5">
                        {p.next_goal.remaining.map((g, i) => (
                          <span key={i} className="inline-block mr-2 text-slate-500">{g}</span>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
                {p.next_goal && p.next_goal.status === 'max_tier' && (
                  <div className="mt-2 flex items-center gap-1.5">
                    <DollarSign className="w-3 h-3 text-amber-400" />
                    <span className="text-[9px] font-bold text-amber-400">LIVE-READY</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
