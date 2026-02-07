# MERID API Reference

**Version:** 1.0.0  
**Base URL:** `http://localhost:8001/api/v1`  
**Documentation:** `/docs` (Swagger UI), `/redoc` (ReDoc)

---

## Authentication

Currently, the API does not require authentication for local development. Production deployments should implement API key authentication.

---

## Endpoints

### Market Data

#### GET `/institutional/prices`
Get current cryptocurrency prices.

**Response:**
```json
{
  "prices": {
    "BTC/USDT": {"price": 94250.50, "change_24h": 2.5},
    "ETH/USDT": {"price": 3420.25, "change_24h": 1.8}
  }
}
```

#### GET `/institutional/predictions/markets`
Get prediction market data from Polymarket.

**Response:**
```json
{
  "markets": [...],
  "count": 49,
  "status": {
    "running": true,
    "total_markets": 49,
    "platforms": ["polymarket", "kalshi", "augur"]
  }
}
```

---

### Agent Mesh

#### GET `/institutional/mesh/status`
Get streaming agent mesh status.

**Response:**
```json
{
  "running": true,
  "total_agents": 8,
  "agents": [
    {"id": "market-analyst-01", "status": "running", "model": "merid-strategist:latest"},
    ...
  ]
}
```

#### POST `/institutional/mesh/agent/{agent_id}/start`
Start a specific agent.

#### POST `/institutional/mesh/agent/{agent_id}/stop`
Stop a specific agent.

---

### Consensus Engine

#### GET `/institutional/consensus/status`
Get consensus engine status.

**Response:**
```json
{
  "running": true,
  "pending_votes": 3,
  "total_processed": 150,
  "consensus_threshold": 0.65
}
```

#### GET `/institutional/consensus/votes`
Get recent votes from agents.

---

### Execution Engine

#### GET `/institutional/execution/status`
Get execution engine status.

**Response:**
```json
{
  "running": true,
  "mode": "paper",
  "balance": 100000.0,
  "equity": 100000.0,
  "positions": 0
}
```

#### GET `/institutional/execution/positions`
Get current positions.

#### POST `/institutional/execution/order`
Submit a new order.

**Parameters:**
- `symbol` (string): Trading pair (e.g., "BTC/USDT")
- `side` (string): "buy" or "sell"
- `quantity` (float): Order quantity
- `order_type` (string): "market" or "limit"
- `price` (float, optional): Limit price

---

### Performance Analytics

#### GET `/institutional/analytics/summary`
Get performance analytics summary.

**Response:**
```json
{
  "total_trades": 25,
  "winning_trades": 15,
  "losing_trades": 10,
  "win_rate": 60.0,
  "total_pnl": 5250.50,
  "sharpe_ratio": 1.85,
  "max_drawdown": 8.5
}
```

#### GET `/institutional/analytics/trades`
Get trade history.

---

### Backtesting

#### GET `/institutional/backtest/strategies`
Get available backtesting strategies.

**Response:**
```json
{
  "strategies": ["momentum", "mean_reversion", "breakout", "ma_crossover"],
  "summary": {
    "total_backtests": 5,
    "completed": 5,
    "failed": 0
  }
}
```

#### POST `/institutional/backtest/run`
Run a backtest.

**Parameters:**
- `strategy` (string): Strategy name
- `symbol` (string): Trading pair
- `days` (int): Number of days to backtest
- `initial_capital` (float): Starting capital

**Response:**
```json
{
  "status": "completed",
  "result": {
    "backtest_id": "bt_abc123",
    "strategy_name": "momentum",
    "total_return_pct": 15.5,
    "sharpe_ratio": 1.25,
    "max_drawdown_pct": 12.3,
    "win_rate": 58.0,
    "total_trades": 42,
    "profit_factor": 1.8
  }
}
```

#### GET `/institutional/backtest/results`
Get all backtest results.

---

### Portfolio Management

#### GET `/institutional/portfolio/summary`
Get portfolio summary.

**Response:**
```json
{
  "total_value": 100000.0,
  "cash": 85000.0,
  "invested": 15000.0,
  "pnl": 500.0,
  "pnl_pct": 0.5,
  "num_positions": 3,
  "allocation_strategy": "equal_weight"
}
```

#### GET `/institutional/portfolio/holdings`
Get current holdings.

#### GET `/institutional/portfolio/allocation`
Get current vs target allocation.

#### POST `/institutional/portfolio/target-weights`
Set target portfolio weights.

**Body:**
```json
{
  "BTC/USDT": 0.4,
  "ETH/USDT": 0.3,
  "SOL/USDT": 0.3
}
```

#### GET `/institutional/portfolio/rebalance`
Get rebalance orders needed.

#### POST `/institutional/portfolio/position-size`
Calculate position size.

**Parameters:**
- `symbol` (string): Trading pair
- `entry_price` (float): Entry price
- `stop_loss` (float): Stop loss price
- `risk_per_trade` (float): Risk as fraction (default: 0.02)

---

### Alerts & Notifications

#### GET `/institutional/alerts/summary`
Get alerts summary.

**Response:**
```json
{
  "running": true,
  "total_alerts": 5,
  "active_alerts": 3,
  "triggered_alerts": 2,
  "unread_notifications": 4
}
```

#### GET `/institutional/alerts`
Get all alerts.

**Parameters:**
- `status` (string, optional): Filter by status ("active", "triggered", "cancelled")

#### POST `/institutional/alerts/price`
Create a price alert.

**Parameters:**
- `symbol` (string): Trading pair
- `target_price` (float): Target price
- `direction` (string): "above" or "below"

#### DELETE `/institutional/alerts/{alert_id}`
Delete an alert.

#### GET `/institutional/notifications`
Get notifications.

#### POST `/institutional/notifications/read-all`
Mark all notifications as read.

---

### Health Monitoring

#### GET `/institutional/health`
Get system health status.

**Response:**
```json
{
  "status": "healthy",
  "uptime_seconds": 3600,
  "components": {
    "event_bus": {"status": "healthy", "message": "Processing events"},
    "consensus": {"status": "healthy", "message": "Running"},
    "execution": {"status": "healthy", "message": "Mode: paper"},
    "agent_mesh": {"status": "healthy", "message": "All 8 agents running"},
    "simulation": {"status": "healthy", "message": "Block 150"},
    "audit": {"status": "healthy", "message": "500 entries"},
    "system": {"status": "healthy", "message": "Normal resource usage"}
  },
  "healthy_count": 7,
  "total_components": 7
}
```

#### GET `/institutional/health/ping`
Simple health ping.

**Response:**
```json
{
  "status": "ok",
  "timestamp": 1704931200.0
}
```

#### GET `/institutional/health/component/{name}`
Get specific component health.

---

### Simulation

#### GET `/institutional/simulation/status`
Get simulation miner status.

#### GET `/institutional/simulation/blocks`
Get recent simulation blocks.

---

### Audit Trail

#### GET `/institutional/audit/entries`
Get audit trail entries.

**Parameters:**
- `limit` (int): Number of entries (default: 100)

---

### WebSocket Endpoints

#### WS `/api/v1/institutional/realtime/stream`
Real-time event stream.

**Events:**
- `price_update` - Price changes
- `agent_vote` - Agent voting events
- `consensus_result` - Consensus decisions
- `trade_executed` - Trade executions
- `alert_triggered` - Alert notifications

---

## Error Responses

All endpoints return errors in this format:

```json
{
  "error": "Error message",
  "detail": "Additional details"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad Request
- `404` - Not Found
- `500` - Internal Server Error

---

## Rate Limits

No rate limits in development mode. Production deployments should implement appropriate rate limiting.
