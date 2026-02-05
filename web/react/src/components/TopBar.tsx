import { Search, Menu, Sun, Moon, Settings } from "lucide-react";
import { useTheme } from '../theme';
import LiveNotifications from './LiveNotifications';

interface TopBarProps {
  onMenuClick: () => void;
}

export default function TopBar({ onMenuClick }: TopBarProps) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="h-16 bg-gradient-to-r from-slate-900/95 via-slate-800/95 to-slate-900/95 backdrop-blur-md border-b border-slate-700/50 shadow-xl shadow-black/20 flex items-center justify-between px-4 lg:px-6">
      {/* Left side */}
      <div className="flex items-center gap-4">
        {/* Mobile menu button */}
        <button
          onClick={onMenuClick}
          className="p-2 rounded-lg hover:bg-slate-700/50 transition-all hover:scale-105 md:hidden"
          title="Open menu"
        >
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
          <span className="px-3 py-1 text-xs font-bold text-emerald-400 bg-gradient-to-r from-emerald-500/20 to-teal-500/20 border border-emerald-400/50 rounded-full shadow-lg shadow-emerald-500/30 animate-pulse-slow">
            <span className="inline-block w-2 h-2 bg-emerald-400 rounded-full mr-1.5 animate-pulse"></span>
            LIVE
          </span>
          
          {/* P&L Summary */}
          <div className="hidden sm:flex items-center gap-3 px-4 py-2 bg-gradient-to-r from-emerald-500/10 via-green-500/10 to-teal-500/10 border border-emerald-500/30 rounded-lg shadow-lg shadow-emerald-500/20">
            <span className="text-slate-300 text-sm font-medium">Daily P&L:</span>
            <span className="font-bold text-emerald-400 text-lg">+$12,847.32</span>
            <span className="text-emerald-400 text-sm font-semibold bg-emerald-500/20 px-2 py-0.5 rounded">(+2.34%)</span>
          </div>
        </div>
      </div>

      {/* Center - Search */}
      <div className="hidden md:block flex-1 max-w-md mx-8">
        <div className="relative group">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-blue-400 transition-colors" />
          <input
            type="text"
            placeholder="Search symbols, commands, or actions..."
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-slate-200 placeholder-slate-400 focus:outline-none focus:border-blue-500 focus:bg-slate-800/70 focus:shadow-lg focus:shadow-blue-500/20 transition-all"
          />
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2">
        {/* Theme toggle */}
        <button
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

        {/* Notifications */}
        <LiveNotifications />

        {/* Settings */}
        <button className="p-2 rounded-lg hover:bg-slate-800/50 transition-all hover:scale-105" title="Settings">
          <Settings className="w-5 h-5 text-slate-300" />
        </button>

        {/* User avatar */}
        <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center text-sm font-bold text-white shadow-lg shadow-blue-500/25">
          JD
        </div>
      </div>
    </header>
  );
}
