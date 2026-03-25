# KALSHI POSITIONS & ORDERS PIPELINE AUDIT
## Deep Inspection for Live/Paper Mode Confusion and Bug Hunt

**Auditor:** MERID/Kalshi Systems Engineer
**Date:** 2026-03-25
**Scope:** Complete positions and orders pipeline, live vs paper separation
**Status:** In Progress - Initial Surface Area Mapped

---

## EXECUTIVE SUMMARY

This audit targets the complete Kalshi positions and orders pipeline, with focus on:
1. **Hard separation** between live trading and paper trading at all layers
2. **Bug hunt** for mode confusion, credential leakage, ghost state, and incorrect fills
3. **Upstream/downstream** tracing for every identified issue
4. **Concrete fixes** and test recommendations

**Current Phase:** Deep inspection completed for positions and orders pipelines

---

## FOCUS: POSITIONS AND ORDERS PIPELINES

### Completed Inspections
1. ✅ Live positions pipeline (REST + WebSocket + Cache)
2. ✅ Paper positions simulation (Matching engine + Paper trading engine)
3. ✅ Live orders pipeline (OrderRouter + OrderManager + Client)
4. ✅ Paper orders simulation (OrderRouter + Matching engine)
5. ✅ Configuration and credentials management
6. ⏳ Shared state auditing (in progress)

### Current Focus
Analyzing bugs and eggs found in positions and orders handling, with upstream/downstream tracing.

---

## MAP: SURFACE AREA

### Components Identified

#### **1. Live Positions Ingestion**

##### **A. REST API Client** (`merid/event_venues/kalshi/client.py`)
- **Type:** Live-only
- **Entry Point:** `get_positions_result()` (line 2208)
- **Pagination:** Cursor-based, up to 10 pages, 100 positions per page
- **Endpoint:** `GET /portfolio/positions`
- **Response:** `market_positions` + `event_positions` arrays
- **Error Handling:** Returns `OperationResult.fail()` on error, partial results on pagination failures
- **Mode Isolation:** ✅ Uses `KalshiConfig.base_url` which respects `use_demo` flag

##### **B. Position Cache** (`merid/event_venues/kalshi/position_cache.py`)
- **Type:** Shared (global singleton)
- **Update Sources:**
  1. WebSocket fill events via `on_fill()` (line 87)
  2. REST sync via `sync_from_rest()` (line 124)
  3. Price updates via `on_price_update()` (line 110)
- **Data Structure:** `Dict[str, CachedPosition]` keyed by `market_id`
- **Singleton Pattern:** Module-level `_instance` with thread-unsafe init
- **Mode Isolation:** ⚠️ **CRITICAL GAP** - No mode tag, no separation

##### **C. WebSocket Positions Stream** (`merid/event_venues/kalshi/ws.py`)
- **Type:** Live-only
- **Channels:**
  - `ticker` - price updates
  - `trade` - fill events
  - `orderbook` - Level 2 deltas
  - `order_groups` - group triggers
- **Message Queue:** Bounded at 4096, drops oldest on overflow
- **Sequence Tracking:** Per-market sequence numbers with gap detection
- **Mode Isolation:** ✅ Uses `KalshiConfig.ws_url` with `use_demo` flag

#### **2. Paper Positions Simulation**

##### **A. Matching Engine** (`merid/matching_engine.py`)
- **Type:** Paper-only
- **Entry Point:** `submit_order()` returns `Fill`
- **Simulation:** Immediate fill at reference price + slippage
- **Slippage:** Configurable (default 5 bps)
- **Mode Isolation:** ✅ Only called when mode == PAPER

##### **B. Paper Trading Engine** (`trading/paper_trading.py`)
- **Type:** Paper-only
- **Portfolio Management:** In-memory `PaperPortfolio` per user
- **Position Tracking:** `Dict[str, PaperPosition]` in portfolio
- **State Persistence:** File-based (`data/paper_positions.json`)
- **Mode Isolation:** ✅ Separate from live client

##### **C. Venue Adapter** (`merid/event_venues/kalshi/venue_adapter.py`)
- **Type:** Shared (mode-aware dispatcher)
- **Constructor:** Takes `mode` parameter ("paper" or "live")
- **Routing:**
  - Paper: Routes to `get_matching_engine("prediction")`
  - Live: Routes to `KalshiVenueClient`
- **Mode Isolation:** ✅ Explicit constructor-time mode selection

#### **3. Live Orders Pipeline**

##### **A. Order Router** (`merid/event_venues/kalshi/order_router.py`)
- **Type:** Mode-aware dispatcher
- **Entry Points:**
  - `route_order()` - Synchronous (MOCK/PAPER only)
  - `route_order_async()` - Async (supports LIVE)
- **Mode Resolution:** `_resolve_mode()` checks `intent.mode` → `get_trade_mode()` → `VenueGate.mode`
- **Dispatching:**
  - MOCK: Calls `simulate_paper_fill()` → immediate return
  - PAPER: Calls `simulate_paper_fill()` → immediate return
  - LIVE: Calls `_route_live()` → KalshiVenueClient
- **Mode Isolation:** ✅ Explicit mode dispatch with clear routing

##### **B. Order Manager** (`merid/event_venues/kalshi/order_manager.py`)
- **Type:** Shared (mode-agnostic order tracking)
- **Entry Point:** `submit_order()` (line 210)
- **Gate Checks:** 3-layer enforcement before submission:
  1. Kill switch via `risk_controller.can_trade()`
  2. VenueGate via `should_simulate_fill()` → blocks non-live
  3. DeploymentController per-agent mode check
- **Tracking:** In-memory `Dict[str, TrackedOrder]`
- **Fill Detection:** Polls order status, detects incremental fills
- **Callbacks:** `on_fill` callback invoked for each fill event
- **Mode Isolation:** ⚠️ **Partial** - No mode tag on TrackedOrder

##### **C. Kalshi REST Order Submission** (`merid/event_venues/kalshi/client.py`)
- **Type:** Live-only
- **Entry Point:** `place_order_result()` (line ~1800)
- **Endpoint:** `POST /portfolio/orders`
- **Payload:**
  ```json
  {
    "ticker": "KXBTC-25JUN-T100000",
    "action": "buy",
    "side": "yes",
    "count": 10,
    "type": "limit",
    "yes_price": 55
  }
  ```
- **Response:** `PlacedOrder` with `order_id`, `client_order_id`, status
- **Mode Isolation:** ✅ Only callable when client configured for live/demo endpoint

#### **4. Paper Orders Simulation**

##### **A. Order Router Paper Fill** (`merid/event_venues/kalshi/order_router.py:241`)
- **Type:** Paper-only simulation
- **Logic:**
  - Slippage: Configurable (default 8 bps)
  - Partial fills: 35% probability, minimum 40% fill ratio
  - Fees: Mirrors Kalshi parabolic fee function
  - Immediate execution (no queue simulation)
- **Mode Isolation:** ✅ Only called when `mode == PAPER` or `mode == MOCK`

##### **B. Matching Engine** (`merid/matching_engine.py`)
- **Type:** Paper-only CLOB simulator
- **Entry Point:** `submit_order()` returns `Fill`
- **Fill Logic:**
  - Matches against reference price (mid or last)
  - Applies configurable slippage (default 5 bps)
  - Returns `Fill` with `fill_type` (MAKER/TAKER/SELF)
- **Mode Isolation:** ✅ Never called in live mode

#### **5. Configuration & Credentials**

##### **A. KalshiConfig** (`merid/event_venues/kalshi/models.py`)
- **Mode Flag:** `use_demo: bool` (False = live, True = demo)
- **Endpoints:**
  - Live: `https://api.elections.kalshi.com/trade-api/v2`
  - Demo: `https://demo-api.kalshi.co/trade-api/v2`
- **Credentials:**
  - Email/password OR RSA-PSS signing
  - Priority: constructor args > settings > env > defaults
- **Mode Isolation:** ✅ Explicit flag, no auto-detection

##### **B. VenueGate** (`merid/prediction/venue_gate.py`)
- **Type:** Global singleton enforcer
- **Modes:** `MOCK`, `PAPER`, `LIVE` (enum)
- **Checks:**
  - `check_venue()` - Kalshi only, blocks Polymarket
  - `check_can_trade()` - Blocks MOCK, requires flag for LIVE
  - `check_order()` - Combined venue + mode check
- **Mode Isolation:** ✅ Explicit enum-based checks

##### **C. TradeMode** (`trading/trade_mode.py`)
- **Type:** Process-wide singleton
- **Modes:** `MOCK`, `PAPER`, `LIVE`
- **Transition Rules:**
  - MOCK → LIVE: ❌ Forbidden
  - PAPER → LIVE: ✅ Only if `MERID_ALLOW_LIVE_TRADES=true`
  - LIVE → PAPER/MOCK: ✅ Always allowed
- **Mode Isolation:** ✅ Strong transition guards

---

## BUGS / EGGS

### 🐛 BUG-001: Position Cache Mode Confusion
**Severity:** CRITICAL
**Location:** `merid/event_venues/kalshi/position_cache.py`
**Type:** Mode Isolation Failure

**Description:**
The `KalshiPositionCache` is a global singleton with no mode tagging. If paper and live sessions run concurrently (or overlap during mode transitions), fills from both modes update the same cache.

**Expected Behavior:**
- Live fills should only update live position cache
- Paper fills should only update paper position cache
- No cross-contamination possible

**Actual Behavior:**
```python
# KalshiPositionCache singleton
class KalshiPositionCache:
    _instance: Optional[KalshiPositionCache] = None  # SHARED GLOBALLY

    def on_fill(self, market_id: str, ...):
        # NO MODE CHECK - accepts fills from ANY source
        position = self._positions.get(market_id)
```

**Reproduction:**
1. Start paper trading session
2. Place paper order, get simulated fill
3. `position_cache.on_fill()` called → position recorded
4. Switch to live mode (without restart)
5. Place live order, get real fill
6. `position_cache.on_fill()` called → SAME cache updated
7. Paper position contaminated with live fill data

**Impact:**
- Paper positions could include live fills
- Live positions could include paper fills
- Risk calculations use contaminated data
- PnL reports mix paper and live results
- Operator cannot trust position views

**Fix:**
Mode-tagged position cache with separate instances:
```python
class KalshiPositionCache:
    def __init__(self, mode: TradeMode):
        self.mode = mode
        self._positions: Dict[str, CachedPosition] = {}

    def on_fill(self, market_id: str, ..., mode: TradeMode):
        if mode != self.mode:
            logger.error(f"Mode mismatch: cache={self.mode}, fill={mode}")
            raise ModeViolationError(...)

_live_cache = None
_paper_cache = None

def get_position_cache(mode: TradeMode) -> KalshiPositionCache:
    global _live_cache, _paper_cache
    if mode == TradeMode.LIVE:
        if _live_cache is None:
            _live_cache = KalshiPositionCache(TradeMode.LIVE)
        return _live_cache
    else:
        if _paper_cache is None:
            _paper_cache = KalshiPositionCache(TradeMode.PAPER)
        return _paper_cache
```

---

### 🥚 EGG-001: RSA Key Global Cache Across Mode Switches
**Severity:** HIGH
**Location:** `merid/event_venues/kalshi/client.py` (line 69)
**Type:** Credential Leak Risk

**Description:**
The RSA private key is cached module-globally:
```python
_cached_private_key: Optional[Any] = None
_cached_key_id: Optional[str] = None
```

If an operator switches from demo to live (or vice versa) without restarting, the cached key could be reused with wrong endpoint.

**Expected Behavior:**
- Demo mode uses demo credentials
- Live mode uses live credentials
- No cross-use possible

**Actual Behavior:**
- Key cached once, never invalidated
- Mode switch doesn't clear cache
- Demo key could be sent to live endpoint (rejected by API, but still logged server-side)
- Live key could be sent to demo endpoint (security exposure)

**Impact:**
- Potential credential leak in logs
- API validation relies on server-side rejection
- No client-side enforcement of credential/endpoint pairing

**Fix:**
Cache key per-config or invalidate on mode change:
```python
# Option 1: Cache keyed by config
_key_cache: Dict[Tuple[str, bool], Any] = {}  # (key_id, use_demo) -> key

# Option 2: Instance-level cache (no global)
class KalshiVenueClient:
    def __init__(self, config: KalshiConfig):
        self._cached_key = None
        self._cached_key_id = None
```

---

### 🥚 EGG-002: Position Cache Not Cleared on Mode Transitions
**Severity:** HIGH
**Location:** `merid/event_venues/kalshi/position_cache.py`
**Type:** Stale State Risk

**Description:**
When transitioning from PAPER → LIVE or LIVE → PAPER, the position cache is not cleared. Stale positions from the previous mode remain visible.

**Expected Behavior:**
- Mode transition clears position cache
- New mode starts with empty cache
- Positions fetched fresh from correct source

**Actual Behavior:**
```python
# VenueGate.mode setter (venue_gate.py:102)
@mode.setter
def mode(self, value: TradingMode) -> None:
    logger.info(f"VenueGate mode changed: {self._mode.value} -> {value.value}")
    self._mode = value
    # NO CACHE INVALIDATION
```

**Impact:**
- Paper positions visible after switching to live
- Live positions visible after switching to paper
- Operator sees ghost positions from previous mode
- Risk calculations use stale data

**Fix:**
```python
@mode.setter
def mode(self, value: TradingMode) -> None:
    old_mode = self._mode
    self._mode = value
    logger.info(f"VenueGate mode changed: {old_mode.value} -> {value.value}")

    # Clear position cache on mode transition
    from merid.event_venues.kalshi.position_cache import get_position_cache
    cache = get_position_cache()
    cache.clear()
    logger.info(f"Position cache cleared after mode transition")
```

---

### 🥚 EGG-003: No Mode Tag in Fill Events
**Severity:** MEDIUM
**Location:** `merid/event_venues/kalshi/position_cache.py:87` and event bus
**Type:** Observability Gap

**Description:**
Fill events published to the event bus have no mode tag. Consumers cannot distinguish live fills from paper fills.

**Expected Behavior:**
- Fill events include `mode: "live"` or `mode: "paper"`
- Consumers filter by mode
- Logs clearly show fill source

**Actual Behavior:**
```python
def on_fill(self, market_id: str, contracts: int, ...):
    # Updates cache - NO MODE RECORDED
    logger.debug(f"Position cache: opened {side} position on {market_id}")
```

**Impact:**
- Logs mix paper and live fills
- Dashboards cannot filter by mode
- Debugging mode confusion requires log archaeology
- No runtime mode verification possible

**Fix:**
```python
@dataclass
class CachedPosition:
    market_id: str
    contracts: int
    side: str
    avg_price_cents: int
    mode: TradeMode  # ADD MODE TAG
    # ...

def on_fill(self, market_id: str, ..., mode: TradeMode):
    position = self._positions.get(market_id)
    if position and position.mode != mode:
        logger.error(f"Mode mismatch: position={position.mode}, fill={mode}")
        raise ModeViolationError(...)
    # ...
```

---

### 🥚 EGG-004: VenueAdapter Mode Not Immutable
**Severity:** MEDIUM
**Location:** `merid/event_venues/kalshi/venue_adapter.py:55`
**Type:** Runtime Safety Gap

**Description:**
The `KalshiVenueAdapter.mode` is set at construction but not enforced as immutable. A bug could change mode mid-session.

**Expected Behavior:**
- Mode set once at construction
- Mode cannot be changed after init
- New mode requires new adapter instance

**Actual Behavior:**
```python
class KalshiVenueAdapter:
    def __init__(self, mode: str = "paper", ...):
        self.mode = DomainMode(mode)  # Public attribute, can be reassigned
```

**Impact:**
- Accidental mode change could route live orders through paper engine
- No runtime protection against mode mutation
- Hard-to-debug mode drift

**Fix:**
```python
class KalshiVenueAdapter:
    def __init__(self, mode: str = "paper", ...):
        self._mode = DomainMode(mode)  # Private

    @property
    def mode(self) -> DomainMode:
        return self._mode

    # No setter - mode is immutable
```

---

### 🥚 EGG-005: REST Positions Parsing Doesn't Filter Zero-Size
**Severity:** LOW
**Location:** `merid/event_venues/kalshi/client.py:2244-2254`
**Type:** Ghost State Risk

**Description:**
The `get_positions_result()` method doesn't filter out positions with zero contracts. Kalshi API may return closed positions that should be hidden.

**Expected Behavior:**
- Only positions with `contracts > 0` are returned
- Fully closed positions filtered out

**Actual Behavior:**
```python
for pos_data in result.data.get("market_positions", []):
    position = self._parse_position(pos_data)
    if position:
        all_positions.append(self._to_venue_position(position))
    # NO CHECK: if position.contracts == 0: continue
```

**Impact:**
- UI shows ghost positions
- Risk calculations may double-count
- PnL reports include noise

**Fix:**
```python
for pos_data in result.data.get("market_positions", []):
    position = self._parse_position(pos_data)
    if position and position.contracts > 0:  # ADD FILTER
        all_positions.append(self._to_venue_position(position))
```

---

## UPSTREAM: CONFIGURATION & CREDENTIALS

### Inspected Components

#### 1. Environment Variable Loading
**Location:** `merid/event_venues/kalshi/models.py` (KalshiConfig)

**Findings:**
✅ **Safe:** Multiple credential sources with clear priority
```
1. Constructor args (highest)
2. merid.settings.settings
3. Environment variables
4. Defaults (empty strings)
```

⚠️ **Gap:** No validation that live credentials aren't used with demo endpoint (relies on server rejection)

**Recommendation:**
Add client-side validation:
```python
def __post_init__(self):
    if self.use_demo and self.private_key_path and "prod" in self.private_key_path:
        raise ValueError("Production key detected with use_demo=True")
    if not self.use_demo and self.private_key_path and "demo" in self.private_key_path:
        raise ValueError("Demo key detected with use_demo=False")
```

#### 2. Mode Selection at Startup
**Location:** `trading/trade_mode.py:52` (_resolve_initial_mode)

**Findings:**
✅ **Safe:** Clear env var → enum mapping
✅ **Safe:** Defaults to PAPER (safest option)
✅ **Safe:** Invalid values log warning and default to PAPER

**No upstream issues found.**

#### 3. Secrets Management
**Location:** Environment variables and file paths

**Findings:**
✅ **Safe:** RSA keys loaded from file system, not hardcoded
✅ **Safe:** No secrets in code or version control

⚠️ **Gap:** No encryption at rest for private keys
⚠️ **Gap:** No audit trail when keys are loaded/used

**Recommendation:**
```python
def _load_private_key(path: str, mode: str) -> Any:
    logger.info(f"Loading RSA key from {path} for mode={mode}", extra={"audit": True})
    # ... load logic
    logger.info(f"RSA key loaded successfully: {key_id}", extra={"audit": True})
```

---

## DOWNSTREAM: POSITION CONSUMPTION

### Inspected Components

#### 1. Portfolio Views (UI/API)
**Location:** TBD (need to inspect web API layer)

**Findings:** Pending inspection

#### 2. Risk Aggregation
**Location:** TBD (need to inspect risk controller)

**Findings:** Pending inspection

#### 3. PnL Calculation
**Location:** `trading/paper_trading.py` (PaperPortfolio) and position cache

**Findings:**
⚠️ **Mode Confusion Risk:** If position cache is contaminated (BUG-001), PnL will mix paper and live results

---

## FIXES / TODOs

### Priority 1: Mode Confusion (CRITICAL)
1. **BUG-001 Fix:** Separate position cache per mode
   - [ ] Add `mode: TradeMode` to `CachedPosition`
   - [ ] Create `get_position_cache(mode)` accessor
   - [ ] Update all `on_fill()` callsites to pass mode
   - [ ] Add mode mismatch guards

### Priority 2: Credential Safety (HIGH)
1. **EGG-001 Fix:** Invalidate RSA key cache on config change
   - [ ] Move key cache to instance-level OR
   - [ ] Key cache by (key_id, use_demo) tuple

2. **EGG-002 Fix:** Clear position cache on mode transitions
   - [ ] Hook VenueGate.mode setter
   - [ ] Hook TradeMode.set_trade_mode()
   - [ ] Clear both live and paper caches

### Priority 3: Observability (MEDIUM)
1. **EGG-003 Fix:** Add mode tags to all position/fill events
   - [ ] Add `mode` field to `CachedPosition`
   - [ ] Add `mode` field to fill event payloads
   - [ ] Update logs to include mode

2. **EGG-004 Fix:** Make adapter mode immutable
   - [ ] Change `self.mode` to `self._mode` (private)
   - [ ] Add read-only property
   - [ ] Remove or block any setters

### Priority 4: Data Quality (LOW)
1. **EGG-005 Fix:** Filter zero-size positions
   - [ ] Add `if position.contracts > 0` filter in REST parsing
   - [ ] Add same filter in cache `get_all_positions()`

---

### 🥚 EGG-006: OrderManager TrackedOrder Has No Mode Tag
**Severity:** MEDIUM
**Location:** `merid/event_venues/kalshi/order_manager.py:67`
**Type:** Observability Gap

**Description:**
The `TrackedOrder` dataclass tracks order lifecycle but has no `mode` field. Orders from paper and live sessions are tracked in the same structure without distinguishing their source.

**Expected Behavior:**
- Each `TrackedOrder` includes `mode: TradeMode`
- Paper orders clearly tagged as paper
- Live orders clearly tagged as live
- Logs show mode for every order

**Actual Behavior:**
```python
@dataclass
class TrackedOrder:
    order_id: str
    client_order_id: str
    ticker: str
    # ... NO MODE FIELD
```

**Impact:**
- Cannot distinguish paper orders from live orders in tracking
- Debugging mode confusion requires correlating with external logs
- OrderManager summary doesn't show mode breakdown
- Risk reports may mix paper and live order counts

**Fix:**
```python
@dataclass
class TrackedOrder:
    order_id: str
    client_order_id: str
    ticker: str
    mode: TradeMode  # ADD MODE TAG
    # ...

    def to_dict(self) -> Dict[str, Any]:
        return {
            # ...
            "mode": self.mode.value,
            # ...
        }
```

---

### 🥚 EGG-007: OrderManager Fill Callback Doesn't Receive Mode
**Severity:** MEDIUM
**Location:** `merid/event_venues/kalshi/order_manager.py:172`
**Type:** Mode Confusion Risk

**Description:**
The `on_fill` callback signature is `Callable[[str, FillEvent], None]` - it receives order_id and fill event, but not the mode. Callbacks cannot verify mode matches expectations.

**Expected Behavior:**
- Fill callback receives `mode: TradeMode` parameter
- Callback can reject fills from wrong mode
- Callback can route fills to mode-specific handlers

**Actual Behavior:**
```python
FillCallback = Callable[[str, FillEvent], None]
# Callback receives (order_id, fill_event) only - NO MODE
```

**Impact:**
- Paper fill callbacks might process live fills (or vice versa)
- No runtime verification that fill matches expected mode
- Risk aggregation may mix modes if callback is shared

**Fix:**
```python
FillCallback = Callable[[str, FillEvent, TradeMode], None]

# In OrderManager.submit_order():
if self._on_fill:
    tracked = self._orders[order_id]
    self._on_fill(order_id, fill_event, tracked.mode)
```

---

### 🐛 BUG-002: OrderRouter Mode Resolution Has Fallback Chain
**Severity:** HIGH
**Location:** `merid/event_venues/kalshi/order_router.py:198-206`
**Type:** Mode Confusion Risk

**Description:**
The `_resolve_mode()` function has a fallback chain: `intent.mode` → `get_trade_mode()` → `VenueGate.mode`. If `get_trade_mode()` fails, it silently falls back to `VenueGate.mode`, which might be different.

**Expected Behavior:**
- Single source of truth for mode
- Mode resolution never silently falls back
- Failures are explicit errors

**Actual Behavior:**
```python
def _resolve_mode(override: Optional[TradingMode]) -> TradingMode:
    if override is not None:
        return override
    try:
        return TradingMode(get_trade_mode().value)
    except Exception as _e:
        logger.debug("_resolve_mode: get_trade_mode failed, falling back to venue_gate: %s", _e)
        return get_venue_gate().mode  # SILENT FALLBACK
```

**Reproduction:**
1. `get_trade_mode()` returns `TradeMode.LIVE`
2. `VenueGate.mode` is `TradeMode.PAPER` (misconfiguration)
3. `get_trade_mode()` raises exception (e.g., import error)
4. OrderRouter silently uses `PAPER` mode
5. Operator believes they're trading live, but orders are paper-simulated

**Impact:**
- Mode confusion on transient failures
- Silent mode mismatch between TradeMode and VenueGate
- Operator may place "live" orders that are actually paper
- Logs show debug message but order proceeds with wrong mode

**Fix:**
```python
def _resolve_mode(override: Optional[TradingMode]) -> TradingMode:
    if override is not None:
        return override

    # Single source of truth - no fallback
    mode = get_trade_mode()

    # Verify consistency with VenueGate
    gate = get_venue_gate()
    if mode != gate.mode:
        raise ModeInconsistencyError(
            f"TradeMode ({mode.value}) != VenueGate.mode ({gate.mode.value}). "
            f"Fix configuration before trading."
        )

    return mode
```

---

### 🥚 EGG-008: Paper Fill Simulation Uses Global Random State
**Severity:** LOW
**Location:** `merid/event_venues/kalshi/order_router.py:258`
**Type:** Non-Deterministic Testing

**Description:**
The `simulate_paper_fill()` function uses Python's global `random.random()` for partial fill simulation. Tests cannot be deterministic without seeding the global RNG.

**Expected Behavior:**
- Tests can pass `random_seed` parameter for deterministic fills
- Paper fills are reproducible in test environments

**Actual Behavior:**
```python
def simulate_paper_fill(intent: OrderIntent) -> Dict[str, Any]:
    # ...
    if requested_count > 1 and random.random() < PAPER_PARTIAL_FILL_PROB:
        # NON-DETERMINISTIC
```

**Impact:**
- Flaky tests when partial fills are random
- Cannot reproduce paper trading bugs
- Integration tests may pass/fail randomly

**Fix:**
```python
def simulate_paper_fill(
    intent: OrderIntent,
    rng: Optional[random.Random] = None
) -> Dict[str, Any]:
    rng = rng or random.Random()  # Use provided or default
    # ...
    if requested_count > 1 and rng.random() < PAPER_PARTIAL_FILL_PROB:
        # ...
```

---

### 🥚 EGG-009: OrderManager Doesn't Validate Order Source Matches Mode
**Severity:** MEDIUM
**Location:** `merid/event_venues/kalshi/order_manager.py:210`
**Type:** Mode Confusion Risk

**Description:**
The `submit_order()` method checks VenueGate mode but doesn't verify the order object itself has consistent mode metadata. A paper order could be submitted in live mode (or vice versa) if metadata is wrong.

**Expected Behavior:**
- Order object includes `mode` field
- OrderManager validates `order.mode == VenueGate.mode`
- Mismatch raises error before submission

**Actual Behavior:**
```python
async def submit_order(self, order: Any) -> Optional[TrackedOrder]:
    # Checks VenueGate but doesn't validate order.mode field exists or matches
    if _gate.should_simulate_fill():
        return None  # Blocks, but no validation of order metadata
```

**Impact:**
- Order metadata could be inconsistent with runtime mode
- Paper order accidentally submitted as live (if gates fail)
- No defense-in-depth validation

**Fix:**
```python
async def submit_order(self, order: Any) -> Optional[TrackedOrder]:
    # Validate order has mode metadata
    order_mode = getattr(order, "mode", None)
    if order_mode is None:
        raise ValueError("Order missing mode field")

    # Validate order mode matches runtime mode
    _gate = get_venue_gate()
    if order_mode != _gate.mode:
        raise ModeViolationError(
            f"Order mode ({order_mode}) != VenueGate.mode ({_gate.mode})"
        )

    # ... continue with submission
```



---

## TESTS TO ADD

### Unit Tests

#### Test: Mode-Tagged Position Cache
```python
def test_position_cache_mode_isolation():
    live_cache = get_position_cache(TradeMode.LIVE)
    paper_cache = get_position_cache(TradeMode.PAPER)

    # Paper fill should not appear in live cache
    paper_cache.on_fill("KXBTC-TEST", 10, 5500, 7, "yes", TradeMode.PAPER)
    assert live_cache.get_position("KXBTC-TEST") is None

    # Live fill should not appear in paper cache
    live_cache.on_fill("KXBTC-TEST", 10, 5500, 7, "yes", TradeMode.LIVE)
    assert paper_cache.get_position("KXBTC-TEST") is None
```

#### Test: Mode Transition Clears Cache
```python
def test_mode_transition_clears_cache():
    gate = VenueGate(mode=TradeMode.PAPER)
    cache = get_position_cache(TradeMode.PAPER)

    # Add paper position
    cache.on_fill("KXBTC-TEST", 10, 5500, 7, "yes", TradeMode.PAPER)
    assert cache.get_position("KXBTC-TEST") is not None

    # Switch to live
    gate.mode = TradeMode.LIVE

    # Paper cache should be cleared
    assert cache.get_position("KXBTC-TEST") is None
```

#### Test: Mode Mismatch Raises Error
```python
def test_position_cache_rejects_wrong_mode_fill():
    live_cache = get_position_cache(TradeMode.LIVE)

    # Attempt paper fill on live cache should raise
    with pytest.raises(ModeViolationError):
        live_cache.on_fill("KXBTC-TEST", 10, 5500, 7, "yes", TradeMode.PAPER)
```

### Integration Tests

#### Test: End-to-End Paper Order Does Not Contaminate Live
```python
@pytest.mark.asyncio
async def test_paper_order_does_not_contaminate_live():
    # Setup
    set_trade_mode(TradeMode.PAPER)
    paper_adapter = KalshiVenueAdapter(mode="paper")
    live_cache = get_position_cache(TradeMode.LIVE)

    # Execute paper order
    order = VenueOrder(...)
    await paper_adapter.submit_order(order)

    # Verify live cache is still empty
    live_positions = live_cache.get_all_positions()
    assert len(live_positions) == 0
```

#### Test: Mode Switch Prevents Accidental Live Order
```python
@pytest.mark.asyncio
async def test_mode_switch_prevents_live_order():
    gate = VenueGate(mode=TradeMode.PAPER)

    # Switch to LIVE without setting env flag
    with pytest.raises(RuntimeError, match="MERID_ALLOW_LIVE_TRADES"):
        set_trade_mode(TradeMode.LIVE)
```

### Chaos Tests

#### Test: Rapid Mode Switching
```python
@pytest.mark.asyncio
async def test_rapid_mode_switching_no_contamination():
    for _ in range(10):
        set_trade_mode(TradeMode.PAPER)
        paper_cache = get_position_cache(TradeMode.PAPER)
        paper_cache.on_fill("KXBTC-TEST", 10, 5500, 7, "yes", TradeMode.PAPER)

        set_trade_mode(TradeMode.LIVE)
        live_cache = get_position_cache(TradeMode.LIVE)
        assert live_cache.get_position("KXBTC-TEST") is None
```

---

## NEXT STEPS

1. ✅ Complete live positions pipeline inspection
2. ⏳ Inspect paper positions simulation (matching engine, paper engine)
3. ⏳ Inspect live orders pipeline (submission, tracking, queue position)
4. ⏳ Inspect paper orders simulation (fill logic, partial fills)
5. ⏳ Audit shared state (OrderManager, EventBus)
6. ⏳ Implement all fixes (Priority 1 → 4)
7. ⏳ Add all recommended tests
8. ⏳ Run full regression suite

---

## APPENDIX: COMPONENT MODE MATRIX

| Component | Live Only | Paper Only | Shared | Mode Isolation |
|-----------|-----------|------------|--------|----------------|
| KalshiVenueClient | ✓ | | | Strong (REST-only) |
| KalshiWebSocket | ✓ | | | Strong (WS-only) |
| PositionCache | | | ✓ | ❌ **WEAK - NO MODE TAG** |
| MatchingEngine | | ✓ | | Strong (paper-only) |
| PaperTradingEngine | | ✓ | | Strong (paper-only) |
| VenueAdapter | | | ✓ | Partial (constructor) |
| VenueGate | ✓ | ✓ | ✓ | Strong (explicit checks) |
| TradeMode | ✓ | ✓ | ✓ | Strong (enum + guards) |

