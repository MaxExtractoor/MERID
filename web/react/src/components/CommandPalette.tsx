import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Search, ArrowRight, LayoutDashboard, ShieldAlert, Terminal, Settings, Briefcase, Gauge, Activity, Sliders, Rocket, FileText, Crosshair, Award } from '../ui/icons';
import type { View } from '../types/views';
import { DEFAULTS } from '../config/constants';
import { useFeatureFlags } from '../config/featureFlags';

interface CommandItem {
  id: View;
  label: string;
  section: string;
  icon: React.ElementType;
  keywords: string[];
  legacy?: boolean;
}

const COMMANDS: CommandItem[] = [
  // Stage 1: Discover (Consolidated - unified view with tabs)
  { id: 'discover', label: 'Discover Markets', section: 'Discover', icon: Search, keywords: ['kalshi', 'markets', 'catalog', 'discovery', 'trade', 'all', 'universe', 'trending', 'focus'] },
  
  // Stage 2: Analyze
  { id: 'analyze-sentiment', label: 'Sentiment', section: 'Analyze', icon: Activity, keywords: ['fear', 'greed', 'sentiment', 'regime', 'index'] },
  { id: 'analyze-vol', label: 'Vol & ATR', section: 'Analyze', icon: Gauge, keywords: ['volatility', 'atr', 'sizing', 'kelly', 'sharpe'] },
  
  // Stage 3: Consensus
  { id: 'consensus-performance', label: 'Performance', section: 'Consensus', icon: Award, keywords: ['performance', 'agent', 'win', 'sharpe', 'calibration', 'pnl'] },
  { id: 'consensus-calibration', label: 'Calibration', section: 'Consensus', icon: Crosshair, keywords: ['calibration', 'brier', 'forecaster', 'weight', 'accuracy'] },
  
  // Stage 4: Size (Consolidated - unified view with tabs)
  { id: 'size', label: 'Size & Bankroll', section: 'Size', icon: Sliders, keywords: ['bankroll', 'capital', 'equity', 'balance', 'lane', 'timeframe', 'sizing', 'kelly', 'risk', 'allocation'] },
  
  // Stage 5: Execute (Consolidated - unified view with tabs)
  { id: 'execute', label: 'Execute Terminal', section: 'Execute', icon: Terminal, keywords: ['terminal', 'trade', 'orderbook', 'ticket', 'execute', 'orders', 'resting', 'cancel', 'positions', 'holdings', 'exposure'] },
  
  // Stage 6: Monitor (Consolidated - unified view with tabs)
  { id: 'monitor', label: 'Monitor Portfolio', section: 'Monitor', icon: Briefcase, keywords: ['portfolio', 'fills', 'pnl', 'equity', 'returns', 'history', 'profit', 'loss', 'health', 'status', 'diagnostics'] },
  
  // Stage 7: Promote (Consolidated - unified view with tabs)
  { id: 'promote', label: 'Promote Pipeline', section: 'Promote', icon: Rocket, keywords: ['pipeline', 'promote', 'paper', 'shadow', 'live', 'deployment', 'grid', 'agents', 'ladder'] },
  
  // Stage 8: Protect (Consolidated - unified view with tabs)
  { id: 'protect', label: 'Protect Risk Center', section: 'Protect', icon: ShieldAlert, keywords: ['risk', 'alerts', 'exposure', 'limits', 'kill', 'halt', 'safety', 'emergency'] },
  
  // System
  { id: 'overview', label: 'Overview', section: 'System', icon: LayoutDashboard, keywords: ['home', 'dashboard', 'summary'] },
  { id: 'operator', label: 'Operator', section: 'System', icon: Sliders, keywords: ['ops', 'control', 'status', 'operator', 'orchestrator'] },
  { id: 'logs', label: 'Logs', section: 'System', icon: FileText, keywords: ['log', 'error', 'debug'] },
  { id: 'settings', label: 'Settings', section: 'System', icon: Settings, keywords: ['config', 'preference', 'theme'] },
];

interface CommandPaletteProps {
  onNavigate: (view: View) => void;
  onOpen?: (fn: () => void) => void;
}

export default function CommandPalette({ onNavigate, onOpen }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const { kalshiOnly } = useFeatureFlags();

  // Register open function with parent ref
  useEffect(() => {
    onOpen?.(() => setOpen(true));
  }, [onOpen]);

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
