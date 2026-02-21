import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { useRealtimeData } from '../hooks/useRealtimeData';
import { WS_PRICE_URL } from '../config/constants';

interface PriceUpdate {
  symbol: string;
  price: number;
  change24h: number;
  volume24h: number;
  timestamp: number;
}

interface RawPriceUpdate {
  symbol?: string;
  price?: number;
  change24h?: number;
  change_24h?: number;
  volume24h?: number;
  volume_24h?: number;
  volume?: number;
  timestamp?: number | string;
}

interface LivePriceStreamProps {
  symbols?: string[];
  className?: string;
}

export default function LivePriceStream({ symbols = ['BTC', 'ETH', 'SOL'], className = '' }: LivePriceStreamProps) {
  const [prices, setPrices] = useState<Map<string, PriceUpdate>>(new Map());
  const [priceData, isConnected] = useRealtimeData<RawPriceUpdate>('price_tick', null, WS_PRICE_URL);

  const normalizePriceUpdate = (payload: RawPriceUpdate): PriceUpdate | null => {
    const rawSymbol = payload.symbol?.toString() ?? '';
    const symbol = rawSymbol.split('/')[0]?.split('-')[0] ?? '';
    if (!symbol) return null;
    const change24h = payload.change24h ?? payload.change_24h ?? 0;
    const volume24h = payload.volume24h ?? payload.volume_24h ?? payload.volume ?? 0;
    const timestamp = typeof payload.timestamp === 'string'
      ? Date.parse(payload.timestamp)
      : (payload.timestamp ?? Date.now());

    return {
      symbol,
      price: payload.price ?? 0,
      change24h: Number.isFinite(change24h) ? change24h : 0,
      volume24h: Number.isFinite(volume24h) ? volume24h : 0,
      timestamp,
    };
  };

  useEffect(() => {
    if (priceData) {
      const normalized = normalizePriceUpdate(priceData);
      if (!normalized) return;
      setPrices(prev => {
        const newPrices = new Map(prev);
        newPrices.set(normalized.symbol, normalized);
        return newPrices;
      });
    }
  }, [priceData]);

  const getPriceColor = (change: number) => {
    if (change > 0) return 'text-green-400';
    if (change < 0) return 'text-red-400';
    return 'text-gray-400';
  };

  return (
    <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-4 ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-white">Live Prices</h3>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
          <span className="text-xs text-gray-400">{isConnected ? 'Live' : 'Disconnected'}</span>
        </div>
      </div>

      <div className="space-y-3">
        {symbols.map(symbol => {
          const data = prices.get(symbol);
          if (!data) {
            return (
              <div key={symbol} className="flex items-center justify-between p-3 bg-slate-900/50 rounded">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-gray-400">{symbol}/USD</span>
                </div>
                <span className="text-sm text-gray-500">Waiting for data...</span>
              </div>
            );
          }

          return (
            <div key={symbol} className="flex items-center justify-between p-3 bg-slate-900/50 rounded hover:bg-slate-900/70 transition-colors">
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-white">{symbol}/USD</span>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <div className="text-lg font-bold text-white">
                    ${data.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </div>
                  <div className="text-xs text-gray-400">
                    Vol: ${(data.volume24h / 1000000).toFixed(1)}M
                  </div>
                </div>
                <div className={`flex items-center gap-1 ${getPriceColor(data.change24h)}`}>
                  {data.change24h > 0 ? (
                    <TrendingUp className="w-4 h-4" />
                  ) : data.change24h < 0 ? (
                    <TrendingDown className="w-4 h-4" />
                  ) : null}
                  <span className="text-sm font-medium">
                    {data.change24h > 0 ? '+' : ''}{data.change24h.toFixed(2)}%
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
