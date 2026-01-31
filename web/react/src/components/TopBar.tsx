import { Bell, Search, Menu, Sun, Moon, Settings } from "lucide-react";
import { useTheme } from '../theme';

interface TopBarProps {
  onMenuClick: () => void;
}

export default function TopBar({ onMenuClick }: TopBarProps) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="h-14 bg-slate-900/95 backdrop-blur-sm border-b border-slate-800/50 flex items-center justify-between px-4 lg:px-6">
      {/* Left side */}
      <div className="flex items-center gap-4">
        {/* Mobile menu button */}
        <button
          onClick={onMenuClick}
          className="p-2 rounded-lg hover:bg-slate-800/50 transition-all hover:scale-105 md:hidden"
          title="Open menu"
        >
          <Menu className="w-5 h-5 text-slate-300" />
        </button>

        {/* Environment badge */}
        <div className="flex items-center gap-3">
          <span className="px-3 py-1 text-xs font-bold text-emerald-400 bg-emerald-400/10 border border-emerald-400/30 rounded-full shadow-sm shadow-emerald-400/20">
            ● LIVE
          </span>
          
          {/* P&L Summary */}
          <div className="hidden sm:flex items-center gap-3 px-3 py-1.5 bg-gradient-to-r from-green-500/10 to-emerald-500/10 border border-green-500/20 rounded-lg">
            <span className="text-slate-400 text-sm">P&L:</span>
            <span className="font-bold text-emerald-400">+$12,847.32</span>
            <span className="text-emerald-400 text-sm font-medium">(+2.34%)</span>
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
            className="w-full pl-10 pr-4 py-2.5 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:border-blue-500 focus:bg-slate-800/70 transition-all"
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
        <button className="p-2 rounded-lg hover:bg-slate-800/50 transition-all hover:scale-105 relative" title="Notifications">
          <Bell className="w-5 h-5 text-slate-300" />
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full animate-pulse"></span>
        </button>

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
