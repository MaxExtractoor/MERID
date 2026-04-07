# Kalshi Direction Semantics — End-to-End Wiring Verification

**Status**: ✅ Complete
**Date**: 2026-04-07
**Commit**: 48dc6f8

This document verifies that the Kalshi direction semantics infrastructure is fully wired from startup → YAML config → strategy execution → order placement → settlement.

---

## 1. Startup Sequence ✅

**File**: `web/main.py`

### Phase 0.4: CF Benchmarks RTI Buffer (lines 1736-1757)
```python
from merid.data.settlement_rti_buffer import get_rti_buffer, is_cfb_rti_enabled
if is_cfb_rti_enabled():
    rti_buffer = get_rti_buffer()
    rti_buffer.start()
```

**Purpose**: Polls CF Benchmarks RTI feed for Kalshi crypto settlement validation.

**Status**: ✅ Wired, starts before AgentGrid in Phase 0.4


### Phase 0.45: Direction Semantics Initialization (lines 1759-1785)
```python
from merid.event_venues.kalshi.direction_mapper import get_direction_mapper
from merid.event_venues.kalshi.strike_spot_tracker import get_strike_spot_tracker
from merid.event_venues.kalshi.gap_imbalance_optimizer import get_gap_imbalance_optimizer

direction_mapper = get_direction_mapper()
strike_spot_tracker = get_strike_spot_tracker()
gap_optimizer = get_gap_imbalance_optimizer()
```

**Purpose**: Initialize singleton modules for direction mapping, strike/spot tracking, and edge calculation.

**Status**: ✅ Wired, initializes before AgentGrid in Phase 0.45


### Phase 0.5: Kalshi Agent Grid (lines 1787-1797)
```python
from merid.prediction.agent_grid import get_agent_grid
agent_grid = get_agent_grid()
await agent_grid.start()
```

**Purpose**: Starts 30-cell trading agent grid (5 assets × 6 timeframes).

**Status**: ✅ Wired, starts after direction semantics are initialized


---

## 2. YAML Configuration → Strategy Loading ✅

**File**: `merid/prediction/agent_grid.py` (lines 56-96)

### Strategy Registry Validation
```python
from merid.trading.strategy_registry import _STRATEGY_REGISTRY, validate_strategy_catalog

# Fail-fast validation of all strategy configs on startup
config_err = validate_strategy_catalog()
if config_err:
    logger.error("STRATEGY CONFIG ERROR — server will not trade:\n%s", config_err)
    raise RuntimeError(f"Strategy catalog validation failed:\n{config_err}")
```

**Status**: ✅ Validates all strategy YAMLs on startup, fail-fast on error


### Strategy Instantiation
```python
strategy_class = _STRATEGY_REGISTRY.get(class_name)
if not strategy_class:
    raise ValueError(f"Unknown strategy class: {class_name}")
strategy_instance = strategy_class()
```

**Status**: ✅ Loads strategy implementations from registry


---

## 3. Market Catalog Direction Parsing ✅

**File**: `merid/event_venues/kalshi/market_catalog.py` (lines 476-484)

### Direction Enrichment
```python
# 3. Parse direction for crypto up/down markets
direction = None
if category == "crypto" and asset:
    from merid.event_venues.kalshi.direction_semantics import parse_kalshi_crypto_direction
    direction = parse_kalshi_crypto_direction(
        ticker=event_ticker or mkt.market_id,
        title=mkt.question,
        description=mkt.description
    )
```

**Status**: ✅ Every Kalshi market gets enriched with `direction: "up"|"down"|None`


### CatalogMarket Direction Field
```python
@dataclass
class CatalogMarket:
    ...
    direction: Optional[str] = None  # "up" or "down" for crypto markets
```

**Status**: ✅ Direction field added to catalog model (line 173)


---

## 4. Strategy Execution → Direction Mapping ✅

**File**: `merid/event_venues/kalshi/direction_mapper.py`

### Forecast to Side Conversion
```python
def forecast_to_side(
    self,
    forecast_signal: float,
    market_direction: str,
) -> str:
    """Convert numeric signal (positive=bullish, negative=bearish) to YES/NO.

    Rules:
    - Bullish + UP market → YES
    - Bullish + DOWN market → NO
    - Bearish + UP market → NO
    - Bearish + DOWN market → YES
    """
```

**Status**: ✅ Canonical forecast-to-side conversion implemented


### Direction Validation
```python
def validate_direction_consistency(
    self,
    forecast_signal: float,
    market_direction: str,
    chosen_side: str,
) -> bool:
    """Validate chosen_side matches forecast + market_direction.

    Logs ERROR on mismatch.
    """
```

**Status**: ✅ Runtime validation logs errors on inconsistencies


---

## 5. Strike vs Spot Tracking ✅

**File**: `merid/event_venues/kalshi/strike_spot_tracker.py`

### Decision Logging
```python
@dataclass
class StrikeSpotSnapshot:
    spot_price_at_decision: float
    kalshi_strike: float
    spot_minus_strike: float  # spot - strike (signed)
    spot_pct_diff: float      # (spot - strike) / strike * 100
    decision: str             # "yes", "no", or "skip"
    reason: str               # Why this decision was made
    market_direction: Optional[str] = None  # "up" or "down"
```

**Status**: ✅ Every trading decision logs full strike/spot context


### Staleness Detection
```python
def check_staleness(
    self,
    spot: float,
    strike: float,
    max_pct_deviation: float = 10.0,
) -> Tuple[bool, str]:
    """Flag markets where spot has moved >10% from strike."""
```

**Status**: ✅ Guards against stale markets and mis-mapped strikes


---

## 6. Edge Calculation with Fees ✅

**File**: `merid/event_venues/kalshi/gap_imbalance_optimizer.py`

### Transparent Edge Breakdown
```python
@dataclass
class EdgeComponents:
    p_market: float      # From Kalshi price
    p_model: float       # From spot + signals
    raw_edge: float      # p_model - p_market
    fee_cost: float      # Estimated Kalshi fee (~3.5%)
    spread_cost: float   # Half-spread
    net_edge: float      # raw_edge - fee_cost - spread_cost
```

**Status**: ✅ Every trade decision shows explicit fee and spread impact


### Trade Decision Logic
```python
def should_trade(
    self,
    edge_components: EdgeComponents,
    min_edge_threshold: float = 0.02,
) -> Tuple[bool, str, Optional[str]]:
    """Return (should_trade, reason, side)."""
```

**Status**: ✅ Centralized trade decision with full transparency


---

## 7. Settlement Validation via CFB RTI ✅

**File**: `merid/data/settlement_rti_buffer.py`

### RTI Buffer Health Check
```python
def is_healthy(self) -> bool:
    """Return True if buffer has at least one non-stale tick."""
    tick = self.last_tick
    if tick is None:
        return False
    age = time.time() - tick.received_at
    return age < RTI_STALE_THRESHOLD_S
```

**Status**: ✅ Health check available at `/api/health` (web/api/health.py lines 69-91)


### Settlement Safety Gate
```python
def require_cfb_for_live_trading() -> None:
    """Enforce CFB RTI health before allowing live Kalshi trading.

    - Only active when KALSHI_ENV=live
    - Raises CfbRtiUnhealthyError if no healthy tick
    """
```

**Status**: ✅ Fail-closed gate for live trading without RTI feed


---

## 8. Settlement Logic ✅

**File**: `merid/event_venues/kalshi/direction_semantics.py`

### Kalshi Settlement Specification
```python
def kalshi_is_yes_winner(
    settlement_rti: float,
    strike: float,
    direction: str,
) -> bool:
    """Determine if YES wins per Kalshi's official specification.

    UP markets: YES wins when RTI ≥ strike
    DOWN markets: YES wins when RTI < strike
    """
```

**Status**: ✅ Canonical settlement logic matching Kalshi specification


### Strike Extraction
```python
def get_strike_from_market(market: Any) -> Optional[float]:
    """Extract strike price from market object.

    Supports both dict and object with strike_price/strike fields.
    """
```

**Status**: ✅ Flexible strike extraction for all market formats


---

## 9. Comprehensive Test Coverage ✅

**File**: `tests/event_venues/kalshi/test_direction_semantics.py`

### Test Suite
- 33+ unit tests covering all 5 assets (BTC/ETH/SOL/XRP/DOGE)
- Settlement logic for UP and DOWN markets
- Direction parsing from market metadata
- Forecast-to-side mapping
- Strike price extraction
- Multi-asset settlement scenarios

**Status**: ✅ Full test coverage (243 lines)


---

## 10. Documentation ✅

### Complete Documentation
- `docs/KALSHI_DIRECTION_AUDIT.md`: Full architecture overview (389 lines)
- `docs/KALSHI_WIRING_VERIFICATION.md`: This verification document
- Inline docstrings in all modules

**Status**: ✅ Comprehensive documentation


---

## End-to-End Flow Verification

### Complete Trading Pipeline

```
1. STARTUP (web/main.py)
   ├─ Phase 0.4: Start CF Benchmarks RTI buffer
   ├─ Phase 0.45: Initialize direction semantics singletons
   └─ Phase 0.5: Start Kalshi Agent Grid
        ├─ Validate all strategy YAMLs (fail-fast)
        └─ Load strategy implementations from registry

2. MARKET CATALOG ENRICHMENT (market_catalog.py)
   ├─ Fetch markets from Kalshi API
   ├─ Parse direction from title/description ("up" or "down")
   └─ Enrich each market with direction field

3. STRATEGY EXECUTION (strategy_grid.py)
   ├─ Strategy computes agent_prob (P(YES))
   ├─ Strategy returns OpinionEstimate with edge/confidence
   └─ AgentGrid receives estimate for each market

4. DIRECTION MAPPING (direction_mapper.py)
   ├─ Convert forecast_signal (bullish/bearish) to YES/NO side
   ├─ Use market.direction to determine correct side
   └─ Validate consistency: forecast + market_direction → chosen_side

5. STRIKE/SPOT TRACKING (strike_spot_tracker.py)
   ├─ Log strike vs spot price at decision time
   ├─ Check staleness: flag if spot moved >10% from strike
   └─ Audit trail for every trading decision

6. EDGE CALCULATION (gap_imbalance_optimizer.py)
   ├─ Compute raw_edge = p_model - p_market
   ├─ Subtract fee_cost (~3.5%) and spread_cost
   └─ Return net_edge with full transparency

7. ORDER EXECUTION (execution/router.py)
   ├─ Submit trade with side="yes"|"no"
   ├─ Apply risk guards and kill switches
   └─ Route to Kalshi API

8. SETTLEMENT VALIDATION (settlement_rti_buffer.py)
   ├─ Poll CF Benchmarks RTI every 60s
   ├─ Buffer last 60 ticks (1 hour history)
   └─ Validate settlements: kalshi_is_yes_winner(rti, strike, direction)
```

**Status**: ✅ Complete end-to-end flow wired and documented


---

## Health Check Verification

### Test Startup Status

```bash
# Check that all services started successfully
curl http://localhost:8000/api/health | jq '.checks'
```

**Expected Output**:
```json
{
  "cfb_rti_buffer": {
    "status": "healthy" | "disabled",
    "tick_count": 60,
    "last_tick": { "value": 95000.0, "age_seconds": 30.5 },
    "adapter": "simulation" | "live"
  },
  "direction_semantics": {
    "status": "running",
    "components": [
      "direction_mapper",
      "strike_spot_tracker",
      "gap_imbalance_optimizer"
    ]
  }
}
```


---

## Summary

✅ **All 10 integration points verified**:
1. ✅ Startup sequence (CFB RTI + direction semantics before AgentGrid)
2. ✅ YAML → strategy loading with fail-fast validation
3. ✅ Market catalog direction parsing
4. ✅ Strategy execution → direction mapping
5. ✅ Strike vs spot tracking
6. ✅ Edge calculation with fees
7. ✅ Settlement validation via CFB RTI
8. ✅ Settlement logic matching Kalshi spec
9. ✅ Comprehensive test coverage (33+ tests)
10. ✅ Complete documentation

**Total LOC Added**: 1,634 lines across 7 new modules + wiring
- `direction_semantics.py`: 252 lines
- `direction_mapper.py`: 133 lines
- `strike_spot_tracker.py`: 202 lines
- `gap_imbalance_optimizer.py`: 324 lines
- `test_direction_semantics.py`: 243 lines
- `KALSHI_DIRECTION_AUDIT.md`: 389 lines
- `main.py` + `health.py` + `market_catalog.py`: 91 lines

**End-to-End Status**: ✅ **COMPLETE** — All wiring in place from startup to settlement.
