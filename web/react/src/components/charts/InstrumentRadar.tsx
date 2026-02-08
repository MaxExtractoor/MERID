/**
 * Instrument Radar / Scanner Widget
 *
 * Tabbed instrument list with PnL, volume, signal strength, and sector.
 * Polls /api/metrics/radar with category filter.
 */

import { useState, useEffect, useCallback } from 'react';
import { Radar, TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react';
import { API_BASE_URL } from '../../config/constants';

type Category = 'all' | 'core' | 'onchain' | 'perps' | 'defi' | 'meme';

interface Instrument {
  symbol: string;
  price: number;
  change_24h: number;
  volume_24h: number;
  pnl: number;
  exposure: number;
  signal_strength: number;
  sector: string;
  category: string;
}

interface InstrumentRadarProps {
  className?: string;
}

const TABS: { value: Category; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'core', label: 'Core' },
  { value: 'onchain', label: 'On-chain' },
  { value: 'perps', label: 'Perps' },
  { value: 'defi', label: 'DeFi' },
  { value: 'meme', label: 'Meme' },
];

function formatPrice(val: number): string {
  if (val >= 1000) return `$${val.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (val >= 1) return `$${val.toFixed(2)}`;
  return `$${val.toFixed(4)}`;
}

function formatVolume(val: number): string {
  if (val >= 1e9) return `${(val / 1e9).toFixed(1)}B`;
  if (val >= 1e6) return `${(val / 1e6).toFixed(1)}M`;
  if (val >= 1e3) return `${(val / 1e3).toFixed(1)}K`;
  return String(Math.round(val));
}

function ChangeCell({ value }: { value: number }) {
  if (value > 0) return <span className="text-emerald-400">+{value.toFixed(2)}%</span>;
  if (value < 0) return <span className="text-rose-400">{value.toFixed(2)}%</span>;
  return <span className="text-slate-500">0.00%</span>;
}

function PnlCell({ value }: { value: number }) {
  if (value > 0) return <span className="text-emerald-400">+${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>;
  if (value < 0) return <span className="text-rose-400">-${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>;
  return <span className="text-slate-500">$0</span>;
}

function SignalDot({ strength }: { strength: number }) {
  const color = strength > 0.5 ? 'bg-emerald-400' : strength > 0 ? 'bg-amber-400' : strength < -0.5 ? 'bg-rose-400' : strength < 0 ? 'bg-amber-400' : 'bg-slate-600';
  return <div className={`w-2 h-2 rounded-full ${color}`} title={`Signal: ${strength.toFixed(2)}`} />;
}

export function InstrumentRadar({ className = '' }: InstrumentRadarProps) {
  const [category, setCategory] = useState<Category>('all');
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'symbol' | 'pnl' | 'change_24h' | 'volume_24h'>('symbol');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/metrics/radar?category=${category}`);
      if (res.ok) {
        const json = await res.json();
        setInstruments(json.instruments || []);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const id = setInterval(fetchData, 10000);
    return () => clearInterval(id);
  }, [fetchData]);

  const sorted = [...instruments].sort((a, b) => {
    const mul = sortDir === 'asc' ? 1 : -1;
    if (sortBy === 'symbol') return a.symbol.localeCompare(b.symbol) * mul;
    return ((a[sortBy] ?? 0) - (b[sortBy] ?? 0)) * mul;
  });

  const toggleSort = (col: typeof sortBy) => {
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortBy(col); setSortDir('desc'); }
  };

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Radar className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-300">Instrument Radar</h3>
        </div>
        <button onClick={() => { setLoading(true); fetchData(); }} className="p-1 rounded hover:bg-slate-800" title="Refresh">
          <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Category Tabs */}
      <div className="flex gap-1 mb-3 overflow-x-auto">
        {TABS.map(t => (
          <button
            key={t.value}
            onClick={() => setCategory(t.value)}
            className={`px-2.5 py-1 rounded text-[11px] font-medium whitespace-nowrap transition-colors ${
              category === t.value
                ? 'bg-blue-600 text-white'
                : 'bg-slate-800 text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Table */}
      {loading && instruments.length === 0 ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-8 bg-slate-800 rounded animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-slate-500 border-b border-slate-800">
                <th className="text-left py-1.5 px-1 cursor-pointer hover:text-slate-300" onClick={() => toggleSort('symbol')}>
                  Symbol {sortBy === 'symbol' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="text-right py-1.5 px-1">Price</th>
                <th className="text-right py-1.5 px-1 cursor-pointer hover:text-slate-300" onClick={() => toggleSort('change_24h')}>
                  24h {sortBy === 'change_24h' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="text-right py-1.5 px-1 cursor-pointer hover:text-slate-300" onClick={() => toggleSort('volume_24h')}>
                  Vol {sortBy === 'volume_24h' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="text-right py-1.5 px-1 cursor-pointer hover:text-slate-300" onClick={() => toggleSort('pnl')}>
                  PnL {sortBy === 'pnl' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="text-center py-1.5 px-1">Sig</th>
                <th className="text-left py-1.5 px-1">Sector</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(inst => (
                <tr key={inst.symbol} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="py-1.5 px-1 font-semibold text-slate-200">{inst.symbol}</td>
                  <td className="py-1.5 px-1 text-right text-slate-300">{formatPrice(inst.price)}</td>
                  <td className="py-1.5 px-1 text-right"><ChangeCell value={inst.change_24h} /></td>
                  <td className="py-1.5 px-1 text-right text-slate-400">{formatVolume(inst.volume_24h)}</td>
                  <td className="py-1.5 px-1 text-right"><PnlCell value={inst.pnl} /></td>
                  <td className="py-1.5 px-1 text-center"><SignalDot strength={inst.signal_strength} /></td>
                  <td className="py-1.5 px-1 text-slate-500">{inst.sector}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {sorted.length === 0 && (
            <div className="text-center text-slate-600 py-4 text-xs">No instruments in this category</div>
          )}
        </div>
      )}
    </div>
  );
}
