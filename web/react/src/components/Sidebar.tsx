import React from 'react';
import { 
  LayoutDashboard, 
  ShieldAlert,
  Terminal,
  Monitor,
  Briefcase,
  Gauge,
  LayoutGrid,
  Search,
  Award,
  Sliders,
  Settings as SettingsIcon,
  Activity,
  GitBranch,
  Target,
  Grid,
} from 'lucide-react';
import type { View } from '../types/views';
import { useKalshiMode } from '../context/KalshiModeContext';

interface SidebarProps {
  current: View;
  onChange: (view: View) => void;
  className?: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

/* ── Sidebar groups aligned to the Kalshi swarm workflow ──────────── */

const tradingCore = [
  { name: 'Overview', href: 'overview', icon: LayoutDashboard, color: 'text-blue-400' },
  { name: 'Terminal', href: 'kalshi-terminal', icon: Monitor, color: 'text-orange-400' },
  { name: 'Markets', href: 'kalshi-dashboard', icon: Search, color: 'text-orange-300' },
  { name: 'Portfolio', href: 'kalshi-portfolio', icon: Briefcase, color: 'text-orange-300' },
];

const swarmIntelligence = [
  { name: 'Agent Grid', href: 'kalshi-grid', icon: LayoutGrid, color: 'text-orange-500' },
  { name: 'Swarm Matrix', href: 'swarm-consensus', icon: Grid, color: 'text-cyan-500' },
  { name: 'Performance', href: 'kalshi-performance', icon: Award, color: 'text-emerald-400' },
  { name: 'Calibration', href: 'calibration-dashboard', icon: Target, color: 'text-rose-400' },
  { name: 'Lane Control', href: 'lane-control', icon: GitBranch, color: 'text-violet-400' },
];

const analytics = [
  { name: 'Fear/Greed', href: 'kalshi-sentiment', icon: Activity, color: 'text-rose-400' },
  { name: 'Vol & Sizing', href: 'kalshi-vol-dashboard', icon: Gauge, color: 'text-purple-400' },
];

const operatorSection = [
  { name: 'Operator', href: 'operator', icon: Sliders, color: 'text-indigo-400' },
  { name: 'Kill Switch', href: 'kill-switch', icon: ShieldAlert, color: 'text-red-400' },
];

const system = [
  { name: 'Logs', href: 'logs', icon: Terminal, color: 'text-gray-400' },
  { name: 'Settings', href: 'settings', icon: SettingsIcon, color: 'text-gray-400' },
];

function NavItem({ item, current, onChange, collapsed, isLive }: { item: typeof tradingCore[0]; current: View; onChange: (v: View) => void; collapsed: boolean; isLive?: boolean }) {
  const Icon = item.icon;
  const isActive = current === item.href;
  const showModeDot = item.href === 'kalshi-dashboard' || item.href === 'kalshi-grid' || item.href === 'kalshi-terminal';
  return (
    <button type="button"
      onClick={() => onChange(item.href as View)}
      title={collapsed ? item.name : undefined}
      className={`
        w-full flex items-center ${collapsed ? 'justify-center' : 'gap-3'} px-3 py-2 text-sm font-medium rounded-lg transition-colors
        ${isActive
          ? 'bg-blue-600 text-white'
          : `${item.color} hover:bg-slate-800 hover:text-white`
        }
      `}
    >
      <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-white' : item.color}`} />
      {!collapsed && (
        <span className="flex-1 flex items-center justify-between">
          {item.name}
          {showModeDot && isLive !== undefined && (
            <span
              className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
                isLive
                  ? 'bg-green-500/20 text-green-400'
                  : 'bg-amber-500/15 text-amber-500'
              }`}
              title={isLive ? 'Live trading active' : 'Paper mode'}
            >
              {isLive ? '● LIVE' : '○ PAPER'}
            </span>
          )}
        </span>
      )}
    </button>
  );
}

function SectionHeader({ label, collapsed }: { label: string; collapsed: boolean }) {
  if (collapsed) return null;
  return <h3 className="px-3 text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">{label}</h3>;
}

function Sidebar({ current, onChange, className, collapsed = false, onToggleCollapse }: SidebarProps) {
  const { data: modeData, isLive } = useKalshiMode();

  const primarySections = [
    { label: 'Trading', items: tradingCore },
    { label: 'Swarm Intelligence', items: swarmIntelligence },
    { label: 'Analytics', items: analytics },
    { label: 'Operator', items: operatorSection },
    { label: 'System', items: system },
  ];

  return (
    <div className={`flex flex-col h-full bg-slate-900 border-r border-slate-800 transition-all duration-200 ${collapsed ? 'w-16' : 'w-64'} ${className}`}>
      {/* Logo */}
      <div className={`flex items-center ${collapsed ? 'justify-center p-4' : 'gap-3 p-6'} border-b border-slate-800`}>
        <button type="button"
          onClick={onToggleCollapse}
          className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center hover:scale-105 transition-transform"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <span className="text-white font-bold text-sm">M</span>
        </button>
        {!collapsed && <span className="text-xl font-bold text-white">MERID</span>}
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-6 overflow-y-auto">
        {primarySections.map((section) => (
          <div key={section.label}>
            <SectionHeader label={section.label} collapsed={collapsed} />
            <div className="space-y-1">
              {section.items.map((item) => (
                <NavItem key={item.name} item={item} current={current} onChange={onChange} collapsed={collapsed} isLive={modeData ? isLive : undefined} />
              ))}
            </div>
          </div>
        ))}

      </nav>
    </div>
  );
}

const MemoizedSidebar = React.memo(Sidebar);
MemoizedSidebar.displayName = 'Sidebar';
export default MemoizedSidebar;
