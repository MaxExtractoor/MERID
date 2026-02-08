import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, DollarSign, Activity } from 'lucide-react';
import { useRealtimeData } from '../hooks/useRealtimeData';

interface PortfolioUpdate {
  total_value: number;
  change_24h: number;
  change_24h_percent: number;
  pnl_today: number;
  positions_count: number;
  timestamp: number;
}

export default function LivePortfolioValue() {
  const [portfolioData, isConnected] = useRealtimeData<PortfolioUpdate>('portfolio_update');
  const [displayData, setDisplayData] = useState<PortfolioUpdate>({
    total_value: 0,
    change_24h: 0,
    change_24h_percent: 0,
    pnl_today: 0,
    positions_count: 0,
    timestamp: Date.now(),
  });

  // REST fallback: fetch portfolio summary when WS is unavailable
  useEffect(() => {
    let cancelled = false;
    const fetchRest = async () => {
      try {
        let res = await fetch('/api/v1/portfolio/summary');
        if (!res.ok) res = await fetch('/api/portfolio/summary');
        if (res.ok && !cancelled) {
          const data = await res.json();
          setDisplayData(prev => ({
            total_value: data.equity ?? data.total_value ?? prev.total_value,
            change_24h: data.dailyPnl ?? data.change_24h ?? prev.change_24h,
            change_24h_percent: data.dailyPnlPct ?? data.change_24h_percent ?? prev.change_24h_percent,
            pnl_today: data.dailyPnl ?? data.pnl_today ?? prev.pnl_today,
            positions_count: data.activeBots ?? data.positions_count ?? prev.positions_count,
            timestamp: Date.now(),
          }));
        }
      } catch { /* WS is primary */ }
    };
    fetchRest();
    const interval = setInterval(fetchRest, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  // WS updates override REST data
  useEffect(() => {
    if (portfolioData) {
      setDisplayData(portfolioData);
    }
  }, [portfolioData]);

  const getChangeColor = (value: number) => {
    if (value > 0) return 'text-green-400';
    if (value < 0) return 'text-red-400';
    return 'text-gray-400';
  };

  return (
    <div className="bg-gradient-to-br from-blue-900/20 to-purple-900/20 rounded-lg border border-blue-500/30 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-500/20 rounded-lg">
            <DollarSign className="w-6 h-6 text-blue-400" />
          </div>
          <div>
            <h3 className="text-sm text-gray-400">Total Portfolio Value</h3>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-gray-500'}`} />
              <span className="text-xs text-gray-500">{isConnected ? 'Live' : 'Offline'}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <div className="text-4xl font-bold text-white mb-2">
            ${displayData.total_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
          <div className="flex items-center gap-4">
            <div className={`flex items-center gap-1 ${getChangeColor(displayData.change_24h)}`}>
              {displayData.change_24h > 0 ? (
                <TrendingUp className="w-4 h-4" />
              ) : displayData.change_24h < 0 ? (
                <TrendingDown className="w-4 h-4" />
              ) : null}
              <span className="text-sm font-medium">
                {displayData.change_24h > 0 ? '+' : ''}${displayData.change_24h.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className="text-sm">
                ({displayData.change_24h_percent > 0 ? '+' : ''}{displayData.change_24h_percent.toFixed(2)}%)
              </span>
            </div>
            <div className="text-sm text-gray-400">24h</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 pt-4 border-t border-slate-700/50">
          <div>
            <div className="text-xs text-gray-400 mb-1">Today's P&L</div>
            <div className={`text-lg font-bold ${getChangeColor(displayData.pnl_today)}`}>
              {displayData.pnl_today > 0 ? '+' : ''}${displayData.pnl_today.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-400 mb-1">Active Positions</div>
            <div className="text-lg font-bold text-white flex items-center gap-2">
              <Activity className="w-4 h-4 text-blue-400" />
              {displayData.positions_count}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
