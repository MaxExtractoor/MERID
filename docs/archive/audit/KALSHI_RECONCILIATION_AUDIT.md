# Kalshi Reconciliation End-to-End Audit

**SPEC_VERSION:** 1.0.0  
**Audit Date**: 2026-01-15
**Scope**: Full reconciliation pipeline from Kalshi API → MERID internal state → Execution Gate
**Objective**: Define contract, audit upstream/ingestion, verify reconciliation logic, validate downstream gate behavior, align with Kalshi expectations

---

## Step 1: Define the Contract with Kalshi

### 1.1 Kalshi Position Surfaces We Rely On

#### Primary REST Endpoints

| Endpoint | Purpose | Response Model | Location |
|----------|---------|----------------|----------|
| `GET /portfolio/positions` | Current positions | `market_positions[]`, `event_positions[]` | `client.py:2858-2928` |
| `GET /portfolio/balance` | Cash balance | `balance`, `locked_balance`, `portfolio_value` | `types.py:46-54` |
| `GET /portfolio/fills` | Fill history | Cursor-based pagination | `fills_ledger.py:846-855` |
| `GET /portfolio/settlements` | Settlement outcomes | Market settlement status | `settlement_poller.py:644-653` |

#### WebSocket Channels

| Channel | Purpose | Location |
|---------|---------|----------|
| `fill` | Real-time fill events | `ws.py:435-444` |

#### Key Implementation Details

**Pagination**: `/portfolio/positions` uses cursor-based pagination with `limit=100` per page (client.py:2872)
- Max pages: 10 (safety limit)
- Handles both `market_positions` and `event_positions` keys

**Dual Ingestion Pattern**:
- HTTP polling: `FillsPoller` polls `/portfolio/fills` every 20s (configurable)
- WebSocket: Real-time fill events via `fill` channel
- Both ingest into `KalshiFillsLedger` with idempotent upserts

### 1.2 Internal Position Models

We have **four distinct position representations**:

#### 1.2.1 KalshiPosition (Raw API Model)
**Location**: `merid/event_venues/kalshi/models.py:77-86`
```python
@dataclass
class KalshiPosition:
    ticker: str
    side: str  # "yes" or "no"
    count: int
    avg_price: Decimal  # Average entry price in cents
    total_cost: Decimal
    unrealized_pnl: Optional[Decimal]
    realized_pnl: Optional[Decimal]
    created_at: Optional[datetime]
```
**Purpose**: Direct 1:1 mapping to Kalshi API response
**Unit**: Cents for prices, Decimal for PnL

#### 1.2.2 CachedPosition (Real-time Cache)
**Location**: `merid/event_venues/kalshi/position_cache.py:73-95`
```python
class CachedPosition:
    market_id: str
    contracts: int
    side: str  # "yes" or "no"
    avg_price_cents: int
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    last_updated: datetime
    fill_source: str  # "alpha" or "hedge"
    client_order_id: Optional[str]
    take_profit_price_cents: Optional[int]
    stop_loss_price_cents: Optional[int]
```
**Purpose**: Real-time position cache updated from WebSocket fill events
**Update Path**: `KalshiPositionCache.on_fill()` → `sync_from_rest()` for reconciliation
**Thread Safety**: Protected by `_mutex` (asyncio.Lock)

#### 1.2.3 Position (Canonical Event-Sourced Model)
**Location**: `merid/event_venues/kalshi/portfolio_models.py:95-119`
```python
@dataclass(frozen=True)
class Position:
    position_id: str
    account_id: str
    ticker: str  # Kalshi market ticker
    side: str  # "yes" or "no"
    quantity: int  # Signed (positive=long, negative=short)
    avg_entry_price_cents: int
    cost_basis_cents: int  # quantity * avg_entry_price_cents
    realized_pnl_cents: int
    last_updated: datetime
```
**Purpose**: Canonical position state from event replay
**Source**: `PortfolioEngine` replays `PortfolioEvent` log to compute current state
**Invariant**: All monetary values in **cents** (integers) to match Kalshi API

#### 1.2.4 VenuePosition (MERID Venue Protocol)
**Location**: `merid/event_venues/base.py` (base protocol)
```python
# Used by reconciliation logic
venue_positions = adapter.get_positions()  # Returns List[VenuePosition]
```
**Purpose**: Unified venue protocol for reconciliation
**Mapping**: Converted from `KalshiPosition` in `venue_adapter.py:246-305`

### 1.3 Kalshi API Response Structure

#### BackendPosition (Risk Projection)
**Location**: `merid/event_venues/kalshi/risk_projection.py:100-113`
```python
class BackendPosition:
    ticker: str
    side: str  # "yes" or "no"
    count: int
    avg_price_dollars: Decimal  # 0-1 range
    total_cost_dollars: Decimal
    unrealized_pnl_dollars: Decimal
    realized_pnl_dollars: Decimal
    created_at: datetime
```
**Critical Note**: Kalshi uses **dollars (0-1 range)** for prices, we use **cents** internally. Conversion happens in multiple places.

### 1.4 Documented Invariants

#### Invariant 1: Per-Market Net Position
- **Statement**: For each `(ticker, side)` pair, `merid.quantity` must equal `kalshi.count`
- **Tolerance**: Exact match (no tolerance for position mismatches)
- **Exception**: Both zero is "fresh start" (benign)
- **Enforcement**: `reconcile_venue()` checks `abs(v["qty"] - m["qty"]) > 0.001` (venue_reconciler.py:383)

#### Invariant 2: Cash Flow Consistency
- **Statement**: Sum of all fill cash impacts must equal Kalshi balance changes
- **Components**:
  - Fees must match between `KalshiFill.fee_cost` and Kalshi API
  - Settlement PnL must match when markets settle
- **Enforcement**: `PortfolioReconciler` compares internal vs Kalshi balance (portfolio_reconciliation.py:109-150)
- **Tolerance**: `_CASH_TOLERANCE_CENTS = 1` (configurable via env)

#### Invariant 3: Fill-to-Position Derivation
- **Statement**: Replaying fills in order must reproduce current internal position
- **Requirements**:
  - No fill can be lost or duplicated (idempotent upserts)
  - Fill IDs from Kalshi are the primary key
  - `fills_ledger.compute_net_positions()` must match `position_cache.get_all_positions()`
- **Enforcement**: `FillsPoller` runs reconciliation every 60s (fills_poller.py:310-320)
- **Tolerance**: `_CACHE_LEDGER_DIVERGENCE_THRESHOLD = 5` contracts (fills_poller.py:403)

#### Invariant 4: Subaccount Isolation
- **Statement**: Each `kalshi_subaccount_id` has independent positions
- **Requirements**:
  - No cross-subaccount position aggregation
  - Reconciliation runs per subaccount
- **Current Status**: Subaccount support exists but single-subaccount deployment assumed
- **Enforcement**: `KalshiFill.subaccount_number` field tracks subaccount

### 1.5 Unit Conversion Map

| Context | Kalshi Unit | MERID Unit | Conversion |
|---------|-------------|------------|------------|
| Prices (API) | Dollars (0-1) | Cents (int) | `cents = dollars * 100` |
| Prices (Internal) | Cents (int) | Cents (int) | No conversion |
| PnL (API) | Dollars | Cents | `cents = dollars * 100` |
| PnL (Internal) | Cents (int) | Cents (int) | No conversion |
| Fees (API) | Dollars | Cents | `cents = dollars * 100` |
| Fees (Internal) | Cents (int) | Cents (int) | No conversion |

**Critical Bug Risk**: Multiple conversion points create drift. Must use consistent conversion in all paths.

---

## Step 2: Upstream Audit - Ingestion, State, and Reconciliation Inputs

### 2.1 Data Ingestion Pathways

#### 2.1.1 HTTP Polling (FillsPoller)
**Location**: `merid/event_venues/kalshi/fills_poller.py`
**Frequency**: Every 20s (configurable via `MERID_FILLS_POLL_INTERVAL_SEC`)
**Endpoint**: `GET /portfolio/fills`
**Pagination**: Cursor-based with `limit=200`
**Ingestion**: `await ledger.ingest_http_fills(fills_list)`
**Idempotency**: Upsert by `fill_id` (primary key)

**Key Features**:
- Backfill loop runs every 300s (fills_poller.py:84)
- Reconciliation loop runs every 60s (fills_poller.py:85)
- Circuit breaker for backfill failures (fills_poller.py:126-130)
- Settlement tracking to prevent duplicate `record_outcome()` calls

#### 2.1.2 WebSocket Fill Events
**Location**: `merid/event_venues/kalshi/ws.py:435-444`
**Channel**: `fill`
**Ingestion**: `await ledger.ingest_ws_fill(fill_dict)`
**Priority**: Real-time (lower latency than HTTP)
**Fallback**: HTTP polling ensures completeness if WS drops

**Key Features**:
- Market filtering via `market_tickers` parameter
- Event ticker filtering via `event_ticker` parameter
- Incomplete fills flagged for HTTP confirmation (fills_ledger.py:1061)

#### 2.1.3 Position Sync from REST
**Location**: `merid/event_venues/kalshi/venue_adapter.py:246-305`
**Trigger**: After `get_positions()` API call
**Function**: `cache.sync_from_rest(rest_pos_list)`
**Purpose**: Reconciliation baseline for position cache
**Preserves**: TP targets from existing cache during reconciliation

**Key Features**:
- Filters test tickers via `_is_test_ticker()` (position_cache.py:450)
- Filters closed positions (contracts=0) to prevent phantom positions
- Mutex-protected async operation (position_cache.py:441)

### 2.2 Internal Position State Sources

#### 2.2.1 Fills Ledger (Primary Truth)
**Location**: `merid/event_venues/kalshi/fills_ledger.py`
**Database**: SQLite at `MERID_FILLS_DB_PATH` (default: `data/kalshi_fills.db`)
**Primary Key**: `fill_id` (from Kalshi, never null for real fills)
**Computation**: `compute_net_positions()` replays all fills to derive positions

**Schema** (fills_ledger.py:197-252):
```python
class KalshiFill:
    fill_id: str  # Kalshi's unique fill ID — THE primary key
    trade_id: Optional[str]
    order_id: Optional[str]
    market_ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count_fp: int  # Number of contracts (fixed-point integer)
    yes_price_dollars: Optional[Decimal]
    no_price_dollars: Optional[Decimal]
    fee_cost: Decimal
    proceeds_dollars: Optional[Decimal]
    client_order_id: Optional[str]
    subaccount_number: Optional[int]
    created_time: datetime
    ingestion_source: str  # "http_poller", "websocket", "backfill"
    ingested_at: datetime
    agent_id: Optional[str]
    intent_id: Optional[str]
    decision_trace_id: Optional[str]
    fill_source: str  # "alpha", "hedge", "manual"
    hedge_reason: Optional[str]
    hedge_pnl_cents: int
    related_alpha_fill_id: Optional[str]
    reconciled: bool
    reconciliation_ts: Optional[datetime]
    derived_id: bool  # True if fill_id was synthesized (not from Kalshi)
    confirmed_by_rest: bool
    is_live: bool  # True if LIVE trade with real money
```

**Position Computation** (fills_ledger.py:1572-1591):
```python
def compute_net_positions(self) -> Dict[str, Dict[str, Any]]:
    positions: Dict[str, Dict[str, Any]] = {}
    for market_ticker in self._fills_by_market.keys():
        if _is_test_ticker(market_ticker):
            continue  # PRODUCTION FIX: Skip test tickers
        pos = self.compute_position_from_fills(market_ticker)
        if pos:  # Only include non-zero positions
            positions[market_ticker] = pos
    return positions
```

**Reconciliation Status** (fills_ledger.py:124-129):
```python
class ReconciliationStatus(Enum):
    OK = "ok"
    DEGRADED = "degraded"  # Minor discrepancies (< 5%)
    BROKEN = "broken"      # Significant divergence
    UNKNOWN = "unknown"
```

#### 2.2.2 Position Cache (Real-time)
**Location**: `merid/event_venues/kalshi/position_cache.py`
**Update Path**: WebSocket fills → `on_fill()` → cache update
**Reconciliation**: `sync_from_rest()` resets cache from REST API
**Purpose**: Low-latency position data for trading decisions

**Key Features**:
- TP target preservation during reconciliation
- Hedge vs alpha position tracking via `fill_source`
- Mutex protection for concurrent WebSocket events
- Stale TP target GC every 100 registrations

#### 2.2.3 Portfolio Engine (Event-Sourced)
**Location**: `merid/event_venues/kalshi/portfolio_engine.py`
**Event Log**: `PortfolioEventLog` (SQLite append-only)
**Computation**: Replays events in sequence to compute current state
**Integration**: `PortfolioReconciler` compares engine snapshot to Kalshi API

**Event Types** (portfolio_models.py:182-194):
```python
class PortfolioEvent:
    event_id: str
    sequence_id: int  # Monotonically increasing
    event_type: EventType  # FILL, ORDER_CREATED, ORDER_FILLED, SETTLEMENT, BANKROLL
    account_id: str
    timestamp: datetime
    data: Dict[str, Any]
```

### 2.3 Reconciliation Input Sources

#### 2.3.1 Venue Reconciliation (Primary)
**Location**: `merid/reconciliation/venue_reconciler.py`
**Function**: `reconcile_venue(venue_name)`
**Inputs**:
- **MERID Side**: `get_paper_engine().get_positions()` filtered by `_is_kalshi_ticker()`
- **Venue Side**: `venue_adapter.get_positions()` → Kalshi API `/portfolio/positions`

**Symbol Filtering** (venue_reconciler.py:518-548):
```python
def _is_kalshi_ticker(symbol: str) -> bool:
    if not symbol:
        return False
    upper = symbol.upper()
    if "TEST" in upper or "MOCK" in upper or "SIM" in upper:
        return False
    _CRYPTO_EXCLUDES = ("PERP", "FUT", "SWAP", "SPOT")
    if any(seg in _CRYPTO_EXCLUDES for seg in upper.split("-")):
        return False
    if upper.startswith("KX"):
        return True
    if "-" in symbol and len(symbol) >= 10:
        if re.search(r'\d{2}[A-Z]{3}|\d{2}Q\d', upper):
            return True
    return False
```

**Matching Logic** (venue_reconciler.py:374-393):
```python
for symbol in all_symbols:
    v = venue_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})
    m = merid_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})
    
    # Skip false positives: both quantities are 0
    if abs(v["qty"]) < 0.001 and abs(m["qty"]) < 0.001:
        continue
    
    if abs(v["qty"] - m["qty"]) > 0.001 or symbol not in venue_map or symbol not in merid_map:
        disc = VenuePositionDiscrepancy(...)
        discrepancies.append(disc)
```

#### 2.3.2 Portfolio Reconciliation (Secondary)
**Location**: `merid/event_venues/kalshi/portfolio_reconciliation.py`
**Function**: `PortfolioReconciler.reconcile_once()`
**Inputs**:
- **Internal**: `PortfolioEngine.get_snapshot(account_id)`
- **Kalshi**: `BankrollService.get_summary()` (v2 unified bankroll service)

**Comparison** (portfolio_reconciliation.py:109-150):
```python
# Get internal snapshot
internal_snapshot = self._engine.get_snapshot(account_id)

# Fetch Kalshi state
summary = await self._bankroll_service.get_summary(caller_module="portfolio_reconciliation")
kalshi_balance = BankrollResult(
    success=True,
    balance_cents=int(summary.available_cash_usd * 100),
    portfolio_value_cents=await self._bankroll_service.get_portfolio_value_cents(),
    equity_usd=summary.equity_usd,
    timestamp=summary.as_of.timestamp(),
)
```

**Tolerances** (portfolio_reconciliation.py:43-61):
```python
_CASH_TOLERANCE_CENTS = 1  # Configurable via env
_PNL_TOLERANCE_CENTS = 10  # Configurable via env
_POSITION_TOLERANCE_CONTRACTS = 0  # Exact match required
_DISCREPANCY_PERSISTENCE_CYCLES = 2  # Alert after 2 consecutive discrepancies
```

### 2.4 Critical Gaps and Risks

#### Gap 1: Unit Conversion Drift
**Risk**: Multiple conversion points between dollars/cents
**Locations**:
- `KalshiPosition.avg_price` (cents) vs `BackendPosition.avg_price_dollars` (dollars)
- `KalshiFill.yes_price_dollars` (dollars) vs internal cents
- `VenuePosition.average_entry_price` (dollars) vs internal cents

**Impact**: Position mismatches due to rounding errors
**Mitigation**: Use consistent cents internally, convert only at API boundaries

#### Gap 2: Test Ticker Filtering
**Risk**: Test positions bleeding into production
**Current Mitigation**:
- `fills_ledger.compute_net_positions()` filters test tickers (fills_ledger.py:1584)
- `position_cache.sync_from_rest()` filters test tickers (position_cache.py:450)
- `_is_test_ticker()` function checks for "TEST", "KXTEST", short codes

**Gap**: Test detection logic may miss edge cases
**Recommendation**: Expand test ticker patterns, add explicit test account ID check

#### Gap 3: Subaccount Isolation
**Risk**: Cross-subaccount position aggregation
**Current State**: Subaccount fields exist but not enforced in reconciliation
**Impact**: Multi-subaccount deployments may have incorrect position calculations
**Recommendation**: Add subaccount filtering to reconciliation logic

#### Gap 4: Phantom Position Detection
**Risk**: Closed positions (contracts=0) persisting in cache
**Current Mitigation**: `sync_from_rest()` filters closed positions (position_cache.py:454)
**Gap**: WebSocket path may not filter closed positions
**Recommendation**: Add closed position filter to `on_fill()` path

---

## Step 3: Reconciliation Logic Audit

### 3.1 Reconciliation Function Signatures

#### 3.1.1 reconcile_venue()
**Location**: `merid/reconciliation/venue_reconciler.py:289-411`
**Signature**: `def reconcile_venue(venue_name: str) -> List[VenuePositionDiscrepancy]`
**Purpose**: Reconcile MERID positions against a single venue
**Flow**:
1. Try Kalshi venue adapter (fail-closed in live mode)
2. Fallback to trading registry adapter
3. Get venue positions via `adapter.get_positions()`
4. Get MERID positions via `_get_merid_positions(venue_name)`
5. Compare positions by symbol
6. Generate discrepancies for mismatches
7. Update global reconciliation state via `_mark_recon_done()`

**Fail-Closed Behavior** (venue_reconciler.py:293-317):
```python
if venue_name == "kalshi":
    try:
        _kadapter = get_kalshi_venue_adapter()
    except Exception as _ke:
        _mode = os.environ.get("MERID_PM_TRADING_MODE", "paper").lower()
        if _mode == "live":
            discrepancies.append(VenuePositionDiscrepancy(
                venue=venue_name,
                symbol=_KALSHI_UNREACHABLE_SYMBOL,
                severity="critical",
                reason=f"venue adapter raised: {_ke}",
            ))
        _mark_recon_done(discrepancies)
        return discrepancies
```

#### 3.1.2 reconcile_all_venues()
**Location**: `merid/reconciliation/venue_reconciler.py:414-435`
**Signature**: `def reconcile_all_venues(venues: Optional[List[str]] = None) -> List[VenuePositionDiscrepancy]`
**Purpose**: Reconcile across all configured venues
**Flow**:
1. Determine venues from config or default to `["kalshi"]`
2. Call `reconcile_venue()` for each venue
3. Aggregate discrepancies
4. Update global state with `_mark_recon_done()`
5. Persist report to disk

**Venue Selection** (venue_reconciler.py:417-426):
```python
if venues is None:
    try:
        venues = get_paper_config().reconciliation_venues()
    except (ImportError, Exception):
        venues = []
    # Always include kalshi — it is the only live venue in this deployment
    if not venues or venues == ["alpaca"]:
        venues = ["kalshi"]
```

#### 3.1.3 has_critical_discrepancies()
**Location**: `merid/reconciliation/venue_reconciler.py:438-446`
**Signature**: `def has_critical_discrepancies() -> bool`
**Purpose**: Check if last reconciliation found critical discrepancies
**Fail-Closed**: Returns `True` if reconciliation has never run
**Usage**: Called by `ExecutionGate` to block trading on critical mismatches

```python
def has_critical_discrepancies() -> bool:
    with _recon_lock:
        if not _reconciliation_has_run:
            return True  # Fail-closed
        return any(d.severity == "critical" for d in _last_discrepancies)
```

### 3.2 Discrepancy Matching Rules

#### 3.2.1 Position Quantity Matching
**Tolerance**: `0.001` contracts (venue_reconciler.py:383)
**Logic**: `abs(v["qty"] - m["qty"]) > 0.001`
**Symbol Filtering**: Only reconcile symbols that appear on at least venue side, plus MERID-side positions matching Kalshi ticker patterns
**Fresh Start Detection**: Both quantities < 0.001 is skipped (benign)

#### 3.2.2 Severity Assignment
**Critical** (venue_reconciler.py:384-392):
- Venue unreachable in live mode
- Genuine position mismatch (both sides non-zero with significant delta)
- One side has position, other has zero (phantom position)

**Warning** (execution_gate.py:230-236):
- Reconciliation not yet run (normal at startup)
- Both sides zero (fresh start)

**Info**:
- Minor drifts below critical threshold

#### 3.2.3 Phantom Kill Switch
**Location**: `merid/reconciliation/venue_reconciler.py:120-189`
**Trigger**: Genuine phantom positions detected
**Criteria** (venue_reconciler.py:146-160):
```python
is_true_phantom = False

if d.merid_qty != 0.0 and d.venue_qty != 0.0:
    if abs(d.delta_qty) > 0.01:  # Significant delta
        is_true_phantom = True
elif d.merid_qty == 0.0 and d.venue_qty != 0.0:
    is_true_phantom = True  # Venue has position but MERID has none
elif d.merid_qty != 0.0 and d.venue_qty == 0.0:
    is_true_phantom = True  # MERID has position but venue has none
```

**Exclusions**:
- Synthetic entries (venue unreachable is dependency issue, not phantom position)
- Transient 5xx/timeout errors
- Missing paper engine
- Missing non-Kalshi adapter

**Clearing**: Only via `clear_phantom_kill_switch()` with operator review and audit trail

### 3.3 Reconciliation State Management

#### 3.3.1 Global State Variables
**Location**: `merid/reconciliation/venue_reconciler.py:1-100`
```python
_reconciliation_has_run: bool = False
_last_discrepancies: List[VenuePositionDiscrepancy] = []
_last_reconciliation_ts: float = 0.0
_phantom_kill_switch: bool = False
_phantom_kill_reason: str = ""
_phantom_kill_timestamp: float = 0.0
_phantom_positions: List[str] = []
```

**Thread Safety**: Protected by `_recon_lock` (threading.Lock)

#### 3.3.2 State Update Flow
1. `reconcile_venue()` completes → returns discrepancies
2. `reconcile_all_venues()` aggregates → calls `_mark_recon_done()`
3. `_mark_recon_done()` updates global state under lock
4. `_evaluate_phantom_kill_locked()` evaluates phantom kill condition
5. `_persist_report()` saves report to disk

### 3.4 Reconciliation Frequency

#### 3.4.1 Startup Reconciliation
**Location**: `web/main.py:4880-4949`
**Trigger**: Background task during startup
**Frequency**: One-time
**Implementation**: `asyncio.create_task(_startup_reconciliation_async())`
**Timeout**: Runs in thread pool executor to avoid blocking startup

#### 3.4.2 Periodic Reconciliation
**Location**: `web/main.py`
**Trigger**: Background loop
**Frequency**: Every 300s (5 minutes)
**Implementation**: `_kalshi_recon_loop_async()`

#### 3.4.3 Fills Ledger Reconciliation
**Location**: `merid/event_venues/kalshi/fills_poller.py:310-320`
**Trigger**: Background loop
**Frequency**: Every 60s
**Purpose**: Compare cache vs ledger positions
**Tolerance**: `_CACHE_LEDGER_DIVERGENCE_THRESHOLD = 5` contracts

### 3.5 Critical Logic Gaps

#### Gap 1: Symbol Filtering False Positives
**Risk**: Cross-domain false positives (e.g., crypto BTC position flagged as Kalshi discrepancy)
**Current Mitigation**: `_is_kalshi_ticker()` filters out generic symbols
**Gap**: Regex pattern may miss valid Kalshi tickers or include invalid ones
**Recommendation**: Expand test coverage for ticker pattern matching

#### Gap 2: Pagination Edge Cases
**Risk**: Missing positions when pagination hits max_pages limit
**Current Limit**: 10 pages (venue_reconciler.py:2869)
**Gap**: No alert when max_pages hit
**Recommendation**: Add warning log when max_pages limit reached

#### Gap 3: Concurrent Reconciliation
**Risk**: Multiple reconciliation runs overlapping
**Current Mitigation**: `_recon_lock` protects global state
**Gap**: No lock on per-venue reconciliation
**Recommendation**: Add per-venue lock to prevent concurrent API calls

---

## Step 4: Downstream Audit - Flag Lifecycle, Gate Semantics, Multi-Venue Interactions

### 4.1 Execution Gate Integration

#### 4.1.1 Gate Check Location
**Location**: `core/execution_gate.py:217-298`
**Check Order**:
1. Kill switch check (lines 200-215)
2. Kalshi venue reconciliation check (lines 217-265)
3. Fills ledger reconciliation check (lines 267-298)

#### 4.1.2 Reconciliation Gate Logic
**Import** (execution_gate.py:222):
```python
from merid.reconciliation import has_critical_discrepancies as kalshi_has_critical, get_last_discrepancies
```

**Fail-Closed Handling** (execution_gate.py:226-236):
```python
if not discrepancies:
    # has_critical_discrepancies() is fail-closed: returns True when
    # reconciliation has never run (empty list). This is normal at startup
    # and should not hard-block trading — downgrade to a transient warning.
    reasons.append(BlockReason(
        source="reconciliation",
        severity="warning",
        message="Kalshi reconciliation not yet run (normal at startup)",
        details="First reconciliation cycle will clear this automatically",
        hint=REMEDIATION_HINTS["reconciliation"],
    ))
```

**Genuine Critical Handling** (execution_gate.py:238-263):
```python
genuine_critical = []
for d in discrepancies:
    if d.severity != "critical":
        continue
    if d.merid_qty == 0.0 and d.venue_qty == 0.0:
        continue  # Fresh start, not a real mismatch
    genuine_critical.append(d)

if not genuine_critical:
    reasons.append(BlockReason(
        source="reconciliation",
        severity="warning",
        message="Kalshi venue reconciliation: no positions to reconcile (fresh start)",
        details="Both MERID and venue report zero positions — benign state",
        hint=REMEDIATION_HINTS["reconciliation"],
    ))
else:
    reasons.append(BlockReason(
        source="reconciliation",
        severity=kalshi_recon_severity,  # "warning" if kalshi_demo else "critical"
        message="Kalshi venue reconciliation found critical discrepancies",
        details=f"{len(genuine_critical)} genuine position mismatches between MERID and Kalshi venue",
        hint=REMEDIATION_HINTS["reconciliation"],
    ))
```

**Demo Mode Downgrade** (execution_gate.py:220):
```python
kalshi_recon_severity = "warning" if kalshi_demo else "critical"
```

#### 4.1.3 Fills Ledger Reconciliation Gate
**Location**: `core/execution_gate.py:267-298`
**Purpose**: Separate from venue-level reconciliation, checks fills ledger internal consistency
**Status Check** (execution_gate.py:273-296):
```python
from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
_ledger = get_fills_ledger()
_fl_recon = _ledger.get_reconciliation_status()
_fl_status = str(_fl_recon.get("status", "unknown"))

if _fl_status == "broken":
    _fl_severity = "warning" if kalshi_demo else "critical"
    reasons.append(BlockReason(
        source="fills_ledger_reconciliation",
        severity=_fl_severity,
        message="Fills ledger reconciliation BROKEN — positions unreliable",
        details=f"fills_ledger reports reconciliation_status=broken",
        hint=REMEDIATION_HINTS["fills_ledger_reconciliation"],
    ))
elif _fl_status == "degraded":
    reasons.append(BlockReason(
        source="fills_ledger_reconciliation",
        severity="warning",
        message="Fills ledger reconciliation degraded — minor divergences detected",
        details=f"divergences={_fl_recon.get('divergences', [])}",
        hint=REMEDIATION_HINTS["fills_ledger_reconciliation"],
    ))
```

### 4.2 Flag Lifecycle

#### 4.2.1 Startup State
- **Initial**: `_reconciliation_has_run = False`
- **Gate Behavior**: `has_critical_discrepancies()` returns `True` (fail-closed)
- **Gate Severity**: "warning" (downgraded from critical)
- **Duration**: Until first reconciliation completes (typically < 30s)

#### 4.2.2 Normal Operation
- **State**: `_reconciliation_has_run = True`, `_last_discrepancies = []`
- **Gate Behavior**: `has_critical_discrepancies()` returns `False`
- **Gate Severity**: No block reason
- **Duration**: Until next discrepancy detected

#### 4.2.3 Discrepancy Detected
- **State**: `_last_discrepancies` populated with mismatches
- **Gate Behavior**: `has_critical_discrepancies()` checks severity
- **Gate Severity**: 
  - Critical: "critical" (blocks trading in live mode)
  - Warning: "warning" (allows trading but alerts)
  - Info: logged only

#### 4.2.4 Phantom Kill Switch
- **Trigger**: Genuine phantom positions detected
- **State**: `_phantom_kill_switch = True`
- **Duration**: Until operator clears via `clear_phantom_kill_switch()`
- **Gate Impact**: Not directly checked by execution gate (separate mechanism)
- **Clearing**: Requires operator review and audit trail

### 4.3 Multi-Venue Interactions

#### 4.3.1 Current Deployment
**Venues**: Kalshi only (single-venue deployment)
**Configuration**: `reconciliation_venues()` defaults to `["kalshi"]`
**Fallback**: Old "alpaca" fallback removed (venue_reconciler.py:425)

#### 4.3.2 Cross-Venue Filtering
**Purpose**: Prevent cross-domain false positives
**Implementation**: `_is_kalshi_ticker()` filters generic symbols (BTC, ETH, AAPL, SPY)
**Pattern Matching**: 
  - KX prefix (Kalshi exchange)
  - Hyphens + date/period segment (DDMON, DDMONYY, YYQ#)
  - Excludes PERP, FUT, SWAP, SPOT

#### 4.3.3 Future Multi-Venue Considerations
**Gap**: No explicit multi-venue position aggregation
**Risk**: Cross-venue exposure not tracked in reconciliation
**Recommendation**: Design multi-venue reconciliation strategy before adding new venues

### 4.4 Gate State Transitions

```
[STARTUP]
  ↓
_reconciliation_has_run = False
  ↓
has_critical_discrepancies() = True (fail-closed)
  ↓
Gate Severity: "warning" (downgraded)
  ↓
[RECONCILIATION COMPLETE]
  ↓
_reconciliation_has_run = True
_last_discrepancies = []
  ↓
has_critical_discrepancies() = False
  ↓
Gate Severity: No block
  ↓
[DISCREPANCY DETECTED]
  ↓
_last_discrepancies populated
  ↓
has_critical_discrepancies() = True (if critical)
  ↓
Gate Severity: "critical" (blocks trading)
```

### 4.5 Critical Downstream Gaps

#### Gap 1: Gate Severity Inconsistency
**Risk**: Demo mode downgrade may hide critical issues
**Current Behavior**: Demo mode downgrades critical to warning
**Gap**: No clear distinction between demo and live reconciliation expectations
**Recommendation**: Separate reconciliation policies for demo vs live

#### Gap 2: Fills Ledger Gate Not Integrated
**Risk**: Fills ledger BROKEN status doesn't block trading in all paths
**Current Behavior**: Checked in execution gate but may be bypassed
**Recommendation**: Ensure all trading paths check fills ledger status

#### Gap 3: No Recovery Path
**Risk**: No automated recovery from critical discrepancies
**Current Behavior**: Manual intervention required
**Recommendation**: Design automated recovery (e.g., force_align_from_venue)

---

## Step 5: External Expectations - Kalshi API Posture, Frequency, Audit Trail

### 5.1 Kalshi API Posture

#### 5.1.1 Rate Limits
**Documentation**: https://docs.kalshi.com/api-reference/portfolio/get-positions
**Current Implementation**: No explicit rate limiting in reconciliation code
**Risk**: Excessive API calls may trigger rate limits
**Recommendation**: Add rate limiting to reconciliation polling

#### 5.1.2 Pagination Requirements
**Requirement**: Cursor-based pagination required for accounts with many positions
**Current Implementation**: 
  - `limit=100` per page
  - Max 10 pages (safety limit)
  - Cursor-based pagination (client.py:2866)
**Gap**: No alert when max_pages hit
**Recommendation**: Add warning log and increase max_pages limit

#### 5.1.3 Authentication
**Method**: RSA signature authentication
**Implementation**: `client_v2.py:161-186`
**Key Sources**:
  - `KALSHI_API_KEY_ID` (generic)
  - `KALSHI_LIVE_API_KEY_ID` (live-specific)
  - `KALSHI_DEMO_API_KEY_ID` (demo-specific)
**Gap**: No key rotation mechanism
**Recommendation**: Design key rotation strategy

### 5.2 Reconciliation Frequency

#### 5.2.1 Current Frequencies
| Component | Frequency | Configurable Via |
|-----------|-----------|------------------|
| Startup reconciliation | One-time | N/A |
| Periodic reconciliation | 300s (5 min) | N/A (hardcoded) |
| Fills polling | 20s | `MERID_FILLS_POLL_INTERVAL_SEC` |
| Fills reconciliation | 60s | `MERID_FILLS_RECONCILE_INTERVAL_SEC` |
| Portfolio reconciliation | 300s | `MERID_PORTFOLIO_RECONCILIATION_INTERVAL_SECONDS` |

#### 5.2.2 Kalshi Expectations
**Documentation**: https://help.kalshi.com/en/articles/13823854-kalshi-api
**Recommendation**: Poll positions every 60s (1 minute)
**Current Status**: 300s (5 minutes) - less frequent than recommended
**Gap**: Reconciliation may miss position changes for up to 5 minutes
**Recommendation**: Reduce periodic reconciliation to 60s to match Kalshi recommendation

### 5.3 Audit Trail

#### 5.3.1 Reconciliation Report Persistence
**Location**: `merid/reconciliation/venue_reconciler.py:461-473`
**Path**: `_REPORT_PATH` (default: `data/reconciliation_report.json`)
**Content**:
```python
{
    "timestamp": time.time(),
    "count": len(discrepancies),
    "critical": sum(1 for d in discrepancies if d.severity == "critical"),
    "discrepancies": [d.to_dict() for d in discrepancies],
}
```
**Retention**: Overwritten on each reconciliation (no history)
**Gap**: No historical reconciliation data
**Recommendation**: Implement time-series reconciliation history

#### 5.3.2 Phantom Kill Switch Audit Trail
**Location**: `merid/reconciliation/venue_reconciler.py:209-287`
**Clearing Function**: `clear_phantom_kill_switch(operator, reason)`
**Audit Fields**:
- Operator who cleared
- Reason for clearing
- Duration of armed state
- Positions cleared
- Timestamp

**Session Log Integration** (venue_reconciler.py:260-276):
```python
from core.session_log import record_event
record_event(
    category="reconciliation",
    severity="critical",
    title="Phantom kill switch cleared",
    detail=f"Cleared by {operator} after {duration:.0f}s",
    hint="Verify reconciliation is clean before resuming full trading.",
    metadata={
        "operator": operator,
        "duration_sec": duration,
        "positions_count": len(positions_cleared),
        "clear_reason": reason,
    },
)
```

#### 5.3.3 Fill Ledger Audit Trail
**Location**: `merid/event_venues/kalshi/fills_ledger.py`
**Database**: SQLite with append-only fills
**Audit Fields per Fill**:
- `fill_id` (primary key)
- `ingestion_source` ("http_poller", "websocket", "backfill")
- `ingested_at` (timestamp)
- `agent_id` (which agent generated the intent)
- `intent_id` (link to intent record)
- `decision_trace_id` (end-to-end audit)
- `is_live` (LIVE vs PAPER tracking)
- `derived_id` (synthesized vs real Kalshi fill ID)
- `confirmed_by_rest` (HTTP confirmation)

**Gap**: No fill modification history (only append)
**Recommendation**: Current append-only design is correct; no changes needed

### 5.4 SLA Documentation

#### 5.4.1 Reconciliation SLA (Proposed)
| Metric | Target | Current Status |
|--------|--------|----------------|
| Reconciliation frequency | 60s | 300s (gap) |
| Position mismatch tolerance | 0 contracts | 0.001 contracts |
| Cash tolerance | 1 cent | 1 cent (OK) |
| PnL tolerance | 10 cents | 10 cents (OK) |
| Max reconciliation latency | 10s | Unknown |
| Audit trail retention | 90 days | 0 days (gap) |

#### 5.4.2 Alerting Requirements
**Current Alerting**:
- Critical discrepancies: Logged at warning level
- Phantom kill switch: Logged at critical level
- Fills ledger BROKEN: Logged at warning level

**Gap**: No external alerting (email, Slack, PagerDuty)
**Recommendation**: Integrate with alertmanager for critical discrepancies

### 5.5 External Integration Points

#### 5.5.1 Kalshi Help Center
**Documentation**: https://help.kalshi.com/en/articles/13823854-kalshi-api
**Key Points**:
- API rate limits: 100 requests per minute
- Authentication: RSA signature required
- Position polling: Recommended every 60s
- WebSocket: Real-time fill events available

**Gap**: No explicit rate limiting in MERID code
**Recommendation**: Implement rate limiting to stay within 100 req/min

#### 5.5.2 Kalshi API Documentation
**Documentation**: https://docs.kalshi.com/api-reference/portfolio/get-positions
**Key Points**:
- Cursor-based pagination required
- Returns `market_positions` and `event_positions`
- Fields: `ticker`, `side`, `count`, `avg_price`, `total_cost`, `unrealized_pnl`, `realized_pnl`

**Current Implementation**: Correctly implements cursor-based pagination
**Gap**: No handling of API changes (version not locked)
**Recommendation**: Lock API version in KalshiConfig

### 5.6 Critical External Gaps

#### Gap 1: Reconciliation Frequency
**Risk**: 5-minute reconciliation may miss position changes
**Kalshi Recommendation**: Poll positions every 60s
**Current Status**: 300s periodic reconciliation
**Recommendation**: Reduce to 60s to match Kalshi recommendation

#### Gap 2: Audit Trail Retention
**Risk**: No historical reconciliation data for post-mortem analysis
**Current Status**: Report overwritten on each reconciliation
**Recommendation**: Implement time-series reconciliation history with 90-day retention

#### Gap 3: Rate Limiting
**Risk**: Excessive API calls may trigger Kalshi rate limits
**Kalshi Limit**: 100 requests per minute
**Current Status**: No explicit rate limiting
**Recommendation**: Implement rate limiting to stay within limits

---

## Summary and Recommendations

### Critical Findings

1. **Unit Conversion Drift**: Multiple conversion points between dollars/cents create risk of position mismatches
2. **Reconciliation Frequency**: 5-minute reconciliation exceeds Kalshi's 60s recommendation
3. **Audit Trail**: No historical reconciliation data for post-mortem analysis
4. **Rate Limiting**: No explicit rate limiting to stay within Kalshi's 100 req/min limit
5. **Test Ticker Filtering**: Test position detection logic may miss edge cases

### High-Priority Recommendations

1. **Standardize on Cents**: Use cents internally for all calculations, convert only at API boundaries
2. **Reduce Reconciliation Frequency**: Change periodic reconciliation from 300s to 60s
3. **Implement Audit History**: Add time-series reconciliation history with 90-day retention
4. **Add Rate Limiting**: Implement rate limiting to stay within Kalshi's 100 req/min limit
5. **Expand Test Detection**: Expand test ticker patterns and add explicit test account ID check

### Medium-Priority Recommendations

1. **Pagination Alerting**: Add warning log when max_pages limit reached
2. **Concurrent Reconciliation Locking**: Add per-venue lock to prevent concurrent API calls
3. **Demo vs Live Policies**: Separate reconciliation policies for demo vs live mode
4. **Automated Recovery**: Design automated recovery path for critical discrepancies
5. **Subaccount Isolation**: Add subaccount filtering to reconciliation logic

### Low-Priority Recommendations

1. **Multi-Venue Strategy**: Design multi-venue reconciliation strategy before adding new venues
2. **Key Rotation**: Design key rotation strategy for RSA authentication
3. **API Version Locking**: Lock API version in KalshiConfig to prevent breaking changes
4. **External Alerting**: Integrate with alertmanager for critical discrepancies

---

## When Kalshi Reconciliation Breaks - Runbook

### Symptoms
- Gate stuck BLOCKED for Kalshi
- Recon metrics show rising discrepancy counts
- E2E tests failing in CI (`pytest -m kalshi_e2e`)
- Live drift monitor alerts on unexpected discrepancies

### Immediate Checks

#### 1. Run E2E Tests Locally
```bash
pytest tests/event_venues/kalshi/test_btc_15m_reconciliation_e2e.py -v -m kalshi_e2e
```
- Identify which test fails (pagination, unit conversion, reconciliation, gate)
- Check if failure is consistent across runs (flaky vs genuine issue)

#### 2. Check Recon/Gate Metrics
```python
from merid.reconciliation.reconciliation_metrics import get_reconciliation_metrics_collector

collector = get_reconciliation_metrics_collector()
summary = await collector.get_summary()
print(summary)
```
- Check `recon_run_duration_seconds` - sudden spikes indicate API latency issues
- Check `discrepancy_count` per asset - identify which asset is drifting
- Check `gate_state` - verify current state and recent transitions
- Check `block_reason_counts` - see which reasons are triggering blocks

#### 3. Verify Kalshi API Status
- Check Kalshi status page: https://status.kalshi.com
- Verify API rate limits: `GET /portfolio/api-limits` (if available)
- Check for recent Kalshi announcements or API changes
- Verify authentication keys are valid and not expired

### Triage Paths

#### Path A: Tests Fail But Live Recon Looks Fine
**Indicates**: Fixture/spec mismatch with intentional contract change

**Actions**:
1. Identify which test assertion is failing
2. Determine if the change is intentional (e.g., Kalshi added new field)
3. Update fixtures in `tests/event_venues/kalshi/test_btc_15m_reconciliation_e2e.py`
4. Update canonical spec in test file header if contract changed
5. Run tests again to verify fix
6. Document change in this audit doc

**Example**:
```python
# If Kalshi adds new field to position response
# Update KalshiPositionFixture to include new field
@dataclass
class KalshiPositionFixture:
    ticker: str
    side: str
    count: int
    avg_price_dollars: Decimal
    total_cost_dollars: Decimal
    unrealized_pnl_dollars: Decimal
    new_field: Optional[str] = None  # Add this
```

#### Path B: Tests Pass But Live Recon Shows Drift
**Indicates**: Kalshi API behavior change not captured in fixtures

**Actions**:
1. Run live drift monitor to get detailed drift info:
   ```bash
   python scripts/kalshi_live_drift_monitor.py --subaccount 0 --minutes 30 --once
   ```
2. Check logs for API response anomalies (new fields, changed structure)
3. Identify which asset is showing discrepancies
4. Pull raw API response to understand change:
   ```python
   from merid.event_venues.kalshi.client import KalshiClient
   client = KalshiClient()
   result = await client.get_positions_result(subaccount=0)
   print(result.data)
   ```
5. Update client code to handle new API structure
6. Add new test case to cover the change
7. Document API change in this audit doc

#### Path C: Kalshi-Side Change Identified (Schema, Limits, etc.)
**Indicates**: Kalshi made breaking change to their API or policies

**Actions**:
1. Check Kalshi changelog: https://news.kalshi.com
2. Review Kalshi docs for updated requirements: https://docs.kalshi.com
3. Update client code to comply with new requirements
4. Update reconciliation logic if matching rules changed
5. Update gate logic if severity thresholds changed
6. Update all affected test fixtures
7. Run full E2E test suite to verify
8. Update this audit doc with new contract details
9. Update canonical spec in test file header

**Common Kalshi Changes**:
- Rate limit changes (update polling frequency)
- New required fields in API responses (update data models)
- Pagination changes (update max_pages limit)
- Authentication changes (rotate keys, update signature logic)

### Recovery Procedures

#### For Critical Discrepancies
1. Stop trading immediately (gate should auto-block)
2. Investigate discrepancy source using metrics and logs
3. If Kalshi-side issue, wait for Kalshi resolution
4. If MERID-side issue, fix bug and redeploy
5. Run reconciliation manually to verify fix:
   ```python
   from merid.reconciliation.venue_reconciler import reconcile_venue
   discrepancies = reconcile_venue("kalshi")
   print(discrepancies)
   ```
6. Clear phantom kill switch if triggered (only after root cause resolved)
7. Monitor gate state transition from BLOCKED to OPEN

#### For Phantom Kill Switch
1. Investigate phantom positions using metrics
2. Verify positions are truly phantom (not API latency issue)
3. Check if positions settled recently (may cause transient phantom)
4. If false positive, clear kill switch with documented reason
5. If true phantom, investigate fill ingestion path for missing fills
6. Run backfill to recover missing fills:
   ```python
   from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
   ledger = get_fills_ledger()
   await ledger.backfill_fills(days_back=7)
   ```
7. Reconcile again to verify positions align
8. Clear kill switch only after verification

### Prevention

#### Monitoring Setup
1. Enable reconciliation metrics in production (already implemented in `merid/reconciliation/reconciliation_metrics.py`)
2. Set up Grafana dashboard for:
   - Recon duration over time
   - Discrepancy count per asset
   - Gate state transitions
   - Block reason frequency
3. Configure alerts for:
   - Recon duration > 30s (indicates API issues)
   - Discrepancy count > 0 (indicates position drift)
   - Gate state = BLOCKED (trading blocked)
   - Phantom kill switch armed (critical issue)

#### Regular Maintenance
1. Run live drift monitor weekly:
   ```bash
   python scripts/kalshi_live_drift_monitor.py --subaccount 0 --minutes 1440 --once
   ```
2. Review reconciliation metrics monthly
3. Check Kalshi changelog monthly for API changes
4. Run full E2E test suite before major deployments
5. Keep fixtures in sync with latest Kalshi API responses

### Cross-References
- Test suite: `tests/event_venues/kalshi/test_btc_15m_reconciliation_e2e.py`
- Metrics module: `merid/reconciliation/reconciliation_metrics.py`
- Drift monitor: `scripts/kalshi_live_drift_monitor.py`
- Reconciliation logic: `merid/reconciliation/venue_reconciler.py`
- Gate logic: `core/execution_gate.py`
- Kalshi docs: https://docs.kalshi.com

---

## Appendix A: Data Models and Signatures

### A.1 Reconciliation Function Signatures

```python
# merid/reconciliation/venue_reconciler.py
def reconcile_venue(venue_name: str) -> List[VenuePositionDiscrepancy]
def reconcile_all_venues(venues: Optional[List[str]] = None) -> List[VenuePositionDiscrepancy]
def has_critical_discrepancies() -> bool
def get_last_reconciliation_ts() -> float
def get_last_discrepancies() -> List[VenuePositionDiscrepancy]
def force_align_from_venue(venue_name: str, user_id: str = "operator") -> Dict[str, Any]
def clear_phantom_kill_switch(operator: str = "system", reason: str = "") -> Dict[str, Any]
```

### A.2 Position Data Models

```python
# merid/event_venues/kalshi/models.py
@dataclass
class KalshiPosition:
    ticker: str
    side: str  # "yes" or "no"
    count: int
    avg_price: Decimal  # cents
    total_cost: Decimal
    unrealized_pnl: Optional[Decimal]
    realized_pnl: Optional[Decimal]
    created_at: Optional[datetime]

# merid/event_venues/kalshi/position_cache.py
class CachedPosition:
    market_id: str
    contracts: int
    side: str  # "yes" or "no"
    avg_price_cents: int
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    last_updated: datetime
    fill_source: str  # "alpha" or "hedge"
    client_order_id: Optional[str]
    take_profit_price_cents: Optional[int]
    stop_loss_price_cents: Optional[int]

# merid/event_venues/kalshi/portfolio_models.py
@dataclass(frozen=True)
class Position:
    position_id: str
    account_id: str
    ticker: str
    side: str  # "yes" or "no"
    quantity: int  # signed (positive=long, negative=short)
    avg_entry_price_cents: int
    cost_basis_cents: int
    realized_pnl_cents: int
    last_updated: datetime
```

### A.3 Fill Data Models

```python
# merid/event_venues/kalshi/fills_ledger.py
@dataclass
class KalshiFill:
    fill_id: str  # Kalshi's unique fill ID — THE primary key
    trade_id: Optional[str]
    order_id: Optional[str]
    market_ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count_fp: int  # Number of contracts (fixed-point integer)
    yes_price_dollars: Optional[Decimal]
    no_price_dollars: Optional[Decimal]
    fee_cost: Decimal
    proceeds_dollars: Optional[Decimal]
    client_order_id: Optional[str]
    subaccount_number: Optional[int]
    created_time: datetime
    ingestion_source: str  # "http_poller", "websocket", "backfill"
    ingested_at: datetime
    agent_id: Optional[str]
    intent_id: Optional[str]
    decision_trace_id: Optional[str]
    fill_source: str  # "alpha", "hedge", "manual"
    hedge_reason: Optional[str]
    hedge_pnl_cents: int
    related_alpha_fill_id: Optional[str]
    reconciled: bool
    reconciliation_ts: Optional[datetime]
    derived_id: bool
    confirmed_by_rest: bool
    is_live: bool
```

### A.4 Discrepancy Data Model

```python
# merid/reconciliation/venue_reconciler.py
@dataclass(frozen=True)
class VenuePositionDiscrepancy:
    venue: str
    symbol: str
    merid_qty: float
    venue_qty: float
    merid_entry_price: float
    venue_entry_price: float
    delta_qty: float
    delta_price: float
    severity: str  # "critical", "warning", "info"
    reason: str
    timestamp: float
```

---

**End of Audit**
