import React, { useEffect, useState } from "react";
import { Search, Menu, Settings } from '../ui/icons';
import { useKalshiStore, selectSystem, selectPortfolio } from '../store';
import type { View } from '../types/views';
import ConnectionStatusIndicator from './ConnectionStatusIndicator';

export interface TopBarProps {
  onMenuClick: () => void;
  onNavigate?: (v: View) => void;
  onOpenSearch?: () => void;
}

/** Seconds until the next 15m market window boundary (:00/:15/:30/:45). */
function secsToWindowClose(nowMs: number): number {
  const next = (Math.floor(nowMs / 900_000) + 1) * 900_000;
  return Math.max(0, Math.round((next - nowMs) / 1000));
}

function fmtClock(d: Date): string {
  return d.toLocaleTimeString('en-US', { hour12: false });
}

function fmtCountdown(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** Live UTC clock + 15m window countdown chip. */
const WindowClock: React.FC = () => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const secs = secsToWindowClose(now);
  const urgent = secs <= 60;
  return (
    <div className="hidden lg:flex items-center gap-3 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50">
      <span className="text-sm font-medium tabular-nums text-slate-300" title="Local time">
        {fmtClock(new Date(now))}
      </span>
      <span className="text-slate-600">·</span>
      <span
        className={`text-sm font-bold tabular-nums ${urgent ? 'text-amber-400' : 'text-cyan-300'}`}
        title="Time to 15m window close"
      >
        ⏱ {fmtCountdown(secs)}
      </span>
    </div>
  );
};

function TopBar({ onMenuClick, onNavigate, onOpenSearch }: TopBarProps) {
  const system = useKalshiStore(selectSystem);
  const portfolio = useKalshiStore(selectPortfolio);

  // Honest live-entry state from the store — populated by the real
  // /api/v1/live-runtime-state endpoint, not a legacy mode context.
  const liveState = system.live?.state ?? null;
  const isLive = liveState === 'LIVE_ENTRIES_ENABLED';
  const entriesHalted = liveState === 'LIVE_ENTRIES_HALTED';

  // Truthful display: until the first authoritative portfolio fetch lands
  // (lastOk set by refreshAll), show n/a — "$0.00" is a real-looking lie.
  const hasData = portfolio.lastOk != null;
  const dailyPnl = portfolio.daily_pnl;
  const pnlPositive = dailyPnl >= 0;
  // Account balance = equity (available cash + positions), NOT
  // portfolio.portfolio_value — that field is positions-value-only, so the
  // chip collapsed to just the new position's mark the moment a fill landed.
  const balanceUsd = portfolio.balance || portfolio.cash || null;

  return (
    <header className="h-16 bg-gradient-to-r from-slate-900/95 via-slate-800/95 to-slate-900/95 backdrop-blur-md border-b border-slate-700/50 shadow-xl shadow-black/20 flex items-center justify-between px-4 lg:px-6">
      {/* Left side */}
      <div className="flex items-center gap-4">
        {/* Mobile menu button */}
        <button type="button"
          onClick={onMenuClick}
          className="p-2 rounded-lg hover:bg-slate-700/50 transition-all hover:scale-105 md:hidden"
          title="Open menu"
         aria-label="Menu">
          <Menu className="w-5 h-5 text-slate-300" />
        </button>

        {/* MERID Logo & Brand */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-blue-500 via-purple-500 to-pink-500 rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/50">
            <span className="text-white font-bold text-sm">M</span>
          </div>
          <div className="hidden lg:block">
            <h1 className="text-lg font-bold bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
              MERID
            </h1>
            <p className="text-xs text-slate-400 -mt-1">Multi-Agent Trading System</p>
          </div>
        </div>

        {/* Environment badge — truthful live runtime state */}
        <div className="flex items-center gap-3">
          <span className={`px-3 py-1 text-xs font-bold rounded-full shadow-lg ${
            isLive
              ? 'text-red-400 bg-gradient-to-r from-red-500/20 to-rose-500/20 border border-red-400/50 shadow-red-500/30'
              : entriesHalted
                ? 'text-amber-400 bg-gradient-to-r from-amber-500/20 to-yellow-500/20 border border-amber-400/50 shadow-amber-500/30'
                : 'text-slate-400 bg-slate-700/40 border border-slate-500/50'
          }`}>
            <span className={`inline-block w-2 h-2 rounded-full mr-1.5 animate-pulse ${
              isLive ? 'bg-red-400' : entriesHalted ? 'bg-amber-400' : 'bg-slate-400'
            }`}></span>
            {isLive ? 'LIVE' : entriesHalted ? 'ENTRIES HALTED' : 'STATE UNKNOWN'}
          </span>

          {/* Kalshi Balance + Daily P&L */}
          <div className={`hidden sm:flex items-center gap-3 px-4 py-2 bg-gradient-to-r rounded-lg shadow-lg ${
            pnlPositive
              ? 'from-emerald-500/10 via-green-500/10 to-teal-500/10 border border-emerald-500/30 shadow-emerald-500/20'
              : 'from-red-500/10 via-red-500/10 to-rose-500/10 border border-red-500/30 shadow-red-500/20'
          }`}>
            <span className="text-slate-300 text-sm font-medium tabular-nums">
              {hasData && balanceUsd != null
                ? balanceUsd.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
                : 'n/a'}
            </span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-300 text-sm font-medium">P&L:</span>
            <span className={`font-bold text-lg tabular-nums ${!hasData ? 'text-slate-400' : pnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
              {hasData
                ? `${pnlPositive ? '+' : ''}${dailyPnl.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}`
                : 'n/a'}
            </span>
          </div>

          {/* Live clock + 15m window countdown */}
          <WindowClock />
        </div>
      </div>

      {/* Center - Search (opens command palette) */}
      <div className="hidden md:block flex-1 max-w-md mx-8">
        <div className="relative group">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-400 transition-colors" />
          <input aria-label="Search symbols, commands, or actions..."
            id="global-search"
            name="globalSearch"
            type="text"
            readOnly
            onClick={() => onOpenSearch?.()}
            onFocus={() => onOpenSearch?.()}
            placeholder="Search symbols, commands, or actions...  (Ctrl+K)"
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500 focus:bg-slate-800/70 focus:shadow-lg focus:shadow-blue-500/20 transition-all cursor-pointer"
          />
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2">
        {/* No theme toggle — every surface hardcodes slate-dark styling, so a
            light-mode switch renders an unreadable dark-on-white hybrid. The
            console is dark-only until a real light theme exists. */}
        {/* Connection Status */}
        <ConnectionStatusIndicator />

        {/* Settings */}
        <button type="button"
          onClick={() => onNavigate?.('system')}
          className="p-2 rounded-lg hover:bg-slate-800/50 transition-all hover:scale-105"
          title="System"
          aria-label="System"
        >
          <Settings className="w-5 h-5 text-slate-300" />
        </button>

        {/* User avatar */}
        <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-sm font-bold text-white shadow-lg shadow-blue-500/25" title="Operator">
          OP
        </div>
      </div>
    </header>
  );
}

TopBar.displayName = 'TopBar';
const MemoizedTopBar = React.memo(TopBar);
export default MemoizedTopBar;
