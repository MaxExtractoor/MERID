/**
 * TradesTable - Real-time streaming trades table.
 * 
 * Displays live trade executions from Kafka/WebSocket stream with:
 * - Symbol, side, size, price, venue, timestamp columns
 * - Color-coded buy/sell rows
 * - Auto-scroll for new trades
 * - Connection status indicator
 */

import { useState, useEffect, useRef } from 'react';
import { 
  Activity,
  TrendingUp, 
  TrendingDown, 
  Bot, 
  User,
  Wifi,
  WifiOff,
  Pause,
  Play,
  Filter,
  X
} from 'lucide-react';
import { useTradeEvents } from '../hooks/useKafkaStream';

interface Trade {
  event_id?: string;
  event_type: string;
  trader_type: 'human' | 'agent' | 'system';
  trader_id: string;
  timestamp: number;
  venue?: string;
  symbol?: string;
  side?: string;
  qty?: number;
  price?: number;
  status?: string;
  order_id?: string;
  is_simulated?: boolean;
}

interface TradesTableProps {
  maxRows?: number;
  showFilters?: boolean;
  compact?: boolean;
  symbols?: string[];
}

export default function TradesTable({
  maxRows = 100,
  showFilters = true,
  compact = false,
  symbols,
}: TradesTableProps) {
  const { events, connected, reconnectCount } = useTradeEvents({ maxEvents: maxRows });
  const [paused, setPaused] = useState(false);
  const [displayedTrades, setDisplayedTrades] = useState<Trade[]>([]);
  const [symbolFilter, setSymbolFilter] = useState<string>('');
  const [sideFilter, setSideFilter] = useState<'all' | 'buy' | 'sell'>('all');
  const [traderFilter, setTraderFilter] = useState<'all' | 'agent' | 'human'>('all');
  const tableRef = useRef<HTMLDivElement>(null);

  // Update displayed trades when not paused
  useEffect(() => {
    if (!paused) {
      let filtered = events as unknown as Trade[];

      // Apply symbol filter
      if (symbolFilter) {
        filtered = filtered.filter(t => 
          t.symbol?.toLowerCase().includes(symbolFilter.toLowerCase())
        );
      }

      // Apply symbols prop filter
      if (symbols && symbols.length > 0) {
        filtered = filtered.filter(t => 
          t.symbol && symbols.includes(t.symbol)
        );
      }

      // Apply side filter
      if (sideFilter !== 'all') {
        filtered = filtered.filter(t => t.side?.toLowerCase() === sideFilter);
      }

      // Apply trader filter
      if (traderFilter !== 'all') {
        filtered = filtered.filter(t => t.trader_type === traderFilter);
      }

      setDisplayedTrades(filtered.slice(0, maxRows));
    }
  }, [events, paused, symbolFilter, sideFilter, traderFilter, symbols, maxRows]);

  const formatTime = (ts: number) => {
    if (!ts) return '-';
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString([], { 
      hour: '2-digit', 
      minute: '2-digit', 
      second: '2-digit',
      hour12: false 
    });
  };

  const formatPrice = (price?: number) => {
    if (!price) return '-';
    return `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatQty = (qty?: number) => {
    if (!qty) return '-';
    if (qty >= 1) return qty.toFixed(4);
    return qty.toFixed(8);
  };

  const getSideColor = (side?: string) => {
    if (!side) return 'text-gray-400';
    return side.toLowerCase() === 'buy' ? 'text-green-400' : 'text-red-400';
  };

  const getSideIcon = (side?: string) => {
    if (!side) return null;
    return side.toLowerCase() === 'buy' 
      ? <TrendingUp className="w-4 h-4 text-green-400" />
      : <TrendingDown className="w-4 h-4 text-red-400" />;
  };

  const getTraderIcon = (traderType: string) => {
    return traderType === 'agent' 
      ? <Bot className="w-4 h-4 text-purple-400" />
      : <User className="w-4 h-4 text-blue-400" />;
  };

  const getRowClass = (trade: Trade) => {
    const base = 'border-t border-slate-700/30 hover:bg-slate-800/50 transition-colors';
    if (trade.side?.toLowerCase() === 'buy') {
      return `${base} bg-green-500/5`;
    }
    if (trade.side?.toLowerCase() === 'sell') {
      return `${base} bg-red-500/5`;
    }
    return base;
  };

  const uniqueSymbols = [...new Set(events.map((e: any) => e.symbol).filter(Boolean))];

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700/50 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-semibold text-white">Live Trades</h2>
          <span className="text-sm text-gray-400">({displayedTrades.length})</span>
        </div>

        <div className="flex items-center gap-3">
          {/* Connection Status */}
          <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs ${
            connected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
          }`}>
            {connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {connected ? 'Live' : `Reconnecting (${reconnectCount})`}
          </div>

          {/* Pause/Play */}
          <button
            onClick={() => setPaused(!paused)}
            className={`p-1.5 rounded transition-colors ${
              paused ? 'bg-yellow-500/20 text-yellow-400' : 'hover:bg-slate-700/50 text-gray-400'
            }`}
            title={paused ? 'Resume updates' : 'Pause updates'}
          >
            {paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Filters */}
      {showFilters && (
        <div className="p-3 border-b border-slate-700/50 flex items-center gap-3 bg-slate-800/30">
          <Filter className="w-4 h-4 text-gray-500" />
          
          {/* Symbol Filter */}
          <div className="relative">
            <input
              id="trades-symbol-filter"
              name="symbolFilter"
              type="text"
              placeholder="Symbol..."
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-gray-300 w-24 focus:outline-none focus:border-blue-500"
            />
            {symbolFilter && (
              <button
                onClick={() => setSymbolFilter('')}
                className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                title="Clear filter"
                aria-label="Clear symbol filter"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          {/* Side Filter */}
          <select
            id="trades-side-filter"
            name="sideFilter"
            value={sideFilter}
            onChange={(e) => setSideFilter(e.target.value as any)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-gray-300"
            aria-label="Filter by side"
          >
            <option value="all">All Sides</option>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>

          {/* Trader Filter */}
          <select
            id="trades-trader-filter"
            name="traderFilter"
            value={traderFilter}
            onChange={(e) => setTraderFilter(e.target.value as any)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm text-gray-300"
            aria-label="Filter by trader type"
          >
            <option value="all">All Traders</option>
            <option value="agent">Agents</option>
            <option value="human">Humans</option>
          </select>

          {/* Quick symbol buttons */}
          {uniqueSymbols.slice(0, 4).map(sym => (
            <button
              key={sym}
              onClick={() => setSymbolFilter(symbolFilter === sym ? '' : sym)}
              className={`px-2 py-0.5 text-xs rounded transition-colors ${
                symbolFilter === sym 
                  ? 'bg-blue-500/20 text-blue-400 border border-blue-500/50'
                  : 'bg-slate-800 text-gray-400 hover:bg-slate-700'
              }`}
            >
              {sym}
            </button>
          ))}
        </div>
      )}

      {/* Table */}
      <div ref={tableRef} className="flex-1 overflow-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-slate-800/90 backdrop-blur">
            <tr className={`text-left text-gray-400 ${compact ? 'text-xs' : 'text-sm'}`}>
              <th className="p-3">Type</th>
              <th className="p-3">Trader</th>
              <th className="p-3">Symbol</th>
              <th className="p-3">Side</th>
              <th className="p-3">Size</th>
              <th className="p-3">Price</th>
              <th className="p-3">Venue</th>
              <th className="p-3">Time</th>
            </tr>
          </thead>
          <tbody>
            {displayedTrades.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-8 text-center text-gray-500">
                  <Activity className="w-8 h-8 mx-auto mb-2 opacity-50 animate-pulse" />
                  <p>Waiting for trades...</p>
                  <p className="text-sm mt-1">Trades will appear here in real-time</p>
                </td>
              </tr>
            ) : (
              displayedTrades.map((trade, idx) => (
                <tr key={trade.event_id || `${trade.timestamp}-${idx}`} className={getRowClass(trade)}>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      trade.event_type?.includes('filled') 
                        ? 'bg-green-500/20 text-green-400'
                        : trade.event_type?.includes('decision')
                        ? 'bg-purple-500/20 text-purple-400'
                        : 'bg-slate-500/20 text-gray-400'
                    }`}>
                      {trade.event_type?.replace('order_', '').replace('agent_', '') || 'trade'}
                    </span>
                  </td>
                  <td className="p-3">
                    <div className="flex items-center gap-2">
                      {getTraderIcon(trade.trader_type)}
                      <span className={`font-mono ${compact ? 'text-xs' : 'text-sm'} text-white truncate max-w-[120px]`}>
                        {trade.trader_id}
                      </span>
                    </div>
                  </td>
                  <td className="p-3 font-medium text-white">
                    {trade.symbol || '-'}
                  </td>
                  <td className={`p-3 font-medium ${getSideColor(trade.side)}`}>
                    <div className="flex items-center gap-1">
                      {getSideIcon(trade.side)}
                      {trade.side?.toUpperCase() || '-'}
                    </div>
                  </td>
                  <td className="p-3 text-gray-300 font-mono text-sm">
                    {formatQty(trade.qty)}
                  </td>
                  <td className="p-3 text-gray-300">
                    {formatPrice(trade.price)}
                  </td>
                  <td className="p-3 text-gray-400 text-sm">
                    {trade.venue || '-'}
                    {trade.is_simulated && (
                      <span className="ml-1 text-xs text-yellow-500">(sim)</span>
                    )}
                  </td>
                  <td className="p-3 text-gray-500 text-sm">
                    {formatTime(trade.timestamp)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Footer Stats */}
      {displayedTrades.length > 0 && (
        <div className="p-2 border-t border-slate-700/50 bg-slate-800/30 flex items-center justify-between text-xs text-gray-500">
          <span>
            Buys: <span className="text-green-400">{displayedTrades.filter(t => t.side?.toLowerCase() === 'buy').length}</span>
            {' | '}
            Sells: <span className="text-red-400">{displayedTrades.filter(t => t.side?.toLowerCase() === 'sell').length}</span>
          </span>
          <span>
            Agents: <span className="text-purple-400">{displayedTrades.filter(t => t.trader_type === 'agent').length}</span>
            {' | '}
            Humans: <span className="text-blue-400">{displayedTrades.filter(t => t.trader_type === 'human').length}</span>
          </span>
        </div>
      )}
    </div>
  );
}
