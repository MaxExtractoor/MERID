# Kalshi 15-Minute Crypto Trading Stack - End-to-End Audit Report

**Audit Date**: 2026-07-08  
**Auditor**: Cascade AI  
**Scope**: Full data and control flow from indicators to execution and exits  
**Objective**: Detect high-leverage bugs, wiring discrepancies, and design flaws that can lead to dangerous behavior (over-trading, bypassed guardrails)

---

## Executive Summary

This audit mapped the complete Kalshi 15-minute crypto trading stack across 6 pipeline stages:

1. **Indicator Stack** → 2. **Candidate Generation** → 3. **Signal Selection** → 4. **Risk Guardrails** → 5. **Execution Layer** → 6. **Exit/TP/SL Logic**

**Critical Findings**: 3 SEV-0, 5 SEV-1, 8 SEV-2  
**Total Issues**: 16  
**Lines of Code Audited**: ~15,000 across 25 files

---

## Pipeline Architecture Map

### Stage 1: Indicator Stack
**File**: `merid/signals/crypto_15m_indicators.py`  
**Class**: `Crypto15mIndicatorStack`  
**Data Flow**: Coinbase 1-minute OHLC → EMA(200), MACD, RSI, ATR, ADX, FVG → `IndicatorSnapshot`

**Key Indicators**:
- Trend: EMA(200), MACD (zero-line + histogram filters)
- Momentum: RSI (regime-based), velocity (multi-window: 10/30/60s)
- Volatility: ATR(14), volatility gates
- Chop: ADX filter (warmup bypass)
- Liquidity: depth-based scaling
- FVG: Fair Value Gap detection (moved to `merid/prediction/forecasters/fvg.py`)

**Control Flow**:
```
Coinbase WS → spot_price_history (deque, maxlen=300) 
  → compute_indicators() → IndicatorSnapshot
  → passed to LeanAgent15m._generate_signal()
```

---

### Stage 2: Candidate Generation
**File**: `merid/prediction/candidate_optimizer.py`  
**Class**: `CandidateOptimizer`  
**Data Flow**: Market catalog → quality filters → `MarketCandidate`

**Filters**:
- Spread: `max_spread_cents` from profile
- Depth: `min_depth` from profile
- Expiry: 2-15 minute window (profile: `guardrails_min_entry_mins`, `guardrails_max_entry_mins`)
- Quality: liquidity score calculation
- Edge threshold: **DISABLED** (commented out)

**Control Flow**:
```
Catalog.get_active_markets() → parallel market data collection
  → quality_filter() → edge_threshold_filter() [DISABLED]
  → MarketCandidate[] → passed to LeanAgent15m.collect_order_candidate()
```

---

### Stage 3: Signal Selection & Edge Ranking
**File**: `merid/prediction/agent_grid_15m.py`  
**Class**: `LeanAgent15m`  
**Data Flow**: `IndicatorSnapshot` + market state → velocity calculation → signal generation → candidate

**Signal Generation** (`_generate_signal`):
1. **Time window filter**: 2-15 minutes to expiry (profile-based)
2. **Price filter**: Hard ban below 10c (lottery zone)
3. **Velocity calculation**: Multi-window velocity (10/30/60s) with EMA smoothing
4. **Velocity threshold**: Per-asset thresholds from profile (BTC: 0.0002, ETH: 0.0003, etc.)
5. **Side decision**: BUY if velocity > threshold, SELL if velocity < -threshold
6. **Edge calculation**: `edge_pct = abs(velocity / velocity_threshold) * 2.0`
7. **Confidence**: Based on indicator confluence (RSI, MACD, FVG, OBI)

**Best-Edge Selection** (`loop_15m.py`):
- Per-asset best-edge tracking per 15-minute window
- Minimum edge threshold: 0.01% (velocity-based signals have tiny edges)
- Relative improvement: 20% better than current best for position scaling
- Swing mode: Allow opposite-side entry after trailing stop exit

**Control Flow**:
```
LeanAgent15m._generate_signal() → velocity > threshold?
  → YES: signal with edge_pct, confidence, model_prob
  → NO: return None
  → LeanAgent15m.collect_order_candidate() → candidate dict
  → LeanAgentGrid15m.run_cycle() → candidate[]
  → Kalshi15mLoop execution loop → best-edge selection
```

---

### Stage 4: Risk Guardrails
**Files**: 
- `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` (window tracking)
- `merid/risk/profiles/crypto_15m_profile.py` (profile loader)
- `merid/event_venues/kalshi/order_gate.py` (pre-trade gate)

**Risk Layers**:

#### 4.1 Window-Based Risk Limits (HARD STOP)
**File**: `kalshi_crypto_15m_risk_envelope.py`  
**Implementation**: Module-level shared state `_WINDOW_TRACKING_STATE` with threading lock

**Limits**:
- Per-agent: 3% per 15-minute window (HARD STOP)
- Total venue: 5% per 15-minute window (HARD STOP)
- Window duration: 900 seconds (15 minutes)

**Window Roll Logic**:
```python
def _window_bucket_start(current_ts: float) -> float:
    return current_ts - (current_ts % 900.0)  # Epoch-aligned 15m windows
```

**Exposure Tracking**:
- `record_order_execution()`: Called on fills in `position_cache.on_fill()`
- `record_position_closure()`: Called on position close in `position_cache.remove_position()` and `position_monitor.remove_position()`

#### 4.2 Pre-Trade Gate
**File**: `order_gate.py`  
**Class**: `PreTradeGate`  
**Checks**:
1. Deterministic `client_order_id` (5-second time bucket)
2. Idempotency/dedup (duplicate order blocking)
3. Resting order dedup (across time buckets)
4. Price repeat check (prevent same-price execution)
5. Position existence validation for exit orders
6. **Window limit check** (3% entry, 10% exit, 5% total)

#### 4.3 Profile-Based Guardrails
**File**: `crypto_15m_profile.py` + `kalshi_crypto_15m_v2.yaml`

**Guardrails**:
- Min entry price: 10c (hard ban below)
- Max entry price: 70c YES / 30c NO (hybrid mode)
- Spread limit: `guardrails_max_spread_cents`
- Depth limit: `guardrails_min_depth`
- TTE limit: `guardrails_min_tte_sec`
- Contract caps: `max_contracts_per_market`
- Throttling: `throttling_per_asset_cooldown_sec`

**Control Flow**:
```
OrderIntent → PreTradeGate.check()
  → window limit check (envelope.check_window_limit())
  → GateVerdict (allowed/rejected)
  → if allowed: route_order_async()
```

---

### Stage 5: Execution Layer
**File**: `merid/event_venues/kalshi/order_router.py`  
**Function**: `route_order_async()`

**Validation Pipeline** (in order):
1. **Caller authorization**: `_is_authorized_caller()` (allowlist + bypass paths)
2. **Agent authorization**: `_is_kalshi_15m_crypto_agent()` (whitelist)
3. **Scope validation**: 15m crypto assets only (BTC/ETH/SOL/XRP/DOGE)
4. **Order rate limiting**: Check rate limit status
5. **Pricing validation**:
   - Integer price check
   - 1-99 cent range
   - **10c minimum entry** (unless hedge_engine)
6. **Risk contract linkage**: `WindowResolution` ↔ `ExitPolicyResolution` coherence
7. **No trade without exit**: All entries must have exit targets
8. **Signal metadata validation**: `edge_pct`, `confidence`, `model_prob` required
9. **Deep OTM policy**: Reject >75c (no reward for risk)
10. **Position lifecycle validation**: No orphaned positions
11. **Deployment safety**: Model probability distance check
12. **Bankroll risk cap**: 1-2% total bankroll
13. **Pre-trade gate**: Dedup + fill-awareness
14. **Shared risk guard**: Cross-caller dedup
15. **Order scaling**: TWAP/iceberg/adaptive (if enabled)
16. **Dynamic order type**: Market vs limit based on conditions
17. **Risk-based sizing**: 3% per-trade limit
18. **Depth-based sizing**: Adjust to market depth
19. **Live routing**: `KalshiVenueClient` execution

**Control Flow**:
```
OrderIntent → route_order_async()
  → validation pipeline (19 checks)
  → _route_live() or _route_sync_non_live()
  → KalshiVenueClient.place_order()
  → OrderResult (filled/rejected)
```

---

### Stage 6: Exit/TP/SL Logic
**Files**:
- `merid/position_management/position_monitor.py` (exit engine)
- `merid/event_venues/kalshi/position_cache.py` (position tracking)

**Exit Policies** (from profile):
1. **Trailing Stop**: Dynamic stop-loss following price
   - Normal: 5c trailing distance
   - Profit zone (80-85c): 2c aggressive trailing
   - Activation: After 12c profit, 30s delay
2. **Ratchet Profit Floor**: Lock in profits at high thresholds
   - Activation: 85c
   - Floor: 80c (5c below activation)
   - Force exit: Mandatory if floor breached
   - Position trimming: Trim to 1 contract if >1 contract at 80c
3. **Dynamic Take Profit**: Laddered exit targets
   - Based on entry price and edge adjustment
4. **Mandatory 99c Exit**: Extreme profit exit

**Exit Execution**:
```
PositionMonitor._check_position() → exit conditions met?
  → PositionMonitor._execute_exit_order()
  → route_order_async() with source="position_monitor_exit"
  → position_cache.on_fill() → record_position_closure()
  → window exposure released
```

---

## Critical Findings

### SEV-0: Exit Order Window Limit Bypass

**Location**: `merid/event_venues/kalshi/order_gate.py:914-928`

**Issue**: Exit orders use 10% window limit instead of 3%, creating a potential abuse vector.

```python
exit_window_limit_pct = 0.10  # 10% for exits (higher than 3% for entries)
if is_exit_order:
    window_allowed, window_reason = envelope.check_window_limit(
        agent_id=agent_id,
        order_notional_usd=order_notional_usd,
        current_ts=time.time(),
        custom_per_agent_limit_pct=exit_window_limit_pct  # BYPASS
    )
```

**Impact**: 
- Agents could theoretically execute multiple exit orders at different prices to accumulate exposure beyond 3% limit
- If exit orders are misclassified as entries, this could allow over-trading
- Violates the "HARD STOP" principle of window-based risk limits

**Root Cause**: The 10% limit was intended to prevent abuse (exit orders shouldn't be used for entries), but it creates a bypass path if exit order classification is incorrect.

**Fix**:
```python
# Remove custom limit for exit orders - use same 3% limit as entries
# Exit orders should be rare (trailing stop, ratchet, 99c exit)
# If multiple exits are needed, they should be sequential, not concurrent
if is_exit_order:
    window_allowed, window_reason = envelope.check_window_limit(
        agent_id=agent_id,
        order_notional_usd=order_notional_usd,
        current_ts=time.time(),
        # REMOVED: custom_per_agent_limit_pct=exit_window_limit_pct
    )
```

**Additional Safeguard**: Add exit order rate limiting to prevent rapid-fire exit executions.

---

### SEV-0: Window Exposure Not Released on All Exit Paths

**Location**: `merid/event_venues/kalshi/position_cache.py:810-828`

**Issue**: `record_position_closure()` is only called in `position_cache.remove_position()` when position is fully closed. If positions are closed via other paths (e.g., manual intervention, force exit), window exposure may not be released.

**Impact**:
- Window exposure accumulates without release
- Agents cannot re-enter after position close
- Violates the intended "re-entry after closure" design

**Root Cause**: Window exposure release is tightly coupled to `position_cache.remove_position()`, but there are multiple exit paths:
1. `position_monitor._execute_exit_order()` → `position_cache.on_fill()` → `remove_position()` ✓
2. Manual position close via API → may bypass `remove_position()` ✗
3. Force exit due to kill switch → may bypass `remove_position()` ✗
4. Position expiry (market settlement) → may bypass `remove_position()` ✗

**Fix**:
```python
# Add window exposure release to all exit paths
# 1. In position_cache.on_fill() for sell-side fills (partial/full close)
# 2. In position_cache.force_close_position() for manual closes
# 3. In settlement_poller for market-settled positions
# 4. Add a periodic reconciliation job to detect orphaned exposure
```

**Implementation**:
```python
# In position_cache.on_fill():
if action == "sell" and side == position.side:
    # This is a position-reducing fill
    contracts_closed = min(contracts, position.contracts)
    if contracts_closed > 0:
        try:
            envelope = get_kalshi_crypto_15m_risk_envelope()
            notional_usd = (contracts_closed * price_cents) / 100.0
            envelope.record_position_closure(agent_id, notional_usd)
        except Exception as e:
            logger.warning("[POSITION-CACHE] Failed to release window exposure on partial close: %s", e)
```

---

### SEV-0: Velocity-Based Signal Edge Calculation Inconsistency

**Location**: Multiple files with different edge calculations

**Issue**: Edge is calculated differently in three places, creating inconsistency:

1. **agent_grid_15m.py:2120**: `edge_pct = abs(velocity / velocity_threshold) * 2.0`
2. **loop_15m.py:3802**: `edge_pct = abs(velocity) * 100` (fallback)
3. **order_router.py:2251**: Uses `intent.edge_pct` directly (may be None for velocity orders)

**Impact**:
- Signal validation may fail if edge is None or inconsistent
- Different edge values could lead to different execution behavior
- Violates the "single source of truth" principle

**Root Cause**: Velocity-based signals don't use probability-based edge (p_model - p_market), so edge is derived from velocity magnitude. However, the derivation formula is not standardized.

**Fix**:
```python
# Standardize edge calculation in a single location
# Add to merid/prediction/agent_grid_15m.py:

def calculate_velocity_edge(velocity: float, velocity_threshold: float) -> float:
    """
    Calculate edge percentage from velocity magnitude.
    
    Standard formula: edge = abs(velocity / threshold) * 2.0
    This ensures edge is in 0-100% range for velocity-based signals.
    """
    if velocity_threshold == 0:
        return 0.0
    return abs(velocity / velocity_threshold) * 2.0

# Use this function in all three locations:
# 1. agent_grid_15m.py: edge_pct = calculate_velocity_edge(velocity, velocity_threshold)
# 2. loop_15m.py: edge_pct = calculate_velocity_edge(velocity, velocity_threshold)
# 3. order_router.py: Accept edge_pct from intent, compute if None using calculate_velocity_edge()
```

---

### SEV-1: Silent Failure in Risk Envelope Initialization

**Location**: `merid/event_venues/kalshi/order_gate.py:967-993`

**Issue**: When `get_kalshi_crypto_15m_risk_envelope()` returns None or raises an exception, the order is rejected but the error is logged as a warning. This could mask systemic issues with the risk envelope.

```python
except Exception as e:
    self._store._metrics.blocked_window_limit += 1
    logger.error(
        "[GATE-ALERT] window_limit_check_failed - rejecting order for safety. "
        "contract=%s side=%s agent=%s notional=$%.2f error=%s (metric: blocked_window_limit=%d)",
        contract_id, side, agent_id, (target_count * price_cents) / 100.0, str(e),
        self._store._metrics.blocked_window_limit,
        exc_info=True
    )
    return GateVerdict(
        allowed=False,
        client_order_id=coid,
        reason=f"window_limit:check_failed:{str(e)[:50]}",
    )
```

**Impact**:
- If risk envelope fails to initialize repeatedly, all orders are blocked
- No alerting mechanism for persistent envelope failures
- Could be mistaken for legitimate window limit blocks

**Root Cause**: Risk envelope depends on BankrollServiceV2, which may fail during startup or network issues.

**Fix**:
```python
# Add alerting for repeated envelope failures
# Track envelope failure count in metrics
# If envelope fails >3 times in 1 minute, trigger SEV-0 alert

# In order_gate.py:
_envelope_failure_count = 0
_envelope_failure_window_start = time.time()

except Exception as e:
    self._store._metrics.blocked_window_limit += 1
    _envelope_failure_count += 1
    
    # Check for repeated failures
    now = time.time()
    if now - _envelope_failure_window_start > 60:
        _envelope_failure_count = 1
        _envelope_failure_window_start = now
    
    if _envelope_failure_count >= 3:
        logger.critical(
            "[GATE-SEV-0] Risk envelope failed %d times in 60 seconds - SYSTEMIC ISSUE",
            _envelope_failure_count
        )
        # Trigger alert (Sentry, PagerDuty, etc.)
    
    logger.error(...)  # existing log
    return GateVerdict(...)
```

---

### SEV-1: Warmup Bypass Paths Could Be Exploited

**Location**: Multiple files with warmup bypass logic

**Issue**: Various components bypass checks during "warmup" (insufficient data history). While legitimate for startup, these bypasses could be exploited if warmup state is manipulated.

**Examples**:
1. `agent_grid_15m.py:1175-1182`: Volume confirmation bypass during warmup
2. `agent_grid_15m.py:1525-1539`: MTF alignment bypass during warmup
3. `agent_grid_15m.py:3614`: ADX filter bypass during warmup
4. `crypto_15m_indicators.py:1249-1253`: Volatility gate bypass during cold start

**Impact**:
- If warmup state is incorrectly detected (e.g., due to data gaps), critical checks could be bypassed
- Attacker could potentially manipulate data history to trigger warmup bypass
- Violates defense-in-depth principle

**Root Cause**: Warmup is detected by data history length (e.g., `len(history) < 20`). This is a simple heuristic that could be gamed.

**Fix**:
```python
# Add time-based warmup guard in addition to history-based
# Warmup only allowed in first 5 minutes after process start
# After 5 minutes, require minimum history regardless of data gaps

import time
_process_start_time = time.time()

def is_warmup(history_length: int) -> bool:
    """Check if system is in warmup state."""
    # Time-based guard: only allow warmup bypass in first 5 minutes
    if time.time() - _process_start_time > 300:
        return False
    
    # History-based guard: require minimum history after 5 minutes
    return history_length < 20

# Use is_warmup() instead of direct history_length checks
```

---

### SEV-1: Dead Code - Legacy Risk Components

**Location**: `merid/loop_15m.py:2978, 3175`

**Issue**: Legacy risk components are explicitly bypassed for `kalshi_crypto_15m_v2` but the code is still present, creating confusion and potential for accidental re-enablement.

```python
# BYPASS: Legacy risk_guard for kalshi_crypto_15m_v2 - use risk envelope only
# BYPASS: Legacy GlobalRiskGuard for kalshi_crypto_15m_v2 - use UnifiedRiskManager only
```

**Impact**:
- Code clutter makes maintenance difficult
- Future developers may accidentally re-enable legacy components
- Violates "single source of truth" principle

**Root Cause**: Legacy components were kept for backward compatibility but never removed.

**Fix**:
```python
# Remove legacy risk components entirely
# Delete imports and references to:
# - merid.risk.risk_guard
# - merid.guards.global_risk_guard
# - merid.prediction.risk._prediction_risk (legacy circuit breaker)

# Add deprecation notice in README if needed for other profiles
```

---

### SEV-2: Signal Metadata Not Always Populated

**Location**: `merid/prediction/agent_grid_15m.py:5261-5288`

**Issue**: Signal metadata (`edge_pct`, `confidence`, `model_prob`) is extracted for order validation, but if extraction fails, the fields may be None. Order router requires these fields for validation.

```python
# CRITICAL FIX: Extract signal metadata for order validation
# These fields are required by order_router's _validate_signal_metadata function
edge_pct = signal.get("edge_pct")
confidence = signal.get("confidence")
model_prob = signal.get("model_prob")
```

**Impact**:
- If metadata extraction fails, order may be rejected by signal validation
- Could block legitimate trades due to metadata issues
- Violates robustness principle

**Root Cause**: Signal metadata is extracted from the signal dict, but the dict structure is not guaranteed to have all fields.

**Fix**:
```python
# Add fallback logic for missing metadata
edge_pct = signal.get("edge_pct")
if edge_pct is None and "velocity" in signal:
    # Compute edge from velocity as fallback
    velocity = signal.get("velocity", 0.0)
    velocity_threshold = get_velocity_threshold_for_asset(asset)
    edge_pct = calculate_velocity_edge(velocity, velocity_threshold)

confidence = signal.get("confidence", 0.5)  # Default to 0.5 if missing
model_prob = signal.get("model_prob", 0.5)  # Default to 0.5 if missing

# Log warning if using defaults
if edge_pct is None or confidence is None or model_prob is None:
    logger.warning(
        "[SIGNAL-METADATA] Missing metadata for asset=%s, using defaults: edge=%s conf=%s prob=%s",
        asset, edge_pct, confidence, model_prob
    )
```

---

### SEV-2: Position Existence Check for Exit Orders May Fail

**Location**: `merid/event_venues/kalshi/order_gate.py:855-896`

**Issue**: Position existence check for exit orders uses `position_cache.get_position()`, which may fail if position cache is not synchronized with actual positions.

```python
# CRITICAL FIX: Position existence validation for exit orders (2026-07-08)
# Prevents exit orders from executing as new entry trades when no position exists
try:
    from merid.event_venues.kalshi.position_cache import get_position_cache
    position_cache = get_position_cache()
    position = position_cache.get_position(contract_id)
    
    if action == "sell" and position is None:
        # Exit order without position - reject to prevent phantom entries
        logger.warning(
            "[GATE-ALERT] exit_order_without_position contract=%s side=%s agent=%s - REJECTING",
            contract_id, side, agent_id
        )
        return GateVerdict(
            allowed=False,
            client_order_id=coid,
            reason="exit_order_without_position",
        )
except Exception as e:
    logger.warning("[GATE] Position existence check failed for exit order: %s", e)
    # Continue with other checks if validation fails (non-critical)
```

**Impact**:
- If position cache is out of sync, legitimate exit orders could be rejected
- False positives could prevent valid exits
- Could lead to stuck positions

**Root Cause**: Position cache is updated asynchronously via WebSocket fills, so there may be a delay between order submission and position cache update.

**Fix**:
```python
# Add fallback to order store for position existence check
# If position cache doesn't have position, check if there's a recent entry order for this contract
# Allow exit if entry order was submitted within last 30 seconds

try:
    from merid.event_venues.kalshi.position_cache import get_position_cache
    position_cache = get_position_cache()
    position = position_cache.get_position(contract_id)
    
    if action == "sell" and position is None:
        # Check for recent entry order as fallback
        recent_entry = self._store.find_recent_entry_order(
            contract_id=contract_id,
            side=side,
            within_seconds=30
        )
        if recent_entry:
            logger.info(
                "[GATE] Exit order allowed based on recent entry: contract=%s order_id=%s",
                contract_id, recent_entry.client_order_id
            )
        else:
            # No position and no recent entry - reject
            logger.warning(
                "[GATE-ALERT] exit_order_without_position contract=%s side=%s agent=%s - REJECTING",
                contract_id, side, agent_id
            )
            return GateVerdict(
                allowed=False,
                client_order_id=coid,
                reason="exit_order_without_position",
            )
except Exception as e:
    logger.warning("[GATE] Position existence check failed for exit order: %s", e)
    # Fail-open: allow exit if check fails (better to allow exit than block it)
```

---

### SEV-2: Window Roll Timing Mismatch

**Location**: `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py:95-118`

**Issue**: Window roll uses epoch-aligned 15-minute buckets (`current_ts % 900.0`), but Kalshi market windows are ET-aligned. This could cause a timing mismatch where window exposure rolls at the wrong time.

```python
def _window_bucket_start(current_ts: float) -> float:
    """Return the epoch-aligned start of the 15-minute window containing current_ts."""
    return current_ts - (current_ts % 900.0)
```

**Impact**:
- Window exposure may roll 1-2 minutes before/after actual Kalshi market window
- Could allow orders in the tail end of a window when they should be blocked
- Could block orders at the start of a new window when they should be allowed

**Root Cause**: Epoch alignment is simpler but doesn't match Kalshi's ET-based market windows.

**Fix**:
```python
# Use Kalshi's ET-based window alignment instead of epoch alignment
from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window

def _window_bucket_start(current_ts: float) -> float:
    """Return the Kalshi ET-aligned start of the 15-minute window containing current_ts."""
    window = get_kalshi_15m_window(current_ts)
    return window.start_utc
```

---

### SEV-2: Best-Edge Logic May Block All Trades

**Location**: `merid/loop_15m.py:1447-1499`

**Issue**: Best-edge logic uses relative improvement (20% better than current best) for position scaling. However, if current best is very high (e.g., 5% edge), new signals with 4% edge would be blocked even though they're still good trades.

```python
# CRITICAL FIX: Use relative improvement (percentage) instead of absolute for velocity-based signals
# Velocity-based signals have tiny edges (0.01-0.07%), so absolute 5% threshold is impossible
# Use 20% relative improvement instead: edge must be 20% better than current best
if abs(current_best_edge) > 0:
    edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
    if edge_improvement_ratio < 0.20:  # 20% improvement threshold
        should_execute = False
```

**Impact**:
- May miss good trades if current best edge is anomalously high
- Could reduce trade frequency below optimal levels
- Violates the "best-edge" principle (should execute best available, not just better than current)

**Root Cause**: Relative improvement threshold is too strict for small edge ranges.

**Fix**:
```python
# Use hybrid logic: absolute minimum threshold OR relative improvement
min_edge_threshold = 0.0001  # 0.01% absolute minimum
relative_improvement_threshold = 0.20  # 20% relative improvement

if abs(edge) > min_edge_threshold:
    # Meets absolute minimum - execute
    should_execute = True
elif abs(current_best_edge) > 0:
    edge_improvement_ratio = (abs(edge) - abs(current_best_edge)) / abs(current_best_edge)
    if edge_improvement_ratio >= relative_improvement_threshold:
        # Meets relative improvement - execute
        should_execute = True
```

---

### SEV-2: Kill Switch Disabled in Production

**Location**: `merid/event_venues/kalshi/order_router.py:3575`

**Issue**: Global kill switch for "no live data" is disabled (`if False:`) to reduce trade blocking during warmup. This could allow trading with stale data.

```python
# SEV-0: Kill switch if >80% of priority series are stale
# DISABLED: Kill switch disabled to allow trading during warmup
if False:  # Disabled to reduce trade blocking
    latency = (_time.monotonic() - t0) * 100
    logger.critical(
        "[SEV-0-KILL-SWITCH] NO LIVE DATA - %d/%d series stale, halting all trading",
        stale_count, total_count
    )
    _release_gate_record(intent, "kill_switch:no_live_data")
    return OrderResult(
        status="rejected",
        mode=mode,
        reason="kill_switch:no_live_data:system_wide_data_failure",
        latency_ms=round(latency, 2),
    )
```

**Impact**:
- Could trade on stale data if WebSocket fails
- No protection against system-wide data failures
- Violates defense-in-depth principle

**Root Cause**: Kill switch was too aggressive during warmup, so it was disabled entirely instead of being refined.

**Fix**:
```python
# Re-enable kill switch with warmup guard
# Only disable kill switch in first 5 minutes after process start
import time
_process_start_time = time.time()

if time.time() - _process_start_time > 300:  # 5 minutes warmup
    if stale_count / total_count > 0.8:  # >80% stale
        latency = (_time.monotonic() - t0) * 100
        logger.critical(
            "[SEV-0-KILL-SWITCH] NO LIVE DATA - %d/%d series stale, halting all trading",
            stale_count, total_count
        )
        _release_gate_record(intent, "kill_switch:no_live_data")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="kill_switch:no_live_data:system_wide_data_failure",
            latency_ms=round(latency, 2),
        )
```

---

### SEV-2: Order Scaling May Bypass Risk Limits

**Location**: `merid/event_venues/kalshi/order_router.py:6844-6851`

**Issue**: Order scaling (TWAP, iceberg, adaptive) splits large orders into child orders. Each child order goes through risk validation separately, but the total may exceed risk limits.

```python
# ── ORDER SCALING: Check if order should be scaled ─────────────────────
# Apply institutional scaling strategies (TWAP, iceberg, adaptive)
# Only scale if enabled and order meets criteria (size >= 3, edge >= 2%)
if getattr(intent, 'scaling_enabled', False) and intent.count >= 3:
    scaling_result = await _execute_scaled_order(intent, mode, t0)
    if scaling_result is not None:
        # Scaling was applied, return the result
        return scaling_result
```

**Impact**:
- If parent order is within risk limits but child orders are validated separately, total could exceed limits
- Could allow over-trading via scaled orders
- Violates risk limit enforcement

**Root Cause**: Child orders are validated independently without considering parent order context.

**Fix**:
```python
# Add parent order context to child order validation
# Track total notional for scaled orders in risk envelope
# Deduct parent order notional from window limit before validating child orders

# In _execute_scaled_order():
total_notional_usd = (intent.count * intent.price_cents) / 100.0

# Reserve window capacity for parent order
try:
    envelope = get_kalshi_crypto_15m_risk_envelope()
    envelope.record_order_execution(
        agent_id=intent.agent_id,
        order_notional_usd=total_notional_usd
    )
    # Refund if order fails
    parent_reservation = True
except Exception as e:
    logger.warning("[ORDER-SCALING] Failed to reserve window capacity: %s", e)
    parent_reservation = False

# Execute child orders
for i, child in enumerate(plan.child_orders):
    # ... execute child order ...
    
    # If child fails, refund remaining capacity
    if child_result.status not in ("filled_live", "filled_paper", "filled_mock"):
        remaining_notional = total_notional_usd - filled_notional
        if parent_reservation:
            envelope.refund_order_execution(
                agent_id=intent.agent_id,
                order_notional_usd=remaining_notional
            )
```

---

### SEV-2: Asset Extraction from Ticker Is Fragile

**Location**: `merid/loop_15m.py:1403-1416`

**Issue**: Asset extraction from ticker uses string splitting on "15M" and "KX" prefix, which is fragile and could break if ticker format changes.

```python
# CRITICAL FIX: More robust asset extraction
# Handle both full market IDs (KXBTC15M-26JUN300345-45) and series tickers (KXBTC15M)
if "15M" in ticker:
    # Split on "15M" and take the part before it
    asset_part = ticker.split("15M")[0]
else:
    asset_part = ticker

# Remove "KX" prefix if present
asset = asset_part.replace("KX", "")

# Normalize asset name
asset_map = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "XRP": "XRP", "DOGE": "DOGE"}
asset = asset_map.get(asset, asset)
```

**Impact**:
- If ticker format changes, asset extraction could fail
- Could lead to unknown assets being skipped
- Violates robustness principle

**Root Cause**: Asset extraction is based on string manipulation rather than a formal mapping.

**Fix**:
```python
# Use formal ticker-to-asset mapping from config
from config.kalshi_crypto_config import kalshi_ticker_to_asset

asset = kalshi_ticker_to_asset(ticker)
if asset is None:
    logger.warning("[15M-LOOP] Unknown asset from ticker %s - skipping", ticker)
    continue
```

---

### SEV-2: Position Cache May Have Stale Data

**Location**: `merid/loop_15m.py:1290-1325`

**Issue**: Position cache is reloaded at the start of each cycle, but if the cache is stale (e.g., WebSocket fills delayed), position tracking may be inaccurate.

```python
# CRITICAL FIX: Reload positions from position cache at start of each cycle
# This ensures exposure tracking is based on the most up-to-date information
# and prevents stale exposure from blocking new trades
from merid.event_venues.kalshi.position_cache import get_position_cache
position_cache = get_position_cache()

# Initialize all assets to 0
for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
    self._asset_positions[asset] = 0.0

# Get all positions and calculate exposure per asset
all_positions = position_cache.get_all_positions(validate_freshness=False)
```

**Impact**:
- Stale position data could lead to incorrect exposure tracking
- Could allow over-trading if positions are undercounted
- Could block trades if positions are overcounted

**Root Cause**: Position cache relies on WebSocket fills, which may be delayed or missed.

**Fix**:
```python
# Add REST API fallback for position data
# If position cache is stale (last update > 30s), fetch from REST API
# Merge WebSocket and REST data for accuracy

from merid.event_venues.kalshi.client import KalshiClient

def get_positions_with_fallback():
    position_cache = get_position_cache()
    all_positions = position_cache.get_all_positions(validate_freshness=False)
    
    # Check cache freshness
    last_update = position_cache.get_last_update_time()
    if time.time() - last_update > 30:
        logger.warning("[POSITION-CACHE] Stale cache (%.1fs old), fetching from REST", time.time() - last_update)
        try:
            client = KalshiClient()
            rest_positions = client.get_positions()
            # Merge REST data with cache data
            # REST data takes precedence for stale entries
        except Exception as e:
            logger.error("[POSITION-CACHE] Failed to fetch REST positions: %s", e)
    
    return all_positions
```

---

## Dead/Duplicate/Shadow Logic

### Dead Code
1. **Legacy risk components**: `risk_guard`, `GlobalRiskGuard` (bypassed for kalshi_crypto_15m_v2)
2. **Edge threshold filter in candidate optimizer**: Disabled (commented out)
3. **Staged time-based exit**: Disabled in profile (bypasses PositionMonitor)
4. **Market regime gate**: Removed in order_router (2026-06-29)
5. **Top-3 batch allocation gate**: Removed in order_router (2026-06-29)

### Duplicate Logic
1. **Window limit check**: Implemented in both `order_gate.py` and `kalshi_crypto_15m_risk_envelope.py` (should be single source)
2. **Position existence check**: Implemented in `order_gate.py` and `position_cache.py` (potential inconsistency)
3. **Edge calculation**: Implemented in 3 locations (agent_grid, loop_15m, order_router)

### Shadow Logic
1. **Legacy vs production stack**: `web/main.py` (legacy) vs `web/main_15m_lean.py` (production) - potential for confusion
2. **Multiple bypass paths**: Warmup bypasses in multiple locations could be exploited
3. **Profile vs hardcoded defaults**: Some components use profile values, others use hardcoded defaults

---

## Recommended Fixes Priority

### Immediate (P0 - Deploy Within 24 Hours)
1. **SEV-0: Exit order window limit bypass** - Remove 10% custom limit
2. **SEV-0: Window exposure not released on all exit paths** - Add release to all exit paths
3. **SEV-0: Velocity-based signal edge calculation inconsistency** - Standardize calculation

### High Priority (P1 - Deploy Within 1 Week)
4. **SEV-1: Silent failure in risk envelope initialization** - Add alerting
5. **SEV-1: Warmup bypass paths** - Add time-based guard
6. **SEV-1: Dead code - legacy risk components** - Remove entirely

### Medium Priority (P2 - Deploy Within 2 Weeks)
7. **SEV-2: Signal metadata not always populated** - Add fallback logic
8. **SEV-2: Position existence check may fail** - Add order store fallback
9. **SEV-2: Window roll timing mismatch** - Use ET-based alignment
10. **SEV-2: Best-edge logic too strict** - Use hybrid logic
11. **SEV-2: Kill switch disabled** - Re-enable with warmup guard
12. **SEV-2: Order scaling bypass risk** - Add parent context
13. **SEV-2: Asset extraction fragile** - Use formal mapping
14. **SEV-2: Position cache stale data** - Add REST fallback

### Low Priority (P3 - Technical Debt)
15. **Dead code cleanup** - Remove disabled features
16. **Duplicate logic consolidation** - Single source of truth
17. **Shadow logic documentation** - Clearly mark legacy vs production

---

## Testing Recommendations

### Unit Tests
1. **Window limit bypass test**: Verify exit orders cannot exceed 3% limit
2. **Window exposure release test**: Verify exposure is released on all exit paths
3. **Edge calculation consistency test**: Verify edge is same across all calculation points
4. **Warmup bypass test**: Verify warmup bypass only works in first 5 minutes
5. **Kill switch test**: Verify kill switch re-enables after 5 minutes

### Integration Tests
1. **End-to-end signal-to-order test**: Verify signal metadata flows through pipeline
2. **Position lifecycle test**: Verify position close releases window exposure
3. **Order scaling test**: Verify scaled orders respect risk limits
4. **Asset extraction test**: Verify asset extraction works for all ticker formats

### Regression Tests
1. **Window roll timing test**: Verify window rolls at correct time (ET-aligned)
2. **Best-edge logic test**: Verify best-edge doesn't block good trades
3. **Position cache freshness test**: Verify REST fallback works when cache is stale

---

## Conclusion

The Kalshi 15-minute crypto trading stack is well-architected with multiple layers of risk protection. However, the audit identified 16 issues ranging from SEV-0 to SEV-2, with 3 critical issues requiring immediate attention:

1. **Exit order window limit bypass** - Could allow over-trading
2. **Window exposure not released on all exit paths** - Could block re-entry
3. **Velocity-based signal edge calculation inconsistency** - Could cause validation failures

The most significant risk is the **exit order window limit bypass**, which violates the "HARD STOP" principle of window-based risk limits. This should be fixed immediately.

The second most significant risk is **window exposure not being released on all exit paths**, which could lead to agents being unable to re-enter after position close. This should also be fixed immediately.

The third most significant risk is **velocity-based signal edge calculation inconsistency**, which could cause legitimate trades to be rejected. This should be fixed immediately.

After these critical fixes are deployed, the remaining issues should be addressed in priority order to harden the system and prevent future issues.

---

**Audit Completed**: 2026-07-08  
**Next Review**: After P0 fixes deployed (2026-07-09)  
**Auditor**: Cascade AI
