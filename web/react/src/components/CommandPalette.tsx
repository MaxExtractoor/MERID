import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Search, ArrowRight, LayoutDashboard, ShieldAlert, Terminal, Settings, Monitor, BarChart3, Briefcase, Gauge, Activity, GitBranch, Grid, Target, Shield, Award, TrendingDown } from 'lucide-react';
import type { View } from '../types/views';
import { DEFAULTS } from '../config/constants';
import { useFeatureFlags } from '../config/featureFlags';

// ─── CommandItem.legacy flag ────────────────────────────────────────────────
// The `legacy?: boolean` field on CommandItem drives zombie-feature deprecation.
// Usage pattern (see docs/UX_Zombie_Features.md):
//   1. After telemetry shows a view at < 1% of sessions for 14 days, open an
//      issue tagged `status:zombie-candidate`.
//   2. Mark the corresponding COMMANDS entry `legacy: true` here.
//   3. The `kalshiOnly` feature flag (line ~78) already filters out `legacy`
//      items when kalshiOnly mode is active — that is the kill-switch for
//      hiding a view without deleting code.
//   4. Monitor for 14 more quiet days, then delete the view and entry.
//
// NEVER mark these views legacy without explicit human sign-off:
//   operator, kill-switch, risk-control, lane-control, position-sizing,
//   promotion-status  — they are always exempt even at 0% session share.
// ────────────────────────────────────────────────────────────────────────────
interface CommandItem {
  id: View;
  label: string;
  section: string;
  icon: React.ElementType;
  keywords: string[];
  legacy?: boolean;
}

const COMMANDS: CommandItem[] = [
  // Trading
  { id: 'overview', label: 'Overview', section: 'Trading', icon: LayoutDashboard, keywords: ['home', 'dashboard', 'summary'] },
  { id: 'kalshi-terminal', label: 'Terminal', section: 'Trading', icon: Monitor, keywords: ['terminal', 'trade', 'kalshi', 'orderbook', 'ticket'] },
  { id: 'kalshi-dashboard', label: 'Markets', section: 'Trading', icon: BarChart3, keywords: ['kalshi', 'markets', 'catalog', 'discovery'] },
  { id: 'kalshi-portfolio', label: 'Portfolio', section: 'Trading', icon: Briefcase, keywords: ['kalshi', 'positions', 'orders', 'fills', 'pnl', 'equity'] },
  // Swarm Intelligence
  { id: 'kalshi-grid', label: 'Agent Grid', section: 'Swarm Intelligence', icon: BarChart3, keywords: ['kalshi', 'grid', 'agents', 'paper'] },
  { id: 'swarm-consensus', label: 'Swarm Matrix', section: 'Swarm Intelligence', icon: Grid, keywords: ['swarm', 'consensus', 'matrix', 'agents', 'voting', 'direction'] },
  { id: 'kalshi-performance', label: 'Performance', section: 'Swarm Intelligence', icon: BarChart3, keywords: ['performance', 'agent', 'win', 'sharpe', 'calibration', 'pnl'] },
  { id: 'calibration-dashboard', label: 'Calibration', section: 'Swarm Intelligence', icon: Target, keywords: ['calibration', 'brier', 'forecaster', 'weight', 'correlation', 'resolver', 'accuracy'] },
  { id: 'lane-control', label: 'Lane Control', section: 'Swarm Intelligence', icon: GitBranch, keywords: ['lane', 'timeframe', 'cross', 'xtf', 'promoter', 'deployment', 'phase'] },
  // Analytics
  { id: 'kalshi-sentiment', label: 'Fear / Greed', section: 'Analytics', icon: Activity, keywords: ['fear', 'greed', 'sentiment', 'regime', 'index'] },
  { id: 'kalshi-vol-dashboard', label: 'Vol & Sizing', section: 'Analytics', icon: Gauge, keywords: ['kalshi', 'volatility', 'sizing', 'kelly', 'sharpe'] },
  // Operator
  { id: 'operator', label: 'Operator', section: 'Operator', icon: Monitor, keywords: ['ops', 'control', 'status', 'operator', 'orchestrator'] },
  { id: 'kill-switch', label: 'Kill Switch', section: 'Operator', icon: ShieldAlert, keywords: ['kill', 'halt', 'safety', 'gate', 'block', 'emergency'] },
  { id: 'risk-dashboard', label: 'Risk Dashboard', section: 'Operator', icon: TrendingDown, keywords: ['risk', 'drawdown', 'zone', 'profit', 'lock', 'multiplier', 'halt'] },
  { id: 'risk-control', label: 'Risk Control', section: 'Operator', icon: Shield, keywords: ['risk', 'circuit', 'breaker', 'protection', 'caps', 'limits'] },
  { id: 'position-sizing', label: 'Position Sizing', section: 'Operator', icon: BarChart3, keywords: ['position', 'sizing', 'kelly', 'vol', 'drawdown', 'tier'] },
  { id: 'promotion-status', label: 'Promotion Status', section: 'Operator', icon: Award, keywords: ['promotion', 'auto', 'promoter', 'shadow', 'live', 'paper', 'gauntlet'] },
  // System
  { id: 'logs', label: 'Logs', section: 'System', icon: Terminal, keywords: ['log', 'error', 'debug'] },
  { id: 'settings', label: 'Settings', section: 'System', icon: Settings, keywords: ['config', 'preference', 'theme'] },
];

interface CommandPaletteProps {
  onNavigate: (view: View) => void;
}

export default function CommandPalette({ onNavigate }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { kalshiOnly } = useFeatureFlags();

  // Ctrl+K / Cmd+K to open
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(prev => !prev);
      }
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIndex(0);
      const timer = setTimeout(() => inputRef.current?.focus(), DEFAULTS.TIMEOUTS.DEBOUNCE);
      return () => clearTimeout(timer);
    }
  }, [open]);

  const filtered = useMemo(() => {
    const base = kalshiOnly ? COMMANDS.filter(c => !c.legacy) : COMMANDS;
    if (!query.trim()) return base;
    const q = query.toLowerCase();
    return base.filter(cmd =>
      cmd.label.toLowerCase().includes(q) ||
      cmd.section.toLowerCase().includes(q) ||
      cmd.keywords.some(kw => kw.includes(q))
    );
  }, [query, kalshiOnly]);

  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const el = listRef.current.children[selectedIndex] as HTMLElement;
      el?.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex]);

  const handleSelect = useCallback((cmd: CommandItem) => {
    onNavigate(cmd.id);
    setOpen(false);
  }, [onNavigate]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(i => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && filtered[selectedIndex]) {
      handleSelect(filtered[selectedIndex]);
    }
  };

  if (!open) return null;

  // Group by section
  const sections = new Map<string, CommandItem[]>();
  filtered.forEach(cmd => {
    const list = sections.get(cmd.section) || [];
    list.push(cmd);
    sections.set(cmd.section, list);
  });

  let flatIndex = 0;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setOpen(false)} role="button" tabIndex={0} aria-label="Close" onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(false); } }} />

      {/* Palette */}
      <div className="relative w-full max-w-lg bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl shadow-black/50 overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-700/60">
          <Search className="w-5 h-5 text-slate-400 shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => { setQuery(e.target.value); setSelectedIndex(0); }}
            onKeyDown={handleKeyDown}
            aria-label="Search views and commands"
            placeholder="Search views, commands..."
            className="flex-1 bg-transparent text-sm text-white placeholder-slate-500 outline-none"
          />
          <kbd className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium text-slate-500 bg-slate-800 border border-slate-700 rounded">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 && (
            <p className="px-3 py-6 text-sm text-slate-500 text-center">No results found</p>
          )}
          {Array.from(sections.entries()).map(([section, items]) => (
            <div key={section}>
              <p className="px-3 pt-2 pb-1 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">{section}</p>
              {items.map(cmd => {
                const idx = flatIndex++;
                const Icon = cmd.icon;
                const isSelected = idx === selectedIndex;
                return (
                  <button type="button"
                    key={cmd.id}
                    onClick={() => handleSelect(cmd)}
                    onMouseEnter={() => setSelectedIndex(idx)}
                    className={`w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-colors ${
                      isSelected ? 'bg-blue-600/20 text-white' : 'text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    <Icon className={`w-4 h-4 ${isSelected ? 'text-blue-400' : 'text-slate-500'}`} />
                    <span className="flex-1 text-left">{cmd.label}</span>
                    {isSelected && <ArrowRight className="w-3.5 h-3.5 text-blue-400" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-4 px-4 py-2 border-t border-slate-700/60 text-[10px] text-slate-500">
          <span><kbd className="px-1 py-0.5 bg-slate-800 border border-slate-700 rounded text-[10px]">↑↓</kbd> navigate</span>
          <span><kbd className="px-1 py-0.5 bg-slate-800 border border-slate-700 rounded text-[10px]">↵</kbd> select</span>
          <span><kbd className="px-1 py-0.5 bg-slate-800 border border-slate-700 rounded text-[10px]">esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
