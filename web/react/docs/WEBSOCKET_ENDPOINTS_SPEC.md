# WebSocket Endpoints Specification

## Overview
This document specifies the WebSocket endpoints required for Tier 1 real-time updates in the MERID-Kalshi integration.

## Required Endpoints

### 1. Order Fills WebSocket
**Endpoint:** `/ws/fills`

**Purpose:** Real-time streaming of order fill updates

**Client Implementation:**
```typescript
// hooks/useOrderFillsWebSocket.ts
import { useEffect, useState } from 'react';
import { io, Socket } from 'socket.io-client';

interface OrderFill {
  fill_id: string;
  order_id: string;
  ticker: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  timestamp: string;
  venue: string;
}

export function useOrderFillsWebSocket() {
  const [fills, setFills] = useState<OrderFill[]>([]);
  const [connected, setConnected] = useState(false);
  const [socket, setSocket] = useState<Socket | null>(null);

  useEffect(() => {
    const ws = io(WS_URLS.KALSHI_FILLS);
    
    ws.on('connect', () => setConnected(true));
    ws.on('disconnect', () => setConnected(false));
    ws.on('fill', (fill: OrderFill) => {
      setFills(prev => [fill, ...prev].slice(0, 100)); // Keep last 100
    });

    setSocket(ws);
    return () => ws.disconnect();
  }, []);

  return { fills, connected };
}
```

**Backend Implementation Required:**
- Create WebSocket handler at `/ws/fills`
- Emit `fill` event on each order fill
- Handle connection/disconnection
- Implement reconnection logic with exponential backoff

**Message Format (Server → Client):**
```json
{
  "event": "fill",
  "data": {
    "fill_id": "fill_123",
    "order_id": "order_456",
    "ticker": "BTC-15m",
    "side": "buy",
    "quantity": 10,
    "price": 0.52,
    "timestamp": "2026-05-11T20:00:00Z",
    "venue": "kalshi"
  }
}
```

---

### 2. Agent Status WebSocket
**Endpoint:** `/ws/agents`

**Purpose:** Real-time streaming of agent status updates

**Client Implementation:**
```typescript
// hooks/useAgentStatusWebSocket.ts
import { useEffect, useState } from 'react';
import { io, Socket } from 'socket.io-client';

interface AgentStatus {
  agent_id: string;
  asset: string;
  timeframe: string;
  status: 'running' | 'paused' | 'stopped' | 'error';
  last_signal: string | null;
  cycle_count: number;
  error_count: number;
  timestamp: string;
}

export function useAgentStatusWebSocket() {
  const [agents, setAgents] = useState<Record<string, AgentStatus>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = io(WS_URLS.KALSHI_AGENTS);
    
    ws.on('connect', () => setConnected(true));
    ws.on('disconnect', () => setConnected(false));
    ws.on('agent_status', (status: AgentStatus) => {
      setAgents(prev => ({ ...prev, [status.agent_id]: status }));
    });

    return () => ws.disconnect();
  }, []);

  return { agents, connected };
}
```

**Backend Implementation Required:**
- Create WebSocket handler at `/ws/agents`
- Emit `agent_status` event on agent state changes
- Handle connection/disconnection
- Implement reconnection logic with exponential backoff

**Message Format (Server → Client):**
```json
{
  "event": "agent_status",
  "data": {
    "agent_id": "btc_15m_lane_1",
    "asset": "BTC",
    "timeframe": "15m",
    "status": "running",
    "last_signal": "2026-05-11T20:00:00Z",
    "cycle_count": 150,
    "error_count": 0,
    "timestamp": "2026-05-11T20:00:00Z"
  }
}
```

---

### 3. Risk State WebSocket
**Endpoint:** `/ws/risk`

**Purpose:** Real-time streaming of risk state updates

**Client Implementation:**
```typescript
// hooks/useRiskStateWebSocket.ts
import { useEffect, useState } from 'react';
import { io, Socket } from 'socket.io-client';

interface RiskState {
  risk_level: 'normal' | 'warning' | 'critical' | 'halt';
  drawdown_pct: number;
  daily_pnl: number;
  position_notional: number;
  kill_switch_active: boolean;
  execution_enabled: boolean;
  timestamp: string;
}

export function useRiskStateWebSocket() {
  const [riskState, setRiskState] = useState<RiskState | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = io(WS_URLS.KALSHI_RISK);
    
    ws.on('connect', () => setConnected(true));
    ws.on('disconnect', () => setConnected(false));
    ws.on('risk_state', (state: RiskState) => {
      setRiskState(state);
    });

    return () => ws.disconnect();
  }, []);

  return { riskState, connected };
}
```

**Backend Implementation Required:**
- Create WebSocket handler at `/ws/risk`
- Emit `risk_state` event on risk state changes
- Handle connection/disconnection
- Implement reconnection logic with exponential backoff

**Message Format (Server → Client):**
```json
{
  "event": "risk_state",
  "data": {
    "risk_level": "warning",
    "drawdown_pct": -2.5,
    "daily_pnl": -1250.00,
    "position_notional": 50000.00,
    "kill_switch_active": false,
    "execution_enabled": true,
    "timestamp": "2026-05-11T20:00:00Z"
  }
}
```

---

### 4. Kalshi Market Data WebSocket
**Endpoint:** `/ws/kalshi/markets`

**Purpose:** Real-time streaming of Kalshi market data updates

**Client Implementation:**
```typescript
// hooks/useKalshiMarketDataWebSocket.ts
import { useEffect, useState } from 'react';
import { io, Socket } from 'socket.io-client';

interface MarketData {
  ticker: string;
  title: string;
  yes_price: number;
  no_price: number;
  volume: number;
  last_trade_time: string;
  timestamp: string;
}

export function useKalshiMarketDataWebSocket(tickers: string[]) {
  const [marketData, setMarketData] = useState<Record<string, MarketData>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = io(WS_URLS.KALSHI_MARKETS);
    
    ws.on('connect', () => {
      setConnected(true);
      ws.emit('subscribe', { tickers });
    });
    
    ws.on('disconnect', () => setConnected(false));
    ws.on('market_update', (data: MarketData) => {
      setMarketData(prev => ({ ...prev, [data.ticker]: data }));
    });

    return () => ws.disconnect();
  }, [tickers]);

  return { marketData, connected };
}
```

**Backend Implementation Required:**
- Create WebSocket handler at `/ws/kalshi/markets`
- Handle `subscribe` event from client
- Emit `market_update` event on market data changes
- Handle connection/disconnection
- Implement reconnection logic with exponential backoff

**Message Format (Client → Server - Subscribe):**
```json
{
  "event": "subscribe",
  "data": {
    "tickers": ["BTC-15m", "ETH-15m", "SOL-15m"]
  }
}
```

**Message Format (Server → Client - Market Update):**
```json
{
  "event": "market_update",
  "data": {
    "ticker": "BTC-15m",
    "title": "Bitcoin > $65,000 at 3pm ET",
    "yes_price": 0.52,
    "no_price": 0.48,
    "volume": 150000,
    "last_trade_time": "2026-05-11T20:00:00Z",
    "timestamp": "2026-05-11T20:00:00Z"
  }
}
```

---

## Constants to Add

Add to `src/config/constants.ts`:

```typescript
export const WS_URLS = {
  KALSHI_FILLS: `${WS_BASE_URL}/ws/fills`,
  KALSHI_AGENTS: `${WS_BASE_URL}/ws/agents`,
  KALSHI_RISK: `${WS_BASE_URL}/ws/risk`,
  KALSHI_MARKETS: `${WS_BASE_URL}/ws/kalshi/markets`,
} as const;
```

## Backend Implementation Checklist

For each WebSocket endpoint:

- [ ] Create WebSocket route handler
- [ ] Implement connection management
- [ ] Implement event emission logic
- [ ] Add reconnection logic with exponential backoff
- [ ] Add authentication/authorization if needed
- [ ] Add rate limiting
- [ ] Add error handling
- [ ] Add logging
- [ ] Write unit tests
- [ ] Write integration tests

## Testing

Once backend endpoints are implemented:

1. Test connection establishment
2. Test message reception
3. Test reconnection after disconnect
4. Test subscription/unsubscription (for market data)
5. Test error handling
6. Test with multiple concurrent clients
7. Load test with high message volume

## Priority

1. **High Priority:** `/ws/fills` - Critical for trading operations
2. **High Priority:** `/ws/risk` - Critical for risk management
3. **Medium Priority:** `/ws/agents` - Important for monitoring
4. **Medium Priority:** `/ws/kalshi/markets` - Important for market data
