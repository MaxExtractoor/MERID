import { useState, useEffect, useCallback, useMemo } from 'react';
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart } from 'recharts';
import { DollarSign, Activity, BarChart3, Shield, Zap, Clock, ArrowUpRight, ArrowDownRight, Minus, RefreshCw, Wallet, Target, Award } from 'lucide-react';
import CollapsibleConsole from '../components/CollapsibleConsole';
import PredictionMarketsPanel from '../components/PredictionMarketsPanel';
import AgentActivityPanel from '../components/AgentActivityPanel';
import QuickActionsPanel from '../components/QuickActionsPanel';
import { API_ENDPOINTS, CHART_COLORS} from '../config/constants';
import { 
  SystemHealthCard, 
  PnLCard, 
  TradingOperationsCard, 
  PrimeStatusCard,
  AgentStatusCard,
  RiskProtectionCard 
} from '../hooks/useDashboard';

/* ── Types ─────────────────────────────────────────── */
interface PortfolioSummary {
  equity: number;
  dailyPnl: number;
  dailyPnlPct: number;
  availableMargin: number;
  activeBots: number;
  totalValue: number;
  unrealizedPnl: number;
  activePositions: number;
  totalTrades: number;
  winRate: number;
  roi: number;
  startingBalance: number;
}

interface WatchlistItem {
  symbol: string;
  price: number;
  change: number;
  volume: string;
  source?: string;
}

interface RecentTrade {
  time: string;
  action: string;
  size: string;
  price: string;
  status?: string;
}

interface RiskExposure {
  total_exposure: number;
  total_exposure_pct: number;
  open_orders_count: number;
  buying_power: number;
  by_symbol: Array<{ symbol: string; pct_of_equity: number }>;
}

interface EquityPoint {
  ts: number;
  equity: number;
  pnl: number;
}

/* ── Hooks ─────────────────────────────────────────── */
function usePortfolio() {
  const [data, setData] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(API_ENDPOINTS.PORTFOLIO_LIVE);
      if (res.ok) setData(await res.json());
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch_();
    const i = setInterval(fetch_, 15_000);
    return () => clearInterval(i);
  }, [fetch_]);

  return { portfolio: data, loading, refresh: fetch_ };
}

function useWatchlist() {
  const [prices, setPrices] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${API_ENDPOINTS.PRICES_LIVE}?symbols=BTC,ETH,SOL,AVAX`);
      if (res.ok) {
        const d = await res.json();
        setPrices(d.prices || []);
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch_();
    const i = setInterval(fetch_, 10_000);
    return () => clearInterval(i);
  }, [fetch_]);

  return { prices, loading };
}

function useRecentTrades() {
  const [trades, setTrades] = useState<RecentTrade[]>([]);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${API_ENDPOINTS.ORDERS_RECENT}?limit=8`);
      if (res.ok) {
        const d = await res.json();
        setTrades(d.orders || []);
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch_();
    const i = setInterval(fetch_, 30_000);
    return () => clearInterval(i);
  }, [fetch_]);

  return { trades, loading };
}

function useRiskExposure() {
  const [exposure, setExposure] = useState<RiskExposure | null>(null);

  useEffect(() => {
    const f = async () => {
      try {
        const r = await fetch(API_ENDPOINTS.RISK_EXPOSURE);
        if (r.ok) setExposure(await r.json());
      } catch { /* silent */ }
    };
    f();
    const i = setInterval(f, 30_000);
    return () => clearInterval(i);
  }, []);

  return exposure;
}

function useEquitySeries() {
  const [points, setPoints] = useState<EquityPoint[]>([]);

  useEffect(() => {
    const f = async () => {
      try {
        const r = await fetch(`${API_ENDPOINTS.EQUITY_SERIES}?window=1d`);
        if (r.ok) {
          const d = await r.json();
          setPoints(d.points || []);
        }
      } catch { /* silent */ }
    };
    f();
    const i = setInterval(f, 60_000);
    return () => clearInterval(i);
  }, []);

  return points;
}

/* ── Helpers ───────────────────────────────────────── */
function fmtUsd(v: number, compact = false): string {
  if (compact && Math.abs(v) >= 1_000_000)
    return `$${(v / 1_000_000).toFixed(2)}M`;
  if (compact && Math.abs(v) >= 1_000)
    return `$${(v / 1_000).toFixed(1)}K`;
  return v.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });
}

function PnlBadge({ value, pct }: { value: number; pct?: number }) {
  const positive = value >= 0;
  const Icon = positive ? ArrowUpRight : value < 0 ? ArrowDownRight : Minus;
  const color = positive ? 'text-emerald-400' : 'text-red-400';
  const bg = positive ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-red-500/10 border-red-500/30';

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${bg} ${color}`}>
      <Icon className="w-3 h-3" />
      {positive ? '+' : ''}{fmtUsd(value)}
      {pct !== undefined && <span className="ml-1 opacity-75">({positive ? '+' : ''}{pct.toFixed(2)}%)</span>}
    </span>
  );
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`bg-slate-700/50 rounded animate-pulse ${className}`} />;
}

/* ── Portfolio Hero Card ──────────────────────────── */
function PortfolioHero({ portfolio, loading, refresh }: { portfolio: PortfolioSummary | null; loading: boolean; refresh: () => void }) {
  if (loading || !portfolio) {
    return (
      <div className="bg-gradient-to-br from-slate-900 via-blue-950/30 to-slate-900 rounded-2xl border border-blue-500/20 p-6 lg:p-8">
        <Skeleton className="h-4 w-32 mb-3" />
        <Skeleton className="h-10 w-48 mb-4" />
        <div className="grid grid-cols-4 gap-4"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      </div>
    );
  }

  const pnlPos = portfolio.dailyPnl >= 0;

  return (
    <div className="bg-gradient-to-br from-slate-900 via-blue-950/30 to-slate-900 rounded-2xl border border-blue-500/20 p-6 lg:p-8 relative overflow-hidden">
      {/* Glow accent */}
      <div className={`absolute -top-20 -right-20 w-40 h-40 rounded-full blur-3xl opacity-20 ${pnlPos ? 'bg-emerald-500' : 'bg-red-500'}`} />

      <div className="relative">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <div className="p-1.5 bg-blue-500/20 rounded-lg">
              <Wallet className="w-4 h-4 text-blue-400" />
            </div>
            <span className="text-sm text-slate-400 font-medium">Portfolio Value</span>
            <span className="flex items-center gap-1 text-xs text-emerald-400">
              <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" /> Live
            </span>
          </div>
          <button type="button" onClick={refresh} className="p-1.5 rounded-lg hover:bg-slate-700/50 transition-colors" title="Refresh" aria-label="Refresh">
            <RefreshCw className="w-4 h-4 text-slate-400" />
          </button>
        </div>

        <div className="text-4xl lg:text-5xl font-bold text-white tracking-tight mb-2">
          {fmtUsd(portfolio.equity)}
        </div>

        <div className="mb-6">
          <PnlBadge value={portfolio.dailyPnl} pct={portfolio.dailyPnlPct} />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-4 border-t border-slate-700/50">
          <div>
            <div className="text-xs text-slate-500 mb-0.5 flex items-center gap-1"><DollarSign className="w-3 h-3" />Available</div>
            <div className="text-base font-semibold text-slate-200">{fmtUsd(portfolio.availableMargin, true)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5 flex items-center gap-1"><Activity className="w-3 h-3" />Positions</div>
            <div className="text-base font-semibold text-slate-200">{portfolio.activePositions}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5 flex items-center gap-1"><Target className="w-3 h-3" />Trades</div>
            <div className="text-base font-semibold text-slate-200">{portfolio.totalTrades}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5 flex items-center gap-1"><Award className="w-3 h-3" />Win Rate</div>
            <div className="text-base font-semibold text-slate-200">{portfolio.winRate}%</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Equity Chart ─────────────────────────────────── */
function EquityChart({ points, portfolio }: { points: EquityPoint[]; portfolio: PortfolioSummary | null }) {
  const chartData = useMemo(() => {
    if (points.length > 0) {
      return points.map(p => ({
        time: new Date(p.ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        equity: p.equity,
        pnl: p.pnl,
      }));
    }
    // Show flat line at current equity if no historical data
    const eq = portfolio?.equity || 10000;
    const now = Date.now();
    return Array.from({ length: 12 }, (_, i) => ({
      time: new Date(now - (11 - i) * 300_000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      equity: eq,
      pnl: 0,
    }));
  }, [points, portfolio]);

  const minVal = Math.min(...chartData.map(d => d.equity)) * 0.9995;
  const maxVal = Math.max(...chartData.map(d => d.equity)) * 1.0005;
  const pnlPositive = (portfolio?.dailyPnl ?? 0) >= 0;

  return (
    <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-blue-400" />
            Equity Curve
          </h3>
          <p className="text-xs text-slate-500">Live session</p>
        </div>
        {portfolio && (
          <span className={`text-xs font-medium ${pnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
            ROI: {pnlPositive ? '+' : ''}{portfolio.roi}%
          </span>
        )}
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={pnlPositive ? CHART_COLORS.TEAL : CHART_COLORS.RED} stopOpacity={0.3} />
                <stop offset="95%" stopColor={pnlPositive ? CHART_COLORS.TEAL : CHART_COLORS.RED} stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.TOOLTIP_BG} />
            <XAxis dataKey="time" stroke={CHART_COLORS.SLATE_500} tick={{ fontSize: 10 }} />
            <YAxis domain={[minVal, maxVal]} stroke={CHART_COLORS.SLATE_500} tick={{ fontSize: 10 }} tickFormatter={(v: number) => fmtUsd(v, true)} />
            <Tooltip
              contentStyle={{ backgroundColor: CHART_COLORS.SLATE_800, border: '1px solid #334155', borderRadius: '8px', fontSize: '12px' }}
              formatter={(v: number) => [fmtUsd(v), 'Equity']}
            />
            <Area type="monotone" dataKey="equity" stroke={pnlPositive ? CHART_COLORS.TEAL : CHART_COLORS.RED} strokeWidth={2} fill="url(#eqGrad)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ── Watchlist Card ────────────────────────────────── */
function WatchlistCard({ prices, loading }: { prices: WatchlistItem[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
        <Skeleton className="h-5 w-28 mb-4" />
        {[1, 2, 3, 4].map(i => <Skeleton key={i} className="h-12 mb-2" />)}
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-400" />
          Live Prices
        </h3>
        <span className="text-xs text-slate-500">{prices.length} assets</span>
      </div>
      <div className="space-y-1">
        {prices.map(item => {
          const up = item.change >= 0;
          return (
            <div key={item.symbol} className="flex items-center justify-between py-2.5 px-3 rounded-lg hover:bg-slate-800/50 transition-colors">
              <div className="flex items-center gap-3">
                <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold ${
                  item.symbol.includes('BTC') ? 'bg-orange-500/20 text-orange-400' :
                  item.symbol.includes('ETH') ? 'bg-blue-500/20 text-blue-400' :
                  item.symbol.includes('SOL') ? 'bg-purple-500/20 text-purple-400' :
                  'bg-slate-600/20 text-slate-400'
                }`}>
                  {item.symbol.replace('-USD', '').slice(0, 3)}
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-200">{item.symbol}</div>
                  <div className="text-xs text-slate-500">{item.source || 'Exchange'}</div>
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm font-semibold text-slate-200">{fmtUsd(item.price)}</div>
                <div className={`text-xs font-medium ${up ? 'text-emerald-400' : 'text-red-400'}`}>
                  {up ? '+' : ''}{item.change.toFixed(2)}%
                </div>
              </div>
            </div>
          );
        })}
        {prices.length === 0 && (
          <div className="text-center py-6 text-slate-500 text-sm">Waiting for price data...</div>
        )}
      </div>
    </div>
  );
}

/* ── Recent Trades Card ───────────────────────────── */
function RecentTradesCard({ trades, loading }: { trades: RecentTrade[]; loading: boolean }) {
  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
        <Skeleton className="h-5 w-28 mb-4" />
        {[1, 2, 3].map(i => <Skeleton key={i} className="h-10 mb-2" />)}
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Clock className="w-4 h-4 text-cyan-400" />
          Recent Trades
        </h3>
        <span className="text-xs text-slate-500">{trades.length} fills</span>
      </div>
      <div className="space-y-1">
        {trades.map((t, i) => {
          const isBuy = t.action.toUpperCase().startsWith('BUY');
          return (
            <div key={i} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-800/50 transition-colors">
              <div className="flex items-center gap-2">
                <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${isBuy ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                  {isBuy ? 'BUY' : 'SELL'}
                </span>
                <div>
                  <div className="text-sm font-medium text-slate-200">{t.action.replace('BUY ', '').replace('SELL ', '')}</div>
                  <div className="text-xs text-slate-500">{t.size} @ ${t.price}</div>
                </div>
              </div>
              <div className="text-xs text-slate-500">{t.time}</div>
            </div>
          );
        })}
        {trades.length === 0 && (
          <div className="text-center py-6 text-slate-500 text-sm">
            <Activity className="w-5 h-5 mx-auto mb-1 opacity-50" />
            No trades yet this session
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Risk Exposure Card ───────────────────────────── */
function RiskExposureCard({ exposure }: { exposure: RiskExposure | null }) {
  if (!exposure) {
    return (
      <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
        <Skeleton className="h-5 w-28 mb-3" />
        <Skeleton className="h-16" />
      </div>
    );
  }

  const topSymbol = exposure.by_symbol?.reduce(
    (max, s) => (s.pct_of_equity > (max?.pct_of_equity || 0) ? s : max),
    exposure.by_symbol?.[0]
  );
  const pctDeployed = ((exposure.total_exposure_pct || 0) * 100);

  return (
    <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
      <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2 mb-3">
        <Shield className="w-4 h-4 text-violet-400" />
        Risk Exposure
      </h3>
      <div className="grid grid-cols-3 gap-3 mb-3">
        <div>
          <div className="text-lg font-semibold text-slate-200">{exposure.open_orders_count}</div>
          <div className="text-xs text-slate-500">Open Orders</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-slate-200">{topSymbol?.symbol || '—'}</div>
          <div className="text-xs text-slate-500">Top Exposure</div>
        </div>
        <div>
          <div className="text-lg font-semibold text-emerald-400">{fmtUsd(exposure.buying_power, true)}</div>
          <div className="text-xs text-slate-500">Buying Power</div>
        </div>
      </div>
      {/* Utilization bar */}
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${pctDeployed > 80 ? 'bg-red-500' : pctDeployed > 50 ? 'bg-amber-500' : 'bg-emerald-500'}`}
          style={{ width: `${Math.min(pctDeployed, 100)}%` }}
        />
      </div>
      <div className="text-xs text-slate-500 mt-1">{pctDeployed.toFixed(1)}% deployed</div>
    </div>
  );
}

/* ── Main Overview ─────────────────────────────────── */
export default function Overview() {
  const { portfolio, loading: portfolioLoading, refresh } = usePortfolio();
  const { prices, loading: pricesLoading } = useWatchlist();
  const { trades, loading: tradesLoading } = useRecentTrades();
  const exposure = useRiskExposure();
  const equityPoints = useEquitySeries();

  return (
    <div className="space-y-5">
      {/* Row 1: System Status Cards */}
      <section className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <SystemHealthCard />
        <PnLCard />
        <TradingOperationsCard />
        <PrimeStatusCard />
        <AgentStatusCard />
        <RiskProtectionCard />
      </section>

      {/* Row 2: Portfolio Hero + Live Prices */}
      <section className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <div className="lg:col-span-3">
          <PortfolioHero portfolio={portfolio} loading={portfolioLoading} refresh={refresh} />
        </div>
        <div className="lg:col-span-2">
          <WatchlistCard prices={prices} loading={pricesLoading} />
        </div>
      </section>

      {/* Row 3: Equity Chart + Risk + Recent Trades */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2">
          <EquityChart points={equityPoints} portfolio={portfolio} />
        </div>
        <div className="space-y-5">
          <RiskExposureCard exposure={exposure} />
          <RecentTradesCard trades={trades} loading={tradesLoading} />
        </div>
      </section>

      {/* Row 4: Agent Activity + Quick Actions */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2">
          <AgentActivityPanel />
        </div>
        <QuickActionsPanel />
      </section>

      {/* Row 5: Prediction Markets */}
      <section>
        <PredictionMarketsPanel />
      </section>

      {/* Console */}
      <CollapsibleConsole />
    </div>
  );
}
