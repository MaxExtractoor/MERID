# Phase 1: Source of Truth and Invariants

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Define canonical data stores, write permissions, and enforceable invariants

---

## Executive Summary

This document establishes the single sources of truth for the MERID Kalshi trading system and defines the invariants that must hold across all components. All reads must go through these canonical stores, and all writes must be mediated by authorized services only.

---

## Canonical Data Stores

### 1. Market Data: `KalshiMarketStateStore`

**Location:** `merid/event_venues/kalshi/market_state.py`  
**Singleton:** `get_kalshi_market_state_store()`

**Purpose:** Single source of truth for real-time Kalshi market state (orderbook, spread, depth, OI, expiry).

**Data Model:**
```python
@dataclass
class KalshiMarketState:
    ticker: str
    book_initialized: bool
    mid_cents: int
    spread_cents: int
    depth_10c: int
    top_of_book_size: int
    volume_24h: int
    open_interest: int
    seconds_to_expiry: int
    expiration_time: datetime
    last_update: datetime
```

**Authorized Writers:**
- `KalshiWebSocketBridge` (via `ws_bridge.py`) - Updates on orderbook deltas
- `KalshiMarketCatalog` (bootstrap) - Initial snapshot from REST API
- **NO HUMAN WRITES** - Manual edits prohibited

**Authorized Readers:**
- All agents (for pricing, edge calculation)
- Order router (for TIF resolution)
- Risk engine (for portfolio valuation)
- UI API endpoints (for display)

**Invariants:**
1. If `book_initialized=True`, then `mid_cents > 0` and `spread_cents >= 0`
2. `depth_10c >= 0` (non-negative)
3. `seconds_to_expiry >= 0` (non-negative, 0 if expired)
4. `last_update` must be within 30 seconds of current time (stale detection)
5. For crypto series tickers (KXBTC-15M, etc.), `ticker` must match `CRYPTO_SERIES_BASE` + `TIMEFRAME_SERIES_SUFFIX` pattern

---

### 2. Trades and Fills: `KalshiFillsLedger`

**Location:** `merid/event_venues/kalshi/fills_ledger.py`  
**Singleton:** `get_fills_ledger()`

**Purpose:** Canonical append-only ledger of all executed trades with dual ingestion (HTTP + WebSocket).

**Data Model:**
```python
@dataclass
class KalshiFill:
    fill_id: str  # PRIMARY KEY from Kalshi
    trade_id: Optional[str]
    order_id: Optional[str]
    market_ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count_fp: int  # Number of contracts
    yes_price_dollars: Optional[Decimal]
    no_price_dollars: Optional[Decimal]
    fee_cost: Decimal
    proceeds_dollars: Optional[Decimal]
    client_order_id: Optional[str]
    created_time: datetime
    
    # MERID metadata
    ingestion_source: str  # "http_poller", "websocket", "backfill"
    ingested_at: datetime
    agent_id: Optional[str]
    intent_id: Optional[str]
    decision_trace_id: Optional[str]
    fill_source: str  # "alpha", "hedge", "manual"
    is_live: bool  # True if LIVE trade, False if PAPER
```

**Authorized Writers:**
- `KalshiFillsPoller` (HTTP ingestion) - Pulls from `/portfolio/fills` API
- `KalshiWebSocketBridge` (WS ingestion) - Real-time fill events
- **NO HUMAN WRITES** - Manual fills prohibited in production

**Authorized Readers:**
- Position cache (for reconciliation)
- PnL attribution engine (for trade analysis)
- Risk engine (for exposure calculation)
- UI API endpoints (for trade history)

**Invariants:**
1. `fill_id` must be unique (primary key)
2. `count_fp > 0` for all fills (no zero-size fills)
3. `fee_cost >= 0` (fees are non-negative)
4. If `is_live=True`, then `fill_id` must NOT be a test fixture (no `fill_integrity_` prefixes)
5. If `side="yes"`, then `yes_price_dollars` must be set; if `side="no"`, then `no_price_dollars` must be set
6. `ingested_at` must be >= `created_time` (cannot ingest before trade happened)
7. For hedge fills, `fill_source="hedge"` and `client_order_id` must start with `HEDGE_`

---

### 3. Positions: `KalshiPositionCache`

**Location:** `merid/event_venues/kalshi/position_cache.py`  
**Singleton:** `get_position_cache()`

**Purpose:** Real-time in-memory position state derived from fills ledger (not a separate source of truth).

**Data Model:**
```python
@dataclass
class CachedPosition:
    market_id: str
    contracts: int
    side: str  # "yes" or "no"
    avg_price_cents: int
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    last_updated: datetime
    take_profit_price_cents: Optional[int]
    stop_loss_price_cents: Optional[int]
    fill_source: str  # "alpha" or "hedge"
    client_order_id: Optional[str]
```

**Authorized Writers:**
- `KalshiFillsLedger` (via `on_fill` callback) - Only fills ledger can update positions
- `sync_from_rest` (reconciliation fallback) - REST API sync when cache stale
- **NO DIRECT WRITES** - Positions are derived, never set directly

**Authorized Readers:**
- Bankroll service (for portfolio value calculation)
- Risk engine (for exposure limits)
- Hedge engine (for exposure snapshots)
- UI API endpoints (for position display)

**Invariants:**
1. `contracts >= 0` (non-negative, zero means no position)
2. `avg_price_cents >= 0` and `<= 100` (valid cent range)
3. `realized_pnl_usd` can be negative (losses allowed)
4. `unrealized_pnl_usd` can be negative (mark-to-market losses allowed)
5. If `contracts > 0`, then `last_updated` must be within 5 minutes of current time
6. For hedge positions, `fill_source="hedge"` must match fills ledger
7. Test tickers (KXTEST, etc.) must never appear in production cache

---

### 4. Bankroll: `BankrollServiceV2`

**Location:** `merid/event_venues/kalshi/bankroll_service_v2.py`  
**Singleton:** `get_bankroll_service()`

**Purpose:** Single source of truth for account equity, available cash, and portfolio value.

**Data Model:**
```python
@dataclass(frozen=True)
class InternalBankroll:
    equity_usd: Decimal
    available_cash_usd: Decimal
    locked_cash_usd: Decimal  # Reserved for open orders
    max_position_usd: Decimal
    state: BalanceState  # FRESH, STALE, ERROR, UNKNOWN
    as_of: datetime
    source: str
```

**Authorized Writers:**
- `KalshiClientV2` (via `get_balance`) - Only Kalshi API can update bankroll
- **NO HUMAN WRITES** - Manual balance adjustments prohibited
- **NO FALLBACK TO HARDCODED VALUES** - Must fail closed if API unavailable

**Authorized Readers:**
- Position sizer (for Kelly calculations)
- Risk engine (for drawdown limits)
- All agents (for position sizing)
- UI API endpoints (for balance display)

**Invariants:**
1. `equity_usd = available_cash_usd + portfolio_value` (within 1 cent tolerance)
2. `available_cash_usd >= 0` (can't have negative available cash)
3. `locked_cash_usd >= 0` (non-negative)
4. `max_position_usd > 0` if state is FRESH
5. If `state=ERROR`, then trading must be blocked
6. If `state=FRESH`, then `as_of` must be within 60 seconds of current time
7. Portfolio value calculated from position cache only (no duplication)

---

### 5. Portfolio State: `PortfolioEngine`

**Location:** `merid/event_venues/kalshi/portfolio_engine.py`  
**Singleton:** `get_portfolio_engine()`

**Purpose:** Event-driven portfolio state reconstruction from append-only event log.

**Data Model:**
```python
@dataclass
class PortfolioSnapshot:
    account_id: str
    sequence_id: int
    timestamp: datetime
    cash_available_cents: int
    cash_reserved_cents: int
    cash_total_cents: int
    positions: Dict[str, Position]
    open_orders: Dict[str, Order]
    realized_pnl_cents: int
    unrealized_pnl_cents: int
```

**Authorized Writers:**
- `PortfolioEventLog` (via `replay_event`) - Only event replay can update state
- **NO DIRECT WRITES** - State is derived from events, never set directly

**Authorized Readers:**
- Reconciliation service (for Kalshi API comparison)
- Risk engine (for portfolio-level limits)
- UI API endpoints (for portfolio summary)

**Invariants:**
1. `cash_total_cents = cash_available_cents + cash_reserved_cents` (exact)
2. `cash_available_cents >= 0` (non-negative)
3. `cash_reserved_cents >= 0` (non-negative)
4. Position quantity × avg entry price ≈ cost basis (within 1 cent tolerance)
5. Open orders must have `reserved_cash_cents > 0`
6. Total reserved cash cannot exceed available cash
7. All monetary values must be integers (cents, no floats)

---

### 6. PnL Attribution: `PnLAttributionEngine`

**Location:** `merid/prediction/pnl_attribution.py`  
**Singleton:** `get_pnl_attribution_engine()`

**Purpose:** Post-trade analysis of realized PnL impact by strategy, signal, and execution layer.

**Data Model:**
```python
@dataclass
class TradeRecord:
    symbol: str
    trade_type: TradeType  # ENTRY, EXIT, TRIM
    timestamp: float
    price: float
    quantity: int
    trade_id: str
    agent_id: Optional[str]
    base_kelly_fraction: float
    debate_multiplier: float
    final_kelly_fraction: float
    realized_pnl: Optional[float]
    base_pnl: Optional[float]
    debate_pnl_impact: Optional[float]
```

**Authorized Writers:**
- Trading agents (via `record_trade`) - Only agents can record trades
- **NO HUMAN WRITES** - Manual attribution prohibited

**Authorized Readers:**
- Strategy review (for performance analysis)
- Risk review (for strategy-level limits)
- UI API endpoints (for attribution dashboard)

**Invariants:**
1. `trade_id` must be unique per trade
2. `quantity > 0` for all trades
3. `price > 0` for all trades
4. `final_kelly_fraction = base_kelly_fraction * debate_multiplier` (math check)
5. If `realized_pnl` is set, then `base_pnl` must also be set
6. Attribution can only be calculated after both entry and exit are recorded

---

## Global Invariants

### Invariant 1: No Trade Bypasses Risk Checks
**Statement:** Every trade must pass through risk checks before execution.

**Enforcement Point:** `order_router.py` → `_run_pre_trade_gate()`

**Check:**
- Kill switch status must be ACTIVE
- Reconciliation status must be OK
- Daily loss limit must not be breached
- Position size must be within limits
- Bankroll must be FRESH (not STALE or ERROR)

**Violation Action:** Reject order, log violation, alert operator.

---

### Invariant 2: No Trade Bypasses Logging
**Statement:** Every trade must be logged to fills ledger and position cache.

**Enforcement Point:** `fills_ledger.py` → `ingest_http_fills()` / `ingest_ws_fill()`

**Check:**
- `fill_id` must be present and unique
- `ingestion_source` must be recorded
- `agent_id` must be recorded if available
- `is_live` flag must be set correctly

**Violation Action:** Reject fill, log error, alert operator.

---

### Invariant 3: No Trade Bypasses Portfolio Update
**Statement:** Every trade must update portfolio state (cash, positions, PnL).

**Enforcement Point:** `position_cache.py` → `on_fill()` + `portfolio_engine.py` → `replay_event()`

**Check:**
- Cash ledger must be updated
- Position quantity must be updated
- Realized PnL must be calculated
- Cost basis must be updated

**Violation Action:** Log violation, trigger reconciliation, alert operator.

---

### Invariant 4: Position ↔ Fill Reconciliation
**Statement:** Sum of fills must equal current position state.

**Enforcement Point:** `fills_ledger.py` → `reconcile_with_kalshi_positions()`

**Check:**
- For each ticker: sum(fill quantities) = position.contracts
- For each ticker: sum(fill costs) = position.cost_basis
- Discrepancy tolerance: 1 contract or 1 cent

**Violation Action:** Log discrepancy, mark reconciliation as DEGRADED, alert operator.

---

### Invariant 5: Portfolio ↔ Bankroll Reconciliation
**Statement:** Portfolio value + available cash must equal bankroll equity.

**Enforcement Point:** `bankroll_service_v2.py` → `_check_equity_invariant_locked()`

**Check:**
- `equity_usd ≈ available_cash_usd + portfolio_value`
- Tolerance: 1 cent (0.01 USD)
- Portfolio value calculated from position cache only

**Violation Action:** Log warning, mark bankroll as ERROR, block trading.

---

### Invariant 6: Market Data Freshness
**Statement:** Market data used for pricing must be fresh (not stale).

**Enforcement Point:** `market_state.py` → `is_trading_enabled()`

**Check:**
- `last_update` within 30 seconds for active markets
- `book_initialized=True` for markets used in trading
- Minimum 3/5 markets must be healthy for trading to continue

**Violation Action:** Disable trading for stale markets, log violation, alert operator.

---

### Invariant 7: No Test Data in Production
**Statement:** Test fixtures and test tickers must never appear in production state.

**Enforcement Point:** Multiple (fills ledger, position cache, market state)

**Check:**
- Fills with `fill_id` starting with `fill_integrity_` rejected
- Positions with ticker containing "TEST" or "KXTEST" filtered
- Market state for test tickers excluded from trading

**Violation Action:** Filter out test data, log warning, alert if persistent.

---

## Write Permission Matrix

| Data Store | Human Write | Service Write | Authorized Services |
|------------|-------------|---------------|---------------------|
| KalshiMarketStateStore | ❌ NO | ✅ YES | WS Bridge, Market Catalog |
| KalshiFillsLedger | ❌ NO | ✅ YES | Fills Poller, WS Bridge |
| KalshiPositionCache | ❌ NO | ✅ YES | Fills Ledger (callback) |
| BankrollServiceV2 | ❌ NO | ✅ YES | Kalshi Client V2 |
| PortfolioEngine | ❌ NO | ✅ YES | Portfolio Event Log |
| PnLAttributionEngine | ❌ NO | ✅ YES | Trading Agents |

**Key Principle:** All writes are mediated by services only. No direct database edits, no manual API calls, no console scripts that bypass the service layer.

---

## Automated Test Plan

### Test Suite: `tests/invariants/test_source_of_truth_invariants.py`

**Test Classes:**

1. `TestMarketStateStoreInvariants`
   - Test: book_initialized implies mid_cents > 0
   - Test: spread_cents non-negative
   - Test: seconds_to_expiry non-negative
   - Test: last_update freshness check
   - Test: crypto series ticker pattern validation

2. `TestFillsLedgerInvariants`
   - Test: fill_id uniqueness
   - Test: count_fp > 0
   - Test: fee_cost non-negative
   - Test: is_live implies no test fixture fill_id
   - Test: side matches price field presence
   - Test: hedge fill client_order_id prefix

3. `TestPositionCacheInvariants`
   - Test: contracts non-negative
   - Test: avg_price_cents in valid range
   - Test: last_update freshness check
   - Test: hedge fill_source consistency
   - Test: test ticker filtering

4. `TestBankrollServiceInvariants`
   - Test: equity = cash + portfolio (within tolerance)
   - Test: available_cash non-negative
   - Test: locked_cash non-negative
   - Test: ERROR state blocks trading
   - Test: FRESH state time freshness

5. `TestPortfolioEngineInvariants`
   - Test: cash_total = cash_available + cash_reserved (exact)
   - Test: cash_available non-negative
   - Test: position quantity × price ≈ cost basis
   - Test: open orders have reserved_cash > 0
   - Test: reserved cash does not exceed available

6. `TestGlobalInvariants`
   - Test: no trade bypasses risk checks
   - Test: no trade bypasses logging
   - Test: no trade bypasses portfolio update
   - Test: position ↔ fill reconciliation
   - Test: portfolio ↔ bankroll reconciliation
   - Test: market data freshness
   - Test: no test data in production

7. `TestWritePermissions`
   - Test: human writes rejected (mock attempts)
   - Test: unauthorized services rejected (mock attempts)
   - Test: authorized services accepted

**Total Target:** 50+ invariant tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify all existing data stores
- ✅ Document current data models
- ✅ Document current invariants (from PortfolioEngine)

### Step 2: Define Canonical Stores (DONE)
- ✅ Name canonical stores
- ✅ Define data models
- ✅ Define write permissions
- ✅ Define authorized writers/readers

### Step 3: Define Global Invariants (DONE)
- ✅ Define 7 global invariants
- ✅ Define enforcement points
- ✅ Define violation actions

### Step 4: Implement Invariant Tests (NEXT)
- [ ] Create `tests/invariants/test_source_of_truth_invariants.py`
- [ ] Implement all 7 test classes
- [ ] Target: 50+ tests passing
- [ ] Wire into CI pipeline

### Step 5: Add Runtime Invariant Checks
- [ ] Add invariant checks to PortfolioEngine (already has some)
- [ ] Add invariant checks to BankrollServiceV2 (already has equity invariant)
- [ ] Add invariant checks to FillsLedger (add fill validation)
- [ ] Add invariant checks to PositionCache (add consistency checks)

### Step 6: Add Write Permission Guards
- [ ] Add service-level authentication checks
- [ ] Add write permission decorators
- [ ] Add audit logging for all writes

### Step 7: Monitoring and Alerting
- [ ] Add Prometheus metrics for invariant violations
- [ ] Add alerting for critical violations
- [ ] Add dashboard for invariant health

---

## Success Criteria

Phase 1 is complete when:

1. ✅ This design document is approved
2. [ ] All 50+ invariant tests are implemented and passing
3. [ ] Runtime invariant checks are added to all canonical stores
4. [ ] Write permission guards are implemented
5. [ ] Monitoring and alerting are wired
6. [ ] CI pipeline includes invariant test suite
7. [ ] No manual writes to canonical stores in production

---

## References

- `merid/event_venues/kalshi/market_state.py` - Market state store
- `merid/event_venues/kalshi/fills_ledger.py` - Fills ledger
- `merid/event_venues/kalshi/position_cache.py` - Position cache
- `merid/event_venues/kalshi/bankroll_service_v2.py` - Bankroll service
- `merid/event_venues/kalshi/portfolio_engine.py` - Portfolio engine
- `merid/prediction/pnl_attribution.py` - PnL attribution
- `merid/risk/kill_switches.py` - Risk controls
- `merid/event_venues/kalshi/order_router.py` - Order routing

---

**Next Phase:** Phase 2A - Data integrity and alignment (candle/orderbook validation, drift checks, Kalshi metadata verification)
