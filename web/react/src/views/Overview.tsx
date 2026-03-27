import { useState, useCallback } from 'react';
import {
  DollarSign,
  Activity,
  Shield,
  Wallet,
  FileText,
  Bot,
  RefreshCw,
  Play,
  Square,
  Database,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import CollapsibleConsole from '../components/CollapsibleConsole';
import AgentActivityPanel from '../components/AgentActivityPanel';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { KalshiBalance, KalshiPosition, KalshiOrder, KalshiFill } from '../types/kalshi';
import { 
  SystemHealthCard, 
  KalshiHealthCard,
  AgentStatusCard,
  RiskProtectionCard 
} from '../hooks/useDashboard';

/* ── Types ─────────────────────────────────────────── */
interface KalshiPnL { daily_pnl_usd: number; total_notional_usd: number; peak_equity_usd: number; current_equity_usd: number; drawdown_pct: number; category_pnl: Record<string, number> }
interface OperatorKillSwitchState {
  global_kill?: boolean;
  active?: boolean;
  can_trade?: boolean;
  kill_reason?: string | null;
  reason?: string | null;
}
interface GridStatusLite {
  running?: boolean;
  agent_count?: number;
  session?: { trading_allowed?: boolean; block_reason?: string | null };
}
interface CatalogResponseLite {
  market_count?: number;
  count?: number;
  markets?: unknown[];
}

/* ── Helpers ───────────────────────────────────────── */
function fmtUsd(v: number | null | undefined): string {
  return (v ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`bg-slate-700/50 rounded animate-pulse ${className}`} />;
}

function RebootControlPanel({
  killSwitch,
  gridStatus,
  catalogCount,
  busyAction,
  message,
  error,
  gridStartMode,
  onGridStartModeChange,
  onRefreshCatalog,
  onStartGrid,
  onStopGrid,
  onRefreshSignals,
}: {
  killSwitch: OperatorKillSwitchState | null;
  gridStatus: GridStatusLite | null;
  catalogCount: number | null;
  busyAction: string | null;
  message: string | null;
  error: string | null;
  gridStartMode: 'paper' | 'live';
  onGridStartModeChange: (mode: 'paper' | 'live') => void;
  onRefreshCatalog: () => void;
  onStartGrid: () => void;
  onStopGrid: () => void;
  onRefreshSignals: () => void;
}) {
  const killActive = Boolean(killSwitch?.global_kill ?? killSwitch?.active ?? false);
  const canTrade = killSwitch?.can_trade ?? !killActive;
  const killReason = killSwitch?.kill_reason ?? killSwitch?.reason;
  const gridRunning = Boolean(gridStatus?.running);

  return (
    <section className="bg-slate-900/70 rounded-2xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Reboot Sequence</h3>
          <p className="text-xs text-slate-500">Pre-flight checks and controls for live Kalshi restart.</p>
        </div>
        <button
          type="button"
          onClick={onRefreshSignals}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border border-slate-700 text-slate-300 hover:bg-slate-800"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className={`rounded-xl border p-3 ${killActive ? 'bg-red-950/40 border-red-500/40' : 'bg-emerald-950/30 border-emerald-500/30'}`}>
          <p className="text-[10px] uppercase text-slate-500 mb-1">Kill Switch</p>
          <div className={`flex items-center gap-1.5 text-sm font-semibold ${killActive ? 'text-red-400' : 'text-emerald-400'}`}>
            {killActive ? <ShieldAlert className="w-4 h-4" /> : <ShieldCheck className="w-4 h-4" />}
            {killActive ? 'HALTED' : 'CLEAR'}
          </div>
          <p className="text-[10px] text-slate-500 mt-1">{canTrade ? 'Trading permitted' : 'Trading blocked'}</p>
          {killReason && <p className="text-[10px] text-red-300 mt-1 truncate" title={killReason}>{killReason}</p>}
        </div>

        <div className={`rounded-xl border p-3 ${gridRunning ? 'bg-blue-950/30 border-blue-500/30' : 'bg-slate-800/70 border-slate-700/40'}`}>
          <p className="text-[10px] uppercase text-slate-500 mb-1">Agent Grid</p>
          <p className={`text-sm font-semibold ${gridRunning ? 'text-blue-300' : 'text-slate-300'}`}>
            {gridRunning ? 'RUNNING' : 'STOPPED'}
          </p>
          <p className="text-[10px] text-slate-500 mt-1">{gridStatus?.agent_count ?? 0} agents</p>
          {gridStatus?.session && (
            <p className="text-[10px] text-slate-500 mt-0.5">
              Session: {gridStatus.session.trading_allowed ? 'Open' : (gridStatus.session.block_reason ?? 'Closed')}
            </p>
          )}
        </div>

        <div className="rounded-xl border p-3 bg-slate-800/70 border-slate-700/40">
          <p className="text-[10px] uppercase text-slate-500 mb-1">Catalog</p>
          <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-200">
            <Database className="w-4 h-4 text-orange-400" />
            {catalogCount != null ? `${catalogCount} markets` : 'Unknown size'}
          </div>
          <p className="text-[10px] text-slate-500 mt-1">Refresh before enabling live agents</p>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={onRefreshCatalog}
          disabled={busyAction !== null}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-orange-500/15 text-orange-300 border border-orange-500/30 hover:bg-orange-500/20 disabled:opacity-50"
        >
          <Database className="w-3.5 h-3.5" />
          {busyAction === 'catalog' ? 'Refreshing…' : 'Refresh Catalog'}
        </button>

        {!gridRunning ? (
          <>
            {/* Mode toggle */}
            <div className="flex items-center rounded-lg overflow-hidden border border-slate-700">
              <button
                type="button"
                onClick={() => onGridStartModeChange('paper')}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  gridStartMode === 'paper' ? 'bg-amber-600 text-white' : 'bg-slate-800 text-gray-400 hover:text-white'
                }`}
              >
                Paper
              </button>
              <button
                type="button"
                onClick={() => onGridStartModeChange('live')}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  gridStartMode === 'live' ? 'bg-red-600 text-white' : 'bg-slate-800 text-gray-400 hover:text-red-400'
                }`}
              >
                Live
              </button>
            </div>
            <button
              type="button"
              onClick={onStartGrid}
              disabled={busyAction !== null || killActive}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border disabled:opacity-50 ${
                gridStartMode === 'live'
                  ? 'bg-red-500/15 text-red-300 border-red-500/30 hover:bg-red-500/20'
                  : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/20'
              }`}
            >
              <Play className="w-3.5 h-3.5" />
              {busyAction === 'grid-start' ? 'Starting…' : `Start Grid${gridStartMode === 'live' ? ' (LIVE)' : ''}`}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onStopGrid}
            disabled={busyAction !== null}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/20 disabled:opacity-50"
          >
            <Square className="w-3.5 h-3.5" />
            {busyAction === 'grid-stop' ? 'Stopping…' : 'Stop Grid'}
          </button>
        )}

        {killActive && (
          <span className="text-[11px] text-red-300">Grid start disabled while kill switch is active.</span>
        )}
        {gridStartMode === 'live' && !gridRunning && !killActive && (
          <span className="text-[11px] text-red-300 font-semibold">⚠ LIVE mode — real money at risk</span>
        )}
      </div>

      {message && <p className="text-xs text-emerald-300">{message}</p>}
      {error && <p className="text-xs text-red-300">{error}</p>}
    </section>
  );
}

/* ── Kalshi Balance Hero ──────────────────────────── */
function KalshiBalanceHero({ balance, pnl }: { balance: KalshiBalance | null; pnl: KalshiPnL | null }) {
  if (!balance) {
    return (
      <div className="bg-gradient-to-br from-slate-900 via-orange-950/20 to-slate-900 rounded-2xl border border-orange-500/20 p-6">
        <Skeleton className="h-4 w-32 mb-3" />
        <Skeleton className="h-10 w-48 mb-4" />
        <div className="grid grid-cols-3 gap-4"><Skeleton className="h-12" /><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
      </div>
    );
  }

  const dayPnl = pnl?.daily_pnl_usd ?? 0;
  const pnlPos = dayPnl >= 0;

  return (
    <div className="bg-gradient-to-br from-slate-900 via-orange-950/20 to-slate-900 rounded-2xl border border-orange-500/20 p-6 relative overflow-hidden">
      <div className={`absolute -top-20 -right-20 w-40 h-40 rounded-full blur-3xl opacity-15 ${pnlPos ? 'bg-emerald-500' : 'bg-red-500'}`} />
      <div className="relative">
        <div className="flex items-center gap-2 mb-1">
          <div className="p-1.5 bg-orange-500/20 rounded-lg"><Wallet className="w-4 h-4 text-orange-400" /></div>
          <span className="text-sm text-slate-400 font-medium">Kalshi Balance</span>
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" /> Live
          </span>
        </div>
        <div className="text-4xl font-bold text-white tracking-tight mb-3">
          {fmtUsd(balance.available)}
        </div>
        <div className="grid grid-cols-3 gap-4 pt-3 border-t border-slate-700/50">
          <div>
            <div className="text-xs text-slate-500 mb-0.5 flex items-center gap-1"><DollarSign className="w-3 h-3" />Available</div>
            <div className="text-base font-semibold text-slate-200">{fmtUsd(balance.available)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5 flex items-center gap-1"><Shield className="w-3 h-3" />Locked</div>
            <div className="text-base font-semibold text-slate-200">{fmtUsd(balance.locked)}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5 flex items-center gap-1"><Activity className="w-3 h-3" />Day P&L</div>
            <div className={`text-base font-semibold ${pnlPos ? 'text-emerald-400' : 'text-red-400'}`}>
              {pnlPos ? '+' : ''}{fmtUsd(dayPnl)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Kalshi Positions Card ────────────────────────── */
function KalshiPositionsCard({ positions }: { positions: KalshiPosition[] }) {
  return (
    <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
      <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2 mb-3">
        <FileText className="w-4 h-4 text-blue-400" />
        Open Positions
        <span className="ml-auto text-xs text-slate-500">{positions.length}</span>
      </h3>
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {positions.map(p => (
          <div key={p.ticker} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-800/50">
            <div>
              <div className="text-sm font-medium text-slate-200 truncate max-w-[200px]">{p.ticker}</div>
              <div className="text-xs text-slate-500">{p.size} contracts · {p.outcome}</div>
            </div>
            <div className="text-right">
              <div className="text-sm font-semibold text-slate-200">{fmtUsd(p.avg_price * p.size)}</div>
              <div className={`text-xs ${p.unrealized_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {p.unrealized_pnl >= 0 ? '+' : ''}{fmtUsd(p.unrealized_pnl)}
              </div>
            </div>
          </div>
        ))}
        {positions.length === 0 && (
          <div className="text-center py-6 text-slate-500 text-sm">No open positions</div>
        )}
      </div>
    </div>
  );
}

/* ── Recent Kalshi Orders ─────────────────────────── */
function KalshiRecentOrders({ orders, fills }: { orders: KalshiOrder[]; fills: KalshiFill[] }) {
  const recent = [...orders].sort((a, b) => new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime()).slice(0, 8);
  const recentFills = [...fills].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()).slice(0, 5);

  return (
    <div className="bg-slate-900/70 rounded-2xl border border-slate-800 p-5">
      <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2 mb-3">
        <Bot className="w-4 h-4 text-cyan-400" />
        Recent Orders &amp; Fills
        <span className="ml-auto text-xs text-slate-500">{orders.length} orders / {fills.length} fills</span>
      </h3>
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {recentFills.map(f => {
          const isBuy = f.side === 'yes' || f.side === 'buy';
          return (
            <div key={f.trade_id} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-800/50">
              <div className="flex items-center gap-2">
                <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${isBuy ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                  {(f.side ?? '').toUpperCase()}
                </span>
                <div>
                  <div className="text-sm font-medium text-slate-200 truncate max-w-[160px]">{f.ticker}</div>
                  <div className="text-xs text-slate-500">{f.size}ct @ {Math.round(f.price * 100)}¢</div>
                </div>
              </div>
              <div className="text-xs text-slate-500">{new Date(f.timestamp).toLocaleTimeString()}</div>
            </div>
          );
        })}
        {recentFills.length === 0 && recent.length === 0 && (
          <div className="text-center py-6 text-slate-500 text-sm">
            <Activity className="w-5 h-5 mx-auto mb-1 opacity-50" />
            No orders or fills yet
          </div>
        )}
        {recentFills.length === 0 && recent.length > 0 && recent.map(o => (
          <div key={o.order_id} className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-800/50">
            <div className="flex items-center gap-2">
              <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${o.status === 'resting' ? 'bg-amber-500/20 text-amber-400' : o.status === 'executed' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-500/20 text-slate-400'}`}>
                {(o.status ?? '').toUpperCase().slice(0, 6)}
              </span>
              <div>
                <div className="text-sm font-medium text-slate-200 truncate max-w-[160px]">{o.ticker}</div>
                <div className="text-xs text-slate-500">{o.side} {o.size}ct @ {o.price !== null ? Math.round(o.price * 100) : '—'}¢</div>
              </div>
            </div>
            <div className="text-xs text-slate-500">{o.created_at ? new Date(o.created_at).toLocaleTimeString() : '—'}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Main Overview ─────────────────────────────────── */
export default function Overview() {
  const { data: balance } = useApiData<KalshiBalance>(API_ENDPOINTS.KALSHI_BALANCE, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  const { data: pnl } = useApiData<KalshiPnL>(API_ENDPOINTS.KALSHI_PNL, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  const { data: posData } = useApiData<{ positions: KalshiPosition[] }>(API_ENDPOINTS.KALSHI_POSITIONS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.POSITIONS,
  });
  const { data: ordData } = useApiData<{ orders: KalshiOrder[] }>(API_ENDPOINTS.KALSHI_ORDERS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.ORDERS,
  });
  const { data: fillData } = useApiData<{ fills: KalshiFill[] }>(API_ENDPOINTS.KALSHI_FILLS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.ORDERS,
  });
  const { data: killSwitch, refetch: refetchKillSwitch } = useApiData<OperatorKillSwitchState>(API_ENDPOINTS.OPERATOR_KILL_SWITCH_STATUS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH,
  });
  const { data: gridStatus, refetch: refetchGridStatus } = useApiData<GridStatusLite>(API_ENDPOINTS.KALSHI_GRID_STATUS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  const { data: catalog, refetch: refetchCatalog } = useApiData<CatalogResponseLite>(API_ENDPOINTS.KALSHI_CATALOG, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });

  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [rebootMessage, setRebootMessage] = useState<string | null>(null);
  const [rebootError, setRebootError] = useState<string | null>(null);
  const [gridStartMode, setGridStartMode] = useState<'paper' | 'live'>('paper');

  // Sync gridStartMode with actual server mode on load
  const { data: venueModeData } = useApiData<{ mode: string; is_live: boolean }>(API_ENDPOINTS.KALSHI_GRID_MODE, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  // Only sync once on first load if server is already in a known mode
  const [modeSynced, setModeSynced] = useState(false);
  useEffect(() => {
    if (!modeSynced && venueModeData?.mode) {
      const serverMode = venueModeData.mode.toLowerCase().includes('paper') ? 'paper' : 'live';
      if (serverMode !== gridStartMode) setGridStartMode(serverMode);
      setModeSynced(true);
    }
  }, [venueModeData?.mode, gridStartMode, modeSynced]);

  const callRebootAction = useCallback(async (action: 'catalog' | 'grid-start' | 'grid-stop', endpoint: string, body?: object) => {
    setBusyAction(action);
    setRebootError(null);
    setRebootMessage(null);
    try {
      const token = localStorage.getItem('merid-access');
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      const payload = await res.json().catch(() => null) as { message?: string } | null;
      if (!res.ok) {
        throw new Error(payload?.message ?? `${res.status} ${res.statusText}`);
      }
      setRebootMessage(payload?.message ?? 'Action complete');
      await Promise.all([refetchKillSwitch(), refetchGridStatus(), refetchCatalog()]);
    } catch (err) {
      setRebootError(err instanceof Error ? err.message : 'Action failed');
    }
    setBusyAction(null);
  }, [refetchCatalog, refetchGridStatus, refetchKillSwitch]);

  const handleStartGrid = useCallback(() => {
    if (gridStartMode === 'live') {
      const confirmed = window.confirm(
        '⚠️ Start grid in LIVE mode?\n\nThis will route real orders to Kalshi with real funds.\nEnsure kill switch is clear and catalog is fresh.\n\nContinue?'
      );
      if (!confirmed) return;
    }
    void callRebootAction('grid-start', `${API_ENDPOINTS.KALSHI_GRID_START}?mode=${gridStartMode}`);
  }, [gridStartMode, callRebootAction]);

  const refreshRebootSignals = useCallback(() => {
    setRebootError(null);
    setRebootMessage('Signals refreshed');
    void Promise.all([refetchKillSwitch(), refetchGridStatus(), refetchCatalog()]);
  }, [refetchCatalog, refetchGridStatus, refetchKillSwitch]);

  const catalogCount = catalog?.market_count
    ?? catalog?.count
    ?? (catalog && Array.isArray(catalog.markets) ? catalog.markets.length : null);

  return (
    <div className="space-y-5">
      {/* Execution Gate — always visible */}
      <ExecutionGateStrip />

      <RebootControlPanel
        killSwitch={killSwitch}
        gridStatus={gridStatus}
        catalogCount={catalogCount}
        busyAction={busyAction}
        message={rebootMessage}
        error={rebootError}
        gridStartMode={gridStartMode}
        onGridStartModeChange={setGridStartMode}
        onRefreshCatalog={() => { void callRebootAction('catalog', API_ENDPOINTS.KALSHI_CATALOG_REFRESH); }}
        onStartGrid={handleStartGrid}
        onStopGrid={() => { void callRebootAction('grid-stop', API_ENDPOINTS.KALSHI_GRID_STOP); }}
        onRefreshSignals={refreshRebootSignals}
      />

      {/* Row 1: Status Cards */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SystemHealthCard />
        <KalshiHealthCard />
        <AgentStatusCard />
        <RiskProtectionCard />
      </section>

      {/* Row 2: Kalshi Balance + Positions */}
      <section className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <div className="lg:col-span-3">
          <KalshiBalanceHero balance={balance} pnl={pnl} />
        </div>
        <div className="lg:col-span-2">
          <KalshiPositionsCard positions={posData?.positions ?? []} />
        </div>
      </section>

      {/* Row 3: Agent Activity + Recent Orders */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <AgentActivityPanel />
        <KalshiRecentOrders orders={ordData?.orders ?? []} fills={fillData?.fills ?? []} />
      </section>

      {/* Console */}
      <CollapsibleConsole />
    </div>
  );
}
