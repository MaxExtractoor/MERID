/**
 * SystemRibbon — the wall's top strip: live-entries verdict, bankroll +
 * trading-shard collateral, per-source feed-age chips, 15m window
 * countdown, and the EMERGENCY HALT / RELEASE control.
 *
 * The halt control is deliberately defensive:
 *   - two-click arm -> confirm, auto-disarms after ~5s
 *   - in-flight requests guarded by a ref (no double-submit)
 *   - errors surfaced inline; a successful action triggers an
 *     authoritative refetch via `onRefresh`
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { haltEntries, releaseEntries } from '../../agents/api';
import { freshnessClass } from '../../agents/types';
import type { WallSources } from '../../agents/useAgentWall';
import type { AgentWallRibbon } from '../../agents/useAgentWall';
import { tradingShardCents } from '../../agents/useAgentWall';
import { cx, fmtAgeMs, fmtCentsAsUsd, fmtMMSS, secsToQuarterEnd } from '../../agents/format';
import { useNow } from '../../agents/hooks';
import { freshnessTextClass } from './agentMeta';
import { Ban, Play } from '../../ui/icons';

/* ------------------------------------------------------------------ */

type ArmState = 'idle' | 'armed' | 'busy';

interface MoneyButtonProps {
  halted: boolean;
  onApplied: () => void;
}

/**
 * Two-step arm -> confirm money control. Shows HALT when entries are live,
 * RELEASE when halted. Never fires twice concurrently.
 */
function MoneyButton({ halted, onApplied }: MoneyButtonProps) {
  const [arm, setArm] = useState<ArmState>('idle');
  const [error, setError] = useState<string | null>(null);
  const inFlightRef = useRef(false);
  const disarmTimerRef = useRef<number | null>(null);

  const clearDisarm = useCallback(() => {
    if (disarmTimerRef.current != null) {
      window.clearTimeout(disarmTimerRef.current);
      disarmTimerRef.current = null;
    }
  }, []);

  useEffect(() => clearDisarm, [clearDisarm]);
  // Re-arm state resets whenever the authoritative verdict flips.
  const haltedRef = useRef(halted);
  if (haltedRef.current !== halted) {
    haltedRef.current = halted;
    if (arm === 'armed') setArm('idle');
  }

  const handleClick = useCallback(async () => {
    if (inFlightRef.current) return;
    if (arm === 'idle') {
      setArm('armed');
      setError(null);
      clearDisarm();
      disarmTimerRef.current = window.setTimeout(() => setArm('idle'), 5000);
      return;
    }
    if (arm !== 'armed') return;
    clearDisarm();
    setArm('busy');
    inFlightRef.current = true;
    try {
      if (halted) {
        await releaseEntries();
      } else {
        await haltEntries('operator_halt_ui');
      }
      setArm('idle');
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setArm('idle');
    } finally {
      inFlightRef.current = false;
    }
  }, [arm, halted, onApplied, clearDisarm]);

  const base = halted
    ? 'border-emerald-500/60 bg-emerald-600/20 text-emerald-300 hover:bg-emerald-600/30'
    : 'border-red-500/60 bg-red-600/15 text-red-300 hover:bg-red-600/25';
  const armedCls = halted
    ? 'border-emerald-400 bg-emerald-600 text-white shadow-[0_0_16px_rgba(16,185,129,0.5)]'
    : 'border-red-400 bg-red-600 text-white shadow-[0_0_16px_rgba(239,68,68,0.55)]';

  return (
    <span className="inline-flex flex-col items-end gap-0.5">
      <button
        type="button"
        onClick={() => void handleClick()}
        disabled={arm === 'busy'}
        className={cx(
          'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-bold tracking-wide',
          'transition-all duration-150 active:scale-[0.97] disabled:opacity-60 disabled:cursor-not-allowed',
          'focus:outline-none focus:ring-2 focus:ring-red-500/50 motion-reduce:transition-none',
          arm === 'armed' ? armedCls : base,
        )}
        aria-label={halted ? 'release entries halt' : 'emergency halt entries'}
        title={
          arm === 'armed'
            ? 'click again to confirm'
            : halted
              ? 'Release halt — backend release assertion must pass'
              : 'Emergency halt — blocks new entries; exits/cancels stay live'
        }
      >
        {halted ? <Play className="w-3.5 h-3.5" /> : <Ban className="w-3.5 h-3.5" />}
        {arm === 'busy'
          ? (halted ? 'RELEASING…' : 'HALTING…')
          : arm === 'armed'
            ? (halted ? 'CONFIRM RELEASE' : 'CONFIRM HALT')
            : (halted ? 'RELEASE ENTRIES' : 'EMERGENCY HALT')}
      </button>
      {error && (
        <span className="text-[9px] text-red-400 max-w-[220px] text-right truncate" title={error}>
          {error}
        </span>
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ */

function SourceAgeChip({ label, lastOkMs, failed, now }: { label: string; lastOkMs?: number; failed: boolean; now: number }) {
  if (failed) {
    return (
      <span className="tabular-nums rounded border border-red-500/40 bg-red-500/10 px-1 py-px text-[8px] font-bold text-red-400" title="source error">
        {label} ERR
      </span>
    );
  }
  const ageMs = lastOkMs != null ? now - lastOkMs : undefined;
  const cls = freshnessClass(ageMs);
  return (
    <span
      className={cx('tabular-nums rounded border border-slate-700/50 bg-slate-800/50 px-1 py-px text-[8px] font-medium', freshnessTextClass(cls))}
      title={`${label} source age ${ageMs != null ? fmtAgeMs(ageMs) : 'n/a'}`}
    >
      {label} {ageMs != null ? fmtAgeMs(ageMs) : 'n/a'}
    </span>
  );
}

/* ------------------------------------------------------------------ */

export interface SystemRibbonProps {
  ribbon: AgentWallRibbon;
  sources: WallSources;
  /** Authoritative refetch after halt/release or manual refresh. */
  onRefresh: () => void;
  className?: string;
}

export const SystemRibbon = memo(function SystemRibbon({ ribbon, sources, onRefresh, className = '' }: SystemRibbonProps) {
  const now = useNow(1000);
  const { runtime, balance } = ribbon;

  const live = runtime?.state === 'LIVE_ENTRIES_ENABLED';
  const halted = runtime?.entry_halted === true || runtime?.state === 'LIVE_ENTRIES_HALTED';
  const verdictKnown = live || halted;
  const shardCents = tradingShardCents(balance);
  const windowSecs = secsToQuarterEnd(now);

  return (
    <div
      className={cx(
        'flex items-center gap-3 flex-wrap rounded-xl border px-3 py-2 backdrop-blur-sm',
        live
          ? 'border-emerald-500/40 bg-emerald-950/30 shadow-[0_0_24px_rgba(16,185,129,0.12)]'
          : halted
            ? 'border-red-500/40 bg-red-950/30 shadow-[0_0_24px_rgba(239,68,68,0.12)]'
            : 'border-slate-700/50 bg-slate-900/70',
        className,
      )}
      role="status"
      aria-label="system ribbon"
    >
      {/* verdict */}
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={cx(
            'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-black tracking-widest',
            live
              ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/50'
              : halted
                ? 'bg-red-500/15 text-red-300 border-red-500/50'
                : 'bg-slate-600/15 text-slate-400 border-slate-600/50 border-dashed',
          )}
        >
          <span className="relative flex h-1.5 w-1.5">
            {verdictKnown && (
              <span className={cx('motion-safe:animate-ping absolute inline-flex h-full w-full rounded-full opacity-60', live ? 'bg-emerald-400' : 'bg-red-400')} />
            )}
            <span className={cx('relative inline-flex rounded-full h-1.5 w-1.5', live ? 'bg-emerald-400' : halted ? 'bg-red-400' : 'bg-slate-500')} />
          </span>
          {live ? 'LIVE ENTRIES ENABLED' : halted ? 'ENTRIES HALTED' : 'STATE n/a'}
        </span>
        {(runtime?.reason || runtime?.reason_code) && (
          <span className="text-[10px] text-slate-400 truncate max-w-[280px]" title={runtime.reason ?? runtime.reason_code}>
            {runtime.reason ?? runtime.reason_code}
          </span>
        )}
      </div>

      <span className="hidden sm:block h-5 w-px bg-slate-700/70" aria-hidden="true" />

      {/* bankroll + trading shard */}
      <div className="flex items-center gap-3">
        <div className="flex flex-col leading-tight">
          <span className="text-[8px] uppercase tracking-widest text-slate-500">bankroll</span>
          <span className="tabular-nums text-sm font-bold text-slate-100">
            {balance?.balance_cents != null ? fmtCentsAsUsd(balance.balance_cents) : 'n/a'}
          </span>
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-[8px] uppercase tracking-widest text-slate-500">
            shard{balance?.trading_shard != null ? ` ${balance.trading_shard}` : ''}
          </span>
          <span className={cx('tabular-nums text-sm font-bold', shardCents != null ? 'text-emerald-300' : 'text-slate-500')}
            title="trading-shard collateral — backs 15m orders">
            {shardCents != null ? fmtCentsAsUsd(shardCents) : 'n/a'}
          </span>
        </div>
        {ribbon.grid?.mode && (
          <div className="flex flex-col leading-tight">
            <span className="text-[8px] uppercase tracking-widest text-slate-500">mode</span>
            <span className="text-sm font-bold text-slate-300 uppercase">{ribbon.grid.mode}</span>
          </div>
        )}
      </div>

      <span className="hidden md:block h-5 w-px bg-slate-700/70" aria-hidden="true" />

      {/* source freshness chips */}
      <div className="flex items-center gap-1 flex-wrap">
        <SourceAgeChip label="AGT" lastOkMs={sources.agents.lastOkMs} failed={sources.agents.attempted && !sources.agents.ok} now={now} />
        <SourceAgeChip label="FEED" lastOkMs={sources.feed.lastOkMs} failed={sources.feed.attempted && !sources.feed.ok} now={now} />
        <SourceAgeChip label="MKT" lastOkMs={sources.markets.lastOkMs} failed={sources.markets.attempted && !sources.markets.ok} now={now} />
        <SourceAgeChip label="BAL" lastOkMs={sources.balance.lastOkMs} failed={sources.balance.attempted && !sources.balance.ok} now={now} />
      </div>

      {/* right cluster: window countdown + money button */}
      <div className="ml-auto flex items-center gap-3">
        <div className="flex flex-col items-end leading-tight" title="time to next 15m window boundary">
          <span className="text-[8px] uppercase tracking-widest text-slate-500">15m close</span>
          <span className={cx('tabular-nums text-lg font-black leading-5', windowSecs < 60 ? 'text-red-400' : 'text-slate-100')}>
            {fmtMMSS(windowSecs)}
          </span>
        </div>
        <MoneyButton halted={halted} onApplied={onRefresh} />
      </div>
    </div>
  );
});

export default SystemRibbon;
