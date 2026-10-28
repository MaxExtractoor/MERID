/**
 * AgentDetail — full-page drill for a single asset agent: live PriceChart
 * (spot-vs-strike or contract-mid modes, series accrued from real polls —
 * never fabricated), OrderBookLadder + DepthChart fed from
 * AGENT_ENDPOINTS.ORDERBOOK(ticker) — fetched only inside this view —
 * plus MoneynessGauge, GateFunnel, position and fills sub-table.
 *
 * Route integration supplies `asset` (prop or route param); when the agent
 * or its ticker is unknown the view renders explicit no-data states.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAgentWall } from '../agents/useAgentWall';
import { AGENT_ENDPOINTS, getJson } from '../agents/api';
import type { AssetSymbol } from '../agents/types';
import { ASSETS } from '../agents/types';
import {
  AssetBadge, GateFunnel, MoneynessGauge, PositionBar, StatePill,
} from '../components/agents';
import {
  DepthChart, OrderBookLadder, PriceChart, TickFlash,
} from '../components/instruments';
import type { BookLevel } from '../components/instruments';
import type { PriceMarker, PricePoint } from '../components/instruments/PriceChart';
import { Skeleton } from '../ui';
import { cx, fmtAgeMs, fmtClock, fmtCents, fmtSignedCents, numOr } from '../agents/format';
import { ChevronLeft } from '../ui/icons';

/* ------------------------------------------------------------------ */
/* Orderbook payload normalization                                     */
/* ------------------------------------------------------------------ */

interface NormalizedBook {
  bids: BookLevel[];
  asks: BookLevel[];
  spreadC?: number;
  midC?: number;
  stale?: boolean;
}

/** price in dollars (<=1) -> cents; values >1 assumed already cents. */
function levelToCents(p: number): number {
  return p <= 1 ? p * 100 : p;
}

function toLevels(raw: unknown): BookLevel[] {
  if (!Array.isArray(raw)) return [];
  const out: BookLevel[] = [];
  for (const l of raw) {
    if (Array.isArray(l) && l.length >= 2) {
      const p = numOr(l[0]);
      const s = numOr(l[1]);
      if (p != null && s != null) out.push({ price: levelToCents(p), size: s });
    } else if (l && typeof l === 'object') {
      const o = l as Record<string, unknown>;
      const p = numOr(o.price ?? o.price_c ?? o.p);
      const s = numOr(o.quantity ?? o.size ?? o.contracts ?? o.count);
      if (p != null && s != null) out.push({ price: levelToCents(p), size: s });
    }
  }
  return out;
}

function normalizeBook(raw: unknown): NormalizedBook {
  const obj = (raw ?? {}) as Record<string, unknown>;
  const bids = toLevels(obj.yes_bids ?? obj.bids);
  const asks = toLevels(obj.yes_asks ?? obj.asks);
  const spread = numOr(obj.spread_cents ?? obj.spread_c);
  const mid = numOr(obj.midpoint ?? obj.mid_c);
  return {
    bids,
    asks,
    spreadC: spread != null ? levelToCents(spread) : undefined,
    midC: mid != null ? levelToCents(mid) : undefined,
    stale: typeof obj.error === 'string' ? true : undefined,
  };
}

/* ------------------------------------------------------------------ */

type ChartMode = 'spot' | 'mid';

interface AgentDetailProps {
  asset?: AssetSymbol | string;
}

export default function AgentDetail({ asset }: AgentDetailProps) {
  const { agents, feed, spotPrices, lastUpdate, loading } = useAgentWall({ pollMs: 5000 });
  const symbol = (asset ?? '').toUpperCase();
  const agent = agents.find((a) => a.asset === symbol) ?? null;
  const spot = spotPrices[symbol as AssetSymbol];

  const ticker = agent?.market?.ticker;
  const midC = numOr(agent?.market?.mid_c ?? agent?.market?.last_price_c);
  const [mode, setMode] = useState<ChartMode>('spot');

  /* ---------------- live series (accrued from real polls) ---------------- */
  const seriesRef = useRef<{ ticker?: string; spot: PricePoint[]; mid: PricePoint[] }>({ spot: [], mid: [] });
  const [, bump] = useState(0);
  useEffect(() => {
    const r = seriesRef.current;
    if (r.ticker !== ticker) {
      r.ticker = ticker;
      r.spot = [];
      r.mid = [];
    }
    const ts = Math.floor(Date.now() / 1000);
    let changed = false;
    if (spot?.price != null) {
      const last = r.spot[r.spot.length - 1];
      if (!last || last.value !== spot.price) {
        r.spot.push({ time: ts, value: spot.price });
        if (r.spot.length > 240) r.spot.shift();
        changed = true;
      }
    }
    if (midC != null) {
      const last = r.mid[r.mid.length - 1];
      if (!last || last.value !== midC) {
        r.mid.push({ time: ts, value: midC });
        if (r.mid.length > 240) r.mid.shift();
        changed = true;
      }
    }
    if (changed) bump((n) => n + 1);
  }, [ticker, spot?.price, midC, lastUpdate]);

  /* ---------------- orderbook fetch (this view only) ---------------- */
  const [book, setBook] = useState<NormalizedBook | null>(null);
  const [bookErr, setBookErr] = useState<string | null>(null);
  const [bookAt, setBookAt] = useState<number | undefined>(undefined);
  useEffect(() => {
    if (!ticker) {
      setBook(null);
      setBookErr(null);
      return;
    }
    let alive = true;
    const load = async () => {
      try {
        const raw = await getJson<unknown>(AGENT_ENDPOINTS.ORDERBOOK(ticker));
        if (!alive) return;
        setBook(normalizeBook(raw));
        setBookErr(null);
        setBookAt(Date.now());
      } catch (e) {
        if (!alive) return;
        setBookErr(e instanceof Error ? e.message : String(e));
      }
    };
    void load();
    const id = window.setInterval(() => void load(), 5000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [ticker]);

  /* ---------------- feed events for this asset ---------------- */
  const assetEvents = useMemo(
    () => feed.filter((e) => String(e.asset ?? '').toUpperCase() === symbol),
    [feed, symbol],
  );
  const markers = useMemo<PriceMarker[]>(() => {
    if (mode !== 'mid') return [];
    return assetEvents
      .filter((e) => e.kind === 'fill')
      .map((e) => ({
        time: e.ts,
        side: e.side,
        text: e.price_c != null ? `${e.side === 'no' ? 'N' : 'Y'}@${e.price_c}` : undefined,
      }))
      .slice(-30);
  }, [assetEvents, mode]);

  const fillsRows = useMemo(
    () => assetEvents.filter((e) => ['fill', 'exit', 'enter', 'order'].includes(e.kind)).slice(0, 24),
    [assetEvents],
  );

  const chartData = mode === 'spot' ? seriesRef.current.spot : seriesRef.current.mid;
  const strike = mode === 'spot' ? numOr(agent?.market?.strike) : undefined;

  const goBack = useCallback(() => {
    try {
      window.history.back();
    } catch {
      /* no-op */
    }
  }, []);

  /* ---------------- render ---------------- */

  if (loading && !agent) {
    return (
      <div className="space-y-3">
        <Skeleton height={44} className="rounded-xl" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <Skeleton height={320} className="rounded-xl lg:col-span-2" />
          <Skeleton height={320} className="rounded-xl" />
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3">
        <AssetBadge asset={symbol || undefined} size="lg" />
        <div className="text-slate-400 text-sm">
          {symbol ? `no agent data for ${symbol}` : 'no asset selected'}
        </div>
        <div className="text-slate-600 text-xs">
          {ASSETS.includes(symbol as AssetSymbol)
            ? 'the agent may be halted or the backend is unreachable'
            : `expected one of: ${ASSETS.join(', ')}`}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* header */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={goBack}
          className="rounded-lg p-1.5 text-slate-400 hover:text-slate-100 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
          aria-label="back"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <AssetBadge asset={agent.asset} size="lg" />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-slate-100">{agent.asset} agent</h1>
            <StatePill state={agent.state} size="sm" />
          </div>
          <div className="text-[11px] text-slate-500 truncate max-w-xl" title={agent.current_task}>
            {agent.current_task || 'n/a'}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-4 tabular-nums text-right">
          <div>
            <div className="text-[8px] uppercase tracking-widest text-slate-500">ticker</div>
            <div className="text-[11px] text-slate-300">{ticker ?? 'n/a'}</div>
          </div>
          <div>
            <div className="text-[8px] uppercase tracking-widest text-slate-500">yes mid</div>
            <TickFlash value={midC} format={(v) => fmtCents(v)} className="text-sm font-bold text-slate-100" />
          </div>
          <div>
            <div className="text-[8px] uppercase tracking-widest text-slate-500">spot</div>
            <TickFlash
              value={spot?.price}
              format={(v) => `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`}
              className="text-sm font-bold text-slate-100"
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        {/* chart (2/3) */}
        <section className="xl:col-span-2 card p-3 space-y-2" aria-label="price chart">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1" role="tablist" aria-label="chart mode">
              {(['spot', 'mid'] as ChartMode[]).map((mMode) => (
                <button
                  key={mMode}
                  type="button"
                  role="tab"
                  aria-selected={mode === mMode}
                  onClick={() => setMode(mMode)}
                  className={cx(
                    'rounded border px-2 py-0.5 text-[9px] font-bold tracking-widest',
                    mode === mMode
                      ? 'bg-blue-500/20 text-blue-300 border-blue-500/50'
                      : 'text-slate-500 border-slate-700/60 hover:text-slate-300',
                  )}
                >
                  {mMode === 'spot' ? 'SPOT vs STRIKE' : 'YES MID ¢'}
                </button>
              ))}
            </div>
            <span className="text-[9px] text-slate-600 tabular-nums">
              {chartData.length} pts · live-accrual
            </span>
          </div>
          <PriceChart
            data={chartData}
            strike={strike}
            strikeLabel={strike != null ? `strike $${strike.toLocaleString('en-US')}` : 'strike'}
            markers={markers}
            height={280}
            color={mode === 'spot' ? '#38bdf8' : '#10b981'}
            emptyLabel={mode === 'spot' ? 'no spot series yet — accruing from polls' : 'no mid series yet — accruing from polls'}
          />
        </section>

        {/* book ladder + depth (1/3) */}
        <section className="card p-3 space-y-2" aria-label="orderbook">
          <div className="flex items-center justify-between">
            <h2 className="text-[10px] font-bold uppercase tracking-widest text-slate-400">yes book</h2>
            <span className="text-[9px] text-slate-600 tabular-nums">
              {bookErr ? (
                <span className="text-red-400" title={bookErr}>err</span>
              ) : bookAt != null ? (
                `${fmtAgeMs(Date.now() - bookAt)} old`
              ) : 'n/a'}
            </span>
          </div>
          {ticker ? (
            <>
              <OrderBookLadder bids={book?.bids} asks={book?.asks} height={200} maxLevels={10} />
              <DepthChart bids={book?.bids} asks={book?.asks} height={110} />
              <div className="flex items-center justify-between text-[9px] tabular-nums text-slate-500 pt-1 border-t border-slate-800/60">
                <span>spread {book?.spreadC != null ? fmtCents(book.spreadC, 1) : 'n/a'}</span>
                <span>mid {book?.midC != null ? fmtCents(book.midC, 1) : 'n/a'}</span>
                {book?.stale && <span className="text-amber-400">stale book</span>}
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-48 rounded-lg border border-dashed border-slate-800 text-[10px] text-slate-600">
              no active ticker — book unavailable
            </div>
          )}
        </section>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        {/* left column: moneyness + gates + position */}
        <div className="space-y-3">
          <section className="card p-3" aria-label="moneyness">
            <h2 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">moneyness bands</h2>
            <MoneynessGauge asset={agent.asset} priceC={midC ?? undefined} side={agent.last_decision?.side} />
          </section>
          <section className="card p-3" aria-label="last decision">
            <h2 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">last decision</h2>
            <GateFunnel decision={agent.last_decision} width={420} />
          </section>
          <section className="card p-3" aria-label="position">
            <h2 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">position</h2>
            {agent.position ? (
              <PositionBar position={agent.position} />
            ) : (
              <div className="text-[10px] text-slate-600">flat — no open position</div>
            )}
            {agent.last_decision?.rejection_reason && (
              <div className="mt-2 text-[10px] text-amber-400/90">
                veto: {agent.last_decision.rejection_reason}
              </div>
            )}
          </section>
        </div>

        {/* fills/orders sub-table (2/3) */}
        <section className="xl:col-span-2 card p-3" aria-label="fills and orders">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-[10px] font-bold uppercase tracking-widest text-slate-400">fills / orders tape</h2>
            <span className="text-[9px] text-slate-600 tabular-nums">{fillsRows.length} rows</span>
          </div>
          {fillsRows.length === 0 ? (
            <div className="flex items-center justify-center h-32 rounded-lg border border-dashed border-slate-800 text-[10px] text-slate-600">
              no fills/orders on tape for {agent.asset}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] tabular-nums">
                <thead>
                  <tr className="text-[8px] uppercase tracking-widest text-slate-600 border-b border-slate-800">
                    <th className="text-left py-1 pr-3 font-semibold">time</th>
                    <th className="text-left py-1 pr-3 font-semibold">kind</th>
                    <th className="text-left py-1 pr-3 font-semibold">side</th>
                    <th className="text-right py-1 pr-3 font-semibold">price</th>
                    <th className="text-right py-1 pr-3 font-semibold">edge</th>
                    <th className="text-left py-1 font-semibold">summary</th>
                  </tr>
                </thead>
                <tbody>
                  {fillsRows.map((e, i) => (
                    <tr key={`${e.ts}-${i}`} className="border-b border-slate-800/50 last:border-0">
                      <td className="py-1 pr-3 text-slate-500">{fmtClock(e.ts)}</td>
                      <td className="py-1 pr-3">
                        <span className={cx(
                          'font-bold',
                          e.kind === 'fill' ? 'text-blue-400' : e.kind === 'enter' ? 'text-emerald-400' : e.kind === 'exit' ? 'text-orange-400' : 'text-cyan-400',
                        )}>
                          {e.kind.toUpperCase()}
                        </span>
                      </td>
                      <td className={cx('py-1 pr-3 font-semibold', e.side === 'no' ? 'text-red-400' : 'text-emerald-400')}>
                        {e.side?.toUpperCase() ?? '—'}
                      </td>
                      <td className="py-1 pr-3 text-right text-slate-300">{e.price_c != null ? `${e.price_c}c` : 'n/a'}</td>
                      <td className={cx('py-1 pr-3 text-right', (e.edge_c ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400')}>
                        {e.edge_c != null ? fmtSignedCents(e.edge_c) : '—'}
                      </td>
                      <td className="py-1 text-slate-400 max-w-[260px] truncate" title={e.summary}>{e.summary}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* decision tape for the asset */}
      <section className="card p-3" aria-label="asset feed">
        <h2 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">{agent.asset} tape</h2>
        <div className="space-y-0.5 max-h-56 overflow-y-auto">
          {assetEvents.length === 0 ? (
            <div className="text-[10px] text-slate-600 py-4 text-center">no tape events for {agent.asset}</div>
          ) : (
            assetEvents.slice(0, 30).map((e, i) => (
              <div key={`${e.ts}-t-${i}`} className={cx('flex items-center gap-2 text-[10px] py-0.5 border-b border-slate-800/40 last:border-0', e.counterfactual && 'italic opacity-80')}>
                <span className="tabular-nums text-slate-600 w-14 shrink-0">{fmtClock(e.ts)}</span>
                <span className="text-slate-300 flex-1 truncate">{e.summary}</span>
                {e.reason && <span className="text-slate-500 shrink-0">{e.reason}</span>}
                {e.counterfactual && <span className="text-amber-400 font-bold shrink-0">CF</span>}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

