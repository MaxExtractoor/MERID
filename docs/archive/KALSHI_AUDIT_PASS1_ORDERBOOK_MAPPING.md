# Kalshi API Audit - Pass 1.2: Orderbook Mapping

**Objective:** Align WS and REST orderbook handlers with Kalshi's documented `GET /markets/{ticker}/orderbook` and `orderbook_delta` schema.

**Kalshi Reference:** 
- [docs.kalshi.com/orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. REST Orderbook Schema

#### Kalshi Documented Format (GET /markets/{ticker}/orderbook)
From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):

```json
{
  "orderbook": {
    "yes": [[0.01, 100], [0.02, 50]],  // YES bids: [price_dollars, size]
    "no": [[0.01, 100], [0.02, 50]]    // NO bids: [price_dollars, size]
  }
}
```

**Field Mapping:**
- `yes`: Array of YES bids (buying YES contracts)
- `no`: Array of NO bids (buying NO contracts)
- Each level: `[price_dollars, size]` where price is 0.00-1.00, size is contracts

---

#### Current Implementation: `client.py` - `_to_venue_orderbook()`
```python
def _to_venue_orderbook(self, data: Dict[str, Any], market_id: str) -> VenueOrderBook:
    """Convert to VenueOrderBook.
    
    Kalshi REST API returns orderbook in format:
    {
      "orderbook_fp": {
        "yes_dollars": [["0.0010", "4613.25"], ...],  # [price, size] - YES bids
        "no_dollars": [["0.0010", "4413.00"], ...]   # [price, size] - NO bids
      }
    }
    """
    # Parse orderbook_fp format (actual API response)
    if "orderbook_fp" in data:
        orderbook_fp = data["orderbook_fp"]
        
        # yes_dollars: YES bids -> goes to bids
        if "yes_dollars" in orderbook_fp and orderbook_fp["yes_dollars"]:
            for price_str, size_str in orderbook_fp["yes_dollars"]:
                price = Decimal(str(price_str))
                size = Decimal(str(size_str))
                bids.append((price, size))
        
        # no_dollars: NO bids -> goes to asks (equivalent to YES asks)
        if "no_dollars" in orderbook_fp and orderbook_fp["no_dollars"]:
            for price_str, size_str in orderbook_fp["no_dollars"]:
                price = Decimal(str(price_str))
                size = Decimal(str(size_str))
                asks.append((price, size))
    else:
        # Legacy format fallback (yes_bid, no_bid, yes_ask, no_ask)
        if "yes_bid" in data and data["yes_bid"]:
            bids.append((Decimal(str(data["yes_bid"])) / 100, Decimal("1")))
```

**Issues:**
- 🚨 **Field name mismatch:** Code expects `orderbook_fp.yes_dollars/no_dollars` but docs show `orderbook.yes/no`
- 🚨 **String parsing:** API returns strings `["0.0010", "4613.25"]` instead of numbers
- 🚨 **Legacy fallback:** Maintains old `yes_bid/no_bid` format which is not documented
- 🚨 **Side mapping confusion:** NO bids mapped to asks (comment says "equivalent to YES asks" but this is semantic, not structural)

**Root Cause:** API response format changed or documentation is outdated

**Required Fix:**
1. Verify actual API response format via test call
2. Update field names to match current API
3. Remove legacy fallback
4. Document side mapping clearly

---

### 2. WS Orderbook Delta Schema

#### Kalshi Documented Format (orderbook_delta)
From [docs.kalshi.com/orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses):

```json
{
  "type": "orderbook_delta",
  "market_ticker": "KXBTC15M-26MAY241830-30",
  "side": "yes",
  "price": 0.50,
  "delta": 10
}
```

**Field Mapping:**
- `type`: Message type ("orderbook_delta")
- `market_ticker`: Market identifier
- `side`: "yes" or "no"
- `price`: Price in dollars (0.00-1.00)
- `delta`: Size change (positive = add, negative = remove)

---

#### Current Implementation: `orderbook.py` - `validate_orderbook_delta()`
```python
def validate_orderbook_delta(msg: Dict[str, Any]) -> None:
    """Validate orderbook delta message matches canonical schema.
    
    Canonical format (WS delta):
    {
        "type": "orderbook_delta",
        "ticker": str,  # or "market_ticker" (Kalshi WS uses both)
        "side": "yes" | "no",
        "price_dollars": float,
        "delta_fp": int,  # signed size delta
    }
    
    Alternative format (internal/legacy):
    {
        "side": "yes" | "no",
        "price": int,  # cents
        "delta": int | "size_delta": int  # signed size delta
    }
    """
    # Accept either price_dollars (WS format) or price (internal cents format)
    has_price_dollars = "price_dollars" in msg and isinstance(msg["price_dollars"], (int, float, str))
    has_price = "price" in msg and isinstance(msg["price"], (int, float, str))
    
    # Accept either delta_fp (WS format) or delta/size_delta (internal format)
    has_delta_fp = "delta_fp" in msg and isinstance(msg["delta_fp"], (int, float, str))
    has_delta = "delta" in msg and isinstance(msg["delta"], (int, float, str))
    has_size_delta = "size_delta" in msg and isinstance(msg["size_delta"], (int, float, str))
```

**Issues:**
- 🚨 **Field name mismatch:** Code expects `price_dollars/delta_fp` but docs show `price/delta`
- 🚨 **Ticker field:** Code accepts both `ticker` and `market_ticker` (inconsistent)
- 🚨 **Alternative formats:** Accepts 3 different delta field names (`delta_fp`, `delta`, `size_delta`)
- 🚨 **String parsing:** Accepts strings for numeric fields (should be strict)
- 🚨 **Unit confusion:** Mixes dollars (`price_dollars`) and cents (`price`)

**Root Cause:** Multiple format support for internal compatibility

**Required Fix:**
1. Verify actual WS message format via test connection
2. Use only documented field names (`price`, `delta`)
3. Remove alternative format support
4. Enforce strict type checking (no strings)
5. Standardize on `market_ticker` field

---

### 3. WS Orderbook Snapshot Schema

#### Kalshi Documented Format (orderbook_snapshot)
From [docs.kalshi.com/orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses):

```json
{
  "type": "orderbook_snapshot",
  "market_ticker": "KXBTC15M-26MAY241830-30",
  "yes": [[0.01, 100], [0.02, 50]],
  "no": [[0.01, 100], [0.02, 50]]
}
```

**Field Mapping:**
- `type`: Message type ("orderbook_snapshot")
- `market_ticker`: Market identifier
- `yes`: YES bids array
- `no`: NO bids array

---

#### Current Implementation: `orderbook.py` - `validate_orderbook_snapshot()`
```python
def validate_orderbook_snapshot(msg: Dict[str, Any]) -> None:
    """Validate orderbook snapshot message matches canonical schema.
    
    Canonical format:
    {
        "type": "orderbook_snapshot",
        "ticker": str,  # or "market_ticker" (Kalshi WS uses both)
        "yes": [[float, float], ...],  # YES bids: [price_dollars, size]
        "no": [[float, float], ...],   # NO bids: [price_dollars, size]
    }
    """
    # Normalize: Kalshi WS uses "market_ticker", we accept both
    if "ticker" not in msg and "market_ticker" not in msg:
        raise KalshiOrderbookShapeError("Missing required key: ticker or market_ticker")
    
    # Check yes/no arrays are present and are lists
    if "yes" not in msg or not isinstance(msg["yes"], list):
        raise KalshiOrderbookShapeError("Missing or invalid key: yes (must be list)")
    
    if "no" not in msg or not isinstance(msg["no"], list):
        raise KalshiOrderbookShapeError("Missing or invalid key: no (must be list)")
```

**Issues:**
- ⚠️ **Ticker field:** Accepts both `ticker` and `market_ticker` (inconsistent)
- ⚠️ **Type checking:** Allows float/int but not strings (good)
- ⚠️ **No validation:** Doesn't validate price range (0.00-1.00) or size (>0)

**Status:** ✅ Mostly correct, minor issues

**Required Fix:**
1. Standardize on `market_ticker` field
2. Add price range validation (0.00-1.00)
3. Add size validation (>0)

---

### 4. Internal Orderbook Representation

#### Current Implementation: `orderbook.py` - `LocalOrderbook`
```python
class LocalOrderbook:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.yes_levels: Dict[int, int] = defaultdict(int)  # price_cents -> size
        self.no_levels: Dict[int, int] = defaultdict(int)
```

**Internal Schema:**
- `yes_levels`: Dict[int, int] - price in cents, size in contracts
- `no_levels`: Dict[int, int] - price in cents, size in contracts

**Issues:**
- ⚠️ **Unit conversion:** Internal uses cents, external uses dollars
- ⚠️ **No normalization:** Conversion happens in multiple places
- ⚠️ **Type inconsistency:** Internal uses int, external uses float

**Status:** ⚠️ Conversion logic scattered, potential for errors

**Required Fix:**
1. Centralize unit conversion in adapter
2. Use consistent types (Decimal for prices)
3. Document conversion rules

---

### 5. Data Flow Diagram

```
Kalshi WS (orderbook_delta)
    ↓
    market_ticker, side, price, delta
    ↓
ws.py (_handle_message)
    ↓
    Add type="orderbook_delta"
    ↓
market_state.py (apply_orderbook_message)
    ↓
    validate_orderbook_delta()
    ↓
    Convert price_dollars → cents
    ↓
LocalOrderbook (yes_levels/no_levels)
```

**Issues in Flow:**
1. 🚨 **Field name mismatch:** WS sends `price/delta`, code expects `price_dollars/delta_fp`
2. 🚨 **Unit conversion:** Multiple conversion points
3. 🚨 **Validation:** Accepts alternative formats

---

## Required Fixes

### Fix 1: Create NormalizedBook Adapter

```python
@dataclass(frozen=True)
class NormalizedBook:
    """Canonical normalized orderbook from Kalshi API.
    
    All fields match Kalshi documented schema exactly.
    Unit conversion happens only in this adapter.
    """
    ticker: str
    yes_bid_cents: int | None
    yes_ask_cents: int | None
    no_bid_cents: int | None
    no_ask_cents: int | None
    ts: datetime
    
    @classmethod
    def from_rest(cls, data: Dict[str, Any]) -> "NormalizedBook":
        """Parse from GET /markets/{ticker}/orderbook response."""
        # Handle documented format: orderbook.yes/no
        # Handle actual format: orderbook_fp.yes_dollars/no_dollars
        # Convert dollars → cents
        pass
    
    @classmethod
    def from_ws_snapshot(cls, data: Dict[str, Any]) -> "NormalizedBook":
        """Parse from WS orderbook_snapshot message."""
        # Handle market_ticker field
        # Convert dollars → cents
        pass
    
    @classmethod
    def from_ws_delta(cls, data: Dict[str, Any]) -> "NormalizedBook":
        """Parse from WS orderbook_delta message."""
        # Handle market_ticker, side, price, delta fields
        # Convert dollars → cents
        pass
```

**Implementation:**
1. Add to `merid/event_venues/kalshi/types.py`
2. Implement parsing for REST and WS formats
3. Handle both documented and actual API formats
4. Centralize unit conversion
5. Use only this adapter for all orderbook data

---

### Fix 2: Update REST Orderbook Parsing

**File:** `client.py` - `_to_venue_orderbook()`

**Changes:**
1. Remove legacy fallback (`yes_bid/no_bid`)
2. Handle both `orderbook.yes/no` and `orderbook_fp.yes_dollars/no_dollars`
3. Use NormalizedBook adapter
4. Log format detection for debugging

**Migration:**
1. Test actual API response format
2. Update field names based on test
3. Remove legacy code
4. Add validation

---

### Fix 3: Update WS Delta Handling

**File:** `orderbook.py` - `validate_orderbook_delta()`

**Changes:**
1. Accept only documented field names (`market_ticker`, `price`, `delta`)
2. Remove alternative format support (`price_dollars`, `delta_fp`, `size_delta`)
3. Enforce strict type checking (no strings)
4. Add price range validation (0.00-1.00)

**Migration:**
1. Test actual WS message format
2. Update field names based on test
3. Remove alternative format code
4. Add strict validation

---

### Fix 4: Update WS Snapshot Handling

**File:** `orderbook.py` - `validate_orderbook_snapshot()`

**Changes:**
1. Standardize on `market_ticker` field
2. Add price range validation (0.00-1.00)
3. Add size validation (>0)
4. Use NormalizedBook adapter

**Migration:**
1. Update validation logic
2. Add range checks
3. Use adapter for parsing

---

### Fix 5: Centralize Unit Conversion

**Current:** Conversion scattered across multiple files
**Target:** All conversion in NormalizedBook adapter

**Benefits:**
- Single source of truth
- Easier to test
- Consistent behavior
- Easier to update if API changes

---

## Audit Checklist

- [ ] Document REST orderbook schema (documented vs actual)
- [ ] Document WS delta schema (documented vs actual)
- [ ] Document WS snapshot schema (documented vs actual)
- [ ] Identify field name mismatches (3 found)
- [ ] Identify unit conversion issues (cents vs dollars)
- [ ] Identify alternative format support (3 delta formats)
- [ ] Design NormalizedBook adapter (proposed)
- [ ] Plan migration path (5 fixes)
- [ ] Add price range validation (0.00-1.00)
- [ ] Add size validation (>0)
- [ ] Remove legacy fallbacks (REST, WS delta)
- [ ] Centralize unit conversion (adapter)
- [ ] Test actual API/WS formats

---

## Next Steps

1. **Immediate:** Test actual API response format for GET /markets/{ticker}/orderbook
2. **Immediate:** Test actual WS message format for orderbook_delta
3. **Short-term:** Implement NormalizedBook adapter
4. **Short-term:** Update REST parsing to use adapter
5. **Medium-term:** Update WS delta/snapshot to use adapter
6. **Medium-term:** Remove legacy code
7. **Long-term:** Add comprehensive validation

**Priority:** HIGH - Schema mismatches can cause incorrect orderbook data

**Risk:** If API format differs from docs, current code may be working by accident. Need to verify actual format.
