import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Search, ArrowRight, LayoutDashboard, Activity, Shield, Bot, Eye, Terminal, Settings, Zap, Brain, Code2, Layers, Star, Radio, Target, Trophy, FileSpreadsheet, GitBranch, Monitor, Wallet, Coins, Twitter, Cpu, Building2, Package, Database, BarChart3 } from 'lucide-react';

type View = "overview" | "trading" | "agents" | "predictions" | "prediction-consensus" | "risk" | "health" | "api" | "research" | "logs" | "settings" | "analytics" | "wallet" | "treasury" | "social" | "betting" | "betting-consensus" | "flow-radar" | "signal-layer" | "mining" | "institutional" | "plugins" | "operator" | "tradefloor" | "devswarm" | "devswarm-governance" | "positions" | "orders" | "rewards" | "cognitive" | "paper-trading" | "sports-live" | "observability" | "loop-orchestration" | "cross-asset";

interface CommandItem {
  id: View;
  label: string;
  section: string;
  icon: React.ElementType;
  keywords: string[];
}

const COMMANDS: CommandItem[] = [
  { id: 'overview', label: 'Overview', section: 'Main', icon: LayoutDashboard, keywords: ['home', 'dashboard', 'summary'] },
  { id: 'trading', label: 'Live Trading', section: 'Main', icon: Activity, keywords: ['trade', 'buy', 'sell', 'order'] },
  { id: 'tradefloor', label: 'Trade Floor', section: 'Main', icon: Zap, keywords: ['floor', 'live', 'stream'] },
  { id: 'positions', label: 'Positions', section: 'Main', icon: BarChart3, keywords: ['portfolio', 'holdings'] },
  { id: 'orders', label: 'Orders', section: 'Main', icon: BarChart3, keywords: ['open', 'pending', 'filled'] },
  { id: 'wallet', label: 'Wallet', section: 'Main', icon: Wallet, keywords: ['balance', 'funds', 'deposit'] },
  { id: 'treasury', label: 'Treasury', section: 'Main', icon: Coins, keywords: ['governance', 'funding', 'proposals'] },
  { id: 'predictions', label: 'Prediction Markets', section: 'Main', icon: Target, keywords: ['kalshi', 'markets', 'forecast'] },
  { id: 'prediction-consensus', label: 'Prediction Consensus', section: 'Main', icon: Target, keywords: ['debate', 'calibration', 'brier'] },
  { id: 'betting', label: 'Betting Markets', section: 'Main', icon: Trophy, keywords: ['bet', 'wager', 'odds'] },
  { id: 'betting-consensus', label: 'Swarm Betting', section: 'Main', icon: Zap, keywords: ['consensus', 'sports', 'edge'] },
  { id: 'sports-live', label: 'Sports Live', section: 'Main', icon: Radio, keywords: ['live', 'scores', 'events'] },
  { id: 'flow-radar', label: 'Flow Radar', section: 'Main', icon: Target, keywords: ['memecoin', 'whale', 'sniper', 'mev'] },
  { id: 'signal-layer', label: 'Signal Layer', section: 'Main', icon: Activity, keywords: ['signal', 'decay', 'drift', 'arb'] },
  { id: 'rewards', label: 'Rewards', section: 'Main', icon: Star, keywords: ['xp', 'quest', 'leaderboard'] },
  { id: 'social', label: 'Social Feed', section: 'Main', icon: Twitter, keywords: ['twitter', 'telegram', 'post'] },
  { id: 'paper-trading', label: 'Paper Trading', section: 'Main', icon: FileSpreadsheet, keywords: ['paper', 'simulation', 'backtest'] },
  { id: 'cross-asset', label: 'Cross-Asset', section: 'Main', icon: Layers, keywords: ['portfolio', 'multi', 'allocation'] },
  { id: 'research', label: 'Research', section: 'Main', icon: Search, keywords: ['backtest', 'strategy'] },
  { id: 'operator', label: 'Operator Dashboard', section: 'Management', icon: Monitor, keywords: ['ops', 'control', 'status'] },
  { id: 'risk', label: 'Risk & Health', section: 'Management', icon: Shield, keywords: ['risk', 'exposure', 'limits'] },
  { id: 'agents', label: 'Bots/Agents', section: 'Management', icon: Bot, keywords: ['agent', 'swarm', 'bot'] },
  { id: 'cognitive', label: 'Cognitive Layer', section: 'Management', icon: Brain, keywords: ['regime', 'reality', 'hypothesis'] },
  { id: 'devswarm', label: 'Dev Swarm', section: 'Management', icon: Code2, keywords: ['dev', 'task', 'code'] },
  { id: 'devswarm-governance', label: 'Swarm Governance', section: 'Management', icon: Shield, keywords: ['proposal', 'approval', 'governance'] },
  { id: 'mining', label: 'Mining', section: 'Management', icon: Cpu, keywords: ['hash', 'rig', 'pool'] },
  { id: 'institutional', label: 'Institutional', section: 'Management', icon: Building2, keywords: ['compliance', 'audit', 'account'] },
  { id: 'plugins', label: 'Plugins', section: 'Management', icon: Package, keywords: ['extension', 'install'] },
  { id: 'api', label: 'API Dashboard', section: 'Management', icon: Database, keywords: ['api', 'endpoint', 'status'] },
  { id: 'analytics', label: 'Analytics', section: 'Management', icon: BarChart3, keywords: ['chart', 'report'] },
  { id: 'settings', label: 'Settings', section: 'Management', icon: Settings, keywords: ['config', 'preference', 'theme'] },
  { id: 'loop-orchestration', label: 'Loop Orchestration', section: 'System', icon: GitBranch, keywords: ['loop', 'pipeline', 'cadence'] },
  { id: 'observability', label: 'Observability', section: 'System', icon: Eye, keywords: ['slo', 'metrics', 'alerts', 'llm'] },
  { id: 'health', label: 'System Health', section: 'System', icon: Shield, keywords: ['uptime', 'latency', 'service'] },
  { id: 'logs', label: 'Logs', section: 'System', icon: Terminal, keywords: ['log', 'error', 'debug'] },
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
      const timer = setTimeout(() => inputRef.current?.focus(), 50);
      return () => clearTimeout(timer);
    }
  }, [open]);

  const filtered = useMemo(() => {
    if (!query.trim()) return COMMANDS;
    const q = query.toLowerCase();
    return COMMANDS.filter(cmd =>
      cmd.label.toLowerCase().includes(q) ||
      cmd.section.toLowerCase().includes(q) ||
      cmd.keywords.some(kw => kw.includes(q))
    );
  }, [query]);

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
          <input aria-label="Query"
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
