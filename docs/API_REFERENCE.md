# MERID API Reference

**Version:** 3.4.0
**Base URL:** `http://localhost:8000`
**Interactive docs:** `/docs` (Swagger UI), `/redoc` (ReDoc)

---

## Kalshi Trading

#### GET `/api/v1/kalshi/markets`

Browse available Kalshi markets with category/status filters.

#### GET `/api/v1/kalshi/market/{ticker}`

Single market detail: orderbook, last price, volume, open interest.

#### GET `/api/v1/kalshi/markets/{ticker}/orderbook`

Get real-time orderbook data. Uses WebSocket service for live data, falls back to REST.

**Response:**
```json
{
  "ticker": "KXBTC-24DEC-ABOVE-60000",
  "yes_bids": [{"price": 0.45, "quantity": 100}],
  "yes_asks": [{"price": 0.55, "quantity": 50}],
  "no_bids": [{"price": 0.45, "quantity": 100}],
  "no_asks": [{"price": 0.55, "quantity": 50}],
  "spread_cents": 10,
  "midpoint": 0.50,
  "source": "websocket"
}
```

#### GET `/api/v1/kalshi/markets/{ticker}/orderbook/stream`

**Server-Sent Events** stream for real-time orderbook updates.

**Events:**
- `snapshot` - Full orderbook state
- `delta` - Incremental price level updates  
- `heartbeat` - Periodic keepalive
- `error` - Connection or parsing errors

**Example:**
```javascript
const eventSource = new EventSource('/api/v1/kalshi/markets/KXBTC-24DEC-ABOVE-60000/orderbook/stream');
eventSource.addEventListener('snapshot', (e) => {
  const orderbook = JSON.parse(e.data);
  console.log('Orderbook snapshot:', orderbook);
});
```

#### GET `/api/v1/kalshi/positions`

Current Kalshi positions with unrealized PnL.

#### GET `/api/v1/kalshi/orders`

Active and recent orders.

#### GET `/api/v1/kalshi/fills`

Trade fill history.

#### POST `/api/v1/kalshi/order`

Place a Kalshi order. Body: `{"ticker": "...", "side": "yes", "count": 10, "price": 55}`

#### DELETE `/api/v1/kalshi/order/{order_id}`

Cancel a pending order.

#### GET `/api/v1/kalshi/portfolio`

Portfolio summary: balance, equity, PnL, positions count.

---

## Agent Grid & Consensus

#### GET `/api/v1/kalshi/agent-grid`

Agent grid status: 5 rows × 4 columns, per-agent signals, confidence, stance.

#### GET `/api/v1/kalshi/agent-performance`

Agent performance metrics: accuracy, PnL contribution, trust score history.

#### GET `/api/v1/kalshi/consensus`

Swarm consensus state: vote distribution, quorum status, agreement level.

---

## Pipeline & Risk

#### GET `/api/v1/pipeline/summary`

Full pipeline status (domains, venues, instruments, proposals).

#### GET `/api/v1/pipeline/risk`

Global risk manager summary (exposure, daily loss, position counts).

#### GET `/api/v1/pipeline/risk-context`

Live RiskContext snapshot (CQI, size_scale_factor, approval_threshold_boost, kill switch).

#### GET `/api/v1/pipeline/proposals`

Recent trade proposal history.

---

## Operator

#### GET `/api/operator/summary`

Bundled operator dashboard (portfolio + risk + swarm + system status).

#### GET `/api/operator/audit-trail`

Operator audit trail entries.

#### POST `/api/v1/operator/mode`

Set trading mode. Body: `{"mode": "paper"}`

---

## Prediction Markets

#### GET `/api/v1/prediction-markets/summary`

Prediction markets dashboard summary.

#### GET `/api/v1/prediction-markets/risk`

Risk summary + breach log.

#### POST `/api/v1/prediction-markets/kill-switch`

Activate/deactivate kill switch. Body: `{"activate": true}`

---

## Safety & Mode Control

#### GET `/api/v1/operator/kill-switch`

Kill switch status: `global_kill`, `can_trade`, `kill_reason`, `daily_pnl`, `daily_loss_limit`.

#### POST `/api/v1/operator/emergency-stop`

Emergency stop — halt all trading immediately. Triggers global kill switch.

#### POST `/api/v1/operator/reset-kill-switch`

Reset kill switch after emergency stop. Requires explicit operator action.

#### GET `/api/v1/kalshi-grid/mode`

Current trading mode: `mode` (mock/paper/live), `is_live`, `live_enabled`.

#### POST `/api/v1/kalshi-grid/mode`

Switch trading mode. Body: `{"mode": "paper"}`. Transition to LIVE requires `MERID_ALLOW_LIVE_TRADES=true` env var.

#### GET `/api/v1/operator/risk-state`

Full risk state: daily PnL, position value, error counts, near-limit warnings.

---

## Health & System

#### GET `/healthz`

Health check.

#### GET `/risk/status`

Circuit breaker + kill switch status.

#### GET `/api/v1/system/fresh-start`

Fresh start status (paper mode reset state).

---

## WebSocket

#### WS `/ws/live`

Real-time portfolio updates (positions, PnL, fills).

#### WS `/ws/market`

Orderbook streaming for focused market.

---

## Safety Defaults

The API server starts with these safety defaults:

- **Trade mode:** `paper` (no real orders)
- **KALSHI_USE_DEMO:** `true` (demo API sandbox)
- **MERID_ALLOW_LIVE_TRADES:** `false` (blocks LIVE mode transitions)
- **Agent limits:** $250 max notional, 500 max contracts, 10 max orders per window
- **Kill switch:** Armed, $500 daily loss limit

Run `python scripts/_deploy_readiness.py` to verify all safety checks pass.

---

## Error Format

```json
{
  "detail": "Error message"
}
```

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad Request |
| 404 | Not Found |
| 422 | Validation Error |
| 500 | Internal Server Error |

---

*Start the server (`make serve`) and visit [http://localhost:8000/docs](http://localhost:8000/docs) for the full interactive API explorer.*
