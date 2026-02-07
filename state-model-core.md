# MERID State Model – Core (Phase 6)

**Version:** 1.1  
**Date:** January 13, 2026  
**Status:** Constitutional specification — authoritative source for every field the dashboard may hold.

> **Constitutional Rule**  
> No event, reducer, or UI component may invent structure that is not declared here.

---

## Canonical state tree

```ts
type DashboardState = {
  system: SystemState;
  markets: MarketsState;
  agents: AgentsState;
  portfolio: PortfolioState;
  risk: RiskState;
  consensus: ConsensusState;
  alerts: AlertsState;
  events: EventLedgerState;
  ui: UIState;
};
```

Every reducer in `web/static/js/dashboard-v2.js` updates exactly one of the domains above and must preserve the invariants described below.

---

## SystemState

```ts
type HealthStatus = 'unknown' | 'connected' | 'disconnected' | 'ok' | 'warn' | 'error';

type TruthProcessState = {
  status: 'idle' | 'running' | 'success' | 'failure';
  reason: string | null;
  build?: string | null;
  startedAt: number | null;
  durationMs: number | null;
  lastSuccess: number | null;
  lastFailure: number | null;
  errors: string[];
};

type HealthMetaEntry = {
  status: HealthStatus;
  message: string;
  updatedAt: number | null;
};

type SystemState = {
  bootstrapping: boolean;
  lastEvent: number | null;
  health: {
    marketFeeds: HealthStatus;
    agents: HealthStatus;
    consensus: HealthStatus;
    execution: HealthStatus;
    websocket: HealthStatus;
  };
  healthMeta: {
    marketFeeds: HealthMetaEntry;
    agents: HealthMetaEntry;
    consensus: HealthMetaEntry;
    execution: HealthMetaEntry;
    websocket: HealthMetaEntry;
  };
  bootstrapStatus: TruthProcessState;
  refreshStatus: TruthProcessState & { reason: string | null };
};
```

### Markets invariants

- `bootstrapping` can only be `true` while `SYSTEM_BOOTSTRAP_STARTED` is active.  
- `health.*` must be recognized `HealthStatus` literals.  
- `bootstrapStatus.errors` and `refreshStatus.errors` are always arrays (may be empty).  
- `lastEvent` monotonically increases with every reducer execution.

---

## MarketsState

```ts
type MarketsState = {
  snapshotId: string | null;
  lastTickTs: number | null;
  overview: {
    totalMarketCap: number;
    totalVolume24h: number;
    assetsTracked: number;
  } | null;
  prices: Record<string, PriceEntry>;
};

type PriceEntry = {
  symbol: string;
  price: number;
  bid?: number;
  ask?: number;
  volume24h?: number;
  change24h?: number;
  timestamp?: number;
};
```

### Invariants

- `snapshotId` must be non-null before any `PRICE_TICK_RECEIVED`.  
- `prices` is a map keyed by stable `symbol` strings; each value must include numeric `price`.  
- `overview`, if present, contains only numeric aggregates.

---

## AgentsState

```ts
type AgentsState = {
  snapshotId: string | null;
  list: AgentSummary[];
  lastUpdate: number | null;
};
**Purpose:** Trading portfolio state

```javascript
portfolio: {
    positions: Map<symbol: string, Position>,
    orders: Map<orderId: string, Order>,
    balance: BalanceState,
    pnl: PnLState,
    history: HistoricalSnapshot[],
    lastUpdate: number
}
```

### **Position**

```javascript
{
    symbol: string,
    size: number,             // Positive = long, negative = short
    entryPrice: number,
    currentPrice: number,
    unrealizedPnL: number,
    realizedPnL: number,
    timestamp: number
}
```

### **Order**

```javascript
{
    id: string,
    symbol: string,
    side: 'BUY' | 'SELL',
    type: 'MARKET' | 'LIMIT' | 'STOP',
    size: number,
    price: number | null,     // Null for market orders
    status: 'PENDING' | 'OPEN' | 'FILLED' | 'CANCELLED' | 'REJECTED',
    filledSize: number,
    avgFillPrice: number | null,
    timestamp: number
}
```

### **BalanceState**

```javascript
{
    total: number,
    available: number,
    locked: number,
    currency: string
}
```

### **PnLState**

```javascript
{
    realized: number,
    unrealized: number,
    total: number,
    dailyPnL: number,
    weeklyPnL: number,
    monthlyPnL: number
}
```

### **HistoricalSnapshot**

```javascript
{
    timestamp: number,
    totalValue: number,
    positions: Position[],
    pnl: PnLState
}
```

**Invariants:**

- `total` = `available` + `locked`
- `total` = `realized` + `unrealized`
- `size` must be non-zero for positions
- `filledSize` ≤ `size` for orders
- `history` array max length 1000

---

## 5️⃣ RISK STATE

**Purpose:** Risk management state

```javascript
risk: {
    exposure: ExposureMetrics,
    limits: RiskLimits,
    violations: Violation[],
    alerts: Alert[],
    lastUpdate: number
}
```

### **ExposureMetrics**

```javascript
{
    totalExposure: number,
    netExposure: number,
    grossExposure: number,
    leverage: number,
    concentration: Map<symbol: string, number>  // % of portfolio
}
```

### **RiskLimits**

```javascript
{
    maxPositionSize: number,
    maxLeverage: number,
    maxDrawdown: number,      // %
    maxDailyLoss: number,     // Absolute value
    maxConcentration: number  // % per symbol
}
```

### **Violation**

```javascript
{
    id: string,
    type: string,
    severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL',
    message: string,
    value: number,
    limit: number,
    timestamp: number
}
```

### **Alert**

```javascript
{
    id: string,
    type: string,
    severity: 'INFO' | 'WARNING' | 'ERROR',
    message: string,
    acknowledged: boolean,
    timestamp: number
}
```

**Invariants:**

- `netExposure` ≤ `grossExposure`
- `leverage` ≥ 1.0
- `concentration` values sum to ≤ 100%
- `violations` array max length 100
- `alerts` array max length 50

---

## 6️⃣ EXECUTION STATE

**Purpose:** Order execution state

```javascript
execution: {
    stats: ExecutionStats,
    recentOrders: Order[],
    fills: Fill[],
    rejections: Rejection[],
    latency: LatencyMetrics,
    lastUpdate: number
}
```

### **ExecutionStats**

```javascript
{
    totalOrders: number,
    filledOrders: number,
    cancelledOrders: number,
    rejectedOrders: number,
    avgFillTime: number,      // Milliseconds
    fillRate: number          // 0.0 - 1.0
}
```

### **Fill**

```javascript
{
    orderId: string,
    symbol: string,
    price: number,
    size: number,
    fee: number,
    timestamp: number
}
```

### **Rejection**

```javascript
{
    orderId: string,
    reason: string,
    timestamp: number
}
```

### **LatencyMetrics**

```javascript
{
    orderToAck: number,       // Milliseconds
    orderToFill: number,      // Milliseconds
    p50: number,
    p95: number,
    p99: number
}
```

**Invariants:**

- `fillRate` ∈ [0.0, 1.0]
- `totalOrders` = `filledOrders` + `cancelledOrders` + `rejectedOrders`
- `recentOrders` array max length 100
- `fills` array max length 500
- `rejections` array max length 100

---

## 7️⃣ PREDICTIONS STATE

**Purpose:** Prediction markets state

```javascript
predictions: {
    markets: Map<marketId: string, PredictionMarket>,
    positions: Map<marketId: string, PredictionPosition>,
    signals: Signal[],
    arbitrage: ArbitrageOpportunity[],
    lastUpdate: number
}
```

### **PredictionMarket**

```javascript
{
    id: string,
    question: string,
    category: string,
    outcomes: Outcome[],
    volume: number,
    liquidity: number,
    closeTime: number,        // Unix timestamp (ms)
    status: 'OPEN' | 'CLOSED' | 'RESOLVED'
}
```

### **Outcome**

```javascript
{
    id: string,
    name: string,
    probability: number,      // 0.0 - 1.0
    price: number,
    volume: number
}
```

### **PredictionPosition**

```javascript
{
    marketId: string,
    outcomeId: string,
    shares: number,
    avgPrice: number,
    currentPrice: number,
    unrealizedPnL: number
}
```

### **Signal**

```javascript
{
    id: string,
    type: 'DRIFT' | 'ARBITRAGE' | 'VOLUME' | 'SENTIMENT',
    marketId: string,
    strength: number,         // 0.0 - 1.0
    message: string,
    timestamp: number
}
```

### **ArbitrageOpportunity**

```javascript
{
    id: string,
    marketIds: string[],
    expectedReturn: number,   // %
    risk: number,             // 0.0 - 1.0
    expiresAt: number,        // Unix timestamp (ms)
    timestamp: number
}
```

**Invariants:**

- `probability` ∈ [0.0, 1.0]
- Sum of outcome probabilities ≈ 1.0
- `strength` ∈ [0.0, 1.0]
- `risk` ∈ [0.0, 1.0]
- `signals` array max length 100
- `arbitrage` array max length 50

---

## 8️⃣ UI STATE (Ephemeral)

**Purpose:** Client-side UI state (not persisted)

```javascript
ui: {
    activeSection: string,
    selectedSymbol: string,
    filters: FilterState,
    modals: ModalState,
    notifications: Notification[]
}
```

### **FilterState**

```javascript
{
    global: {
        timeRange: '1h' | '4h' | '1d' | '1w' | '1m',
        symbols: string[]     // Empty = all
    },
    predictions: {
        category: string | null,
        status: 'OPEN' | 'CLOSED' | 'ALL'
    },
    execution: {
        orderType: 'MARKET' | 'LIMIT' | 'STOP' | 'ALL',
        status: 'PENDING' | 'OPEN' | 'FILLED' | 'ALL'
    },
    agents: {
        role: string | null,
        status: 'ACTIVE' | 'IDLE' | 'ERROR' | 'ALL'
    }
}
```

### **ModalState**

```javascript
{
    active: string | null,    // Modal ID or null
    data: object | null       // Modal-specific data
}
```

### **Notification**

```javascript
{
    id: string,
    type: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR',
    message: string,
    duration: number | null,  // Milliseconds, null = persistent
    timestamp: number
}
```

**Invariants:**

- `activeSection` must be valid section name
- `selectedSymbol` must exist in `markets.prices`
- `notifications` array max length 10
- Filters only reference existing state

---

## 🔐 STATE INVARIANTS (Global)

### **Temporal Consistency**

- All `timestamp` fields must be ≤ `system.timestamp`
- `lastUpdate` fields must be ≤ `system.timestamp`
- Timestamps must be monotonically increasing within same entity

### **Referential Integrity**

- `ui.selectedSymbol` must exist in `markets.prices`
- `portfolio.orders[].symbol` must exist in `markets.prices`
- `agents.consensus.participants` must be subset of `agents.active`
- `execution.fills[].orderId` must exist in `portfolio.orders`

### **Numeric Constraints**

- All percentages ∈ [0.0, 100.0]
- All probabilities ∈ [0.0, 1.0]
- All prices must be positive
- All sizes must be non-zero

### **Collection Limits**

- Arrays have max lengths to prevent memory issues
- Maps use string keys only
- No nested collections deeper than 3 levels

---

## 📝 USAGE RULES

### **For Events (state-model-events.md)**

- Events may only modify state defined here
- Events must preserve all invariants
- Events must provide complete payload (no partial updates)

### **For Flow (state-model-flow.md)**

- UI may only read from state tree
- UI may only write to `ui` domain
- Filters operate on existing state, never trigger fetches
- WebSocket updates flow through events, not direct state mutation

### **For Implementation**

- State tree is immutable - create new objects on update
- Use structural sharing for performance
- Validate invariants on every state transition
- Log invariant violations but don't crash

---

**This document is the constitutional foundation. All other documents must reference this as the single source of truth.**
