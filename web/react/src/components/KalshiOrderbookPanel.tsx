import React from 'react';
import { useKalshiOrderbookStream } from '../hooks/useKalshiOrderbookStream';

interface OrderbookLevel {
  price: number;
  quantity: number;
}

interface KalshiOrderbookPanelProps {
  ticker: string | null;
  depth?: number;
}

function LevelRow({ level, side, maxQty }: { level: OrderbookLevel; side: 'bid' | 'ask'; maxQty: number }) {
  const pct = maxQty > 0 ? (level.quantity / maxQty) * 100 : 0;
  const isBid = side === 'bid';
  return (
    <div className="relative flex items-center justify-between px-2 py-0.5 text-xs font-mono">
      <div
        className={`absolute inset-0 ${isBid ? 'bg-green-500/10' : 'bg-red-500/10'}`}
        style={{ width: `${Math.min(100, pct)}%`, left: 0 }}
      />
      <span className="relative z-10 text-gray-400 w-12 text-right">{level.quantity}</span>
      <span className={`relative z-10 ${isBid ? 'text-green-400' : 'text-red-400'}`}>
        {((level.price ?? 0) * 100).toFixed(0)}¢
      </span>
    </div>
  );
}

function KalshiOrderbookPanel({ ticker, depth = 5 }: KalshiOrderbookPanelProps) {
  const { data, connected, error, updates } = useKalshiOrderbookStream(ticker, { depth });

  if (!ticker) return null;

  // Show connection status
  const getConnectionIndicator = () => {
    if (error) {
      return (
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
          <span className="text-xs text-red-400">Error</span>
        </div>
      );
    }
    if (connected) {
      return (
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 bg-green-500 rounded-full"></div>
          <span className="text-xs text-green-400">Live</span>
          {updates > 0 && (
            <span className="text-xs text-gray-500">({updates})</span>
          )}
        </div>
      );
    }
    return (
      <div className="flex items-center gap-1">
        <div className="w-2 h-2 bg-yellow-500 rounded-full animate-pulse"></div>
        <span className="text-xs text-yellow-400">Connecting…</span>
      </div>
    );
  };

  if (!data && !connected) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Orderbook</h4>
        <div className="h-32 flex items-center justify-center text-xs text-gray-600">
          Connecting to stream…
        </div>
      </div>
    );
  }

  const bids = (data?.yes_bids ?? []).slice(0, depth);
  const asks = (data?.yes_asks ?? []).slice(0, depth);
  const maxQty = Math.max(
    ...bids.map(l => l.quantity),
    ...asks.map(l => l.quantity),
    1,
  );

  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Orderbook</h4>
          {getConnectionIndicator()}
          {data?.source === 'websocket' && (
            <span className="text-xs text-blue-400">WS</span>
          )}
        </div>
        {data?.spread_cents != null && (
          <span className="text-[10px] text-gray-500">
            Spread: <span className="font-mono text-gray-400">{data.spread_cents}¢</span>
            {data.midpoint != null && (
              <> · Mid: <span className="font-mono text-gray-400">{((data.midpoint ?? 0) * 100).toFixed(1)}¢</span></>
            )}
          </span>
        )}
      </div>

      {/* Asks (reversed so best ask is at bottom) */}
      <div className="space-y-px">
        <div className="flex justify-between text-[9px] text-gray-600 px-2 pb-1">
          <span>QTY</span>
          <span>ASK</span>
        </div>
        {asks.length > 0 ? (
          [...asks].reverse().map((l, i) => <LevelRow key={`a${i}`} level={l} side="ask" maxQty={maxQty} />)
        ) : (
          <div className="text-center text-[10px] text-gray-600 py-2">No asks</div>
        )}
      </div>

      {/* Spread divider */}
      <div className="flex items-center gap-2 py-1.5 px-2">
        <div className="flex-1 h-px bg-slate-700" />
        {data?.spread_cents != null && (
          <span className="text-[10px] font-mono text-gray-500">{data.spread_cents}¢</span>
        )}
        <div className="flex-1 h-px bg-slate-700" />
      </div>

      {/* Bids */}
      <div className="space-y-px">
        <div className="flex justify-between text-[9px] text-gray-600 px-2 pb-1">
          <span>QTY</span>
          <span>BID</span>
        </div>
        {bids.length > 0 ? (
          bids.map((l, i) => <LevelRow key={`b${i}`} level={l} side="bid" maxQty={maxQty} />)
        ) : (
          <div className="text-center text-[10px] text-gray-600 py-2">No bids</div>
        )}
      </div>
    </div>
  );
}

KalshiOrderbookPanel.displayName = 'KalshiOrderbookPanel';
export default React.memo(KalshiOrderbookPanel);
