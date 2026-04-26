import React, { useState, useCallback, useEffect, useRef } from 'react';
import { useKalshiOrderbookStream } from '../hooks/useKalshiOrderbookStream';
import { Wifi, WifiOff, AlertTriangle, RefreshCw } from '../ui/icons';

interface OrderbookLevel {
  price: number;
  quantity: number;
}

interface OrderbookData {
  ticker: string;
  yes_bids: OrderbookLevel[];
  yes_asks: OrderbookLevel[];
  no_bids: OrderbookLevel[];
  no_asks: OrderbookLevel[];
  spread_cents: number | null;
  midpoint: number | null;
  source?: string;
}

interface KalshiOrderbookPanelProps {
  ticker: string | null;
  depth?: number;
  enhanced?: boolean;
}

type ConnectionStatus = 'connected' | 'disconnected' | 'reconnecting' | 'error';

function LevelRow({ level, side, maxQty, isStale = false }: { level: OrderbookLevel; side: 'bid' | 'ask'; maxQty: number; isStale?: boolean }) {
  const pct = maxQty > 0 ? (level.quantity / maxQty) * 100 : 0;
  const isBid = side === 'bid';
  return (
    <div className={`relative flex items-center justify-between px-2 py-0.5 text-xs font-mono ${isStale ? 'opacity-60' : ''}`}>
      <div className={`absolute inset-0 ${isBid ? 'bg-green-500/10' : 'bg-red-500/10'}`} style={{ width: `${Math.min(100, pct)}%`, left: 0 }} />
      <span className="relative z-10 text-gray-400 w-12 text-right">{level.quantity}</span>
      <span className={`relative z-10 ${isBid ? 'text-green-400' : 'text-red-400'}`}>
        {((level.price ?? 0) * 100).toFixed(0)}¢
      </span>
      {isStale && <span className="relative z-10 text-amber-400 text-[8px] ml-1">STALE</span>}
    </div>
  );
}

function ConnectionStatusIndicator({ status, reconnectAttempts, onRetry, isRetrying }: {
  status: ConnectionStatus;
  reconnectAttempts: number;
  onRetry: () => void;
  isRetrying: boolean;
}) {
  const getStatusIcon = () => {
    switch (status) {
      case 'connected': return <Wifi className="w-4 h-4 text-green-400" />;
      case 'reconnecting': return <RefreshCw className="w-4 h-4 text-amber-400 animate-spin" />;
      case 'error': return <AlertTriangle className="w-4 h-4 text-red-400" />;
      default: return <WifiOff className="w-4 h-4 text-gray-400" />;
    }
  };

  const getStatusColor = () => {
    switch (status) {
      case 'connected': return 'text-green-400';
      case 'reconnecting': return 'text-amber-400';
      case 'error': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getStatusText = () => {
    switch (status) {
      case 'connected': return 'Connected';
      case 'reconnecting': return `Reconnecting... (${reconnectAttempts})`;
      case 'error': return 'Connection failed';
      default: return 'Disconnected';
    }
  };

  return (
    <div className="flex items-center justify-between p-2 bg-slate-800 border-b border-slate-700">
      <div className="flex items-center gap-2">
        {getStatusIcon()}
        <span className={`text-xs ${getStatusColor()}`}>{getStatusText()}</span>
      </div>
      {(status === 'error' || status === 'disconnected') && (
        <button onClick={onRetry} disabled={isRetrying} className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 text-white text-xs rounded">
          <RefreshCw className={`w-3 h-3 ${isRetrying ? 'animate-spin' : ''}`} />
          {isRetrying ? 'Connecting...' : 'Reconnect'}
        </button>
      )}
    </div>
  );
}

function FallbackOrderbook({ ticker, cachedData }: { ticker: string; cachedData: OrderbookData | null }) {
  const hasCachedLevels = cachedData && (cachedData.yes_bids?.length + cachedData.yes_asks?.length) > 0;
  const maxYesBidQty = Math.max(...(cachedData?.yes_bids ?? []).map(l => l.quantity), 1);
  const maxYesAskQty = Math.max(...(cachedData?.yes_asks ?? []).map(l => l.quantity), 1);

  return (
    <div className="bg-slate-800 rounded-xl">
      <div className="p-2 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-xs text-amber-400">{hasCachedLevels ? 'Using cached data (stale)' : 'Orderbook unavailable'}</span>
        </div>
      </div>
      {hasCachedLevels ? (
        <div className="p-3">
          <div className="space-y-1">
            <div className="text-[10px] text-gray-500">Bids</div>
            {cachedData?.yes_bids?.slice(0, 5).map((level, i) => (
              <LevelRow key={`bid-${i}`} level={level} side="bid" maxQty={maxYesBidQty} isStale />
            ))}
          </div>
          <div className="space-y-1 mt-3">
            <div className="text-[10px] text-gray-500">Asks</div>
            {cachedData?.yes_asks?.slice(0, 5).map((level, i) => (
              <LevelRow key={`ask-${i}`} level={level} side="ask" maxQty={maxYesAskQty} isStale />
            ))}
          </div>
        </div>
      ) : (
        <div className="p-6 text-center">
          <WifiOff className="w-6 h-6 text-gray-500 mx-auto mb-2" />
          <p className="text-xs text-gray-500">No orderbook data available</p>
        </div>
      )}
    </div>
  );
}

function KalshiOrderbookPanel({ ticker, depth = 5, enhanced = false }: KalshiOrderbookPanelProps) {
  const [cachedData, setCachedData] = useState<OrderbookData | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  const [isRetrying, setIsRetrying] = useState(false);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const { data, connected, error, updates, lastUpdate } = useKalshiOrderbookStream(ticker, { depth });

  useEffect(() => {
    if (connected) {
      setConnectionStatus('connected');
      setReconnectAttempts(0);
      if (data) setCachedData(data);
    } else if (error) {
      setConnectionStatus('error');
    } else if (!connected && ticker) {
      setConnectionStatus('disconnected');
    }
  }, [connected, error, data, ticker]);

  const handleReconnect = useCallback(async () => {
    setIsRetrying(true);
    setReconnectAttempts(prev => prev + 1);
    setConnectionStatus('reconnecting');
    await new Promise(resolve => setTimeout(resolve, 1000));
    setIsRetrying(false);
  }, []);

  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, []);

  if (!ticker) return null;

  // Base mode - simple
  if (!enhanced) {
    const getConnectionIndicator = () => {
      if (error) return <><div className="w-2 h-2 bg-red-500 rounded-full animate-pulse" /><span className="text-xs text-red-400">Error</span></>;
      if (connected) return <><div className="w-2 h-2 bg-green-500 rounded-full" /><span className="text-xs text-green-400">Live</span>{updates > 0 && <span className="text-xs text-gray-500">({updates})</span>}</>;
      return <><div className="w-2 h-2 bg-yellow-500 rounded-full animate-pulse" /><span className="text-xs text-yellow-400">Connecting…</span></>;
    };

    if (!data && !connected) {
      return (
        <div className="bg-slate-800 rounded-xl p-3">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Orderbook</h4>
          <div className="h-32 flex items-center justify-center text-xs text-gray-600">Connecting to stream…</div>
        </div>
      );
    }

    const bids = (data?.yes_bids ?? []).slice(0, depth);
    const asks = (data?.yes_asks ?? []).slice(0, depth);
    const maxQty = Math.max(...bids.map(l => l.quantity), ...asks.map(l => l.quantity), 1);

    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Orderbook</h4>
            <div className="flex items-center gap-1">{getConnectionIndicator()}</div>
            {data?.source === 'websocket' && <span className="text-xs text-blue-400">WS</span>}
          </div>
          {data?.spread_cents != null && (
            <span className="text-[10px] text-gray-500">
              Spread: <span className="font-mono text-gray-400">{data.spread_cents}¢</span>
              {data.midpoint != null && <> · Mid: <span className="font-mono text-gray-400">{((data.midpoint ?? 0) * 100).toFixed(1)}¢</span></>}
            </span>
          )}
        </div>
        <div className="space-y-px">
          <div className="flex justify-between text-[9px] text-gray-600 px-2 pb-1"><span>QTY</span><span>ASK</span></div>
          {asks.length > 0 ? [...asks].reverse().map((l, i) => <LevelRow key={`a${i}`} level={l} side="ask" maxQty={maxQty} />) : <div className="text-center text-[10px] text-gray-600 py-2">No asks</div>}
        </div>
        <div className="flex items-center gap-2 py-1.5 px-2">
          <div className="flex-1 h-px bg-slate-700" />
          {data?.spread_cents != null && <span className="text-[10px] font-mono text-gray-500">{data.spread_cents}¢</span>}
          <div className="flex-1 h-px bg-slate-700" />
        </div>
        <div className="space-y-px">
          <div className="flex justify-between text-[9px] text-gray-600 px-2 pb-1"><span>QTY</span><span>BID</span></div>
          {bids.length > 0 ? bids.map((l, i) => <LevelRow key={`b${i}`} level={l} side="bid" maxQty={maxQty} />) : <div className="text-center text-[10px] text-gray-600 py-2">No bids</div>}
        </div>
      </div>
    );
  }

  // Enhanced mode
  const isStale = lastUpdate ? Date.now() - lastUpdate > 30000 : false;
  const currentData = data || cachedData;

  if (connectionStatus === 'error' && !cachedData) {
    return (
      <div className="bg-slate-800 rounded-xl">
        <ConnectionStatusIndicator status={connectionStatus} reconnectAttempts={reconnectAttempts} onRetry={handleReconnect} isRetrying={isRetrying} />
        <div className="p-4 text-center">
          <AlertTriangle className="w-8 h-8 text-red-400 mx-auto mb-2" />
          <p className="text-sm text-red-400 mb-2">Orderbook connection failed</p>
          <p className="text-xs text-gray-500">Attempts: {reconnectAttempts}</p>
        </div>
      </div>
    );
  }

  if (!currentData) {
    return (
      <div className="bg-slate-800 rounded-xl">
        <ConnectionStatusIndicator status={connectionStatus} reconnectAttempts={reconnectAttempts} onRetry={handleReconnect} isRetrying={isRetrying} />
        <div className="p-4 text-center text-gray-500 text-sm">Loading orderbook...</div>
      </div>
    );
  }

  const maxYesBidQty = Math.max(...(currentData.yes_bids ?? []).map(l => l.quantity), 1);
  const maxYesAskQty = Math.max(...(currentData.yes_asks ?? []).map(l => l.quantity), 1);

  return (
    <div className="bg-slate-800 rounded-xl">
      <ConnectionStatusIndicator status={connectionStatus} reconnectAttempts={reconnectAttempts} onRetry={handleReconnect} isRetrying={isRetrying} />
      <div className="p-3">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white">{ticker}</h3>
          <div className="flex items-center gap-2">
            {currentData.spread_cents !== null && <span className="text-xs text-gray-400">Spread: {currentData.spread_cents}¢</span>}
            {isStale && <span className="text-xs text-amber-400">Stale</span>}
          </div>
        </div>
        <div className="space-y-1">
          <div className="text-[10px] text-gray-500 mb-1">Asks</div>
          {[...(currentData.yes_asks ?? [])].reverse().slice(0, depth).map((level, i) => (
            <LevelRow key={`ask-${i}`} level={level} side="ask" maxQty={maxYesAskQty} isStale={isStale} />
          ))}
        </div>
        <div className="flex items-center gap-2 py-1.5 px-2">
          <div className="flex-1 h-px bg-slate-700" />
          {currentData.spread_cents != null && <span className="text-[10px] font-mono text-gray-500">{currentData.spread_cents}¢</span>}
          <div className="flex-1 h-px bg-slate-700" />
        </div>
        <div className="space-y-1">
          <div className="text-[10px] text-gray-500 mb-1">Bids</div>
          {(currentData.yes_bids ?? []).slice(0, depth).map((level, i) => (
            <LevelRow key={`bid-${i}`} level={level} side="bid" maxQty={maxYesBidQty} isStale={isStale} />
          ))}
        </div>
      </div>
    </div>
  );
}

KalshiOrderbookPanel.displayName = 'KalshiOrderbookPanel';
export default React.memo(KalshiOrderbookPanel);
