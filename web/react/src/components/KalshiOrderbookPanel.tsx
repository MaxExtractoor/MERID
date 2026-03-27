import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

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
        style={{ width: `${Math.min(100, pct)}%`, [isBid ? 'right' : 'left']: 0 }}
      />
      <span className="relative z-10 text-gray-400 w-12 text-right">{level.quantity}</span>
      <span className={`relative z-10 ${isBid ? 'text-green-400' : 'text-red-400'}`}>
        {(level.price * 100).toFixed(0)}¢
      </span>
    </div>
  );
}

export default function KalshiOrderbookPanel({ ticker, depth = 5 }: KalshiOrderbookPanelProps) {
  if (!ticker) return null;

  const { data, loading, error } = useApiData<OrderbookData>(
    API_ENDPOINTS.KALSHI_ORDERBOOK(ticker),
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  if (loading && !data) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Orderbook</h4>
        <div className="h-32 flex items-center justify-center text-xs text-gray-600">Loading…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Orderbook</h4>
        <div className="text-rose-400 text-xs p-4">Failed to load orderbook: {error.message || 'Unknown error'}</div>
      </div>
    );
  }

  const bids = (data?.yes_bids ?? []).slice(0, depth);
  const asks = (data?.yes_asks ?? []).slice(0, depth);
  const quantities = [
    ...bids.map(l => l.quantity),
    ...asks.map(l => l.quantity),
  ];
  const maxQty = quantities.length > 0 ? Math.max(...quantities) : 1;

  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Orderbook</h4>
        {data?.spread_cents != null && (
          <span className="text-[10px] text-gray-500">
            Spread: <span className="font-mono text-gray-400">{data.spread_cents}¢</span>
            {data.midpoint != null && (
              <> · Mid: <span className="font-mono text-gray-400">{(data.midpoint * 100).toFixed(1)}¢</span></>
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
