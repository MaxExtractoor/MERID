import React from 'react';
import { 
  LayoutDashboard, 
  ShieldAlert,
  Shield,
  Terminal,
  Search,
  Globe,
  Flame,
  Target,
  Activity,
  Gauge,
  Grid,
  Award,
  Crosshair,
  Wallet,
  GitBranch,
  Sliders,
  Briefcase,
  DollarSign,
  Heart,
  Rocket,
  LayoutGrid,
  Bell,
  Settings as SettingsIcon,
  FileText,
  TrendingUp,
  ClipboardList,
  MessageSquare,
} from 'lucide-react';
import type { View } from '../types/views';
import { useKalshiMode } from '../context/KalshiModeContext';
import { MODE_COLORS, resolveModeKey } from '../config/modeColors';

interface SidebarProps {
  current: View;
  onChange: (view: View) => void;
  className?: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

/* ── 8-Stage Workflow Navigation ───────────────────────────────────── */

const STAGE_NAV = [
  {
    stage: '1',
    label: 'Discover',
    color: 'blue',
    accent: 'from-blue-500 to-blue-600',
    items: [
      { name: 'Markets', href: 'discover', icon: Search },
      { name: 'All Markets', href: 'discover-all-markets', icon: Globe },
      { name: 'Trending', href: 'discover-trending', icon: Flame },
    ],
  },
  {
    stage: '2',
    label: 'Analyze',
    color: 'purple',
    accent: 'from-purple-500 to-purple-600',
    items: [
      { name: 'Edge Signals', href: 'analyze-edge', icon: Target },
      { name: 'Sentiment', href: 'analyze-sentiment', icon: Activity },
      { name: 'Vol & ATR', href: 'analyze-vol', icon: Gauge },
    ],
  },
  {
    stage: '3',
    label: 'Consensus',
    color: 'cyan',
    accent: 'from-cyan-500 to-cyan-600',
    items: [
      { name: 'Swarm Matrix', href: 'consensus-swarm', icon: Grid },
      { name: 'Debates', href: 'consensus-debates', icon: MessageSquare },
      { name: 'Performance', href: 'consensus-performance', icon: Award },
      { name: 'Calibration', href: 'consensus-calibration', icon: Crosshair },
    ],
  },
  {
    stage: '4',
    label: 'Size',
    color: 'amber',
    accent: 'from-amber-500 to-amber-600',
    items: [
      { name: 'Bankroll', href: 'size-bankroll', icon: Wallet },
      { name: 'Lane Control', href: 'size-lanes', icon: GitBranch },
      { name: 'Sizing Metrics', href: 'size-sizing', icon: Sliders },
    ],
  },
  {
    stage: '5',
    label: 'Execute',
    color: 'emerald',
    accent: 'from-emerald-500 to-emerald-600',
    items: [
      { name: 'Terminal', href: 'execute-terminal', icon: Terminal },
      { name: 'Orders', href: 'execute-orders', icon: ClipboardList },
      { name: 'Positions', href: 'execute-positions', icon: TrendingUp },
    ],
  },
  {
    stage: '6',
    label: 'Monitor',
    color: 'orange',
    accent: 'from-orange-500 to-orange-600',
    items: [
      { name: 'Portfolio', href: 'monitor-portfolio', icon: Briefcase },
      { name: 'PnL History', href: 'monitor-pnl', icon: DollarSign },
      { name: 'Health', href: 'monitor-health', icon: Heart },
    ],
  },
  {
    stage: '7',
    label: 'Promote',
    color: 'violet',
    accent: 'from-violet-500 to-violet-600',
    items: [
      { name: 'Pipeline', href: 'promote-pipeline', icon: Rocket },
      { name: 'Agent Grid', href: 'promote-grid', icon: LayoutGrid },
    ],
  },
  {
    stage: '8',
    label: 'Protect',
    color: 'red',
    accent: 'from-red-500 to-red-600',
    items: [
      { name: 'Risk Center', href: 'protect-risk', icon: ShieldAlert },
      { name: 'Kill Switch', href: 'protect-kill-switch', icon: Shield },
      { name: 'Alerts', href: 'protect-alerts', icon: Bell },
    ],
  },
] as const;

const SYSTEM_NAV = [
  { name: 'Overview', href: 'overview', icon: LayoutDashboard },
  { name: 'Operator', href: 'operator', icon: Sliders },
  { name: 'Logs', href: 'logs', icon: FileText },
  { name: 'Settings', href: 'settings', icon: SettingsIcon },
] as const;

// Color mapping for stage accents
const STAGE_COLORS: Record<string, { text: string; bg: string; border: string; hover: string }> = {
  blue: { text: 'text-blue-400', bg: 'bg-blue-500/10', border: 'border-blue-500/30', hover: 'hover:bg-blue-500/20' },
  purple: { text: 'text-purple-400', bg: 'bg-purple-500/10', border: 'border-purple-500/30', hover: 'hover:bg-purple-500/20' },
  cyan: { text: 'text-cyan-400', bg: 'bg-cyan-500/10', border: 'border-cyan-500/30', hover: 'hover:bg-cyan-500/20' },
  amber: { text: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/30', hover: 'hover:bg-amber-500/20' },
  emerald: { text: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', hover: 'hover:bg-emerald-500/20' },
  orange: { text: 'text-orange-400', bg: 'bg-orange-500/10', border: 'border-orange-500/30', hover: 'hover:bg-orange-500/20' },
  violet: { text: 'text-violet-400', bg: 'bg-violet-500/10', border: 'border-violet-500/30', hover: 'hover:bg-violet-500/20' },
  red: { text: 'text-red-400', bg: 'bg-red-500/10', border: 'border-red-500/30', hover: 'hover:bg-red-500/20' },
  slate: { text: 'text-slate-400', bg: 'bg-slate-500/10', border: 'border-slate-500/30', hover: 'hover:bg-slate-500/20' },
};

// Views that show live/paper mode indicator
const MODE_INDICATOR_VIEWS = new Set<View>([
  'discover', 'discover-all-markets', 'discover-trending',
  'execute-terminal', 'execute-orders', 'execute-positions',
  'promote-grid', 'promote-pipeline',
]);

interface NavItemProps {
  item: { name: string; href: View; icon: React.ElementType };
  current: View;
  onChange: (v: View) => void;
  collapsed: boolean;
  stageColor: string;
  isLive?: boolean;
}

function NavItem({ item, current, onChange, collapsed, stageColor, isLive }: NavItemProps) {
  const Icon = item.icon;
  const isActive = current === item.href;
  const colors = STAGE_COLORS[stageColor] ?? STAGE_COLORS.slate;
  const showModeDot = MODE_INDICATOR_VIEWS.has(item.href);
  
  return (
    <button
      type="button"
      onClick={() => onChange(item.href)}
      title={collapsed ? item.name : undefined}
      className={`
        w-full flex items-center ${collapsed ? 'justify-center' : 'gap-3'} px-3 py-2 text-sm font-medium rounded-lg transition-all duration-150
        ${isActive
          ? `${colors.bg} ${colors.text} border ${colors.border} shadow-sm`
          : `text-slate-400 ${colors.hover} hover:text-white`
        }
      `}
    >
      <Icon className={`w-4 h-4 shrink-0 ${isActive ? colors.text : 'text-slate-500'}`} />
      {!collapsed && (
        <span className="flex-1 flex items-center justify-between">
          <span>{item.name}</span>
          {showModeDot && isLive !== undefined && (
            <span
              className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${MODE_COLORS[resolveModeKey(undefined, isLive)].badge}`}
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

interface StageSectionProps {
  stage: {
    stage: string;
    label: string;
    color: string;
    accent: string;
    items: ReadonlyArray<{ name: string; href: View; icon: React.ElementType }>;
  };
  current: View;
  onChange: (v: View) => void;
  collapsed: boolean;
  isLive?: boolean;
}

function StageSection({ stage, current, onChange, collapsed, isLive }: StageSectionProps) {
  const colors = STAGE_COLORS[stage.color] ?? STAGE_COLORS.slate;
  const hasActiveItem = stage.items.some(item => item.href === current);
  
  if (collapsed) {
    return (
      <div className="space-y-1">
        {stage.items.map((item) => (
          <NavItem
            key={item.href}
            item={item}
            current={current}
            onChange={onChange}
            collapsed={collapsed}
            stageColor={stage.color}
            isLive={isLive}
          />
        ))}
      </div>
    );
  }
  
  return (
    <div className="space-y-1">
      <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${hasActiveItem ? colors.bg : ''}`}>
        <span className={`text-[10px] font-bold ${colors.text} bg-slate-800 px-1.5 py-0.5 rounded`}>
          {stage.stage}
        </span>
        <span className={`text-xs font-semibold ${hasActiveItem ? colors.text : 'text-slate-500'} uppercase tracking-wider`}>
          {stage.label}
        </span>
      </div>
      <div className="space-y-0.5 pl-2">
        {stage.items.map((item) => (
          <NavItem
            key={item.href}
            item={item}
            current={current}
            onChange={onChange}
            collapsed={collapsed}
            stageColor={stage.color}
            isLive={isLive}
          />
        ))}
      </div>
    </div>
  );
}

function Sidebar({ current, onChange, className, collapsed = false, onToggleCollapse }: SidebarProps) {
  const { data: modeData, isLive } = useKalshiMode();

  return (
    <div className={`flex flex-col h-full bg-slate-900 border-r border-slate-800 transition-all duration-200 ${collapsed ? 'w-16' : 'w-64'} ${className}`}>
      {/* Logo */}
      <div className={`flex items-center ${collapsed ? 'justify-center p-4' : 'gap-3 p-6'} border-b border-slate-800`}>
        <button
          type="button"
          onClick={onToggleCollapse}
          className="w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center hover:scale-105 transition-transform shadow-lg shadow-blue-500/20"
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <span className="text-white font-bold text-sm">M</span>
        </button>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="text-xl font-bold text-white">MERID</span>
            <span className="text-[10px] text-slate-500 font-medium">8-Stage Workflow</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-4 overflow-y-auto">
        {/* Workflow Stages */}
        <div className="space-y-3">
          {STAGE_NAV.map((stage) => (
            <StageSection
              key={stage.stage}
              stage={stage as StageSectionProps['stage']}
              current={current}
              onChange={onChange}
              collapsed={collapsed}
              isLive={modeData ? isLive : undefined}
            />
          ))}
        </div>
        
        {/* Divider */}
        <div className="border-t border-slate-800 pt-3">
          {!collapsed && (
            <span className="px-3 text-[10px] font-semibold text-slate-600 uppercase tracking-wider mb-2 block">
              System
            </span>
          )}
          <div className="space-y-0.5">
            {SYSTEM_NAV.map((item) => (
              <NavItem
                key={item.href}
                item={item}
                current={current}
                onChange={onChange}
                collapsed={collapsed}
                stageColor="slate"
              />
            ))}
          </div>
        </div>
      </nav>
      
      {/* Bottom Status */}
      {!collapsed && (
        <div className="p-3 border-t border-slate-800">
          <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${isLive ? 'bg-red-500/10 border border-red-500/30' : 'bg-emerald-500/10 border border-emerald-500/30'}`}>
            <div className={`w-2 h-2 rounded-full animate-pulse ${isLive ? 'bg-red-400' : 'bg-emerald-400'}`} />
            <span className={`text-xs font-medium ${isLive ? 'text-red-400' : 'text-emerald-400'}`}>
              {isLive ? 'LIVE MODE' : 'PAPER MODE'}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

const MemoizedSidebar = React.memo(Sidebar);
MemoizedSidebar.displayName = 'Sidebar';
export default MemoizedSidebar;
