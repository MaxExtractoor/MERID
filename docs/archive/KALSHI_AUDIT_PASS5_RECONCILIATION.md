# Kalshi API Audit - Pass 5.2: Reconciliation Loop

**Objective:** Map fills ledger vs get-trades and document reconciliation mechanisms.

**Kalshi Reference:** 
- [docs.kalshi.com/portfolio](https://docs.kalshi.com/getting_started/portfolio)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. Fills Ledger (Canonical Source)

#### Current Implementation: `fills_ledger.py`

**Purpose:** Authoritative source of truth for all fills

**Data Sources:**
- **Primary:** WebSocket fills channel (`fills`)
- **Secondary:** REST API sync on reconnection
- **Fallback:** HTTP polling (legacy, deprecated)

**Key Features:**
```python
class KalshiFillsLedger:
    """Canonical fills ledger for Kalshi trading.
    
    Ingests fills from WebSocket and REST API, provides:
    - Fill lookup by ID
    - Open exposure calculation
    - Realized PnL calculation
    - Hedge fill tracking
    - Reconciliation status
    """
```

**Status:** ✅ Single source of truth for fills

**Issues:**
- ⚠️ **Multiple ingestion paths:** WS + REST + HTTP poller
- ⚠️ **Duplicate detection:** Handles duplicate fills (expected behavior)
- ⚠️ **No validation:** Doesn't validate against REST API continuously

---

### 2. REST API: get_trades

#### Kalshi Documented Endpoint

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Endpoint:** `GET /portfolio/trades`
- **Purpose:** Fetch trade history
- **Parameters:** `limit`, `cursor`, `created_at_min`, `created_at_max`
- **Response:** Array of trade objects

---

#### Current Implementation: `client.py` - `get_trades_result()`

```python
async def get_trades_result(self, limit: int = 100) -> OperationResult[List[VenueTrade]]:
    """Get trade history with explicit result.

    Supports cursor-based pagination to fetch all trades up to the limit.
    Uses 100-item pages with cursor chaining.
    """
    all_trades: List[VenueTrade] = []
    cursor: Optional[str] = None
    remaining = limit
    max_pages = max(1, (limit + 99) // 100)

    for page in range(max_pages):
        page_size = min(remaining, 100)
        params = {"limit": page_size}
        if cursor:
            params["cursor"] = cursor

        result = await self._request_with_resilience(
            "GET", "/portfolio/trades", params=params, operation_name="get_trades"
        )

        if not result.success:
            if all_trades:
                # Return what we have so far on partial failure
                logger.warning(f"get_trades: Partial failure on page {page}, returning {len(all_trades)} trades")
                break
            return OperationResult.fail(result.error, ...)

        for trade_data in result.data.get("trades", []):
            trade = self._parse_trade(trade_data)
            if trade:
                all_trades.append(self._to_venue_trade(trade))
                remaining -= 1

        cursor = result.data.get("cursor")
        if not cursor or remaining <= 0:
            break

    return OperationResult.ok(all_trades[:limit], ...)
```

**Endpoint Used:** `GET /portfolio/trades`

**Status:** ✅ Matches documented endpoint

**Features:**
- ✅ Cursor-based pagination
- ✅ Partial failure handling
- ✅ Trade parsing

**Issues:**
- ⚠️ **Not used for reconciliation:** Only used for display/analysis
- ⚠️ **No continuous sync:** Not used to validate fills ledger
- ⚠️ **Limited to 100 trades:** Default limit is 100

---

### 3. Reconciliation Mechanisms

#### Mechanism 1: WS Reconnection Sync

**File:** `ws_bridge.py` - `_sync_fills_with_rest_on_reconnect()`

```python
async def _sync_fills_with_rest_on_reconnect(self) -> None:
    """Sync fills ledger with REST API after reconnection.

    This catches any fills that may have been missed during WebSocket
    downtime by querying the Kalshi REST API for recent fills.
    """
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
    ledger = get_fills_ledger()

    # Get recent fills from REST API (last 5 minutes)
    recent_fills = await rest_client.get_recent_fills(
        limit=100,
        created_at_min=datetime.now(timezone.utc) - timedelta(minutes=5)
    )

    new_fills = 0
    duplicates = 0

    for fill in recent_fills:
        # Check if already in ledger
        existing = ledger.get_fill_by_id(fill.fill_id)
        if existing:
            duplicates += 1
        else:
            # Ingest into fills ledger
            ledger.ingest_fill(fill, source="rest_reconnect_sync")
            new_fills += 1

    logger.info(
        "[WS-RECONNECT-SYNC] REST sync complete: %d new fills, %d duplicates",
        new_fills, duplicates
    )
```

**Purpose:** Catch fills missed during WS downtime

**Status:** ✅ Reconciliation on reconnection

**Issues:**
- ⚠️ **5-minute window:** Only syncs last 5 minutes
- ⚠️ **Limited to 100 fills:** May miss fills if high volume
- ⚠️ **No continuous validation:** Only runs on reconnection

---

#### Mechanism 2: Position Cache Reconciliation

**File:** `position_cache.py` - `reconcile_with_fills_ledger()`

```python
async def reconcile_with_fills_ledger(
    self,
    ledger: Optional["KalshiFillsLedger"] = None
) -> Dict[str, Any]:
    """Reconcile position cache with fills_ledger for consistency.

    Compares hedge fills in position cache vs fills_ledger.
    """
    ledger = ledger or self._fills_ledger

    if not ledger:
        return {"error": "No fills_ledger available for reconciliation"}

    hedge_fills_in_cache = 0
    hedge_fills_in_ledger = 0
    issues = []

    # Get hedge fills from ledger
    ledger_hedge_fills = ledger.get_hedge_fills(limit=10000)
    hedge_fills_in_ledger = len(ledger_hedge_fills)

    # Count hedge fills in cache
    for ticker, state in self._positions.items():
        if state.action == "hedge":
            hedge_fills_in_cache += 1
            matching = [f for f in ledger_hedge_fills if f.market_ticker == ticker]
            if not matching:
                issues.append(f"Hedge fill in cache not in ledger: {ticker}")

    return {
        "hedge_fills_in_cache": hedge_fills_in_cache,
        "hedge_fills_in_ledger": hedge_fills_in_ledger,
        "issues": issues,
        "is_consistent": len(issues) == 0 and hedge_fills_in_cache == hedge_fills_in_ledger,
    }
```

**Purpose:** Validate position cache against fills ledger

**Status:** ✅ Reconciliation for hedge fills

**Issues:**
- ⚠️ **Manual trigger:** Must be called explicitly
- ⚠️ **Hedge fills only:** Only validates hedge fills
- ⚠️ **No continuous validation:** Not run automatically

---

#### Mechanism 3: PnL Reconciliation

**File:** `portfolio_reconciliation.py`

```python
# Validate position_cache realized PnL against fills_ledger canonical source
from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
fills_ledger = get_fills_ledger()

# Get canonical realized PnL from fills_ledger
ledger_summary = fills_ledger.summary()
ledger_realized_pnl = ledger_summary.get("realized_pnl_cents", 0)

# Compare with position cache
cache_realized_pnl = position_cache.get_realized_pnl_cents()
pnl_drift = abs(cache_realized_pnl - ledger_realized_pnl)

if pnl_drift > 100:  # 1 cent tolerance
    logger.warning(
        "PnL calculation drift: position_cache=%dc fills_ledger=%dc diff=%dc",
        cache_realized_pnl, ledger_realized_pnl, pnl_drift
    )
```

**Purpose:** Validate PnL calculations

**Status:** ✅ PnL reconciliation

**Issues:**
- ⚠️ **Manual trigger:** Must be called explicitly
- ⚠️ **1 cent tolerance:** May miss small drifts
- ⚠️ **No continuous validation:** Not run automatically

---

### 4. Data Flow: Fills

```
Kalshi WS (fills channel)
    ↓
    ws_bridge._handle_fills()
    ↓
    fills_ledger.ingest_fill(source="websocket")
    ↓
    position_cache.apply_fill()
    ↓
    portfolio_engine.ingest_fill()
    ↓
    PnL calculation
    ↓
    Risk calculation
```

**Status:** ✅ Clear data flow

**Issues:**
- ⚠️ **Single path:** Only WS ingestion (no REST validation)
- ⚠️ **No backup:** If WS fails, fills may be lost
- ⚠️ **No continuous reconciliation:** Only on reconnection

---

### 5. Data Flow: REST Trades

```
get_trades() / get_trades_result()
    ↓
    GET /portfolio/trades
    ↓
    Parse trades
    ↓
    Return VenueTrade list
    ↓
    Display / Analysis (not used for reconciliation)
```

**Status:** ⚠️ Not used for reconciliation

**Issues:**
- 🚨 **No reconciliation:** REST trades not compared to fills ledger
- 🚨 **No validation:** No continuous validation against REST
- 🚨 **Limited use:** Only used for display/analysis

---

## Required Fixes

### Fix 1: Add Continuous REST Validation

**File:** `fills_ledger.py`

**Add:**
```python
async def validate_against_rest(
    self,
    client: KalshiClientV2,
    time_window_minutes: int = 5
) -> Dict[str, Any]:
    """Validate fills ledger against REST API.
    
    Fetches recent fills from REST API and compares with ledger.
    Detects missing fills and discrepancies.
    """
    # Get recent fills from REST
    recent_rest_fills = await client.get_recent_fills(
        limit=100,
        created_at_min=datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)
    )
    
    # Get recent fills from ledger
    recent_ledger_fills = self.get_recent_fills(
        limit=100,
        since=datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)
    )
    
    # Compare
    rest_fill_ids = {f.fill_id for f in recent_rest_fills}
    ledger_fill_ids = {f.fill_id for f in recent_ledger_fills}
    
    missing_in_ledger = rest_fill_ids - ledger_fill_ids
    extra_in_ledger = ledger_fill_ids - rest_fill_ids
    
    return {
        "rest_count": len(rest_fill_ids),
        "ledger_count": len(ledger_fill_ids),
        "missing_in_ledger": len(missing_in_ledger),
        "extra_in_ledger": len(extra_in_ledger),
        "is_consistent": len(missing_in_ledger) == 0 and len(extra_in_ledger) == 0,
    }
```

**Implementation:**
1. Add validation method to fills_ledger
2. Fetch recent fills from REST
3. Compare with ledger
4. Return discrepancies
5. Run periodically (e.g., every 5 minutes)

---

### Fix 2: Expand Reconnection Sync Window

**File:** `ws_bridge.py` - `_sync_fills_with_rest_on_reconnect()`

**Current:**
```python
# Get recent fills from REST API (last 5 minutes)
recent_fills = await rest_client.get_recent_fills(
    limit=100,
    created_at_min=datetime.now(timezone.utc) - timedelta(minutes=5)
)
```

**Proposed:**
```python
# Get recent fills from REST API (last 30 minutes)
# Expanded window to catch fills missed during longer outages
recent_fills = await rest_client.get_recent_fills(
    limit=500,  # Increased limit
    created_at_min=datetime.now(timezone.utc) - timedelta(minutes=30)
)
```

**Implementation:**
1. Expand time window from 5 to 30 minutes
2. Increase limit from 100 to 500
3. Document trade-off (longer window = more API calls)

---

### Fix 3: Add Automated Reconciliation

**File:** `fills_ledger.py`

**Add:**
```python
async def start_reconciliation_loop(
    self,
    client: KalshiClientV2,
    interval_seconds: int = 300  # 5 minutes
) -> None:
    """Start continuous reconciliation loop.
    
    Validates fills ledger against REST API periodically.
    """
    while self._running:
        try:
            result = await self.validate_against_rest(client)
            
            if not result["is_consistent"]:
                logger.warning(
                    "[FILLS-RECONCILIATION] Discrepancy detected: "
                    "rest=%d ledger=%d missing=%d extra=%d",
                    result["rest_count"],
                    result["ledger_count"],
                    result["missing_in_ledger"],
                    result["extra_in_ledger"]
                )
                
                # Trigger alert or automatic sync
                if result["missing_in_ledger"] > 0:
                    await self._sync_missing_fills(client, result)
            
        except Exception as e:
            logger.error("[FILLS-RECONCILIATION] Validation failed: %s", e)
        
        await asyncio.sleep(interval_seconds)
```

**Implementation:**
1. Add reconciliation loop
2. Run every 5 minutes
3. Log discrepancies
4. Trigger sync on missing fills
5. Start on fills_ledger initialization

---

### Fix 4: Use get_trades for Reconciliation

**File:** `fills_ledger.py`

**Add:**
```python
async def reconcile_with_trades(
    self,
    client: KalshiClientV2,
    time_window_minutes: int = 5
) -> Dict[str, Any]:
    """Reconcile fills ledger with get_trades endpoint.
    
    Uses GET /portfolio/trades as an additional validation source.
    """
    # Get recent trades from REST
    recent_trades = await client.get_trades_result(limit=100)
    
    if not recent_trades.success:
        return {"error": "Failed to fetch trades", "is_consistent": False}
    
    # Convert trades to fill format
    trade_fill_ids = {t.trade_id for t in recent_trades.data}
    
    # Get recent fills from ledger
    recent_ledger_fills = self.get_recent_fills(
        limit=100,
        since=datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)
    )
    
    ledger_fill_ids = {f.fill_id for f in recent_ledger_fills}
    
    # Compare
    missing_in_ledger = trade_fill_ids - ledger_fill_ids
    extra_in_ledger = ledger_fill_ids - trade_fill_ids
    
    return {
        "trades_count": len(trade_fill_ids),
        "ledger_count": len(ledger_fill_ids),
        "missing_in_ledger": len(missing_in_ledger),
        "extra_in_ledger": len(extra_in_ledger),
        "is_consistent": len(missing_in_ledger) == 0 and len(extra_in_ledger) == 0,
    }
```

**Implementation:**
1. Add reconciliation with trades endpoint
2. Compare trade IDs with fill IDs
3. Detect discrepancies
4. Run alongside REST fills validation

---

### Fix 5: Add Reconciliation Metrics

**File:** `fills_ledger.py`

**Add:**
```python
@dataclass
class ReconciliationMetrics:
    """Metrics for fills ledger reconciliation."""
    last_validation_time: Optional[datetime] = None
    last_validation_result: Optional[Dict[str, Any]] = None
    total_validations: int = 0
    failed_validations: int = 0
    missing_fills_detected: int = 0
    extra_fills_detected: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "last_validation_time": self.last_validation_time.isoformat() if self.last_validation_time else None,
            "last_validation_result": self.last_validation_result,
            "total_validations": self.total_validations,
            "failed_validations": self.failed_validations,
            "missing_fills_detected": self.missing_fills_detected,
            "extra_fills_detected": self.extra_fills_detected,
        }
```

**Implementation:**
1. Add metrics dataclass
2. Track validation results
3. Track discrepancies
4. Expose via summary()
5. Display in monitoring dashboard

---

## Audit Checklist

- [ ] Document fills ledger (✅ documented)
- [ ] Document get_trades endpoint (✅ documented)
- [ ] Document reconciliation mechanisms (✅ documented)
- [ ] Document data flow (✅ documented)
- [ ] Identify single path ingestion (⚠️ WS only)
- [ ] Identify no continuous validation (⚠️ only on reconnection)
- [ ] Identify limited use of get_trades (⚠️ not used for reconciliation)
- [ ] Identify limited sync window (⚠️ 5 minutes)
- [ ] Plan migration path (5 fixes)
- [ ] Add continuous REST validation
- [ ] Expand reconnection sync window
- [ ] Add automated reconciliation loop
- [ ] Use get_trades for reconciliation
- [ ] Add reconciliation metrics

---

## Next Steps

1. **Immediate:** Add continuous REST validation
2. **Immediate:** Expand reconnection sync window
3. **Short-term:** Add automated reconciliation loop
4. **Short-term:** Use get_trades for reconciliation
5. **Medium-term:** Add reconciliation metrics
6. **Medium-term:** Add reconciliation alerts
7. **Long-term:** Add automated sync on discrepancy

**Priority:** HIGH - No continuous validation means fills may be lost or incorrect

**Risk:** If WS fails and fills are missed, there's no continuous validation to detect the discrepancy. get_trades endpoint exists but is not used for reconciliation.

**Note:** Fills ledger is the canonical source of truth, but there's no continuous validation against REST API. get_trades endpoint exists but is only used for display/analysis, not reconciliation.
