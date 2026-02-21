# MERID API Endpoints Specification

Complete API endpoints for wiring into the MERID trading dashboard charts and real-time data updates.

## **Portfolio & P&L Endpoints**

### **GET /api/v1/portfolio/summary**
Returns current portfolio summary with key metrics.

**Response:**
```json
{
  "equity": 562847.32,
  "dailyPnl": 12847.32,
  "dailyPnlPct": 2.34,
  "availableMargin": 124523.18,
  "marginUsed": 438324.14,
  "marginUsedPct": 77.9,
  "activeBots": 12,
  "pausedBots": 3,
  "timestamp": "2026-01-30T13:30:00.000Z"
}
```

### **GET /api/v1/portfolio/history?window=1M&granularity=1D**
Returns historical portfolio data for charts.

**Parameters:**
- `window`: Time window (1D, 1W, 1M, 3M, 1Y)
- `granularity`: Data granularity (1m, 5m, 15m, 1h, 1D)

**Response:**
```json
{
  "data": [
    { "timestamp": "2026-01-24T00:00:00Z", "equity": 545000, "pnl": 0 },
    { "timestamp": "2026-01-25T00:00:00Z", "equity": 548000, "pnl": 3000 },
    { "timestamp": "2026-01-26T00:00:00Z", "equity": 542000, "pnl": -3000 }
  ]
}
```

## **Positions & Orders Endpoints**

### **GET /api/v1/positions**
Returns all open positions across all venues.

**Response:**
```json
{
  "positions": [
    {
      "id": "pos_001",
      "symbol": "BTC/USD",
      "side": "LONG",
      "size": 0.25,
      "entryPrice": 42150.00,
      "currentPrice": 43256.78,
      "unrealizedPnl": 276.50,
      "unrealizedPnlPct": 0.66,
      "venue": "Coinbase",
      "marginUsed": 10628.95,
      "timestamp": "2026-01-30T13:30:00Z"
    }
  ]
}
```

### **GET /api/v1/orders/open**
Returns all open orders.

**Response:**
```json
{
  "orders": [
    {
      "id": "order_001",
      "symbol": "BTC/USD",
      "side": "BUY",
      "type": "LIMIT",
      "size": 0.15,
      "price": 42800.00,
      "status": "PENDING",
      "venue": "Coinbase",
      "createTime": "2026-01-30T13:25:00Z",
      "timeInForce": "GTC"
    }
  ]
}
```

### **GET /api/v1/orders/recent?limit=10**
Returns recent filled orders.

**Parameters:**
- `limit`: Number of recent orders to return (default: 10)

**Response:**
```json
{
  "orders": [
    {
      "id": "order_002",
      "symbol": "BTC/USD",
      "side": "BUY",
      "type": "MARKET",
      "size": 0.1,
      "fillPrice": 43256.78,
      "status": "FILLED",
      "venue": "Coinbase",
      "fillTime": "2026-01-30T13:28:00Z",
      "commission": 4.33
    }
  ]
}
```

## **Price Feed Endpoints**

### **GET /api/v1/prices/live?symbols=BTC-USD,ETH-USD,SOL-USD**
Returns real-time price data for specified symbols.

**Parameters:**
- `symbols`: Comma-separated list of symbols

**Response:**
```json
{
  "prices": {
    "BTC/USD": {
      "symbol": "BTC/USD",
      "price": 43256.78,
      "change24h": 2.34,
      "change24hPct": 0.0234,
      "volume24h": 1200000000,
      "high24h": 43800.00,
      "low24h": 42000.00,
      "venue": "Coinbase",
      "timestamp": "2026-01-30T13:30:00Z"
    },
    "ETH/USD": {
      "symbol": "ETH/USD",
      "price": 2245.12,
      "change24h": -1.23,
      "change24hPct": -0.0123,
      "volume24h": 890000000,
      "high24h": 2280.00,
      "low24h": 2200.00,
      "venue": "Kraken",
      "timestamp": "2026-01-30T13:30:00Z"
    }
  }
}
```

### **GET /api/v1/prices/history?symbol=BTC-USD&window=1D&granularity=1m**
Returns historical price data for charts.

**Parameters:**
- `symbol`: Trading symbol
- `window`: Time window (1h, 4h, 1D, 1W)
- `granularity`: Data granularity (1m, 5m, 15m, 1h)

**Response:**
```json
{
  "data": [
    { "timestamp": "2026-01-30T12:00:00Z", "open": 43000, "high": 43200, "low": 42800, "close": 43150, "volume": 1500000 },
    { "timestamp": "2026-01-30T12:01:00Z", "open": 43150, "high": 43300, "low": 43050, "close": 43200, "volume": 1200000 }
  ]
}
```

## **Agents Endpoints**

### **GET /api/v1/agents**
Returns status and performance of all trading agents.

**Response:**
```json
{
  "agents": [
    {
      "id": "trend-analyst-01",
      "name": "Trend Agent",
      "role": "trend",
      "status": "RUNNING",
      "confidence": 87,
      "lastDecision": "2026-01-30T13:28:00Z",
      "dailyPnl": 2340.50,
      "totalPnl": 15420.75,
      "winRate": 72.4,
      "tradesToday": 8,
      "currentThesis": "BTC showing strong upward momentum with increasing volume"
    },
    {
      "id": "arb-analyst-01",
      "name": "Arbitrage Agent",
      "role": "arbitrage",
      "status": "RUNNING",
      "confidence": 92,
      "lastDecision": "2026-01-30T13:27:00Z",
      "dailyPnl": 5670.25,
      "totalPnl": 45230.80,
      "winRate": 84.1,
      "tradesToday": 12,
      "currentThesis": "BTC/USD arbitrage opportunity on Binance vs Coinbase"
    }
  ]
}
```

### **GET /api/v1/agents/{agentId}/details**
Returns detailed information for a specific agent.

**Response:**
```json
{
  "id": "trend-analyst-01",
  "name": "Trend Agent",
  "status": "RUNNING",
  "confidence": 87,
  "currentThesis": "BTC showing strong upward momentum with increasing volume and RSI indicating bullish continuation",
  "recentTrades": [
    {
      "symbol": "BTC/USD",
      "side": "BUY",
      "size": 0.15,
      "price": 42800.00,
      "pnl": 340.50,
      "timestamp": "2026-01-30T13:25:00Z"
    }
  ],
  "confidenceHistory": [
    { "timestamp": "2026-01-30T12:00:00Z", "confidence": 75 },
    { "timestamp": "2026-01-30T13:00:00Z", "confidence": 82 },
    { "timestamp": "2026-01-30T13:30:00Z", "confidence": 87 }
  ],
  "performanceMetrics": {
    "winRate": 72.4,
    "avgTradeDuration": "2h 15m",
    "riskAdjustedReturn": 1.84
  }
}
```

## **Prediction Markets Endpoints**

### **GET /api/v1/prediction/markets**
Returns all prediction markets from Polymarket and Kalshi.

**Parameters:**
- `platform`: Filter by platform (polymarket, kalshi)
- `category`: Filter by category (crypto, politics, economics, sports)

**Response:**
```json
{
  "markets": [
    {
      "id": "btc-45k-dec31",
      "title": "Bitcoin will exceed $45,000 by December 31",
      "platform": "Polymarket",
      "category": "crypto",
      "yesPrice": 0.65,
      "noPrice": 0.35,
      "yesProbability": 65,
      "noProbability": 35,
      "volume": 2100000,
      "liquidity": 125000,
      "resolvesAt": "2024-12-31T23:59:59Z",
      "yourPosition": {
        "side": "YES",
        "size": 500,
        "avgPrice": 0.62,
        "pnl": 120.50
      }
    },
    {
      "id": "fed-rate-cut-march",
      "title": "Federal Reserve will cut rates in March 2024",
      "platform": "Kalshi",
      "category": "economics",
      "yesPrice": 0.72,
      "noPrice": 0.28,
      "yesProbability": 72,
      "noProbability": 28,
      "volume": 890000,
      "liquidity": 45000,
      "resolvesAt": "2024-03-31T23:59:59Z",
      "yourPosition": {
        "side": "YES",
        "size": 1000,
        "avgPrice": 0.70,
        "pnl": 340.00
      }
    }
  ]
}
```

### **GET /api/v1/prediction/markets/pinned**
Returns pinned prediction markets for dashboard display.

**Response:**
```json
{
  "pinnedMarkets": [
    {
      "id": "btc-45k-dec31",
      "title": "BTC > $45k by Dec 31",
      "platform": "Polymarket",
      "yesProbability": 65,
      "noProbability": 35,
      "volume": "$2.1M",
      "resolvesIn": "5 days"
    }
  ]
}
```

## **Risk & Health Endpoints**

### **GET /api/v1/health**
Returns overall system health status.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-01-30T13:30:00Z",
  "uptime": 86400,
  "version": "1.0.0",
  "environment": "production"
}
```

### **GET /api/v1/api-status**
Returns detailed status of all API integrations.

**Response:**
```json
{
  "summary": {
    "totalApis": 18,
    "onlineApis": 17,
    "offlineApis": 1,
    "degradedApis": 0,
    "overallHealth": 94.4
  },
  "categories": {
    "marketData": {
      "services": [
        {
          "name": "CoinGecko",
          "status": "online",
          "responseTime": 67,
          "lastSuccess": "2026-01-30T13:29:55Z",
          "errorRate": 0.1
        }
      ]
    },
    "trading": {
      "services": [
        {
          "name": "Alpaca",
          "status": "online",
          "responseTime": 45,
          "lastSuccess": "2026-01-30T13:29:58Z",
          "errorRate": 0.1
        }
      ]
    }
  }
}
```

### **GET /api/v1/risk/alerts**
Returns current risk alerts and warnings.

**Parameters:**
- `severity`: Filter by severity (low, medium, high, critical)
- `status`: Filter by status (active, acknowledged, resolved)

**Response:**
```json
{
  "alerts": [
    {
      "id": "alert_001",
      "timestamp": "2026-01-30T13:28:00Z",
      "severity": "medium",
      "type": "MARGIN_WARNING",
      "title": "Margin usage approaching 80%",
      "description": "Current margin usage is 78%, approaching the 80% warning threshold",
      "source": "Risk Monitor",
      "status": "active",
      "actions": ["reduce_positions", "add_margin"]
    },
    {
      "id": "alert_002",
      "timestamp": "2026-01-30T13:15:00Z",
      "severity": "low",
      "type": "LATENCY_SPIKE",
      "title": "API latency increased",
      "description": "TD Ameritrade API latency increased to 234ms",
      "source": "Connectivity Monitor",
      "status": "acknowledged",
      "actions": ["check_network", "contact_support"]
    }
  ]
}
```

## **WebSocket Endpoints**

### **WS /ws/live-prices**
Real-time price updates via WebSocket.

**Message Format:**
```json
{
  "type": "price_update",
  "data": {
    "symbol": "BTC/USD",
    "price": 43256.78,
    "change24h": 2.34,
    "volume24h": 1200000000,
    "timestamp": "2026-01-30T13:30:00Z"
  }
}
```

### **WS /ws/portfolio-updates**
Real-time portfolio updates via WebSocket.

**Message Format:**
```json
{
  "type": "portfolio_update",
  "data": {
    "equity": 562847.32,
    "dailyPnl": 12847.32,
    "dailyPnlPct": 2.34,
    "timestamp": "2026-01-30T13:30:00Z"
  }
}
```

### **WS /ws/agent-updates**
Real-time agent status updates via WebSocket.

**Message Format:**
```json
{
  "type": "agent_update",
  "data": {
    "agentId": "trend-analyst-01",
    "status": "RUNNING",
    "confidence": 87,
    "lastDecision": "2026-01-30T13:28:00Z",
    "timestamp": "2026-01-30T13:30:00Z"
  }
}
```

## **Polling Recommendations**

### **High-Frequency Data (1-5 seconds)**
- `/api/v1/prices/live` - Price updates
- `/api/v1/portfolio/summary` - Portfolio metrics
- WebSocket connections for real-time updates

### **Medium-Frequency Data (15-30 seconds)**
- `/api/v1/positions` - Position updates
- `/api/v1/orders/open` - Order status
- `/api/v1/agents` - Agent status

### **Low-Frequency Data (1-5 minutes)**
- `/api/v1/api-status` - API health
- `/api/v1/risk/alerts` - Risk alerts
- `/api/v1/prediction/markets` - Prediction markets

## **Error Handling**

All endpoints return appropriate HTTP status codes:

- `200 OK` - Successful request
- `400 Bad Request` - Invalid parameters
- `401 Unauthorized` - Authentication required
- `404 Not Found` - Resource not found
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error

**Error Response Format:**
```json
{
  "error": {
    "code": "INVALID_SYMBOL",
    "message": "Symbol 'INVALID' is not supported",
    "timestamp": "2026-01-30T13:30:00Z"
  }
}
```

## **Authentication**

All endpoints require authentication via API key in headers:

```
Authorization: Bearer <api_key>
X-API-Key: <api_key>
```

## **Rate Limits**

- **Price endpoints**: 100 requests/minute
- **Portfolio endpoints**: 60 requests/minute
- **Trading endpoints**: 30 requests/minute
- **Agent endpoints**: 20 requests/minute
- **Risk endpoints**: 10 requests/minute

---

## **Implementation Notes**

### **Chart Data Formatting**
- Use `timestamp` fields for x-axis
- Convert all monetary values to numbers (not strings)
- Handle null/undefined values gracefully
- Implement proper error boundaries in React components

### **Real-time Updates**
- Implement WebSocket connections for live data
- Fall back to polling if WebSocket fails
- Use React Query or SWR for caching and deduplication
- Implement proper cleanup on component unmount

### **Performance Optimization**
- Implement pagination for large datasets
- Use memoization for expensive calculations
- Debounce rapid API calls
- Cache frequently accessed data

This specification provides all the endpoints needed to power the MERID trading dashboard with real-time data, charts, and comprehensive monitoring capabilities.
