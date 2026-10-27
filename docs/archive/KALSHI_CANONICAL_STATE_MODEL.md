# Kalshi Canonical State Model

**Date:** 2026-05-12  
**Purpose:** Phase 1 - Define canonical backend state model for UI (single source of truth)

---

## Design Principles

1. **Backend is source of truth** - All UI state comes from backend, no client-side derivation
2. **Single aggregation endpoint** - `/api/v1/kalshi/ui-state` returns all essential state
3. **Progressive disclosure** - Detail data loaded on-demand via separate endpoints
4. **WebSocket push** - Real-time updates for fills, orders, risk events
5. **Cache-friendly** - State includes timestamp for cache invalidation

---

## Canonical State Structure

### Core State (Always Present)

```typescript
interface KalshiUIState {
  // Metadata
  version: string;
  timestamp: string; // ISO 8601 UTC
  cache_ttl_seconds: number; // Recommended cache duration

  // System Status
  system: SystemStatus;

  // Capital State
  capital: CapitalState;

  // Market State
  markets: MarketState;

  // Risk State
  risk: RiskState;

  // Agent Grid State
  grid: GridState;
}
```

### System Status

```typescript
interface SystemStatus {
  // Trading mode
  mode: 'paper' | 'shadow' | 'live';
  is_live_enabled: boolean;

  // Execution gate
  execution_gate: 'clear' | 'limited' | 'blocked';
  execution_gate_reasons: string[];
  execution_gate_near_limit?: {
    exposure_pct: number;
    daily_loss_pct: number;
  };

  // Kill switch
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  kill_switch_triggered_at: string | null;

  // Venue health
  venue_healthy: boolean;
  venue_latency_ms: number;
  venue_last_error: string | null;

  // Reconciliation
  reconciliation_status: 'ok' | 'discrepancy' | 'error';
  reconciliation_last_check: string | null;
  reconciliation_discrepancy_count: number;
}
```

### Capital State

```typescript
interface CapitalState {
  // Balance
  balance_usd: number;
  portfolio_usd: number;
  total_value_usd: number;
  locked_usd: number; // Pending orders, etc.

  // PnL
  daily_pnl_usd: number;
  total_pnl_usd: number;
  daily_pnl_pct: number;

  // Drawdown
  drawdown_pct: number;
  drawdown_tier: 'normal' | 'warning' | 'downsize' | 'halt';
  drawdown_from_peak_usd: number;
  peak_equity_usd: number;

  // Limits
  daily_loss_limit_usd: number;
  daily_loss_remaining_usd: number;
  notional_limit_usd: number;
  notional_used_usd: number;
  notional_utilization_pct: number;
}
```

### Market State

```typescript
interface MarketState {
  // Positions
  open_position_count: number;
  positions: PositionSummary[];

  // Orders
  open_order_count: number;
  recent_orders: OrderSummary[];

  // Fills
  recent_fills: FillSummary[];

  // Active markets
  active_tickers: string[];
  active_market_count: number;

  // Market quality
  avg_spread_cents: number;
  avg_depth_10c: number;
  illiquid_market_count: number;
}

interface PositionSummary {
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  avg_price_cents: number;
  current_price_cents: number;
  unrealized_pnl_usd: number;
  expiry_time: string;
  seconds_to_expiry: number;
}

interface OrderSummary {
  order_id: string;
  ticker: string;
  side: 'yes' | 'no';
  action: 'buy' | 'sell';
  contracts: number;
  limit_price_cents: number;
  status: 'pending' | 'open' | 'filled' | 'cancelled' | 'rejected';
  created_at: string;
  seconds_ago: number;
}

interface FillSummary {
  fill_id: string;
  order_id: string;
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  price_cents: number;
  fee_cents: number;
  pnl_usd: number;
  filled_at: string;
  seconds_ago: number;
}
```

### Risk State

```typescript
interface RiskState {
  // Daily limits
  daily_loss_usd: number;
  daily_loss_limit_usd: number;
  daily_loss_pct: number;

  // Position limits
  total_notional_usd: number;
  notional_limit_usd: number;
  notional_utilization_pct: number;

  // Exposure
  gross_exposure_usd: number;
  net_exposure_usd: number;
  max_single_asset_exposure_pct: number;

  // Breaches
  breach_count: number;
  active_breaches: BreachSummary[];

  // Alerts
  recent_alerts: RiskAlertSummary[];
  unacknowledged_alert_count: number;
}

interface BreachSummary {
  check: string;
  reason: string;
  severity: 'warning' | 'critical';
  triggered_at: string;
  acknowledged: boolean;
}

interface RiskAlertSummary {
  id: string;
  level: 'warning' | 'critical' | 'info';
  category: string;
  message: string;
  timestamp: string;
  acknowledged: boolean;
}
```

### Grid State

```typescript
interface GridState {
  // Grid status
  running: boolean;
  agent_count: number;
  active_agent_count: number;

  // Cycle metrics
  last_cycle_at: string | null;
  cycles_run: number;
  cycles_per_minute: number;

  // Trading metrics
  total_orders: number;
  total_fills: number;
  fill_rate_pct: number;

  // Coverage
  active_markets: number;
  coverage_pct: number;

  // Errors
  recent_errors: GridErrorSummary[];
  error_count: number;
}

interface GridErrorSummary {
  agent_id: string;
  error: string;
  timestamp: string;
}
```

---

## Detail State (Lazy-Loaded)

These are loaded on-demand when user drills into specific areas:

### Agent Performance Detail

```typescript
interface AgentPerformanceDetail {
  agent_id: string;
  total_fills: number;
  total_closes: number;
  total_volume_usd: number;
  win_rate: number;
  avg_pnl_per_trade: number;
  total_pnl: number;
  sharpe_ratio: number | null;
  edge_accuracy: number;
  confidence_calibration_error: number;
  brier_score: number | null;
  last_trade_at: string | null;
  recent_trades: TradeDetail[];
}
```

### Sentiment Detail

```typescript
interface SentimentDetail {
  asset: string;
  sentiment_value: number; // 0-100
  sentiment_regime: 'extreme_fear' | 'fear' | 'neutral' | 'greed' | 'extreme_greed';
  sentiment_confidence: number;
  sizing_multiplier: number; // 0.0-1.5
  sizing_regime: 'halted' | 'caution' | 'normal' | 'aggressive';
  components: {
    volatility: number;
    volume_heat: number;
    book_imbalance: number;
  };
  timeframe_sentiment: TimeframeSentiment[];
}

interface TimeframeSentiment {
  timeframe: string;
  sentiment: number;
  regime: string;
  signal_count: number;
}
```

### Market Detail

```typescript
interface MarketDetail {
  ticker: string;
  title: string;
  subtitle: string;
  yes_ask: number;
  no_ask: number;
  yes_bid: number;
  no_bid: number;
  spread_cents: number;
  mid_cents: number;
  volume_24h: number;
  open_interest: number;
  seconds_to_expiry: number;
  expiration_time: string;
  orderbook: OrderbookLevel[];
  recent_trades: TradeDetail[];
}
```

---

## Backend Implementation Plan

### Phase 1a: Create Aggregation Endpoint

**File:** `web/api/kalshi_ui_state_api.py` (new)

```python
router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi-ui-state"])

@router.get("/ui-state")
async def get_kalshi_ui_state():
    """Aggregate all essential Kalshi state for UI consumption."""
    # Fetch from existing endpoints:
    # - KALSHI_GRID_MODE -> system.mode
    # - SYSTEM_EXECUTION_GATE -> system.execution_gate
    # - KALSHI_HEALTH -> system.venue_healthy
    # - KALSHI_BALANCE -> capital.balance_usd
    # - KALSHI_PNL -> capital.daily_pnl_usd
    # - KALSHI_RISK -> risk.*
    # - KALSHI_POSITIONS -> markets.positions
    # - KALSHI_ORDERS -> markets.recent_orders
    # - KALSHI_FILLS -> markets.recent_fills
    # - KALSHI_GRID_STATUS -> grid.*
    # - RECONCILIATION_STATUS -> system.reconciliation_status
    # - OPERATOR_KILL_SWITCH_STATUS -> system.kill_switch_*
    
    # Aggregate and return canonical state
    pass
```

### Phase 1b: Add WebSocket Push

**File:** `web/api/kalshi_ui_state_api.py`

```python
@router.websocket("/ui-state/ws")
async def kalshi_ui_state_websocket(websocket: WebSocket):
    """Push real-time updates for fills, orders, risk events."""
    await websocket.accept()
    
    # Subscribe to:
    # - Fill notifications (via existing WS bridge)
    # - Order status updates
    # - Risk alerts
    # - Kill switch changes
    # - Execution gate changes
    
    # Push updates as they occur
    pass
```

### Phase 1c: Add Detail Endpoints

```python
@router.get("/ui-state/agent/{agent_id}")
async def get_agent_performance_detail(agent_id: str):
    """Lazy-loaded agent performance detail."""
    pass

@router.get("/ui-state/sentiment/{asset}")
async def get_sentiment_detail(asset: str):
    """Lazy-loaded sentiment detail."""
    pass

@router.get("/ui-state/market/{ticker}")
async def get_market_detail(ticker: str):
    """Lazy-loaded market detail."""
    pass
```

---

## Frontend Implementation Plan

### Phase 1d: Create TypeScript Types

**File:** `web/react/src/types/kalshiUIState.ts` (new)

```typescript
export interface KalshiUIState {
  version: string;
  timestamp: string;
  cache_ttl_seconds: number;
  system: SystemStatus;
  capital: CapitalState;
  markets: MarketState;
  risk: RiskState;
  grid: GridState;
}

// ... all other interfaces from above
```

### Phase 1e: Create State Hook

**File:** `web/react/src/hooks/useKalshiUIState.ts` (new)

```typescript
export function useKalshiUIState() {
  const { data, loading, error, refetch } = useApiData<KalshiUIState>(
    API_ENDPOINTS.KALSHI_UI_STATE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  
  // WebSocket connection for real-time updates
  // Merge WS updates into cached state
  
  return { state: data, loading, error, refetch };
}
```

### Phase 1f: Add Constants

**File:** `web/react/src/config/constants.ts`

```typescript
export const API_ENDPOINTS = {
  // ... existing endpoints
  
  // UI State (new)
  KALSHI_UI_STATE: "/api/v1/kalshi/ui-state",
  KALSHI_UI_STATE_WS: "/api/v1/kalshi/ui-state/ws",
  KALSHI_UI_STATE_AGENT_DETAIL: (agentId: string) => `/api/v1/kalshi/ui-state/agent/${agentId}`,
  KALSHI_UI_STATE_SENTIMENT_DETAIL: (asset: string) => `/api/v1/kalshi/ui-state/sentiment/${asset}`,
  KALSHI_UI_STATE_MARKET_DETAIL: (ticker: string) => `/api/v1/kalshi/ui-state/market/${ticker}`,
}
```

---

## Data Aggregation Strategy

### Existing Endpoints to Aggregate

| System Field | Source Endpoint | Notes |
|--------------|----------------|-------|
| system.mode | `KALSHI_GRID_MODE` | Trading mode |
| system.execution_gate | `SYSTEM_EXECUTION_GATE` | Gate status |
| system.kill_switch_* | `OPERATOR_KILL_SWITCH_STATUS` | Kill switch |
| system.venue_healthy | `KALSHI_HEALTH` | Venue health |
| system.reconciliation_* | `RECONCILIATION_STATUS` | Reconciliation |

| Capital Field | Source Endpoint | Notes |
|--------------|----------------|-------|
| capital.balance_usd | `KALSHI_BALANCE` | Use total_value_cents/100 |
| capital.daily_pnl_usd | `KALSHI_PNL` | Daily PnL |
| capital.drawdown_* | `KALSHI_SIZING_METRICS` | Drawdown data |
| capital.*_limit | `KALSHI_RISK` | Risk limits |

| Market Field | Source Endpoint | Notes |
|--------------|----------------|-------|
| markets.positions | `KALSHI_POSITIONS` | Filter test tickers |
| markets.recent_orders | `KALSHI_ORDERS` | Last 10 orders |
| markets.recent_fills | `KALSHI_FILLS` | Last 10 fills |
| markets.active_tickers | Derived from positions | Unique tickers |

| Risk Field | Source Endpoint | Notes |
|--------------|----------------|-------|
| risk.* | `KALSHI_RISK` | All risk fields |
| risk.recent_alerts | `RISK_ALERTS` | Recent alerts |

| Grid Field | Source Endpoint | Notes |
|--------------|----------------|-------|
| grid.* | `KALSHI_GRID_STATUS` | All grid fields |

### Caching Strategy

- **Cache TTL:** 10 seconds for core state
- **Cache Key:** None (public state, authenticated via session)
- **Invalidation:** WebSocket pushes updates, or time-based expiry
- **Stale-while-revalidate:** Allow stale data while fetching fresh

---

## WebSocket Event Types

```typescript
type UIStateEvent =
  | { type: 'fill'; data: FillSummary }
  | { type: 'order'; data: OrderSummary }
  | { type: 'risk_alert'; data: RiskAlertSummary }
  | { type: 'kill_switch'; data: { active: boolean; reason: string | null } }
  | { type: 'execution_gate'; data: { state: string; reasons: string[] } }
  | { type: 'grid_status'; data: Partial<GridState> }
  | { type: 'capital_update'; data: Partial<CapitalState> };
```

---

## Migration Path

### Phase 1: Backend State Model (Current)
- Create aggregation endpoint
- Define TypeScript interfaces
- Add WebSocket support

### Phase 2: Compact Overview Panel
- Build new Overview using canonical state
- Keep old Overview as fallback (feature flag)

### Phase 3: Live Activity Stream
- Build activity stream component
- Use WebSocket for real-time updates

### Phase 4: Detail Drawer
- Build drawer component
- Implement lazy-loaded detail endpoints

### Phase 5: Troubleshooting View
- Build troubleshooting view
- Aggregate logs, errors, reconciliation data

### Phase 6: Minimal Action Area
- Consolidate controls into single action bar
- Remove duplicated controls from views

### Phase 7: WebSocket Sync
- Implement reliable WebSocket connection
- Add reconnection logic
- Add event deduplication

### Phase 8: Screen Migration
- Migrate KalshiVolDashboardView
- Migrate KalshiAgentPerformanceView
- Migrate KalshiSentimentView
- Remove old views after validation

---

## Next Steps

1. **Implement backend aggregation endpoint** (`web/api/kalshi_ui_state_api.py`)
2. **Add TypeScript types** (`web/react/src/types/kalshiUIState.ts`)
3. **Create state hook** (`web/react/src/hooks/useKalshiUIState.ts`)
4. **Add constants** (`web/react/src/config/constants.ts`)
5. **Test endpoint** with curl/Postman
6. **Build prototype Overview** using canonical state
