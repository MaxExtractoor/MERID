import { Bell, Search, Menu, Sun, Moon, Settings } from "lucide-react";
import { useTheme } from '../hooks/useTheme';

interface TopBarProps {
  onMenuClick: () => void;
}

export default function TopBar({ onMenuClick }: TopBarProps) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="h-14 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-4 lg:px-6">
      {/* Left side */}
      <div className="flex items-center gap-4">
        {/* Mobile menu button */}
        <button
          onClick={onMenuClick}
          className="p-2 rounded-lg hover:bg-slate-800 transition-colors md:hidden"
          title="Open menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Environment badge */}
        <div className="flex items-center gap-3">
          <span className="px-2 py-1 text-xs font-semibold text-green-400 bg-green-400/10 border border-green-400/30 rounded-full">
            LIVE
          </span>
          
          {/* P&L Summary */}
          <div className="hidden sm:flex items-center gap-2 text-sm">
            <span className="text-slate-400">P&L:</span>
            <span className="font-semibold text-green-400">+$12,847.32</span>
            <span className="text-green-400">(+2.34%)</span>
          </div>
        </div>
      </div>

      {/* Center - Search */}
      <div className="hidden md:block flex-1 max-w-md mx-8">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search symbols, commands, or actions..."
            className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-2">
        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="p-2 rounded-lg hover:bg-slate-800 transition-colors"
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? (
            <Sun className="w-5 h-5" />
          ) : (
            <Moon className="w-5 h-5" />
          )}
        </button>

        {/* Notifications */}
        <button className="p-2 rounded-lg hover:bg-slate-800 transition-colors relative" title="Notifications">
          <Bell className="w-5 h-5" />
          <span className="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full"></span>
        </button>

        {/* Settings */}
        <button className="p-2 rounded-lg hover:bg-slate-800 transition-colors" title="Settings">
          <Settings className="w-5 h-5" />
        </button>

        {/* User avatar */}
        <div className="w-8 h-8 bg-slate-700 rounded-full flex items-center justify-center text-sm font-medium">
          JD
        </div>
      </div>
    </header>
  );
}
