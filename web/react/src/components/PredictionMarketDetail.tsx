import { useState, useEffect, useCallback } from 'react';
import {
  Clock, DollarSign, BarChart3, RefreshCw
} from 'lucide-react';

interface MarketSnapshot {
  ticker: string;
  title: string;
  category: string;
  yesAsk: number;
  yesBid: number;
  noAsk: number;
  noBid: number;
  impliedProb: number;
  volume24h: number;
  openInterest: number;
  expiresAt: string;
  expiryPhase: 'EARLY' | 'MID' | 'LATE' | 'TERMINAL';
  edge: number;
  edgeType: 'arb' | 'speculative' | 'none';
  positionQty: number;
  positionSide: 'yes' | 'no' | 'none';
  unrealizedPnl: number;
  status: 'TRADING' | 'CLOSING' | 'CLOSED' | 'SETTLED';
}

interface PredictionMarketDetailProps {
  ticker?: string;
}

const PHASE_COLORS: Record<string, string> = {
  EARLY: 'bg-green-500/20 text-green-400',
  MID: 'bg-blue-500/20 text-blue-400',
  LATE: 'bg-amber-500/20 text-amber-400',
  TERMINAL: 'bg-red-500/20 text-red-400',
};

const STATUS_COLORS: Record<string, string> = {
  TRADING: 'bg-green-500/20 text-green-400',
  CLOSING: 'bg-amber-500/20 text-amber-400',
  CLOSED: 'bg-gray-500/20 text-gray-400',
  SETTLED: 'bg-blue-500/20 text-blue-400',
};

export default function PredictionMarketDetail({ ticker }: PredictionMarketDetailProps) {
  const [markets, setMarkets] = useState<MarketSnapshot[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<MarketSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchMarkets = useCallback(async () => {
    try {
      const url = ticker
        ? `/api/v1/prediction-markets/summary?ticker=${ticker}`
        : '/api/v1/prediction-markets/summary';
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        if (data.markets) {
          setMarkets(data.markets);
          if (!selectedMarket && data.markets.length > 0) {
            setSelectedMarket(data.markets[0]);
          }
          setLoading(false);
          return;
        }
      }
    } catch {
      // fallback
    }

    const mock: MarketSnapshot[] = [
      {
        ticker: 'KXBTC-105K-YES', title: 'BTC above $105K by Feb 14', category: 'Crypto',
        yesAsk: 62, yesBid: 60, noAsk: 40, noBid: 38,
        impliedProb: 0.61, volume24h: 12500, openInterest: 45000,
        expiresAt: '2026-02-14T23:59:00Z', expiryPhase: 'MID',
        edge: 3.2, edgeType: 'speculative', positionQty: 50, positionSide: 'yes',
        unrealizedPnl: 15.50, status: 'TRADING',
      },
      {
        ticker: 'KXFED-HOLD-YES', title: 'Fed holds rates in March', category: 'Economics',
        yesAsk: 78, yesBid: 76, noAsk: 24, noBid: 22,
        impliedProb: 0.77, volume24h: 8200, openInterest: 32000,
        expiresAt: '2026-03-19T18:00:00Z', expiryPhase: 'EARLY',
        edge: 1.5, edgeType: 'speculative', positionQty: 0, positionSide: 'none',
        unrealizedPnl: 0, status: 'TRADING',
      },
      {
        ticker: 'KXETH-4K-YES', title: 'ETH above $4K by Feb 28', category: 'Crypto',
        yesAsk: 35, yesBid: 33, noAsk: 67, noBid: 65,
        impliedProb: 0.34, volume24h: 5600, openInterest: 18000,
        expiresAt: '2026-02-28T23:59:00Z', expiryPhase: 'MID',
        edge: -2.0, edgeType: 'none', positionQty: 30, positionSide: 'no',
        unrealizedPnl: -8.20, status: 'TRADING',
      },
    ];
    setMarkets(mock);
    if (!selectedMarket) setSelectedMarket(mock[0]);
    setLoading(false);
  }, [ticker, selectedMarket]);

  useEffect(() => {
    fetchMarkets();
    const interval = setInterval(fetchMarkets, 5000);
    return () => clearInterval(interval);
  }, [fetchMarkets]);

  const daysToExpiry = (expiresAt: string) => {
    const ms = new Date(expiresAt).getTime() - Date.now();
    if (ms <= 0) return '0d';
    const days = Math.floor(ms / 86400000);
    const hours = Math.floor((ms % 86400000) / 3600000);
    return days > 0 ? `${days}d ${hours}h` : `${hours}h`;
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading prediction markets...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-orange-400" />
          <h3 className="text-lg font-bold text-white">Prediction Markets</h3>
          <span className="text-sm text-gray-400">{markets.length} active</span>
        </div>
        <button
          onClick={fetchMarkets}
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh markets"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Market List + Detail */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Market List */}
        <div className="space-y-2">
          {markets.map(m => {
            const isSelected = selectedMarket?.ticker === m.ticker;
            const hasPosition = m.positionQty > 0;
            return (
              <button
                key={m.ticker}
                onClick={() => setSelectedMarket(m)}
                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                  isSelected
                    ? 'bg-blue-600/20 border-blue-500/50'
                    : 'bg-slate-800/50 border-slate-700/50 hover:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-white truncate">{m.title}</span>
                  {hasPosition && (
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      m.unrealizedPnl >= 0 ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {m.positionSide.toUpperCase()} {m.positionQty}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-400">{m.ticker}</span>
                  <div className="flex items-center gap-2">
                    <span className={`font-mono ${m.impliedProb > 0.5 ? 'text-green-400' : 'text-red-400'}`}>
                      {(m.impliedProb * 100).toFixed(0)}%
                    </span>
                    <span className={`px-1.5 py-0.5 rounded ${PHASE_COLORS[m.expiryPhase]}`}>
                      {m.expiryPhase}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        {/* Detail Panel */}
        {selectedMarket && (
          <div className="lg:col-span-2 bg-slate-800/50 rounded-lg border border-slate-700/50 p-4 space-y-4">
            {/* Title + Status */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <h4 className="text-lg font-bold text-white">{selectedMarket.title}</h4>
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLORS[selectedMarket.status]}`}>
                    {selectedMarket.status}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded ${PHASE_COLORS[selectedMarket.expiryPhase]}`}>
                    {selectedMarket.expiryPhase}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-3 text-sm text-gray-400">
                <span>{selectedMarket.ticker}</span>
                <span>·</span>
                <span>{selectedMarket.category}</span>
                <span>·</span>
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {daysToExpiry(selectedMarket.expiresAt)}
                </span>
              </div>
            </div>

            {/* Order Book Summary */}
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-900/50 rounded-lg p-3">
                <div className="text-center mb-2">
                  <span className="text-xs text-gray-400 uppercase">Yes</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <div>
                    <span className="text-gray-500">Bid</span>
                    <p className="font-mono text-green-400 font-medium">{selectedMarket.yesBid}¢</p>
                  </div>
                  <div className="text-center">
                    <span className="text-2xl font-bold text-white">
                      {(selectedMarket.impliedProb * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="text-gray-500">Ask</span>
                    <p className="font-mono text-red-400 font-medium">{selectedMarket.yesAsk}¢</p>
                  </div>
                </div>
              </div>
              <div className="bg-slate-900/50 rounded-lg p-3">
                <div className="text-center mb-2">
                  <span className="text-xs text-gray-400 uppercase">No</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <div>
                    <span className="text-gray-500">Bid</span>
                    <p className="font-mono text-green-400 font-medium">{selectedMarket.noBid}¢</p>
                  </div>
                  <div className="text-center">
                    <span className="text-2xl font-bold text-white">
                      {((1 - selectedMarket.impliedProb) * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="text-gray-500">Ask</span>
                    <p className="font-mono text-red-400 font-medium">{selectedMarket.noAsk}¢</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Metrics Row */}
            <div className="grid grid-cols-4 gap-3">
              <div className="text-center">
                <span className="text-xs text-gray-400">Volume (24h)</span>
                <p className="text-sm font-medium text-white">${selectedMarket.volume24h.toLocaleString()}</p>
              </div>
              <div className="text-center">
                <span className="text-xs text-gray-400">Open Interest</span>
                <p className="text-sm font-medium text-white">${selectedMarket.openInterest.toLocaleString()}</p>
              </div>
              <div className="text-center">
                <span className="text-xs text-gray-400">Edge</span>
                <p className={`text-sm font-medium font-mono ${
                  selectedMarket.edge > 0 ? 'text-green-400' : selectedMarket.edge < 0 ? 'text-red-400' : 'text-gray-400'
                }`}>
                  {selectedMarket.edge > 0 ? '+' : ''}{selectedMarket.edge.toFixed(1)}%
                </p>
              </div>
              <div className="text-center">
                <span className="text-xs text-gray-400">Edge Type</span>
                <p className={`text-sm font-medium ${
                  selectedMarket.edgeType === 'arb' ? 'text-green-400' :
                  selectedMarket.edgeType === 'speculative' ? 'text-amber-400' : 'text-gray-400'
                }`}>
                  {selectedMarket.edgeType}
                </p>
              </div>
            </div>

            {/* Position */}
            {selectedMarket.positionQty > 0 && (
              <div className="bg-slate-900/50 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <DollarSign className="w-4 h-4 text-gray-400" />
                    <span className="text-sm text-gray-400">Position</span>
                    <span className="text-sm font-medium text-white">
                      {selectedMarket.positionQty} {selectedMarket.positionSide.toUpperCase()} contracts
                    </span>
                  </div>
                  <span className={`text-sm font-mono font-medium ${
                    selectedMarket.unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {selectedMarket.unrealizedPnl >= 0 ? '+' : ''}${selectedMarket.unrealizedPnl.toFixed(2)}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
