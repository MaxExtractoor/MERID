# Exit Decision Specification

**Version:** 1.0  
**Last Updated:** 2026-07-16  
**Status:** Production

## Overview

This document specifies the exit decision architecture for the Kalshi 15-minute crypto trading system. It defines all possible exit reasons, their precedence order, source layer expectations, and required metadata fields.

## Architecture Components

### ExitDecision DTO
```python
@dataclass
class ExitDecision:
    reason: ExitReason              # Exit reason enum
    priority: ExitPriority         # Priority value (higher = more important)
    source_layer: ExitSourceLayer  # Position-level or Policy-layer
    exit_price_cents: int          # Exit price in cents
    contracts_to_close: Optional[int]  # None = full exit, N = partial
    metadata: dict                 # Context-specific debugging data
```

### ExitSourceLayer Enum
```python
class ExitSourceLayer(str, Enum):
    POSITION_LEVEL = "position_level"  # position_monitor exits
    POLICY_LAYER = "policy_layer"      # ExitPolicy.evaluate() exits
```

## Exit Reason Catalog

### Policy-Layer Exits (ExitPolicy.evaluate())

These exits are evaluated by `ExitPolicy.evaluate()` in strict precedence order:

| Exit Reason | Priority | Description | Emitted By |
|-------------|----------|-------------|------------|
| **RISK** | 100 | Global risk layer kill switch (highest priority) | ExitPolicy.evaluate_risk() |
| **STALE_DATA** | 85 | Market data staleness (P0 safety fix) | ExitPolicy.evaluate_stale_data() |
| **CANDLE_REVERSAL** | 50 | Momentum reversal signal from candle patterns | ExitPolicy.evaluate_candle_reversal() |
| **ADAPTIVE_TIMING** | 45 | Historical performance-based optimal exit timing | ExitPolicy.evaluate_adaptive_timing() |
| **TIME_STOP** | 40 | Volatility-adjusted time-based exit | ExitPolicy.evaluate_time_stop() |
| **EDGE_DECAY** | 35 | Exit when computed edge drops below threshold | ExitPolicy.evaluate_edge_decay() |

### Position-Level Exits (position_monitor._check_position())

These exits are evaluated by `position_monitor._check_position()` before policy-layer evaluation:

| Exit Reason | Priority | Description | Emitted By |
|-------------|----------|-------------|------------|
| **EXTREME_PROFIT** | 90 | Extreme profit threshold (e.g., 99c price) | position_monitor._check_position() |
| **DYNAMIC_TAKE_PROFIT** | 80 | Dynamic take profit based on market conditions | position_monitor._check_position() |
| **RATCHET_FLOOR** | 70 | Ratchet profit floor breach | position_monitor._check_position() |
| **RATCHET_TRIM** | 60 | Ratchet-based partial trim | position_monitor._check_position() |
| **STOP_LOSS** | 55 | Stop loss trigger | position_monitor._check_position() |
| **TAKE_PROFIT** | 50 | Static take profit trigger | position_monitor._check_position() |
| **SCALE_OUT** | 30 | Systematic scale-out (partial exit) | position_monitor._check_position() |
| **TRAIL** | 25 | Trailing stop trigger | position_monitor._check_position() |

### Manual/Admin Exits

| Exit Reason | Priority | Description | Emitted By |
|-------------|----------|-------------|------------|
| **MANUAL** | 20 | Manual/admin-triggered exit | Admin interface |

## Priority Table (Single Source of Truth)

```python
class ExitPriority(int, Enum):
    # Policy-layer exits (highest priority)
    RISK = 100
    EXTREME_PROFIT = 90
    STALE_DATA = 85
    DYNAMIC_TAKE_PROFIT = 80
    RATCHET_FLOOR = 70
    RATCHET_TRIM = 60
    STOP_LOSS = 55
    TAKE_PROFIT = 50
    CANDLE_REVERSAL = 50
    ADAPTIVE_TIMING = 45
    TIME_STOP = 40
    EDGE_DECAY = 35
    SCALE_OUT = 30
    TRAIL = 25
    MANUAL = 20
```

**Precedence Order (highest to lowest):**
1. RISK (100)
2. EXTREME_PROFIT (90)
3. STALE_DATA (85)
4. DYNAMIC_TAKE_PROFIT (80)
5. RATCHET_FLOOR (70)
6. RATCHET_TRIM (60)
7. STOP_LOSS (55)
8. TAKE_PROFIT (50) / CANDLE_REVERSAL (50) - tie, first wins
9. ADAPTIVE_TIMING (45)
10. TIME_STOP (40)
11. EDGE_DECAY (35)
12. SCALE_OUT (30)
13. TRAIL (25)
14. MANUAL (20)

## Source Layer Expectations

### POSITION_LEVEL
- **Emitted by:** `position_monitor._check_position()`
- **Exits:** EXTREME_PROFIT, DYNAMIC_TAKE_PROFIT, RATCHET_FLOOR, RATCHET_TRIM, STOP_LOSS, TAKE_PROFIT, SCALE_OUT, TRAIL
- **Evaluation Order:** Before policy-layer exits
- **Integration:** Creates ExitDecision via `_create_exit_decision()` helper
- **Logging:** `[EXIT-INTENT]` with `source=position_level`

### POLICY_LAYER
- **Emitted by:** `ExitPolicy.evaluate()`
- **Exits:** RISK, STALE_DATA, CANDLE_REVERSAL, ADAPTIVE_TIMING, TIME_STOP, EDGE_DECAY, SCALE_OUT, MANUAL
- **Evaluation Order:** After position-level exits
- **Integration:** Returns ExitDecision directly from `evaluate()`
- **Logging:** `[EXIT-POLICY-RESOLVER]` with `source=policy_layer`

## Required Metadata by Exit Reason

### RISK
```python
metadata = {
    "kill_switch": bool,  # True if risk kill switch enabled
}
```

### STALE_DATA
```python
metadata = {
    "md_age_ms": int,              # Current market data age in milliseconds
    "max_age_ms": int,             # Maximum allowed age in milliseconds
    "time_to_expiry_seconds": float,  # Time to contract expiry
}
```

### CANDLE_REVERSAL
```python
metadata = {
    "candles_count": int,          # Number of candles analyzed
    "pattern_id": str,             # Identified pattern (e.g., "bearish_engulfing")
}
```

### ADAPTIVE_TIMING
```python
metadata = {
    "time_since_entry_seconds": float,  # Time since position entry
    "optimal_exit_time": float,        # Calculated optimal exit time
}
```

### TIME_STOP
```python
metadata = {
    "time_since_entry_seconds": float,  # Time since position entry
    "effective_max_hold": float,       # Volatility-adjusted max hold time
    "r_multiple": float,              # Current R multiple
    "volatility_regime": str,          # Volatility regime (LOW/NORMAL/HIGH/EXTREME)
}
```

### EDGE_DECAY
```python
metadata = {
    "current_edge_pct": float,     # Current edge percentage
    "min_edge_threshold": float,   # Minimum edge threshold
}
```

### EXTREME_PROFIT
```python
metadata = {
    "trigger": str,                # Trigger description (e.g., "extreme_profit_99c")
    "exit_price_cents": int,       # Exit price
}
```

### DYNAMIC_TAKE_PROFIT
```python
metadata = {
    "dynamic_tp_cents": int,       # Dynamic take profit price
    "pnl_cents": int,              # Realized PnL
}
```

### RATCHET_FLOOR
```python
metadata = {
    "ratchet_level_cents": int,    # Current ratchet floor
    "floor_breach_cents": int,     # Floor breach amount
}
```

### RATCHET_TRIM
```python
metadata = {
    "ratchet_level_cents": int,    # Current ratchet level
    "trim_amount_cents": int,      # Trim amount
}
```

### STOP_LOSS
```python
metadata = {
    "stop_loss_cents": int,        # Stop loss price
    "loss_cents": int,             # Loss amount
}
```

### TAKE_PROFIT
```python
metadata = {
    "take_profit_cents": int,      # Take profit price
    "profit_cents": int,           # Profit amount
}
```

### SCALE_OUT
```python
metadata = {
    "scale_out_ratio": float,      # Scale-out ratio (e.g., 0.5 for 50%)
    "remaining_size": int,         # Remaining position size
}
```

### TRAIL
```python
metadata = {
    "trail_price_cents": int,      # Current trailing stop price
    "trail_distance_cents": int,   # Trail distance from high
}
```

### MANUAL
```python
metadata = {
    "admin_user": str,             # Admin user who triggered exit
    "reason_text": str,           # Free-text reason
}
```

## Exit Decision Flow

### 1. Position-Level Evaluation (position_monitor._check_position())
```
position_monitor._check_position()
  ├─ Check EXTREME_PROFIT → create ExitDecision if triggered
  ├─ Check DYNAMIC_TAKE_PROFIT → create ExitDecision if triggered
  ├─ Check RATCHET_FLOOR → create ExitDecision if triggered
  ├─ Check RATCHET_TRIM → create ExitDecision if triggered
  ├─ Check STOP_LOSS → create ExitDecision if triggered
  ├─ Check TAKE_PROFIT → create ExitDecision if triggered
  ├─ Check SCALE_OUT → create ExitDecision if triggered
  └─ Check TRAIL → create ExitDecision if triggered
```

### 2. Policy-Level Evaluation (ExitPolicy.evaluate())
```
ExitPolicy.evaluate()
  ├─ evaluate_risk() → RISK (priority 100)
  ├─ evaluate_stale_data() → STALE_DATA (priority 85)
  ├─ evaluate_candle_reversal() → CANDLE_REVERSAL (priority 50)
  ├─ evaluate_adaptive_timing() → ADAPTIVE_TIMING (priority 45)
  ├─ evaluate_time_stop() → TIME_STOP (priority 40)
  └─ evaluate_edge_decay() → EDGE_DECAY (priority 35)
```

### 3. Exit Resolution (ExitResolver.resolve())
```
ExitResolver.resolve([position_decisions, policy_decision])
  ├─ Sort all decisions by priority (highest first)
  ├─ Select highest priority decision as winner
  ├─ Log all candidate decisions and winner
  └─ Record decision history
```

## Logging Schema

### EXIT-INTENT (position_monitor)
```
[EXIT-INTENT] position=%s market=%s side=%s reason=%s priority=%d source=%s 
exit_price=%dc entry_price=%dc pnl=%dc R=%.2f size=%d type=FULL_EXIT|PARTIAL_EXIT
```

### EXIT-POLICY-RESOLVER (exit_policy_resolver)
```
[EXIT-POLICY-RESOLVER] position=%s reason=%s priority=%d source=%s R=%.2f metadata=%s
```

### EXIT-RESOLVER (exit_resolver)
```
[EXIT-RESOLVER] position=%s reason=%s priority=%d source=%s from [%s]
```

### STALE_DATA Special Logging
```
[EXIT-RESOLVER] STALE_DATA exit: position=%s md_age_ms=%s max_age_ms=%s 
time_to_expiry=%s metadata=%s
```

## Integration Points

### position_monitor.py
- **Method:** `_create_exit_decision(position, exit_reason, exit_price_cents, contracts_to_close, metadata)`
- **Purpose:** Create ExitDecision for position-level exits
- **Usage:** Called before emitting exit intent

### exit_policy.py
- **Method:** `evaluate(current_edge_pct, candles, md_age_ms, max_age_ms) -> Optional[ExitDecision]`
- **Purpose:** Evaluate policy-layer exits and return ExitDecision
- **Usage:** Called by exit_policy_resolver

### exit_policy_resolver.py
- **Method:** `resolve_with_decision(...) -> Optional[ExitDecision]`
- **Purpose:** New method that returns ExitDecision directly
- **Usage:** Preferred method for getting ExitDecision from policy

### exit_resolver.py
- **Method:** `resolve(decisions: List[ExitDecision], position_id) -> Optional[ExitDecision]`
- **Purpose:** Merge multiple ExitDecision objects and select winner
- **Usage:** Central exit decision arbiter

## Testing Requirements

### Unit Tests
- **test_exit_policy.py:** 38 tests for ExitPolicy.evaluate() with ExitDecision
- **test_exit_resolver.py:** 17 tests for ExitResolver decision merging
- **test_exit_lifecycle.py:** 11 tests for end-to-end integration

### Integration Tests
- Position-level exit → policy-level exit → resolver flow
- Metadata preservation through pipeline
- Precedence order enforcement
- Partial vs full exit handling

### Log Schema Tests
- Verify log format includes required fields
- Verify STALE_DATA special logging with MD age/SLA
- Verify resolver logs all candidate decisions

## Kalshi 15-Minute Market Alignment

### Price Range
- **Canonical Range:** 10-75 cents
- **Exit Price Validation:** `exit_price_cents` must be within 10-75c range
- **Kalshi Mid/Last Price:** Use Kalshi mid-price for exit execution

### Position Sizing
- **Global Cap:** $1.00 fixed exposure cap (MERID_FIXED_EXPOSURE_CAP_USD)
- **Per Asset:** Maximum 1 contract per asset (BTC, ETH, SOL, XRP, DOGE)
- **Exit Validation:** `contracts_to_close` must respect position sizing rules

### Time Alignment
- **Market Duration:** 15 minutes per market
- **Exit Timing:** Exits should occur with sufficient time for order execution
- **STALE_DATA Threshold:** Configured based on 15m market data refresh rate

## Version History

### v1.0 (2026-07-16)
- Initial specification
- Defined ExitDecision DTO architecture
- Documented all exit reasons and priorities
- Specified metadata requirements
- Added logging schema
- Included Kalshi 15m market alignment notes

## References

- **Exit Decision Implementation:** `merid/position_management/exit_decision.py`
- **Exit Policy:** `merid/position_management/exit_policy.py`
- **Exit Resolver:** `merid/position_management/exit_resolver.py`
- **Position Monitor:** `merid/position_management/position_monitor.py`
- **Log Queries:** `docs/EXIT_LOG_QUERIES.md`
- **Test Suite:** `tests/position_management/test_exit_*.py`
