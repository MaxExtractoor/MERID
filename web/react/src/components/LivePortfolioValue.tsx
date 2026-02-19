import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, DollarSign, Activity, Radio } from 'lucide-react';
import { useRealtimeData } from '../hooks/useRealtimeData';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS, WS_PORTFOLIO_URL } from '../config/constants';
import { logUiError } from '../utils/logger';

interface PortfolioUpdate {
  total_value: number;
  change_24h: number;
  change_24h_percent: number;
  pnl_today: number;
  positions_count: number;
  timestamp: number;
}

interface RawPortfolioUpdate {
  total_equity?: number;
  total_pnl?: number;
  unrealized_pnl?: number;
  position_count?: number;
  exposure?: Record<string, number>;
  timestamp?: number | string;
}

export default function LivePortfolioValue() {
  const [portfolioData, isConnected] = useRealtimeData<RawPortfolioUpdate>('risk_summary', null, WS_PORTFOLIO_URL);
  const [displayData, setDisplayData] = useState<PortfolioUpdate>({
    total_value: 0,
    change_24h: 0,
    change_24h_percent: 0,
    pnl_today: 0,
    positions_count: 0,
    timestamp: Date.now(),
  });

  // Kalshi-specific live data
  const { data: kalshiRisk } = useApiData<{
    daily_pnl_usd: number;
    daily_realized_pnl_usd: number;
    total_notional_usd: number;
    open_market_count: number;
  }>(API_ENDPOINTS.KALSHI_RISK, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });

  const { data: kalshiBalance } = useApiData<{
    usd: number;
    available: number;
    locked: number;
  }>(API_ENDPOINTS.KALSHI_BALANCE, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });

  const { data: gridPortfolio } = useApiData<{
    equity_usd: number;
    daily_pnl_usd: number;
    position_count: number;
  }>(API_ENDPOINTS.KALSHI_GRID_PORTFOLIO, { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD });

  const { data: modeData } = useApiData<{ mode: string; is_live: boolean }>(
    API_ENDPOINTS.KALSHI_GRID_MODE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  const isLive = modeData?.is_live ?? false;
  const currentMode = modeData?.mode?.toUpperCase() ?? 'PAPER';

  const normalizePortfolioUpdate = (payload: RawPortfolioUpdate): PortfolioUpdate | null => {
    const totalValue = payload.total_equity ?? 0;
    const totalPnl = payload.total_pnl ?? 0;
    const changePercent = totalValue ? (totalPnl / totalValue) * 100 : 0;
    const timestamp = typeof payload.timestamp === 'string'
      ? Date.parse(payload.timestamp)
      : (payload.timestamp ?? Date.now());

    return {
      total_value: Number.isFinite(totalValue) ? totalValue : 0,
      change_24h: Number.isFinite(totalPnl) ? totalPnl : 0,
      change_24h_percent: Number.isFinite(changePercent) ? changePercent : 0,
      pnl_today: Number.isFinite(totalPnl) ? totalPnl : 0,
      positions_count: payload.position_count ?? 0,
      timestamp,
    };
  };

  // Sync Kalshi live data into displayData whenever it updates
  useEffect(() => {
    const equity = gridPortfolio?.equity_usd
      ?? (kalshiBalance ? (Math.abs(kalshiBalance.usd) > 100000 ? kalshiBalance.usd / 100 : kalshiBalance.usd) : null);
    const pnl = gridPortfolio?.daily_pnl_usd ?? kalshiRisk?.daily_pnl_usd ?? 0;
    const positions = gridPortfolio?.position_count ?? kalshiRisk?.open_market_count ?? 0;
    const pct = equity && equity > 0 ? (pnl / equity) * 100 : 0;

    if (equity != null) {
      setDisplayData(prev => ({
        total_value: equity,
        change_24h: pnl,
        change_24h_percent: Number.isFinite(pct) ? pct : prev.change_24h_percent,
        pnl_today: pnl,
        positions_count: positions,
        timestamp: Date.now(),
      }));
    }
  }, [gridPortfolio, kalshiRisk, kalshiBalance]);

  // REST fallback for WS gap — only used if Kalshi hooks return nothing
  useEffect(() => {
    if (gridPortfolio || kalshiRisk) return; // Kalshi data takes priority
    let cancelled = false;
    const fetchRest = async () => {
      try {
        let res = await fetch(API_ENDPOINTS.PORTFOLIO_SUMMARY);
        if (!res.ok) res = await fetch(API_ENDPOINTS.PORTFOLIO_LIVE);
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
      } catch (err) { logUiError('LivePortfolioValue', 'REST fallback failed', err); }
    };
    fetchRest();
    const interval = setInterval(fetchRest, DEFAULTS.POLLING_INTERVALS.BACKGROUND);
    return () => { cancelled = true; clearInterval(interval); };
  }, [gridPortfolio, kalshiRisk]);

  // WS updates override REST data
  useEffect(() => {
    if (portfolioData) {
      const normalized = normalizePortfolioUpdate(portfolioData);
      if (normalized) {
        setDisplayData(normalized);
      }
    }
  }, [portfolioData]);

  const getChangeColor = (value: number) => {
    if (value > 0) return 'text-green-400';
    if (value < 0) return 'text-red-400';
    return 'text-gray-400';
  };

  return (
    <div className={`rounded-lg border p-6 bg-gradient-to-br ${
      isLive
        ? 'from-green-900/20 to-emerald-900/20 border-green-500/30'
        : 'from-blue-900/20 to-purple-900/20 border-blue-500/30'
    }`}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${isLive ? 'bg-green-500/20' : 'bg-blue-500/20'}`}>
            <DollarSign className={`w-6 h-6 ${isLive ? 'text-green-400' : 'text-blue-400'}`} />
          </div>
          <div>
            <h3 className="text-sm text-gray-400">Kalshi Portfolio Value</h3>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-gray-500'}`} />
              <span className="text-xs text-gray-500">{isConnected ? 'WS live' : 'Polling'}</span>
            </div>
          </div>
        </div>
        {/* Mode badge */}
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold border ${
          isLive
            ? 'bg-green-500/20 text-green-300 border-green-500/30'
            : 'bg-slate-700 text-gray-400 border-slate-600'
        }`}>
          <Radio className={`w-3 h-3 ${isLive ? 'animate-pulse' : ''}`} />
          {currentMode}
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
