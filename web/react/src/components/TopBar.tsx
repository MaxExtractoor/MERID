import React from "react";
import { Search, Menu, Sun, Moon, Settings } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';
import { useTheme } from '../theme';
import { useKalshiMode } from '../context/KalshiModeContext';
import type { View } from '../types/views';
import LiveNotifications from './LiveNotifications';
import ConnectionStatusIndicator from './ConnectionStatusIndicator';

export interface TopBarProps {
  onMenuClick: () => void;
  onNavigate?: (v: View) => void;
  onOpenSearch?: () => void;
}

function TopBar({ onMenuClick }: TopBarProps) {
  const { theme, toggleTheme } = useTheme();

  const { data: pnlData } = useApiData<{ daily_pnl_usd?: number }>(
    API_ENDPOINTS.KALSHI_PNL,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const { data: balData } = useApiData<{ available?: number }>(
    API_ENDPOINTS.KALSHI_BALANCE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const { isLive } = useKalshiMode();

  const dailyPnl = pnlData?.daily_pnl_usd ?? 0;
  const pnlPositive = dailyPnl >= 0;

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
          <div className="w-8 h-8 bg-gradient-to-br from-blue-500 via-purple-500 to-pink-500 rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/50 animate-glow">
            <span className="text-white font-bold text-sm">M</span>
          </div>
          <div className="hidden lg:block">
            <h1 className="text-lg font-bold bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
              MERID
            </h1>
            <p className="text-xs text-slate-400 -mt-1">Multi-Agent Trading System</p>
          </div>
        </div>

        {/* Environment badge */}
        <div className="flex items-center gap-3">
          <span className={`px-3 py-1 text-xs font-bold rounded-full shadow-lg animate-pulse-slow ${
            isLive
              ? 'text-red-400 bg-gradient-to-r from-red-500/20 to-rose-500/20 border border-red-400/50 shadow-red-500/30'
              : 'text-amber-400 bg-gradient-to-r from-amber-500/20 to-yellow-500/20 border border-amber-400/50 shadow-amber-500/30'
          }`}>
            <span className={`inline-block w-2 h-2 rounded-full mr-1.5 animate-pulse ${
              isLive ? 'bg-red-400' : 'bg-amber-400'
            }`}></span>
            {isLive ? 'LIVE' : 'PAPER'}
          </span>
          
          {/* Kalshi Balance + Daily P&L */}
          <div className={`hidden sm:flex items-center gap-3 px-4 py-2 bg-gradient-to-r rounded-lg shadow-lg ${
            pnlPositive
              ? 'from-emerald-500/10 via-green-500/10 to-teal-500/10 border border-emerald-500/30 shadow-emerald-500/20'
              : 'from-red-500/10 via-red-500/10 to-rose-500/10 border border-red-500/30 shadow-red-500/20'
          }`}>
            {balData?.available != null && (
              <span className="text-slate-300 text-sm font-medium">
                {(balData.available ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
              </span>
            )}
            {balData?.available != null && <span className="text-slate-600">·</span>}
            <span className="text-slate-300 text-sm font-medium">P&L:</span>
            <span className={`font-bold text-lg ${pnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
              {pnlPositive ? '+' : ''}{(dailyPnl ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
            </span>
          </div>
        </div>
      </div>

      {/* Center - Search */}
      <div className="hidden md:block flex-1 max-w-md mx-8">
        <div className="relative group">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-400 transition-colors" />
          <input aria-label="Search symbols, commands, or actions..."
            id="global-search"
            name="globalSearch"
            type="text"
            placeholder="Search symbols, commands, or actions..."
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500 focus:bg-slate-800/70 focus:shadow-lg focus:shadow-blue-500/20 transition-all"
          />
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2">
        {/* Theme toggle */}
        <button type="button"
          onClick={toggleTheme}
          className="p-2 rounded-lg hover:bg-slate-800/50 transition-all hover:scale-105"
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? (
            <Sun className="w-5 h-5 text-yellow-400" />
          ) : (
            <Moon className="w-5 h-5 text-slate-600" />
          )}
        </button>

        {/* Connection Status */}
        <ConnectionStatusIndicator />

        {/* Notifications */}
        <LiveNotifications />

        {/* Settings */}
        <button type="button" className="p-2 rounded-lg hover:bg-slate-800/50 transition-all hover:scale-105" title="Settings" aria-label="Settings">
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
export default React.memo(TopBar);
