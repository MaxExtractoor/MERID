# Kalshi API Audit - Pass 3.3: REST Snapshot Bootstrap

**Objective:** Ensure single snapshot bootstrap path using correct endpoint and proper initialization.

**Kalshi Reference:** 
- [docs.kalshi.com/orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. REST Orderbook Endpoint

#### Kalshi Documented Endpoint

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Endpoint:** `GET /markets/{ticker}/orderbook`
- **Purpose:** Fetch current orderbook for a specific market
- **Response:** Orderbook with YES/NO bids

---

#### Current Implementation: `client.py` - `get_orderbook_result()`

```python
async def get_orderbook_result(
    self, market_id: str, outcome_id: Optional[str] = None
) -> OperationResult[Optional[VenueOrderBook]]:
    """Get order book with explicit result."""
    result = await self._request_with_resilience(
        "GET", f"/markets/{market_id}/orderbook",
        operation_name=f"get_orderbook({market_id})"
    )
    
    if not result.success:
        return OperationResult.fail(result.error, ...)
    
    return OperationResult.ok(
        self._to_venue_orderbook(result.data, market_id),
        ...
    )
```

**Endpoint Used:** `GET /markets/{market_id}/orderbook`

**Status:** ✅ Matches documented endpoint

---

### 2. Snapshot Bootstrap Paths

#### Path 1: Post-WS Subscription Bootstrap

**File:** `ws_bridge.py` - Lines 390-438

```python
# After WS subscription, fetch REST snapshots
for ticker in tickers:
    logger.info("[SNAPSHOT-BOOTSTRAP] Fetching snapshot for %s", ticker)
    try:
        result = await asyncio.wait_for(
            client._request_with_resilience(
                "GET", f"/markets/{ticker}/orderbook",
                operation_name=f"get_orderbook({ticker})"
            ),
            timeout=5.0
        )
        if result.success and result.data:
            # Parse raw REST response
            data = result.data
            orderbook_fp = data.get("orderbook_fp", {})
            if "no_dollars" in orderbook_fp:
                no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]
            if "yes_dollars" in orderbook_fp:
                yes_levels = [[float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]
            
            snapshot_msg = {
                "ticker": ticker,
                "type": "orderbook_snapshot",
                "no": no_levels,
                "yes": yes_levels,
            }
            # Apply to market state store
            await loop.run_in_executor(None, store.apply_orderbook_message, snapshot_msg)
```

**Purpose:** Bootstrap orderbook after WS subscription to ensure initial state

**Endpoint:** `GET /markets/{ticker}/orderbook`

**Parsing:** Handles `orderbook_fp.yes_dollars/no_dollars` format

**Status:** ✅ Correct endpoint and parsing

**Issues:**
- ⚠️ **Inline parsing:** Parses raw response instead of using adapter
- ⚠️ **Thread pool execution:** Uses run_in_executor to avoid blocking (workaround)

---

#### Path 2: REST Fallback Mode

**File:** `ws_bridge.py` - Lines 640-685

```python
# When WS connection fails, use REST polling
for ticker in ut:
    try:
        # Fetch orderbook via REST API
        orderbook = await client.get_orderbook(ticker)
        if orderbook:
            # Convert REST orderbook to WS message format
            yes_levels = []
            if orderbook.bids:
                for b in orderbook.bids:
                    if hasattr(b, 'price'):
                        yes_levels.append([float(b.price), float(b.size)])
                    else:
                        yes_levels.append([float(b[0]), float(b[1])])
            
            no_levels = []
            if orderbook.asks:
                for a in orderbook.asks:
                    if hasattr(a, 'price'):
                        no_levels.append([float(a.price), float(a.size)])
                    else:
                        no_levels.append([float(a[0]), float(a[1])])
            
            msg = {
                "type": "orderbook_snapshot",
                "ticker": ticker,
                "sequence": 0,
                "yes": yes_levels,
                "no": no_levels,
            }
            store.apply_orderbook_message(msg)
```

**Purpose:** Fallback to REST polling when WS connection fails

**Endpoint:** `GET /markets/{ticker}/orderbook` (via client.get_orderbook)

**Parsing:** Handles VenueOrderBook object with bids/asks attributes

**Status:** ⚠️ Different parsing logic than Path 1

**Issues:**
- 🚨 **Different parsing:** Uses VenueOrderBook object instead of raw response
- 🚨 **Dual format support:** Handles both object attributes and tuples
- 🚨 **No thread pool:** Direct call (may block event loop)

---

### 3. Parsing Inconsistencies

#### Path 1 Parsing (Post-WS)

```python
# Raw response parsing
orderbook_fp = data.get("orderbook_fp", {})
if "no_dollars" in orderbook_fp:
    no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]
if "yes_dollars" in orderbook_fp:
    yes_levels = [[float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]
```

**Format:** `orderbook_fp.yes_dollars/no_dollars` (string arrays)

---

#### Path 2 Parsing (REST Fallback)

```python
# VenueOrderBook object parsing
yes_levels = []
if orderbook.bids:
    for b in orderbook.bids:
        if hasattr(b, 'price'):
            yes_levels.append([float(b.price), float(b.size)])
        else:
            yes_levels.append([float(b[0]), float(b[1])])
```

**Format:** `VenueOrderBook.bids/asks` (object or tuple)

---

#### Inconsistency Summary

| Aspect | Path 1 (Post-WS) | Path 2 (REST Fallback) |
|--------|------------------|------------------------|
| Data Source | Raw API response | VenueOrderBook object |
| Field Names | yes_dollars/no_dollars | bids/asks |
| Data Type | String arrays | Objects or tuples |
| Conversion | Inline parsing | Attribute/tuple check |
| Execution | Thread pool | Direct call |

**Status:** 🚨 Two completely different parsing paths

**Risk:** Inconsistent parsing can lead to different orderbook data depending on which path is used

---

### 4. Initialization State

#### Path 1 Initialization

```python
# Apply snapshot
await loop.run_in_executor(None, store.apply_orderbook_message, snapshot_msg)

# Log completion
state = store.get(ticker)
bid_str = f"{state.best_bid_cents}" if state and state.best_bid_cents else "None"
ask_str = f"{state.best_ask_cents}" if state and state.best_ask_cents else "None"
logger.info(
    "[SNAPSHOT-BOOTSTRAP] complete market=%s levels=%d bid=%s ask=%s source=REST",
    ticker, n_levels, bid_str, ask_str
)
```

**Initialization:** Sets `book_initialized=True` in market state

**Status:** ✅ Proper initialization

---

#### Path 2 Initialization

```python
# Apply snapshot
store.apply_orderbook_message(msg)

# Log completion
logger.info("[WS-FALLBACK] Fetched REST orderbook for %s: %d yes, %d no", ticker, len(msg["yes"]), len(msg["no"]))
```

**Initialization:** Sets `book_initialized=True` in market state

**Status:** ✅ Proper initialization

---

### 5. Data Flow Diagram

```
WS Bridge Start
    ↓
    WS Connection Attempt
    ↓
    ├─ Success → Path 1: Post-WS Bootstrap
    │   ↓
    │   GET /markets/{ticker}/orderbook (raw response)
    │   ↓
    │   Parse orderbook_fp.yes_dollars/no_dollars
    │   ↓
    │   Convert to snapshot message
    │   ↓
    │   Apply to MarketStateStore (thread pool)
    │   ↓
    │   book_initialized=True
    │
    └─ Failure → Path 2: REST Fallback
        ↓
        GET /markets/{ticker}/orderbook (VenueOrderBook)
        ↓
        Parse bids/asks (object or tuple)
        ↓
        Convert to snapshot message
        ↓
        Apply to MarketStateStore (direct call)
        ↓
        book_initialized=True
```

**Issues in Flow:**
1. 🚨 **Two paths:** Different parsing logic
2. 🚨 **Different execution:** Thread pool vs direct call
3. 🚨 **Different data sources:** Raw response vs VenueOrderBook

---

## Required Fixes

### Fix 1: Unify Parsing Logic

**Create single adapter:**

```python
@dataclass(frozen=True)
class NormalizedBook:
    """Canonical normalized orderbook from Kalshi API."""
    
    @classmethod
    def from_rest_response(cls, data: Dict[str, Any], ticker: str) -> "NormalizedBook":
        """Parse from GET /markets/{ticker}/orderbook raw response."""
        # Handle documented format: orderbook.yes/no
        # Handle actual format: orderbook_fp.yes_dollars/no_dollars
        orderbook = data.get("orderbook") or data.get("orderbook_fp", {})
        
        yes_levels = []
        if "yes" in orderbook:
            yes_levels = [[float(p), float(s)] for p, s in orderbook["yes"]]
        elif "yes_dollars" in orderbook:
            yes_levels = [[float(p), float(s)] for p, s in orderbook["yes_dollars"]]
        
        no_levels = []
        if "no" in orderbook:
            no_levels = [[float(p), float(s)] for p, s in orderbook["no"]]
        elif "no_dollars" in orderbook:
            no_levels = [[float(p), float(s)] for p, s in orderbook["no_dollars"]]
        
        return cls(
            ticker=ticker,
            yes_levels=yes_levels,
            no_levels=no_levels,
            source="REST"
        )
    
    @classmethod
    def from_venue_orderbook(cls, orderbook: VenueOrderBook, ticker: str) -> "NormalizedBook":
        """Parse from VenueOrderBook object."""
        yes_levels = []
        if orderbook.bids:
            for b in orderbook.bids:
                price = float(b.price) if hasattr(b, 'price') else float(b[0])
                size = float(b.size) if hasattr(b, 'size') else float(b[1])
                yes_levels.append([price, size])
        
        no_levels = []
        if orderbook.asks:
            for a in orderbook.asks:
                price = float(a.price) if hasattr(a, 'price') else float(a[0])
                size = float(a.size) if hasattr(a, 'size') else float(a[1])
                no_levels.append([price, size])
        
        return cls(
            ticker=ticker,
            yes_levels=yes_levels,
            no_levels=no_levels,
            source="REST"
        )
    
    def to_snapshot_message(self) -> Dict[str, Any]:
        """Convert to WS snapshot message format."""
        return {
            "ticker": self.ticker,
            "type": "orderbook_snapshot",
            "yes": self.yes_levels,
            "no": self.no_levels,
        }
```

**Implementation:**
1. Add to `merid/event_venues/kalshi/types.py`
2. Handle both raw response and VenueOrderBook
3. Convert to snapshot message
4. Use in both paths

---

### Fix 2: Use Single Snapshot Bootstrap Method

**Create single method:**

```python
async def _bootstrap_snapshot(
    self,
    ticker: str,
    client: KalshiClientV2,
    store: KalshiMarketStateStore
) -> None:
    """Bootstrap orderbook snapshot using REST API.
    
    Single path for both post-WS bootstrap and REST fallback.
    """
    try:
        # Fetch orderbook
        result = await asyncio.wait_for(
            client.get_orderbook_result(ticker),
            timeout=5.0
        )
        
        if not result.success or not result.data:
            logger.warning(
                "[SNAPSHOT-BOOTSTRAP] Failed to fetch orderbook for %s: %s",
                ticker, result.error
            )
            return
        
        # Use adapter for parsing
        normalized = NormalizedBook.from_venue_orderbook(result.data, ticker)
        snapshot_msg = normalized.to_snapshot_message()
        
        # Apply to store
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, store.apply_orderbook_message, snapshot_msg)
        
        # Log completion
        state = store.get(ticker)
        logger.info(
            "[SNAPSHOT-BOOTSTRAP] complete market=%s levels=%d bid=%s ask=%s source=REST",
            ticker,
            len(normalized.yes_levels) + len(normalized.no_levels),
            state.best_bid_cents if state else "None",
            state.best_ask_cents if state else "None"
        )
        
    except asyncio.TimeoutError:
        logger.warning("[SNAPSHOT-BOOTSTRAP] Timeout for %s (5s limit)", ticker)
    except Exception as e:
        logger.error("[SNAPSHOT-BOOTSTRAP] Failed for %s: %s", ticker, e)
```

**Implementation:**
1. Add to `ws_bridge.py`
2. Use in both Path 1 and Path 2
3. Always use thread pool execution
4. Consistent logging

---

### Fix 3: Remove Path 2 REST Fallback

**Current:** Path 2 is a complete REST polling fallback when WS fails
**Target:** Remove REST fallback, fail-fast on WS connection failure

**Rationale:**
- REST fallback is not documented by Kalshi
- Dual paths create inconsistency
- WS is required for real-time trading
- If WS fails, system should not trade

**Implementation:**
1. Remove REST fallback logic (lines 640-685)
2. Fail-fast on WS connection failure
3. Log clear error message
4. Require manual intervention

---

### Fix 4: Add Snapshot Validation

**Add validation in adapter:**

```python
@classmethod
def from_rest_response(cls, data: Dict[str, Any], ticker: str) -> "NormalizedBook":
    """Parse from GET /markets/{ticker}/orderbook raw response."""
    # Validate response structure
    if not data:
        raise ValueError(f"Empty response for ticker {ticker}")
    
    orderbook = data.get("orderbook") or data.get("orderbook_fp")
    if not orderbook:
        raise ValueError(f"No orderbook data for ticker {ticker}")
    
    # Validate price ranges
    for price, size in yes_levels + no_levels:
        if not (0.00 <= price <= 1.00):
            logger.warning(
                "[SNAPSHOT-VALIDATION] Invalid price %s for ticker %s (must be 0.00-1.00)",
                price, ticker
            )
        if size <= 0:
            logger.warning(
                "[SNAPSHOT-VALIDATION] Invalid size %s for ticker %s (must be >0)",
                size, ticker
            )
```

**Implementation:**
1. Add response structure validation
2. Add price range validation
3. Add size validation
4. Log warnings for invalid data

---

## Audit Checklist

- [ ] Document REST endpoint (✅ documented)
- [ ] Document Path 1 bootstrap (✅ documented)
- [ ] Document Path 2 fallback (✅ documented)
- [ ] Identify parsing inconsistencies (🚨 two different parsers)
- [ ] Identify execution inconsistencies (thread pool vs direct)
- [ ] Identify data source inconsistencies (raw vs object)
- [ ] Design unified adapter (proposed)
- [ ] Design single bootstrap method (proposed)
- [ ] Plan migration path (4 fixes)
- [ ] Implement NormalizedBook adapter
- [ ] Implement single bootstrap method
- [ ] Remove REST fallback
- [ ] Add snapshot validation

---

## Next Steps

1. **Immediate:** Implement NormalizedBook adapter
2. **Immediate:** Implement single bootstrap method
3. **Short-term:** Replace Path 1 with single method
4. **Short-term:** Replace Path 2 with single method
5. **Medium-term:** Remove REST fallback entirely
6. **Medium-term:** Add snapshot validation
7. **Long-term:** Add automated snapshot monitoring

**Priority:** HIGH - Multiple parsing paths create inconsistency risk

**Risk:** If the two paths produce different orderbook data, trading decisions may be inconsistent depending on which path was used.

**Note:** Both paths use the correct endpoint (`GET /markets/{ticker}/orderbook`), but parsing logic is completely different. This is a critical inconsistency that must be fixed.
