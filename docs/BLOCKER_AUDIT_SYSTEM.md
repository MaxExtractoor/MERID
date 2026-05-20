# Blocker Audit System — Implementation Summary

## Overview

This document describes the systematic blocker audit system implemented for MERID to differentiate legitimate trade blocks (risk/execution guards doing their job) from "fake" blocks (bugs, miswiring, or legacy code).

## Architecture

### 1. Canonical BlockReason Enum

**File:** `merid/guards/block_reasons.py`

Defines the ONLY allowed reasons an order can be blocked. Any block not using one of these reasons is considered a bug or legacy code.

**Categories:**
- **RISK_LIMITS**: Hard risk controls (bankroll, exposure, drawdown)
  - `BANKROLL_CAP`, `DAILY_LOSS_LIMIT`, `POSITION_LIMIT`, `ASSET_EXPOSURE_CAP`, `CATEGORY_EXPOSURE_CAP`, `VENUE_EXPOSURE_CAP`, `DOMAIN_DAILY_CAP`, `DRAWDOWN_GUARD`

- **STRATEGY_FILTERS**: Signal quality and strategy logic
  - `MIN_EDGE_THRESHOLD`, `MIN_CONFIDENCE_THRESHOLD`, `MARKET_REGIME_GATE`, `SENTIMENT_NOTIONAL_CAP`, `CQI_THROTTLE`, `PROMOTION_INELIGIBLE`

- **VENUE_CONSTRAINTS**: Market/venue-specific rules
  - `MARKET_CLOSED`, `INVALID_TICKER`, `MAX_ORDER_SIZE`, `PRICE_BAND_VIOLATION`, `DEEP_OTM_REJECT`, `DEEP_ITM_REJECT`, `MODEL_PROB_DISTANCE`, `SETTLEMENT_GUARD`, `EXPIRY_TOO_CLOSE`

- **SYSTEM_STATE**: Global system state
  - `KILL_SWITCH`, `TRADING_MODE_GATE`, `EXECUTION_GATE_BLOCKED`, `EXECUTION_GATE_LIMITED`, `RECONCILIATION_BLOCKED`, `LOOP_LAG_HALT`, `DEPENDENCY_HEALTH`

- **DATA_INTEGRITY**: Data validation failures
  - `MISSING_PRICE`, `STALE_PRICE`, `MISSING_MARKET_DATA`, `INVALID_ORDER_PARAMS`, `SNAPSHOT_STALE`, `DATA_VERSION_MISMATCH`

- **INTERNAL_ERROR**: Should not happen in production
  - `INTERNAL_ERROR`, `INFRASTRUCTURE_UNAVAILABLE`

### 2. OrderStage Enum

Defines stages in the order lifecycle where blocking can occur:
- `SIGNAL_GENERATION`, `SIGNAL_TO_INTENT`, `STRATEGY_FILTER`, `RISK_GATE`, `EXECUTION_GATE`, `PRE_TRADE_GATE`, `ROUTER_VALIDATION`, `VENUE_SUBMISSION`

### 3. Structured Logging

**Function:** `log_block_event()`

Logs a structured block event with:
- `order_id`, `stage`, `reason` (canonical BlockReason)
- Context: `asset`, `timeframe`, `side`, `action`, `edge_pct`, `confidence`
- Details: arbitrary dict for additional context
- Caller info: `caller_module`, `agent_id`

Emits Prometheus counter: `merid_orders_blocked_total` with labels: `stage`, `reason`, `asset`

### 4. Order Router Instrumentation

**File:** `merid/event_venues/kalshi/order_router.py`

Added:
- Import of canonical block reasons module
- `_map_legacy_reason_to_canonical()` - maps legacy reason strings to canonical enum
- `_log_structured_block()` - wrapper for logging block events
- Instrumented key blocking functions:
  - `_check_intent_risk()` - validates order parameters
  - `_validate_price_band()` - checks 50¢ band with edge/confidence
  - `_check_bankroll_risk_cap()` - enforces bankroll limits

## Scripts

### 1. Blocker Audit Script

**File:** `scripts/blocker_audit.py`

Scans log files for blocked order events and generates a report:
- Groups blocks by `block_reason` and `stage`
- Flags non-canonical reasons
- Flags blocks from unexpected code paths
- Can scan codebase for blocking patterns

**Usage:**
```bash
python scripts/blocker_audit.py --logs-path data/logs/ --days 7
python scripts/blocker_audit.py --json > blocker_audit_report.json
python scripts/blocker_audit.py --scan-codebase
```

### 2. CI Blocker Audit

**File:** `scripts/ci_blocker_audit.py`

Runs as part of CI to ensure:
- All block reasons use canonical BlockReason enum
- No direct venue calls outside order_router
- No silent blocking patterns (return without logging)
- All order lifecycle stages use OrderStage enum

**Exit codes:**
- `0`: All checks passed
- `1`: Critical or non-critical violations found

**Usage:**
```bash
python scripts/ci_blocker_audit.py
```

## Tests

**File:** `tests/test_block_reasons.py`

Comprehensive test coverage:
- `TestBlockReasonEnum`: Validates enum completeness and categorization
- `TestOrderStageEnum`: Validates stage definitions and logical ordering
- `TestBlockEvent`: Tests event creation and serialization
- `TestLogBlockEvent`: Tests logging function
- `TestValidationHelpers`: Tests helper functions
- `TestCanonicalConstants`: Validates constant sets
- `TestIntegrationScenarios`: Tests common blocking scenarios

**Run tests:**
```bash
python -m pytest tests/test_block_reasons.py -v
```

## CI Integration

**File:** `.github/workflows/ci.yml`

Added blocker audit check to `kalshi-deployment-safety` job:
```yaml
- name: Run blocker audit check
  run: |
    python scripts/ci_blocker_audit.py
```

This runs on every push to main/develop and on PRs to main.

## Migration Strategy

### Phase 1: Infrastructure (✅ Complete)
- Define canonical BlockReason enum
- Add structured logging infrastructure
- Instrument key blocking points in order_router.py
- Add Prometheus metrics
- Build audit scripts
- Add CI checks
- Add unit tests

### Phase 2: Codebase Sweep (✅ Complete)
- CI scan identifies non-canonical block patterns
- Audit script analyzes logs for non-canonical reasons
- No critical violations found in current codebase

### Phase 3: Legacy Refactoring (⏳ Ongoing)
- Map legacy reason strings to canonical enum
- Refactor silent blocks to use structured logging
- Ensure all order paths route through canonical router
- Incremental migration as code is touched

## Usage Examples

### Blocking an Order with Canonical Reason

```python
from merid.guards.block_reasons import BlockReason, OrderStage, log_block_event

# In your blocking logic
if effective_equity_usd is None or effective_equity_usd <= 0:
    log_block_event(
        order_id=intent.intent_id,
        stage=OrderStage.RISK_GATE,
        reason=BlockReason.BANKROLL_CAP,
        asset=asset,
        details={"effective_equity_usd": effective_equity_usd}
    )
    return OrderResult(status="rejected", reason="bankroll_unavailable...")
```

### Running Audit

```bash
# Scan logs for last 7 days
python scripts/blocker_audit.py --logs-path data/logs/ --days 7

# Scan codebase for blocking patterns
python scripts/blocker_audit.py --scan-codebase

# Get JSON output for automation
python scripts/blocker_audit.py --json > report.json
```

## Benefits

1. **Observability**: Every block is logged with structured data, making it easy to analyze why trades aren't happening.

2. **Audit Trail**: Canonical reasons provide a clear separation between "by design" blocks and suspicious blocks.

3. **CI Enforcement**: Automated checks prevent introduction of new non-canonical blocking patterns.

4. **Metrics**: Prometheus counters enable monitoring of block rates by reason, stage, and asset.

5. **Gradual Migration**: Legacy reason mapping allows incremental migration without breaking existing code.

## Next Steps

1. **Incremental Refactoring**: As code is touched, migrate legacy block patterns to use canonical reasons.

2. **Monitoring**: Set up Prometheus alerts for unusual block rates or non-canonical reasons.

3. **Documentation**: Add block reason documentation to operator dashboard.

4. **Expansion**: Add canonical reasons for new blocking scenarios as they emerge.

## References

- Industry best practices: [FIA Best Practices for Automated Trading Risk Controls](https://www.fia.org/fia/articles/fia-releases-best-practices-automated-trading-risk-controls-and-system-safeguards)
- OMS gatekeeper patterns: Centralized pre-trade risk controls
- Related work: Single-executor enforcement, magic number elimination
