import { useState, useEffect, useCallback } from 'react';
import { DollarSign, RefreshCw } from 'lucide-react';

interface PnLDataPoint {
  timestamp: string;
  prediction: number;
  crypto: number;
  equity: number;
  total: number;
}

const DOMAIN_COLORS: Record<string, string> = {
  prediction: '#f97316',
  crypto: '#3b82f6',
  equity: '#22c55e',
  total: '#a78bfa',
};

export default function DomainPnLChart() {
  const [data, setData] = useState<PnLDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState<'1h' | '4h' | '24h' | '7d'>('24h');

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`/api/v1/pipeline/pnl?range=${timeRange}`);
      if (res.ok) {
        const json = await res.json();
        if (json.data) { setData(json.data); return; }
      }
    } catch { /* fallback */ }

    const now = Date.now();
    const points: PnLDataPoint[] = [];
    let predPnl = 0, cryptoPnl = 0, eqPnl = 0;
    const intervals = timeRange === '1h' ? 12 : timeRange === '4h' ? 48 : timeRange === '24h' ? 96 : 168;
    const stepMs = timeRange === '1h' ? 300000 : timeRange === '4h' ? 300000 : timeRange === '24h' ? 900000 : 3600000;

    for (let i = intervals; i >= 0; i--) {
      predPnl += (Math.random() - 0.45) * 8;
      cryptoPnl += (Math.random() - 0.42) * 15;
      eqPnl += (Math.random() - 0.48) * 5;
      points.push({
        timestamp: new Date(now - i * stepMs).toISOString(),
        prediction: Math.round(predPnl * 100) / 100,
        crypto: Math.round(cryptoPnl * 100) / 100,
        equity: Math.round(eqPnl * 100) / 100,
        total: Math.round((predPnl + cryptoPnl + eqPnl) * 100) / 100,
      });
    }
    setData(points);
    setLoading(false);
  }, [timeRange]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const latest = data.length > 0 ? data[data.length - 1] : null;
  const minVal = data.length > 0 ? Math.min(...data.map(d => Math.min(d.prediction, d.crypto, d.equity, d.total))) : 0;
  const maxVal = data.length > 0 ? Math.max(...data.map(d => Math.max(d.prediction, d.crypto, d.equity, d.total))) : 100;
  const range = maxVal - minVal || 1;

  const toY = (val: number) => {
    return 100 - ((val - minVal) / range) * 100;
  };

  const buildPath = (key: keyof PnLDataPoint) => {
    if (data.length === 0) return '';
    return data.map((d, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = toY(d[key] as number);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    }).join(' ');
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading PnL data...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-green-400" />
          <h3 className="text-lg font-bold text-white">Domain PnL</h3>
          {latest && (
            <span className={`text-sm font-mono font-medium ${latest.total >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {latest.total >= 0 ? '+' : ''}${latest.total.toFixed(2)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {(['1h', '4h', '24h', '7d'] as const).map(r => (
              <button
                key={r}
                onClick={() => setTimeRange(r)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  timeRange === r ? 'bg-green-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          <button onClick={fetchData} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh PnL">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4">
        {Object.entries(DOMAIN_COLORS).map(([domain, color]) => (
          <div key={domain} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-xs text-gray-400 capitalize">{domain}</span>
            {latest && (
              <span className={`text-xs font-mono ${(latest[domain as keyof PnLDataPoint] as number) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {(latest[domain as keyof PnLDataPoint] as number) >= 0 ? '+' : ''}
                ${(latest[domain as keyof PnLDataPoint] as number).toFixed(0)}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* SVG Chart */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
        <svg viewBox="0 0 100 50" className="w-full h-40" preserveAspectRatio="none">
          {/* Zero line */}
          <line x1="0" y1={toY(0)} x2="100" y2={toY(0)} stroke="#475569" strokeWidth="0.2" strokeDasharray="1,1" />
          {/* Domain lines */}
          {(['prediction', 'crypto', 'equity', 'total'] as const).map(key => (
            <path
              key={key}
              d={buildPath(key)}
              fill="none"
              stroke={DOMAIN_COLORS[key]}
              strokeWidth={key === 'total' ? '0.6' : '0.4'}
              opacity={key === 'total' ? 1 : 0.7}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
        <div className="flex justify-between text-[10px] text-gray-600 mt-1">
          <span>{data.length > 0 ? new Date(data[0].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
          <span>{data.length > 0 ? new Date(data[data.length - 1].timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
        </div>
      </div>
    </div>
  );
}
