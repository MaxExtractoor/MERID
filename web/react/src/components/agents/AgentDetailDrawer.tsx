/**
 * AgentDetailDrawer — slide-in right panel (~480px) with the full drill on
 * one asset agent: heartbeat tiles, moneyness gauge, last-decision gate
 * funnel, lane strip, position ledger fields, veto waterfall, raw JSON.
 * Closes on Esc and backdrop click.
 */

import { memo, useEffect, useMemo, useState } from 'react';
import type { AssetAgent } from '../../agents/types';
import { LANE_LABELS, freshnessClass } from '../../agents/types';
import type { SpotInfo } from '../../agents/format';
import {
  cx, fmtAgeMs, fmtCents, fmtClock, fmtContracts, fmtSignedCents,
  fmtSignedUsd, numOr,
} from '../../agents/format';
import { AssetBadge } from './AssetBadge';
import { StatePill } from './StatePill';
import { MoneynessGauge } from './MoneynessGauge';
import { GateFunnel } from './GateFunnel';
import { PositionBar } from './PositionBar';
import { LANE_META, freshnessTextClass } from './agentMeta';
import { X } from '../../ui/icons';

/* ------------------------------------------------------------------ */

function HeartbeatTile({ label, ageMs }: { label: string; ageMs?: number }) {
  const cls = freshnessClass(ageMs);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-2">
      <div className="text-[8px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className={cx('tabular-nums text-sm font-bold', freshnessTextClass(cls))}>
        {ageMs != null ? fmtAgeMs(ageMs) : 'n/a'}
      </div>
      <div className="text-[8px] text-slate-600">{cls}</div>
    </div>
  );
}

function LedgerRow({ label, value, tone }: { label: string; value: string; tone?: 'pos' | 'neg' | 'dim' }) {
  return (
    <div className="flex items-center justify-between py-1 border-b border-slate-800/50 last:border-0">
      <span className="text-[10px] text-slate-500">{label}</span>
      <span className={cx(
        'tabular-nums text-[11px] font-medium',
        tone === 'pos' ? 'text-emerald-400' : tone === 'neg' ? 'text-red-400' : tone === 'dim' ? 'text-slate-500' : 'text-slate-200',
      )}>
        {value}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */

export interface AgentDetailDrawerProps {
  agent: AssetAgent | null;
  spot?: SpotInfo;
  open: boolean;
  onClose: () => void;
}

export const AgentDetailDrawer = memo(function AgentDetailDrawer({
  agent,
  spot,
  open,
  onClose,
}: AgentDetailDrawerProps) {
  const [showRaw, setShowRaw] = useState(false);

  // Esc to close.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const waterfallMax = useMemo(() => {
    if (!agent?.veto_waterfall?.length) return 0;
    return Math.max(...agent.veto_waterfall.map((s) => numOr(s.rejected) ?? 0), 1);
  }, [agent?.veto_waterfall]);

  if (!open || !agent) return null;

  const m = agent.market;
  const midC = numOr(m?.mid_c);
  const priceC = midC ?? numOr(m?.last_price_c);
  const d = agent.last_decision;
  const p = agent.position;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={`${agent.asset} agent detail`}>
      {/* backdrop */}
      <button
        type="button"
        aria-label="close detail drawer"
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px] cursor-default"
        onClick={onClose}
      />
      {/* panel */}
      <aside
        className={cx(
          'absolute right-0 top-0 bottom-0 w-full max-w-[480px] overflow-y-auto',
          'bg-slate-950/95 border-l border-slate-800 shadow-2xl',
          'motion-safe:animate-[drawer-in_160ms_ease-out]',
        )}
      >
        <style>{'@keyframes drawer-in { from { transform: translateX(24px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }'}</style>

        {/* header */}
        <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-slate-800 bg-slate-950/95 backdrop-blur px-4 py-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <AssetBadge asset={agent.asset} size="lg" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-slate-100 truncate">{agent.name || agent.asset}</h2>
                <StatePill state={agent.state} size="sm" />
              </div>
              <div className="text-[10px] text-slate-500 truncate" title={agent.current_task}>
                {agent.current_task || 'n/a'}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-100 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
            aria-label="close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-3 space-y-4">
          {/* heartbeat tiles */}
          <section aria-label="heartbeats">
            <div className="grid grid-cols-4 gap-1.5">
              <HeartbeatTile label="EVAL" ageMs={agent.heartbeat.last_eval_ms} />
              <HeartbeatTile label="BOOK" ageMs={agent.heartbeat.book_age_ms} />
              <HeartbeatTile label="WMARK" ageMs={agent.heartbeat.watermark_ms} />
              <HeartbeatTile label="SPOT" ageMs={agent.heartbeat.spot_age_ms} />
            </div>
          </section>

          {/* market strip */}
          <section aria-label="market">
            <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 space-y-1">
              <div className="flex items-center justify-between text-[10px] text-slate-500">
                <span className="truncate max-w-[70%]" title={m?.ticker}>{m?.ticker ?? 'ticker n/a'}</span>
                <span className="tabular-nums">{m?.secs_to_close != null ? `${Math.round(m.secs_to_close)}s to close` : 'window n/a'}</span>
              </div>
              <div className="flex items-baseline gap-3 tabular-nums">
                <span className="text-lg font-bold text-slate-100">{priceC != null ? fmtCents(priceC) : 'n/a'}</span>
                <span className="text-[10px] text-slate-500">
                  bid {m?.yes_bid_c != null ? fmtCents(m.yes_bid_c) : 'n/a'} / ask {m?.yes_ask_c != null ? fmtCents(m.yes_ask_c) : 'n/a'}
                  {m?.spread_c != null && <span> · spr {fmtCents(m.spread_c, 1)}</span>}
                </span>
              </div>
              {spot?.price != null && m?.strike != null && (
                <div className="text-[10px] text-slate-500 tabular-nums">
                  spot ${spot.price.toLocaleString('en-US', { maximumFractionDigits: 2 })} vs strike ${m.strike.toLocaleString('en-US')}
                </div>
              )}
            </div>
          </section>

          {/* moneyness */}
          <section aria-label="moneyness">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">moneyness</h3>
            <MoneynessGauge asset={agent.asset} priceC={priceC ?? undefined} side={d?.side} />
          </section>

          {/* gate funnel */}
          <section aria-label="last decision gates">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">
              last decision{d?.action ? ` — ${d.action}` : ''}{d?.ts ? ` · ${fmtClock(d.ts)}` : ''}
            </h3>
            <GateFunnel decision={d} width={440} />
          </section>

          {/* lanes */}
          <section aria-label="lanes">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">lanes</h3>
            <div className="space-y-1">
              {agent.lanes.map((l) => {
                const meta = LANE_META[l.status] ?? LANE_META.unknown;
                return (
                  <div key={l.lane} className="flex items-center gap-2 text-[10px]">
                    <span className={cx('w-14 shrink-0 rounded border px-1 py-0.5 text-center text-[8px] font-bold', meta.cell)}>
                      {LANE_LABELS[l.lane] ?? l.lane}
                    </span>
                    <span className={cx('tabular-nums font-medium w-16 shrink-0', meta.text)}>{l.status}</span>
                    <span className="flex-1 min-w-0 truncate text-slate-500" title={l.reason}>
                      {l.reason ?? 'n/a'}
                    </span>
                    {l.last_order_ts && (
                      <span className="tabular-nums text-slate-600 shrink-0">{fmtClock(l.last_order_ts)}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          {/* position ledger */}
          <section aria-label="position ledger">
            <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">position</h3>
            {p ? (
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 space-y-1.5">
                <PositionBar position={p} />
                <LedgerRow label="side" value={p.side.toUpperCase()} />
                <LedgerRow label="quantity" value={`${fmtContracts(p.qty_centi)} contracts (${p.qty_centi}cc)`} />
                <LedgerRow label="avg price" value={p.avg_price_c != null ? fmtCents(p.avg_price_c, 2) : 'n/a'} />
                <LedgerRow
                  label="unrealized pnl"
                  value={p.unrealized_pnl_c != null ? fmtSignedCents(p.unrealized_pnl_c) : 'n/a'}
                  tone={p.unrealized_pnl_c == null ? 'dim' : p.unrealized_pnl_c >= 0 ? 'pos' : 'neg'}
                />
                <LedgerRow
                  label="exits armed"
                  value={p.exits_armed == null ? 'n/a' : p.exits_armed ? 'yes' : 'NO'}
                  tone={p.exits_armed === false ? 'neg' : undefined}
                />
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-slate-800 px-3 py-2 text-[11px] text-slate-600">
                flat — no open position
              </div>
            )}
            {agent.pnl && (
              <div className="grid grid-cols-3 gap-1.5 mt-2">
                <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1.5">
                  <div className="text-[8px] uppercase tracking-widest text-slate-500">realized</div>
                  <div className="tabular-nums text-xs font-bold text-slate-200">{agent.pnl.realized_c != null ? fmtSignedUsd(agent.pnl.realized_c / 100) : 'n/a'}</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1.5">
                  <div className="text-[8px] uppercase tracking-widest text-slate-500">session</div>
                  <div className="tabular-nums text-xs font-bold text-slate-200">{agent.pnl.session_c != null ? fmtSignedUsd(agent.pnl.session_c / 100) : 'n/a'}</div>
                </div>
                <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-2.5 py-1.5">
                  <div className="text-[8px] uppercase tracking-widest text-slate-500">fills 24h</div>
                  <div className="tabular-nums text-xs font-bold text-slate-200">{agent.pnl.fills_24h != null ? String(agent.pnl.fills_24h) : 'n/a'}</div>
                </div>
              </div>
            )}
          </section>

          {/* veto waterfall */}
          {agent.veto_waterfall && agent.veto_waterfall.length > 0 && (
            <section aria-label="veto waterfall">
              <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">veto waterfall</h3>
              <div className="space-y-1">
                {agent.veto_waterfall.map((s, i) => {
                  const n = numOr(s.rejected) ?? 0;
                  const pct = Math.max(2, (n / waterfallMax) * 100);
                  return (
                    <div key={`${s.stage}-${i}`} className="flex items-center gap-2 text-[10px]" title={s.final_reason ?? s.stage}>
                      <span className="w-24 shrink-0 truncate text-slate-400">{s.stage}</span>
                      <div className="flex-1 h-3 rounded-sm bg-slate-800/70 overflow-hidden">
                        <div className="h-full rounded-sm bg-amber-500/50" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="tabular-nums w-8 text-right text-slate-400">{n}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* edge context */}
          {agent.edge && (
            <section aria-label="edge">
              <h3 className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">edge</h3>
              <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-1">
                <LedgerRow label="net ev" value={agent.edge.net_ev_c != null ? fmtSignedCents(agent.edge.net_ev_c) : 'n/a'} tone={agent.edge.net_ev_c != null && agent.edge.net_ev_c >= 0 ? 'pos' : 'neg'} />
                <LedgerRow label="threshold" value={agent.edge.threshold_c != null ? fmtCents(agent.edge.threshold_c, 1) : 'n/a'} />
                <LedgerRow label="model p" value={agent.edge.model_p != null ? `${(agent.edge.model_p * 100).toFixed(1)}%` : 'n/a'} />
                <LedgerRow label="market p" value={agent.edge.market_p != null ? `${(agent.edge.market_p * 100).toFixed(1)}%` : 'n/a'} />
                <LedgerRow label="calibrated" value={agent.edge.calibrated == null ? 'n/a' : agent.edge.calibrated ? 'yes' : 'no'} />
              </div>
            </section>
          )}

          {/* raw json */}
          <section aria-label="raw payload">
            <button
              type="button"
              onClick={() => setShowRaw((v) => !v)}
              aria-expanded={showRaw}
              className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 hover:text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500/50 rounded"
            >
              {showRaw ? '▾ raw payload' : '▸ raw payload'}
            </button>
            {showRaw && (
              <pre className="mt-1.5 max-h-72 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-2 text-[9px] leading-4 text-slate-400">
                {JSON.stringify(agent.raw ?? agent, null, 2)}
              </pre>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
});

export default AgentDetailDrawer;
