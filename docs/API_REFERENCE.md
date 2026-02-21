# MERID API Reference

**Version:** 3.0.0
**Base URL:** `http://localhost:8000`
**Interactive docs:** `/docs` (Swagger UI), `/redoc` (ReDoc)

---

## Kalshi Trading

#### GET `/api/v1/kalshi/markets`

Browse available Kalshi markets with category/status filters.

#### GET `/api/v1/kalshi/market/{ticker}`

Single market detail: orderbook, last price, volume, open interest.

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

## Health & System

#### GET `/healthz`

Health check.

#### GET `/risk/status`

Circuit breaker + kill switch status.

#### POST `/risk/kill-switch/enable`

Emergency stop — halt all trading immediately.

#### GET `/api/v1/system/fresh-start`

Fresh start status (paper mode reset state).

---

## WebSocket

#### WS `/ws/market/{symbol}`

Real-time market data stream for a symbol.

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
