# MERID WebSocket Message Formats

Base URL: `WS_URL` from `web/react/src/config/constants.ts` (default `ws://127.0.0.1:8000`).

## Conventions

- Most streams send **heartbeat** messages to keep connections alive.
- Some streams support **ping/pong** (send `{ "type": "ping" }`).
- Timestamps are Unix seconds unless noted otherwise.

## Trade Events (`/ws/trades`)

Unified trade events stream for TradeFloor (`web/api/ws_trade_events.py`).

**Message shape**
```json
{
  "event_type": "order_filled",
  "trader_type": "agent",
  "trader_id": "agent-123",
  "timestamp": 1730000000,
  "symbol": "BTC-USD",
  "side": "BUY",
  "qty": 0.5,
  "price": 63000,
  "status": "filled",
  "order_id": "ord_abc123",
  "is_simulated": true
}
```

**Special messages**
- `event_type: "mode_status"` emitted on connect
- `event_type: "heartbeat"`

## Orders Stream (`/ws/orders`)

Orders-only filter of trade events (same schema as `/ws/trades`).

## Risk Stream (`/ws/risk`)

Risk events plus periodic summaries.

**Risk summary**
```json
{
  "event_type": "risk_summary",
  "timestamp": 1730000000,
  "total_equity": 100000,
  "total_pnl": 1200,
  "unrealized_pnl": 400,
  "position_count": 8,
  "exposure": 25000
}
```

## Prices Stream (`/ws/prices`)

Live price updates from `web/api/ws_dedicated_streams.py`.

**Snapshot**
```json
{
  "type": "prices_snapshot",
  "prices": { "BTC-USD": { "price": 63000, "volume": 1200 } },
  "timestamp": 1730000000
}
```

**Updates**
```json
{
  "type": "price_update",
  "symbol": "BTC-USD",
  "price": 63010,
  "volume": 1250,
  "timestamp": 1730000005,
  "change_24h": 1.2
}
```

## Portfolio Stream (`/ws/portfolio`)

Portfolio stats + position updates.

**Portfolio snapshot**
```json
{
  "type": "portfolio_snapshot",
  "total_equity": 100000,
  "total_pnl": 1200,
  "timestamp": 1730000000
}
```

**Positions update**
```json
{
  "type": "positions_update",
  "positions": [ { "symbol": "BTC-USD", "qty": 0.5 } ],
  "timestamp": 1730000000
}
```

## Consensus Stream (`/api/v1/consensus/ws/stream`)

Streams consensus opinions/plans/status updates.

**Init payload**
```json
{
  "type": "init",
  "data": {
    "metrics": {},
    "recent_opinions": [],
    "active_plans": []
  },
  "ts": 1730000000
}
```

**Event payload**
```json
{
  "type": "opinion",
  "data": { "opinion_id": "op_123", "symbol": "BTC" },
  "ts": 1730000001
}
```

## Streaming Bus (`/ws/live`, `/ws/market`, `/ws/news`, `/ws/agents`)

Event bus streams from `web/api/live_stream.py`.

```json
{
  "channel": "market_data",
  "event_type": "tick",
  "data": { "symbol": "BTC-USD", "price": 63000 },
  "timestamp": 1730000000,
  "source": "live_price_feed"
}
```

## Paper Trading (`/ws/paper/*`)

Endpoints in `web/api/ws_paper.py`:

- `/ws/paper/summary`
- `/ws/paper/trades`
- `/ws/paper/positions`
- `/ws/agents/activity`

Messages include a `type` field (e.g., `"trade"`, `"summary"`, `"positions"`, `"agent_snapshot"`) and a `ts` timestamp.
