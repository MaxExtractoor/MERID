# Kalshi Function Signatures for Test Design

Representative function signatures from Kalshi client, reconciliation, and execution layers for designing BTC/ETH/SOL/XRP/DOGE 15-minute E2E test scenarios.

---

## 1. Kalshi Client Layer

### 1.1 Position Fetching

```python
# merid/event_venues/kalshi/client.py:2858-2899
async def get_positions_result(self) -> OperationResult[List[VenuePosition]]:
    """Get positions with explicit result.

    Supports cursor-based pagination to fetch all positions across multiple pages.
    Handles both market_positions and event_positions from Kalshi API.
    This is critical for accounts with many open positions.
    """
    all_positions: List[VenuePosition] = []
    cursor: Optional[str] = None
    total_latency = 0.0
    total_retries = 0
    max_pages = 10  # Safety limit to prevent runaway pagination

    for page in range(max_pages):
        params: Dict[str, Any] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        result = await self._request_with_resilience(
            "GET", "/portfolio/positions", params=params, operation_name="get_positions"
        )

        # Parse market_positions (if present)
        for pos_data in result.data.get("market_positions", []):
            position = self._parse_position(pos_data)
            if position:
                all_positions.append(self._to_venue_position(position))

        # Parse event_positions (if present)
        for pos_data in result.data.get("event_positions", []):
            position = self._parse_position(pos_data)
            if position:
                all_positions.append(self._to_venue_position(position))

        # Update cursor for next page
        cursor = result.data.get("cursor")
        if not cursor:
            break

    return OperationResult.ok(all_positions, latency_ms=total_latency, retries=total_retries)
```

### 1.2 Fill Fetching

```python
# merid/event_venues/kalshi/client.py:3226-3231
async def get_fills(
    self,
    limit: int = 200,
    since_ts: Optional[int] = None,
) -> OperationResult[List[Dict[str, Any]]]:
    """Get paginated fills with optional time filter.

    Args:
        limit: Number of fills per page (default 200)
        since_ts: Unix timestamp for time filter (optional)

    Returns:
        OperationResult containing list of fill dicts from Kalshi API
    """
```

```python
# merid/event_venues/kalshi/kalshi_rest_client.py:38-43
async def get_fills(
    self,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 100,
    cursor: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get fills with datetime range and cursor pagination.

    Args:
        start_time: Start of time range (optional)
        end_time: End of time range (optional)
        limit: Number of fills per page (default 100)
        cursor: Pagination cursor (optional)

    Returns:
        List of fill dicts from Kalshi API
    """
```

### 1.3 Balance Fetching

```python
# merid/event_venues/kalshi/client.py:2996-3000
async def get_balance_result(self) -> OperationResult[Dict[str, Decimal]]:
    """Get account balance with explicit result."""
    result = await self._request_with_resilience(
        "GET", "/portfolio/balance", operation_name="get_balance"
    )
    # Returns: {"USD": Decimal, "locked": Decimal, ...}
```

### 1.4 Position Parsing

```python
# merid/event_venues/kalshi/client.py (internal)
def _parse_position(self, pos_data: Dict[str, Any]) -> Optional[KalshiPosition]:
    """Parse Kalshi API position response to KalshiPosition dataclass.

    Key fields:
        ticker: str  # e.g., "KXBTC-26FEB24-50000"
        side: str  # "yes" or "no"
        count: int  # Number of contracts
        avg_price: Decimal  # Average entry price in dollars (0-1 range)
        total_cost: Decimal
        unrealized_pnl: Optional[Decimal]
        realized_pnl: Optional[Decimal]
    """
```

---

## 2. Fills Ledger Layer

### 2.1 HTTP Fill Ingestion

```python
# merid/event_venues/kalshi/fills_ledger.py:844-889
async def ingest_http_fills(
    self,
    fills: List[Dict[str, Any]],
    agent_map: Optional[Dict[str, str]] = None
) -> Tuple[int, List[str]]:
    """Ingest fills from HTTP /portfolio/fills endpoint.

    Args:
        fills: List of fill dicts from Kalshi API
        agent_map: Optional mapping of client_order_id -> agent_id

    Returns:
        (new_count, new_fill_ids) — IDs are new rows only (for bus/UI hooks)

    Behavior:
        - Idempotent upsert by fill_id
        - HTTP upsert over prior WS row (enriches without zeroing good data)
        - Confirms fills via confirmed_by_rest flag
        - Handles incomplete fills by deriving count from proceeds if needed
    """
    new_count = 0
    new_fill_ids: List[str] = []

    async with self._mutex:
        for raw in fills:
            fill = self._parse_fill(raw, "http_poller")
            if _is_test_fixture_fill(fill.fill_id):
                continue

            if fill.fill_id in self._fills:
                # HTTP upsert over prior WS row
                existing = self._fills[fill.fill_id]
                # Enrich without zeroing good data
                if fill.action in ("buy", "sell") and existing.action not in ("buy", "sell"):
                    existing.action = fill.action
                if not existing.confirmed_by_rest:
                    existing.confirmed_by_rest = True
                # Count: never replace positive with zero
                if fill.count_fp > 0:
                    existing.count_fp = fill.count_fp
            else:
                # New fill
                self._fills[fill.fill_id] = fill
                self._index_fill(fill)
                new_count += 1
                new_fill_ids.append(fill.fill_id)

    return new_count, new_fill_ids
```

### 2.2 WebSocket Fill Ingestion

```python
# merid/event_venues/kalshi/fills_ledger.py:1040-1109
async def ingest_ws_fill(self, fill_dict: Dict[str, Any]) -> bool:
    """Ingest a single fill from WebSocket.

    Args:
        fill_dict: Fill data from WebSocket message

    Returns:
        True if fill was ingested, False if duplicate or incomplete

    Behavior:
        - Idempotent upsert by fill_id
        - Incomplete fills (missing size/price) are rejected (HTTP will complete later)
        - Tracks deep OTM/ITM fills for deployment safety
        - Calls on_fill() for new fills (session-based PnL tracking)
    """
    fill = self._parse_fill(fill_dict, "websocket")

    async with self._mutex:
        if fill.fill_id in self._fills:
            return False  # Duplicate

        if fill.is_incomplete():
            # Incomplete WebSocket fills are expected - HTTP will complete later
            return False

        self._fills[fill.fill_id] = fill
        self._index_fill(fill)
        self._ws_ingested += 1

        # Track deep OTM/ITM fills for deployment safety
        if fill.price_cents < DEEP_OTM_THRESHOLD_CENTS:
            logger.warning(f"Deep OTM fill detected: {fill.market_ticker} @ {fill.price_cents}c")
        elif fill.price_cents > DEEP_ITM_THRESHOLD_CENTS:
            logger.warning(f"Deep ITM fill detected: {fill.market_ticker} @ {fill.price_cents}c")

        # Session-based PnL tracking
        self.on_fill(fill)

    return True
```

### 2.3 Position Computation

```python
# merid/event_venues/kalshi/fills_ledger.py:1572-1591
def compute_net_positions(self) -> Dict[str, Dict[str, Any]]:
    """Compute positions for all markets from fills ledger.

    Returns:
        Dict mapping market_ticker -> position dict:
        {
            "yes_contracts": int,
            "no_contracts": int,
            "net_contracts": int,  # yes - no
            "yes_cost": Decimal,
            "no_cost": Decimal,
            "fees": Decimal,
            "avg_price_cents": Optional[int],
        }

    Behavior:
        - Replays all fills in order
        - Filters out test tickers (PRODUCTION FIX)
        - Only includes non-zero positions
    """
    positions: Dict[str, Dict[str, Any]] = {}

    for market_ticker in self._fills_by_market.keys():
        # PRODUCTION FIX: Skip test tickers
        if _is_test_ticker(market_ticker):
            continue

        pos = self.compute_position_from_fills(market_ticker)
        if pos:  # Only include non-zero positions
            positions[market_ticker] = pos

    return positions
```

### 2.4 Fill Query

```python
# merid/event_venues/kalshi/fills_ledger.py:1308-1313
def get_fills(
    self,
    since: Optional[datetime] = None,
    market_ticker: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 500
) -> List[KalshiFill]:
    """Query fills with filters.

    Args:
        since: Filter fills after this timestamp
        market_ticker: Filter by market ticker
        agent_id: Filter by agent ID
        limit: Max number of fills to return

    Returns:
        List of KalshiFill objects matching filters
    """
```

---

## 3. Reconciliation Layer

### 3.1 Single Venue Reconciliation

```python
# merid/reconciliation/venue_reconciler.py:289-411
def reconcile_venue(venue_name: str) -> List[VenuePositionDiscrepancy]:
    """Reconcile MERID positions against a single venue.

    Args:
        venue_name: Venue name (e.g., "kalshi")

    Returns:
        List of VenuePositionDiscrepancy objects

    Flow:
        1. Try Kalshi venue adapter (fail-closed in live mode)
        2. Fallback to trading registry adapter
        3. Get venue positions via adapter.get_positions()
        4. Get MERID positions via _get_merid_positions(venue_name)
        5. Compare positions by symbol
        6. Generate discrepancies for mismatches
        7. Update global reconciliation state via _mark_recon_done()
    """
    discrepancies: List[VenuePositionDiscrepancy] = []

    # Get venue positions
    try:
        if venue_name == "kalshi":
            _kadapter = get_kalshi_venue_adapter()
            venue_positions = _kadapter.get_positions()
    except Exception as _ke:
        # Fail-closed in live mode
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

    # Get MERID positions
    merid_positions = _get_merid_positions(venue_name)

    # Build maps for comparison
    venue_map = {p["symbol"]: p for p in venue_positions}
    merid_map = {p["symbol"]: p for p in merid_positions}
    all_symbols = set(venue_map.keys()) | set(merid_map.keys())

    # Compare positions
    for symbol in all_symbols:
        v = venue_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})
        m = merid_map.get(symbol, {"qty": 0.0, "entry_price": 0.0})

        # Skip false positives: both quantities are 0
        if abs(v["qty"]) < 0.001 and abs(m["qty"]) < 0.001:
            continue

        # Check for mismatch
        if abs(v["qty"] - m["qty"]) > 0.001 or symbol not in venue_map or symbol not in merid_map:
            disc = VenuePositionDiscrepancy(
                venue=venue_name,
                symbol=symbol,
                merid_qty=m["qty"],
                venue_qty=v["qty"],
                merid_entry_price=m["entry_price"],
                venue_entry_price=v["entry_price"],
                delta_qty=v["qty"] - m["qty"],
                delta_price=v["entry_price"] - m["entry_price"],
                severity="critical" if abs(v["qty"] - m["qty"]) > 0.001 else "warning",
                reason=f"Quantity mismatch: MERID={m['qty']}, Venue={v['qty']}",
                timestamp=time.time(),
            )
            discrepancies.append(disc)

    _mark_recon_done(discrepancies)
    return discrepancies
```

### 3.2 Multi-Venue Reconciliation

```python
# merid/reconciliation/venue_reconciler.py:414-435
def reconcile_all_venues(venues: Optional[List[str]] = None) -> List[VenuePositionDiscrepancy]:
    """Reconcile across all configured venues.

    Args:
        venues: List of venue names (defaults to ["kalshi"])

    Returns:
        List of VenuePositionDiscrepancy from all venues

    Flow:
        1. Determine venues from config or default to ["kalshi"]
        2. Call reconcile_venue() for each venue
        3. Aggregate discrepancies
        4. Update global state with _mark_recon_done()
        5. Persist report to disk
    """
    if venues is None:
        try:
            venues = get_paper_config().reconciliation_venues()
        except (ImportError, Exception):
            venues = []
        # Always include kalshi — it is the only live venue
        if not venues or venues == ["alpaca"]:
            venues = ["kalshi"]

    all_discrepancies: List[VenuePositionDiscrepancy] = []
    for venue in venues:
        all_discrepancies.extend(reconcile_venue(venue))

    with _recon_lock:
        _last_discrepancies = all_discrepancies
        _reconciliation_has_run = True
        _last_reconciliation_ts = time.time()

    _persist_report(all_discrepancies)
    return all_discrepancies
```

### 3.3 Critical Discrepancy Check

```python
# merid/reconciliation/venue_reconciler.py:438-446
def has_critical_discrepancies() -> bool:
    """Check if the last reconciliation found any critical discrepancies.

    Returns True (fail-closed) if no reconciliation has ever completed.
    """
    with _recon_lock:
        if not _reconciliation_has_run:
            return True  # Fail-closed
        return any(d.severity == "critical" for d in _last_discrepancies)
```

### 3.4 Phantom Kill Switch

```python
# merid/reconciliation/venue_reconciler.py:209-287
def _evaluate_phantom_kill_locked(discrepancies: List[VenuePositionDiscrepancy]) -> None:
    """Evaluate phantom kill switch condition.

    Criteria for phantom position:
        - MERID has position, venue has zero (phantom long)
        - Venue has position, MERID has zero (phantom short)
        - Significant delta (> 0.01 contracts) between sides

    Exclusions:
        - Synthetic entries (venue unreachable is dependency issue)
        - Transient 5xx/timeout errors
        - Missing paper engine
        - Missing non-Kalshi adapter

    If phantom detected:
        - Sets _phantom_kill_switch = True
        - Records phantom positions
        - Logs session event
    """
    is_true_phantom = False

    for d in discrepancies:
        if d.merid_qty != 0.0 and d.venue_qty != 0.0:
            if abs(d.delta_qty) > 0.01:  # Significant delta
                is_true_phantom = True
        elif d.merid_qty == 0.0 and d.venue_qty != 0.0:
            is_true_phantom = True  # Venue has position but MERID has none
        elif d.merid_qty != 0.0 and d.venue_qty == 0.0:
            is_true_phantom = True  # MERID has position but venue has none

    if is_true_phantom:
        _phantom_kill_switch = True
        _phantom_kill_reason = f"Phantom positions detected: {len(discrepancies)}"
        _phantom_kill_timestamp = time.time()
        _phantom_positions = [d.symbol for d in discrepancies]

        # Log session event
        from core.session_log import record_event
        record_event(
            category="reconciliation",
            severity="critical",
            title="Phantom kill switch armed",
            detail=f"Phantom positions: {_phantom_positions}",
        )
```

---

## 4. Execution Gate Layer

### 4.1 Gate State Enum

```python
# core/execution_gate.py:44-48
class GateState(str, Enum):
    """Fine-grained execution gate state."""
    CLEAR = "clear"        # all checks pass — full trading
    LIMITED = "limited"    # warnings only — reduce/close positions OK, no new risk
    BLOCKED = "blocked"    # critical issues — no execution at all
```

### 4.2 Block Reason Dataclass

```python
# core/execution_gate.py:51-70
@dataclass(frozen=True)
class BlockReason:
    """Reason why execution is blocked or limited."""
    source: str  # "kill_switch", "reconciliation", "fills_ledger_reconciliation", etc.
    severity: str  # "critical", "warning"
    message: str
    details: str = ""
    hint: str = ""
```

### 4.3 Main Gate Check

```python
# core/execution_gate.py:72-180
def check_execution_gate(
    kalshi_demo: bool = False,
    ws_staleness_threshold_seconds: float = 30.0,
) -> Tuple[GateState, List[BlockReason]]:
    """Unified execution gate check.

    Checks in order:
        1. Kill switch status
        2. Kalshi venue reconciliation
        3. Fills ledger reconciliation
        4. WebSocket staleness
        5. PnL consistency

    Args:
        kalshi_demo: If True, downgrade critical to warning for demo mode
        ws_staleness_threshold_seconds: Threshold for WS staleness check

    Returns:
        (gate_state, block_reasons)
    """
    reasons: List[BlockReason] = []

    # 1. Kill switch check
    try:
        from merid.risk.kill_switches import get_risk_controller
        risk_controller = get_risk_controller()
        if risk_controller.is_killed():
            reasons.append(BlockReason(
                source="kill_switch",
                severity="critical",
                message="Kill switch is engaged",
                details=risk_controller._kill_details or str(risk_controller._kill_reason),
                hint=REMEDIATION_HINTS["kill_switch"],
            ))
    except Exception as exc:
        # Fail-closed: if we can't verify kill switch, assume it's triggered
        reasons.append(BlockReason(
            source="kill_switch",
            severity="critical",
            message="Kill switch check failed - assuming triggered",
            details=f"Exception: {exc}",
            hint="Check risk_controller module and system health.",
        ))

    # 2. Kalshi venue reconciliation
    kalshi_recon_severity = "warning" if kalshi_demo else "critical"
    try:
        from merid.reconciliation import has_critical_discrepancies as kalshi_has_critical, get_last_discrepancies
        if kalshi_has_critical():
            discrepancies = get_last_discrepancies()

            if not discrepancies:
                # Fail-closed: reconciliation hasn't run yet (normal at startup)
                reasons.append(BlockReason(
                    source="reconciliation",
                    severity="warning",
                    message="Kalshi reconciliation not yet run (normal at startup)",
                    details="First reconciliation cycle will clear this automatically",
                    hint=REMEDIATION_HINTS["reconciliation"],
                ))
            else:
                # Distinguish genuine discrepancies from benign zero-qty states
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
                        severity=kalshi_recon_severity,
                        message="Kalshi venue reconciliation found critical discrepancies",
                        details=f"{len(genuine_critical)} genuine position mismatches between MERID and Kalshi venue",
                        hint=REMEDIATION_HINTS["reconciliation"],
                    ))
    except Exception as exc:
        logger.debug("Kalshi venue reconciliation check skipped: %s", exc)

    # 3. Fills ledger reconciliation
    try:
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
    except Exception as _fl_exc:
        logger.debug("Fills-ledger reconciliation gate check skipped: %s", _fl_exc)

    # Determine gate state
    if any(r.severity == "critical" for r in reasons):
        return GateState.BLOCKED, reasons
    elif reasons:
        return GateState.LIMITED, reasons
    else:
        return GateState.CLEAR, reasons
```

---

## 5. Position Cache Layer

### 5.1 Position Cache Sync from REST

```python
# merid/event_venues/kalshi/position_cache.py:420-454
async def sync_from_rest(self, rest_pos_list: List[Dict[str, Any]]) -> None:
    """Synchronize position cache with positions fetched from Kalshi REST API.

    Args:
        rest_pos_list: List of position dicts from Kalshi API

    Behavior:
        - Mutex-protected async operation
        - Filters test tickers
        - Filters closed positions (contracts=0)
        - Preserves TP targets from existing cache during reconciliation
    """
    async with self._mutex:
        current_positions = {p.market_id: p for p in self._positions.values()}

        for raw in rest_pos_list:
            ticker = raw.get("ticker", "")
            if not ticker:
                continue

            # Filter test tickers
            if _is_test_ticker(ticker):
                continue

            # Filter closed positions
            contracts = raw.get("count", 0)
            if contracts == 0:
                continue

            # Preserve TP targets from existing cache
            existing = current_positions.get(ticker)
            tp_price = existing.take_profit_price_cents if existing else None
            sl_price = existing.stop_loss_price_cents if existing else None

            # Update cache
            self._positions[ticker] = CachedPosition(
                market_id=ticker,
                contracts=contracts,
                side=raw.get("side", "yes"),
                avg_price_cents=int(float(raw.get("avg_price", 0)) * 100),
                realized_pnl_usd=Decimal(str(raw.get("realized_pnl", 0))),
                unrealized_pnl_usd=Decimal(str(raw.get("unrealized_pnl", 0))),
                last_updated=datetime.now(timezone.utc),
                fill_source=existing.fill_source if existing else "alpha",
                take_profit_price_cents=tp_price,
                stop_loss_price_cents=sl_price,
            )

        # Remove positions not in REST (closed or settled)
        rest_tickers = {raw.get("ticker") for raw in rest_pos_list if raw.get("ticker")}
        for ticker in list(self._positions.keys()):
            if ticker not in rest_tickers:
                del self._positions[ticker]
```

### 5.2 Position Cache Fill Handler

```python
# merid/event_venues/kalshi/position_cache.py:300-380
def on_fill(self, fill: KalshiFill) -> None:
    """Handle fill event to update position cache.

    Args:
        fill: KalshiFill object from fills_ledger

    Behavior:
        - Updates position cache incrementally
        - Distinguishes alpha vs hedge positions via fill_source
        - Updates TP targets if fill is related to TP order
    """
    ticker = fill.market_ticker
    if not ticker:
        return

    with self._mutex:
        existing = self._positions.get(ticker)

        # Determine new position
        if fill.side == "yes":
            if fill.action == "buy":
                new_contracts = (existing.contracts if existing else 0) + fill.count_fp
            else:  # sell
                new_contracts = (existing.contracts if existing else 0) - fill.count_fp
        else:  # no
            if fill.action == "buy":
                new_contracts = (existing.contracts if existing else 0) - fill.count_fp
            else:  # sell
                new_contracts = (existing.contracts if existing else 0) + fill.count_fp

        # Remove position if closed
        if new_contracts == 0:
            if ticker in self._positions:
                del self._positions[ticker]
            return

        # Update or create position
        fill_source = fill.fill_source or "alpha"
        self._positions[ticker] = CachedPosition(
            market_id=ticker,
            contracts=new_contracts,
            side="yes" if new_contracts > 0 else "no",
            avg_price_cents=fill.price_cents,
            realized_pnl_usd=existing.realized_pnl_usd if existing else Decimal("0"),
            unrealized_pnl_usd=Decimal("0"),  # Recomputed separately
            last_updated=datetime.now(timezone.utc),
            fill_source=fill_source,
            take_profit_price_cents=existing.take_profit_price_cents if existing else None,
            stop_loss_price_cents=existing.stop_loss_price_cents if existing else None,
        )
```

---

## 6. Data Models

### 6.1 VenuePosition (MERID Venue Protocol)

```python
# merid/event_venues/base.py
class VenuePosition:
    """Unified venue protocol for reconciliation."""
    symbol: str  # Market ticker
    quantity: float  # Number of contracts
    average_entry_price: float  # Average entry price in dollars
```

### 6.2 KalshiPosition (Raw API Model)

```python
# merid/event_venues/kalshi/models.py:77-86
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

### 6.3 KalshiFill (Canonical Fill Model)

```python
# merid/event_venues/kalshi/fills_ledger.py:197-252
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
    derived_id: bool  # True if fill_id was synthesized (not from Kalshi)
    confirmed_by_rest: bool
    is_live: bool  # True if LIVE trade with real money
```

### 6.4 VenuePositionDiscrepancy (Reconciliation Result)

```python
# merid/reconciliation/venue_reconciler.py:1-100
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

## 7. Test Design Guidance

### 7.1 BTC/ETH/SOL/XRP/DOGE 15-Minute Ticker Patterns

**Series Tickers:**
- KXBTC15M (BTC 15-minute)
- KXETH15M (ETH 15-minute)
- KXSOL15M (SOL 15-minute)
- KXXRP15M (XRP 15-minute)
- KXDOGE15M (DOGE 15-minute)

**Market Ticker Pattern:**
`KX{ASSET}{DATE}-{STRIKE}-{SIDE}`

Examples:
- `KXBTC-26FEB24-50000` (BTC above $50,000 on Feb 26, 2024)
- `KXETH-26FEB24-3000` (ETH above $3,000 on Feb 26, 2024)
- `KXSOL-26FEB24-100` (SOL above $100 on Feb 26, 2024)

**15-Minute Specific Pattern:**
15-minute markets typically use hourly series tickers (KXBTC) with 15-minute expiry windows.

### 7.2 Unit Conversion Test Pattern

```python
def test_dollar_cents_conversion():
    """Test round-trip conversion between dollars and cents."""
    # Test random prices in 0-1 dollar range
    for _ in range(1000):
        dollars = random.random()  # 0.0 to 1.0
        cents = int(dollars * 100)
        reconstructed = cents / 100.0

        # Assert within 1 cent tolerance
        assert abs(dollars - reconstructed) < 0.01
```

### 7.3 Multi-Page Cursor Test Pattern

```python
def test_multi_page_positions():
    """Test cursor-based pagination for position fetching."""
    # Mock Kalshi API responses with 3 pages
    page1 = {
        "market_positions": [{"ticker": "KXBTC-26FEB24-50000", "count": 10, ...}],
        "cursor": "page2_cursor"
    }
    page2 = {
        "market_positions": [{"ticker": "KXETH-26FEB24-3000", "count": 5, ...}],
        "cursor": "page3_cursor"
    }
    page3 = {
        "market_positions": [{"ticker": "KXSOL-26FEB24-100", "count": 3, ...}],
        "cursor": None  # Last page
    }

    # Assert all positions are fetched
    positions = await client.get_positions_result()
    assert len(positions.unwrap()) == 3
```

### 7.4 Reconciliation Matching Test Pattern

```python
def test_reconciliation_matching():
    """Test reconciliation matching rules."""
    # Mock inputs
    kalshi_positions = [
        {"symbol": "KXBTC-26FEB24-50000", "qty": 10, "entry_price": 0.50}
    ]
    merid_positions = [
        {"symbol": "KXBTC-26FEB24-50000", "qty": 10, "entry_price": 0.50}
    ]

    # Assert no discrepancies
    discrepancies = reconcile_venue("kalshi")
    assert len(discrepancies) == 0

    # Test mismatch
    merid_positions[0]["qty"] = 5
    discrepancies = reconcile_venue("kalshi")
    assert len(discrepancies) == 1
    assert discrepancies[0].severity == "critical"
```

### 7.5 Gate State Transition Test Pattern

```python
def test_gate_state_transitions():
    """Test gate state transitions based on discrepancies."""
    # Test startup (reconciliation not run)
    assert has_critical_discrepancies() == True  # Fail-closed
    state, reasons = check_execution_gate()
    assert state == GateState.LIMITED  # Downgraded to warning

    # Test normal operation
    reconcile_all_venues(["kalshi"])
    assert has_critical_discrepancies() == False
    state, reasons = check_execution_gate()
    assert state == GateState.CLEAR

    # Test critical discrepancy
    # Inject phantom position
    discrepancies = [VenuePositionDiscrepancy(..., severity="critical")]
    _mark_recon_done(discrepancies)
    state, reasons = check_execution_gate()
    assert state == GateState.BLOCKED
```

---

**End of Function Signatures**
