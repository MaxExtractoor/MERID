/**
 * Portfolio — dense operator portfolio view (replaces Monitor +
 * KalshiPortfolioView).
 *
 * Data (store slices are refreshed by the app-level 30s poller; view-level
 * sources poll through usePoll):
 * - Bankroll:   store.portfolio (balance/cash/portfolio_value) +
 *               trading-shard cash via fetchBalance -> tradingShardCents
 *               ('n/a' when the trading shard is unknown — never aggregate
 *               as a stand-in).
 * - PnL:        GET /api/v1/kalshi/pnl        -> daily/realized/unrealized/
 *               session + per-category attribution (store risk slice as
 *               fallback for realized/unrealized/daily).
 * - Equity:     GET /api/v1/kalshi/pnl-history -> cumulative PnL curve.
 * - Tables:     store.portfolio positions / orders / fills. Empty tables
 *               render honest 'no …' rows, not zeros.
 * - Mutations:  order cancel -> DELETE /api/v1/kalshi/orders/{id}
 *               (verified kalshi_api.py:3539), useRef in-flight guard +
 *               ConfirmModal + authoritative refreshAll() refetch.
 */

import { memo, useRef, useState } from 'react';
import {
  useKalshiStore, selectPortfolio, selectRisk, selectConnected,
} from '../store';
import type { KalshiOrder } from '../store';
import { usePoll } from '../hooks/usePoll';
import { AGENT_ENDPOINTS, delJson, fetchBalance } from '../agents/api';
import { tradingShardCents } from '../agents/useAgentWall';
import { Briefcase, Activity, TrendingUp, DollarSign, Layers } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';
import { ConfirmModal } from '../components/ConfirmModal';
import { EquityCurve } from '../components/instruments/EquityCurve';
import { Marquee } from '../components/instruments/Marquee';
import type { PricePoint } from '../components/instruments/PriceChart';
import { cx, fmtCentsAsUsd, fmtUsd, numOr } from '../agents/format';

/* ------------------------------------------------------------------ */
/* Server shapes (defensive)                                           */
/* ------------------------------------------------------------------ */

interface PnlSummary {
  daily_pnl_usd?: number;
  realized_pnl_usd?: number;
  unrealized_pnl_usd?: number;
  session_total_pnl_usd?: number;
  session_realized_pnl_usd?: number;
  session_unrealized_pnl_usd?: number;
  session_date?: string | null;
  category_pnl?: Record<string, number>;
  reconciliation_status?: string;
  source?: string;
}

interface PnlHistoryPoint {
  ts?: string | number;
  equity?: number;
  daily_pnl?: number;
  cumulative_pnl?: number;
}

const mapPnlSummary = (raw: unknown): PnlSummary =>
  (raw && typeof raw === 'object' ? (raw as PnlSummary) : {});

const mapPnlHistory = (raw: unknown): PricePoint[] => {
  const pts = (raw as { points?: PnlHistoryPoint[] } | null)?.points;
  if (!Array.isArray(pts)) return [];
  const out: PricePoint[] = [];
  for (const p of pts) {
    if (!p || typeof p !== 'object') continue;
    const value = numOr(p.cumulative_pnl) ?? numOr(p.equity);
    const time = p.ts;
    if (value == null || time == null) continue;
    if (typeof time !== 'number' && typeof time !== 'string') continue;
    out.push({ time, value });
  }
  return out;
};

/* ------------------------------------------------------------------ */
/* Mutations                                                           */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/* Small shared bits                                                   */
/* ------------------------------------------------------------------ */

const usd = (v: number | undefined): string => (v == null ? 'n/a' : fmtUsd(v));

const FreshnessChip = memo(function FreshnessChip({
  error, lastOk,
}: { error?: string | null; lastOk?: number }) {
  if (error) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded border border-red-500/40 bg-red-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-red-400"
        title={error}
        role="alert"
      >
        source error{lastOk ? ' — showing last good' : ''}
      </span>
    );
  }
  if (lastOk != null) {
    return (
      <span className="text-[9px] text-slate-600 tabular-nums">
        updated {Math.max(0, Math.round((Date.now() - lastOk) / 1000))}s ago
      </span>
    );
  }
  return null;
});

const MoneyTile = memo(function MoneyTile({
  label, value, sub, tone = 'text-slate-100',
}: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className={cx('mt-0.5 text-xl font-bold tabular-nums', tone)}>{value}</div>
      {sub && <div className="mt-0.5 text-[10px] text-slate-600 truncate">{sub}</div>}
    </div>
  );
});

const EmptyRow = memo(function EmptyRow({ colSpan, label }: { colSpan: number; label: string }) {
  return (
    <tr>
      <td colSpan={colSpan} className="p-6 text-center text-slate-600 text-sm">
        {label}
      </td>
    </tr>
  );
});

/* ------------------------------------------------------------------ */
/* View                                                                */
/* ------------------------------------------------------------------ */

const Portfolio = () => {
  const portfolio = useKalshiStore(selectPortfolio);
  const risk = useKalshiStore(selectRisk);
  const connected = useKalshiStore(selectConnected);
  const refreshAll = useKalshiStore((s) => s.refreshAll);

  // View-level sources (store slices are refreshed app-wide every 30s).
  const balancePoll = usePoll({ fetcher: fetchBalance }, { ms: 30_000 });
  const pnlPoll = usePoll<PnlSummary>(AGENT_ENDPOINTS.PNL, { ms: 15_000, map: mapPnlSummary });
  const histPoll = usePoll<PricePoint[]>(
    `${AGENT_ENDPOINTS.PNL_HISTORY}?limit=200`,
    { ms: 30_000, map: mapPnlHistory },
  );

  // Order-cancel mutation state (guarded).
  const cancelRef = useRef(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<KalshiOrder | null>(null);

  const runCancel = async (order: KalshiOrder) => {
    if (cancelRef.current) return;
    cancelRef.current = true;
    setCancelBusy(true);
    setCancelError(null);
    try {
      await delJson(`${AGENT_ENDPOINTS.ORDERS}/${encodeURIComponent(order.order_id)}`);
      await refreshAll();
    } catch (e) {
      setCancelError(e instanceof Error ? e.message : String(e));
    } finally {
      cancelRef.current = false;
      setCancelBusy(false);
    }
  };

  const pnl = pnlPoll.data;
  const shardCents = tradingShardCents(balancePoll.data);
  const balanceOk = portfolio.lastOk != null;

  // PnL tiles — PNL endpoint first, store slices as fallback for shared fields.
  const dailyPnl = numOr(pnl?.daily_pnl_usd) ?? (balanceOk ? portfolio.daily_pnl : undefined);
  const realizedPnl = numOr(pnl?.realized_pnl_usd) ?? (risk.lastOk != null ? risk.realized_pnl : undefined);
  const unrealizedPnl = numOr(pnl?.unrealized_pnl_usd) ?? (risk.lastOk != null ? risk.unrealized_pnl : undefined);
  const sessionPnl = numOr(pnl?.session_total_pnl_usd);

  const pnlTone = (v: number | undefined) =>
    v == null ? 'text-slate-100' : v >= 0 ? 'text-emerald-400' : 'text-red-400';

  const positions = portfolio.positions;
  const orders = portfolio.orders;
  // Fills arrive oldest->newest in some backends; show latest first either way.
  const fills = [...portfolio.fills]
    .sort((a, b) => (Date.parse(b.filled_at) || 0) - (Date.parse(a.filled_at) || 0))
    .slice(0, 50);

  const categoryPnl = Object.entries(pnl?.category_pnl ?? {})
    .map(([k, v]) => ({ asset: k, pnl: numOr(v) ?? 0 }))
    .filter((e) => e.asset && Number.isFinite(e.pnl));
  const maxAbsCatPnl = Math.max(1, ...categoryPnl.map((e) => Math.abs(e.pnl)));

  const reconStatus = pnl?.reconciliation_status;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Briefcase className="w-8 h-8 text-cyan-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Portfolio</h1>
            <p className="text-sm text-slate-400">Bankroll, PnL, positions, orders and fills</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <FreshnessChip error={portfolio.error} lastOk={portfolio.lastOk} />
          <Badge variant={connected ? 'success' : 'danger'}>
            {connected ? 'Connected' : 'Disconnected'}
          </Badge>
        </div>
      </div>

      {/* Bankroll strip */}
      <section aria-label="bankroll" className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MoneyTile
          label="Available Cash"
          value={balanceOk ? fmtUsd(portfolio.cash) : 'n/a'}
        />
        <MoneyTile
          label="Portfolio Value"
          value={balanceOk ? fmtUsd(portfolio.portfolio_value) : 'n/a'}
        />
        <MoneyTile
          label="Total Account"
          value={balanceOk ? fmtUsd(portfolio.balance) : 'n/a'}
          sub="cash + positions"
        />
        <MoneyTile
          label="Trading-Shard Cash"
          value={shardCents != null ? fmtCentsAsUsd(shardCents) : 'n/a'}
          sub={
            balancePoll.data?.trading_shard != null
              ? `shard ${balancePoll.data.trading_shard} — backs 15m orders`
              : balancePoll.error
                ? 'balance source error'
                : 'trading shard unknown'
          }
          tone={shardCents != null ? 'text-emerald-400' : 'text-slate-500'}
        />
      </section>
      {balancePoll.error && (
        <div className="text-[10px] text-red-400" role="alert">
          Balance/shard source error: {balancePoll.error}
        </div>
      )}

      {/* PnL strip */}
      <section aria-label="pnl" className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-slate-500" />
            <h2 className="text-[11px] font-bold uppercase tracking-widest text-slate-400">PnL</h2>
            {reconStatus && (
              <Badge
                variant={reconStatus === 'ok' ? 'success' : reconStatus === 'degraded' ? 'warning' : 'danger'}
                size="sm"
              >
                recon: {reconStatus}
              </Badge>
            )}
          </div>
          <FreshnessChip error={pnlPoll.error} lastOk={pnlPoll.lastOk} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MoneyTile label="Daily PnL" value={usd(dailyPnl)} tone={pnlTone(dailyPnl)} />
          <MoneyTile
            label="Session PnL"
            value={usd(sessionPnl)}
            tone={pnlTone(sessionPnl)}
            sub={pnl?.session_date ? `session ${pnl.session_date}` : 'fills-ledger session'}
          />
          <MoneyTile
            label="Realized PnL"
            value={usd(realizedPnl)}
            tone={pnlTone(realizedPnl)}
            sub="closed trades"
          />
          <MoneyTile
            label="Unrealized PnL"
            value={usd(unrealizedPnl)}
            tone={pnlTone(unrealizedPnl)}
            sub="mark-to-market"
          />
        </div>
      </section>

      {/* Equity curve */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-slate-500" />
              Cumulative PnL
            </CardTitle>
            <FreshnessChip error={histPoll.error} lastOk={histPoll.lastOk} />
          </div>
        </CardHeader>
        <CardContent>
          {histPoll.loading && !histPoll.data ? (
            <div className="h-[200px] flex items-center justify-center text-slate-600 text-sm">
              Loading PnL history…
            </div>
          ) : (
            <EquityCurve
              data={histPoll.data}
              height={200}
              emptyLabel={histPoll.error ? 'pnl history unavailable' : 'no pnl history'}
            />
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* Positions */}
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Open Positions</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="open positions">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                    <th className="text-left p-3" scope="col">Market</th>
                    <th className="text-left p-3" scope="col">Side</th>
                    <th className="text-right p-3" scope="col">Contracts</th>
                    <th className="text-right p-3" scope="col">Avg Price</th>
                    <th className="text-right p-3" scope="col">Unrealized</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.length === 0 ? (
                    <EmptyRow colSpan={5} label="No open positions" />
                  ) : positions.map((pos, idx) => (
                    <tr key={pos.ticker || idx} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3">
                        <div className="font-medium text-white">{pos.ticker || 'n/a'}</div>
                        <div className="text-xs text-slate-500">{pos.outcome}</div>
                      </td>
                      <td className="p-3">
                        <Badge variant={pos.side === 'yes' ? 'success' : 'danger'}>
                          {pos.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="p-3 text-right tabular-nums text-white">{pos.quantity}</td>
                      <td className="p-3 text-right font-mono tabular-nums text-white">
                        {pos.avg_entry_price_cents}¢
                      </td>
                      <td
                        className={cx(
                          'p-3 text-right font-mono tabular-nums',
                          pos.unrealized_pnl_cents >= 0 ? 'text-emerald-400' : 'text-red-400',
                        )}
                      >
                        {fmtUsd(pos.unrealized_pnl_cents / 100)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* Per-asset PnL */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-slate-500" />
              PnL by Asset
            </CardTitle>
          </CardHeader>
          <CardContent>
            {categoryPnl.length === 0 ? (
              <div className="text-center py-8 text-slate-600 text-sm">
                {pnlPoll.error ? 'PnL source unavailable' : 'No per-asset PnL reported'}
              </div>
            ) : (
              <div className="space-y-2.5">
                {categoryPnl.map((e) => (
                  <div key={e.asset}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-slate-300 font-medium">{e.asset}</span>
                      <span className={cx('font-mono tabular-nums', e.pnl >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                        {e.pnl >= 0 ? '+' : ''}{fmtUsd(e.pnl)}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className={cx('h-full rounded-full', e.pnl >= 0 ? 'bg-emerald-500' : 'bg-red-500')}
                        style={{ width: `${Math.max(3, (Math.abs(e.pnl) / maxAbsCatPnl) * 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Open orders */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Open Orders</CardTitle>
            <FreshnessChip error={portfolio.error} lastOk={portfolio.lastOk} />
          </div>
        </CardHeader>
        <CardContent>
          {cancelError && (
            <div className="mb-3 text-xs text-red-400 break-words" role="alert">
              Cancel failed: {cancelError}
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="open orders">
              <thead>
                <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                  <th className="text-left p-3" scope="col">Order</th>
                  <th className="text-left p-3" scope="col">Side</th>
                  <th className="text-right p-3" scope="col">Size</th>
                  <th className="text-right p-3" scope="col">Price</th>
                  <th className="text-right p-3" scope="col">Filled/Remaining</th>
                  <th className="text-left p-3" scope="col">Status</th>
                  <th className="text-right p-3" scope="col">Action</th>
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 ? (
                  <EmptyRow colSpan={7} label="No open orders" />
                ) : orders.map((o) => (
                  <tr key={o.order_id || `${o.ticker}-${o.created_at}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="p-3">
                      <div className="font-medium text-white">{o.ticker || 'n/a'}</div>
                      <div className="text-xs text-slate-500 font-mono">
                        {o.order_id ? o.order_id.slice(0, 18) : 'n/a'}
                      </div>
                    </td>
                    <td className="p-3">
                      <Badge variant={o.side === 'yes' ? 'success' : 'danger'}>
                        {(o.side || '?').toUpperCase()}
                      </Badge>
                    </td>
                    <td className="p-3 text-right tabular-nums text-white">{o.size}</td>
                    <td className="p-3 text-right font-mono tabular-nums text-white">{o.price_cents}¢</td>
                    <td className="p-3 text-right tabular-nums text-white">
                      {o.filled}/{o.remaining ?? '—'}
                    </td>
                    <td className="p-3 text-xs text-slate-400">{o.status || '—'}</td>
                    <td className="p-3 text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={cancelBusy || !o.order_id}
                        onClick={() => setConfirmCancel(o)}
                      >
                        Cancel
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Fills tape (latest first) */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DollarSign className="w-4 h-4 text-slate-500" />
            Fills Tape
            <span className="text-xs font-normal text-slate-500">
              {fills.length > 0 ? `latest ${fills.length}` : ''}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {/* scrolling fills rail */}
          <Marquee
            durationS={40}
            className="mb-2 border-b border-slate-800/60 pb-1.5"
            items={fills.slice(0, 20).map((f) => (
              <span key={f.fill_id} className="inline-flex items-baseline gap-1.5 text-[11px] tabular-nums">
                <span className={f.side === 'yes' ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>
                  {f.side.toUpperCase()}
                </span>
                <span className="text-slate-300 font-medium">{f.contracts}×</span>
                <span className="text-slate-500">{f.ticker}</span>
                <span className="text-slate-200 font-mono">@{f.price_cents}¢</span>
                {f.pnl_cents !== 0 && (
                  <span className={f.pnl_cents >= 0 ? 'text-emerald-500' : 'text-red-500'}>
                    {f.pnl_cents >= 0 ? '+' : ''}{fmtUsd(f.pnl_cents / 100)}
                  </span>
                )}
              </span>
            ))}
          />
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm" aria-label="recent fills">
              <thead className="sticky top-0 bg-slate-800 z-10">
                <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                  <th className="text-left p-3" scope="col">Time</th>
                  <th className="text-left p-3" scope="col">Market</th>
                  <th className="text-left p-3" scope="col">Side</th>
                  <th className="text-right p-3" scope="col">Contracts</th>
                  <th className="text-right p-3" scope="col">Price</th>
                  <th className="text-right p-3" scope="col">Fee</th>
                  <th className="text-right p-3" scope="col">PnL</th>
                </tr>
              </thead>
              <tbody>
                {fills.length === 0 ? (
                  <EmptyRow colSpan={7} label="No recent fills" />
                ) : fills.map((f, idx) => (
                  <tr key={f.fill_id || `${f.ticker}-${f.filled_at}-${idx}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="p-3 text-xs text-slate-400 tabular-nums">
                      {f.filled_at ? new Date(f.filled_at).toLocaleTimeString() : 'n/a'}
                    </td>
                    <td className="p-3">
                      <div className="font-medium text-white">{f.ticker || 'n/a'}</div>
                      {f.market_question && (
                        <div className="text-[10px] text-slate-600 truncate max-w-[260px]" title={f.market_question}>
                          {f.market_question}
                        </div>
                      )}
                    </td>
                    <td className="p-3">
                      <Badge variant={f.side === 'yes' ? 'success' : 'danger'}>
                        {f.side.toUpperCase()}
                      </Badge>
                    </td>
                    <td className="p-3 text-right tabular-nums text-white">{f.contracts}</td>
                    <td className="p-3 text-right font-mono tabular-nums text-white">{f.price_cents}¢</td>
                    <td className="p-3 text-right font-mono tabular-nums text-slate-400">
                      {fmtUsd(f.fee_cents / 100)}
                    </td>
                    <td
                      className={cx(
                        'p-3 text-right font-mono tabular-nums',
                        f.pnl_cents > 0 ? 'text-emerald-400' : f.pnl_cents < 0 ? 'text-red-400' : 'text-slate-400',
                      )}
                    >
                      {fmtUsd(f.pnl_cents / 100)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <ConfirmModal
        isOpen={confirmCancel !== null}
        title="Cancel Order"
        message={
          confirmCancel
            ? `Cancel resting order on ${confirmCancel.ticker} (${confirmCancel.order_id.slice(0, 18)}…)?`
            : ''
        }
        confirmText="Cancel Order"
        confirmVariant="danger"
        onConfirm={() => {
          const target = confirmCancel;
          setConfirmCancel(null);
          if (target) void runCancel(target);
        }}
        onCancel={() => setConfirmCancel(null)}
      />
    </div>
  );
};

export default Portfolio;
