# Kalshi Module Ownership Matrix

**Purpose**: Define single source of truth for each concern across the Kalshi trading pipeline to prevent drift and ensure end-to-end alignment.

---

## Ownership Principles

1. **One Owner Per Concern**: Each invariant, policy, or calculation has exactly one canonical implementation.
2. **Upstream → Midstream → Downstream**: Data flows unidirectionally; downstream modules call upstream, never reimplement.
3. **Explicit Fallbacks**: Any fallback or alternate path must be explicitly marked and never treated as canonical truth.
4. **No Silent Duplication**: If logic appears in multiple places, it must be either delegation or documented intentional divergence.

---

## Module Ownership Matrix

### UPSTREAM: Data Sources & Venue Invariants

| Module | Owns (Single Source of Truth) | Calls (Delegates To) | Forbidden |
|--------|------------------------------|---------------------|-----------|
| `merid/event_venues/kalshi/invariants.py` | - `clamp_probability()` - probability bounds<br>- `is_within_entry_window()` - time window validation<br>- `get_effective_edge_threshold()` - edge threshold calculation<br>- `compute_max_notional()` - max notional from bankroll<br>- `compute_contracts()` - contract count from notional<br>- `is_trade_valid()` - trade validity checks<br>- `is_liquid_enough()` - liquidity policy | None (pure functions) | - No probability clamps elsewhere<br>- No edge threshold logic elsewhere<br>- No sizing math elsewhere |
| `merid/event_venues/kalshi/market_state.py` | - `KalshiMarketState` - book freshness tracking<br>- `last_book_update_ts` - staleness detection<br>- `executable` flag - liquidity + anomaly status<br>- Health monitoring (`log_book_health`) | `orderbook.py` for price parsing<br>`invariants.py` for liquidity checks | - No separate freshness checks<br>- No manual executable flag overrides |
| `merid/event_venues/kalshi/orderbook.py` | - `Orderbook.apply_snapshot()` - price parsing<br>- YES/NO symmetry conversion (`100 - no_price`)<br>- `get_best_bid()`, `get_best_ask()` - price accessors | None (pure data structure) | - No price normalization elsewhere<br>- No manual symmetry math elsewhere |
| `merid/event_venues/kalshi/market_catalog.py` | - Market discovery from Kalshi API<br>- `minutes_to_expiry` calculation (UTC-based)<br>- Series ticker resolution | `client.py` for API calls<br>`universe_sync.py` for market wiring | - No alternate market sources<br>- No local expiry calculation |
| `merid/event_venues/kalshi/kalshi_risk.py` | - Fee model (trading + settlement fees)<br>- Payout calculations ($1 contract payoff)<br>- Post-fee edge calculations | None (venue-specific math) | - No fee logic elsewhere<br>- No payout assumptions elsewhere |

---

### MIDSTREAM: Decision & Policy

| Module | Owns (Single Source of Truth) | Calls (Delegates To) | Forbidden |
|--------|------------------------------|---------------------|-----------|
| `merid/prediction/agent_grid_15m.py` | - Signal generation logic<br>- Market selection from catalog<br>- Trade intent creation | `invariants.py` - clamp, window, edge, sizing<br>`market_state.py` - book freshness<br>`market_catalog.py` - market discovery | - No probability clamps (use `clamp_probability`)<br>- No edge threshold logic (use `get_effective_edge_threshold`)<br>- No sizing math (use `compute_*` helpers) |
| `merid/prediction/unified_sizing.py` | - **INTENTIONAL WRAPPER**: Position-aware sizing<br>- Risk pct interlock logic<br>- Fee adjustment on max_notional<br>- Per-asset position tracking | `invariants.py` - `compute_max_notional`, `compute_contracts`, `is_trade_valid`<br>`position_cache.py` - existing positions | - No pure sizing math (delegate to invariants)<br>- Document wrapper intent clearly |
| `merid/prediction/edge_model.py` | - Edge adjustment factors (time decay, spread, regime)<br>- Signal combination logic | `invariants.py` - `clamp_probability` (MUST USE)<br>`invariants.py` - `get_effective_edge_threshold` | - **CRITICAL**: No manual `max(0.02, min(0.98, ...))` - use `clamp_probability`<br>- No edge threshold logic (use `get_effective_edge_threshold`) |
| `merid/prediction/dynamic_edge_calibrator.py` | - Dynamic edge scaling based on realized performance<br>- Calibration state management | `invariants.py` - `get_effective_edge_threshold` (base) | - No static edge logic (use invariant) |
| `merid/prediction/risk.py` | - Pre-trade validation logic<br>- Position limit enforcement (internal) | `invariants.py` - `is_trade_valid`<br>`unified_sizing.py` - sizing | - No duplicate validity checks<br>- No sizing logic |

---

### DOWNSTREAM: Execution & Accounting

| Module | Owns (Single Source of Truth) | Calls (Delegates To) | Forbidden |
|--------|------------------------------|---------------------|-----------|
| `merid/event_venues/kalshi/order_router.py` | - Order submission to Kalshi API<br>- Limit order price setting<br>- Execution intent creation | `market_state.py` - price source<br>`agent_grid_15m.py` - trade intent | - No price source assumptions<br>- No contract semantics assumptions |
| `merid/event_venues/kalshi/fills_ledger.py` | - Fill recording and accounting<br>- PnL calculation ($1 payoff)<br>- Settlement PnL (gross vs net) | `kalshi_risk.py` - fee model<br>`settlement_poller.py` - outcomes | - No payout assumptions (use $1 from kalshi_risk)<br>- No fee logic (use kalshi_risk) |
| `merid/event_venues/kalshi/portfolio_engine.py` | - Position state management<br>- Real-time PnL tracking | `fills_ledger.py` - fill accounting<br>`market_state.py` - mark-to-market | - No position limit logic (use risk.py) |
| `merid/event_venues/kalshi/settlement_poller.py` | - Settlement outcome polling<br>- Outcome resolution (YES/NO) | `client.py` - API calls<br>`fills_ledger.py` - PnL update | - No outcome assumptions |
| `merid/metrics/realized_edge.py` | - Expected vs realized edge tracking<br>- Post-trade performance analysis | `fills_ledger.py` - fill data<br>`agent_grid_15m.py` - trace context | - No edge recalculation (use original trace) |

---

## End-to-End Flow

### Single Market Candidate Flow

```
1. DISCOVERY (Upstream)
   market_catalog.py → discovers market from Kalshi API
   └─ minutes_to_expiry (UTC-based)
   └─ series_ticker resolution

2. STATE VALIDATION (Upstream)
   market_state.py → checks freshness and liquidity
   └─ last_book_update_ts staleness check
   └─ executable flag (liquidity + anomaly status)
   └─ is_liquid_enough() from invariants.py

3. SIGNAL GENERATION (Midstream)
   agent_grid_15m.py → generates signal
   └─ clamp_probability() from invariants.py
   └─ get_effective_edge_threshold() from invariants.py
   └─ is_within_entry_window() from invariants.py
   └─ price_source tracking (LIVE_BOOK, FALLBACK_50C, UNKNOWN)

4. SIZING (Midstream)
   unified_sizing.py → computes position size
   └─ compute_max_notional() from invariants.py
   └─ compute_contracts() from invariants.py
   └─ is_trade_valid() from invariants.py
   └─ position-aware adjustments (wrapper logic)
   └─ fee adjustment (wrapper logic)

5. PRE-TRADE VALIDATION (Midstream)
   risk.py → validates trade
   └─ is_trade_valid() from invariants.py
   └─ position limit checks (internal)
   └─ same assumptions as sizing

6. ORDER ROUTING (Downstream)
   order_router.py → submits order
   └─ uses same price_source as sizing
   └─ limit price from best_ask/best_bid
   └─ contract semantics from kalshi_risk.py

7. FILL ACCOUNTING (Downstream)
   fills_ledger.py → records fill
   └─ $1 payoff from kalshi_risk.py
   └─ fee model from kalshi_risk.py
   └─ links to original TRADE-TRACE

8. SETTLEMENT (Downstream)
   settlement_poller.py → resolves outcome
   └─ updates fills_ledger.py
   └─ realized PnL calculation

9. POST-TRADE ANALYSIS (Downstream)
   realized_edge.py → compares expected vs realized
   └─ uses original trace context
   └─ uses fill data from fills_ledger.py
```

---

## Critical Gaps to Close

### Gap 1: edge_model.py Manual Clamps
**Current**: `edge_model.py` line 231 uses `max(0.02, min(0.98, fair_prob))`
**Required**: Replace with `clamp_probability(fair_prob)` from `invariants.py`
**Priority**: HIGH

### Gap 2: Fee Model Integration
**Current**: `get_effective_edge_threshold` is pre-fee; fee-aware EV exists but not integrated
**Required**: 
- Add documentation that edge threshold is pre-fee
- Add placeholder for fee-aware variant
**Priority**: MEDIUM

### Gap 3: unified_sizing Wrapper Intent
**Current**: Contains position-aware sizing and fee adjustment (not pure delegation)
**Required**: 
- Document as intentional wrapper with clear ownership
- OR refactor to pure delegation (move logic to invariants)
**Priority**: MEDIUM

### Gap 4: Venue Position Limits
**Current**: Only internal position limits enforced; Kalshi API limits not queried
**Required**: Add venue position limit query from Kalshi API if available
**Priority**: LOW

---

## Validation Checklist

For any new code or refactoring:

- [ ] Does this modify a concern owned by another module? If yes, delegate instead.
- [ ] Does this duplicate logic from `invariants.py`? If yes, use the canonical helper.
- [ ] Does this introduce a new fallback path? If yes, mark explicitly and never treat as truth.
- [ ] Does this change contract semantics? If yes, verify against `kalshi_risk.py` $1 payoff.
- [ ] Does this change fee assumptions? If yes, verify against `kalshi_risk.py` fee model.
- [ ] Does this change edge threshold logic? If yes, use `get_effective_edge_threshold`.
- [ ] Does this change probability bounds? If yes, use `clamp_probability`.
- [ ] Does this change sizing math? If yes, use `compute_max_notional`/`compute_contracts`.
- [ ] Does this change time window logic? If yes, use `is_within_entry_window`.
- [ ] Does this change liquidity policy? If yes, use `is_liquid_enough`.

---

## Migration Path

### Phase 1: Close Critical Gaps
1. Fix `edge_model.py` to use `clamp_probability`
2. Document `get_effective_edge_threshold` as pre-fee
3. Document `unified_sizing` wrapper intent

### Phase 2: Strengthen Validation
1. Add lint rule to detect manual probability clamps
2. Add lint rule to detect manual edge thresholds
3. Add unit tests for end-to-end flow

### Phase 3: Venue Integration
1. Add Kalshi API position limit query
2. Integrate venue limits into sizing logic
3. Add post-trade logging for edge vs realized PnL
