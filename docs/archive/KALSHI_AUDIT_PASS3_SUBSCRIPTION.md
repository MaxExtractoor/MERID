# Kalshi API Audit - Pass 3.2: Subscription and Delta Handling

**Objective:** Verify subscription payload matches Kalshi's documented examples and delta handling follows their schema.

**Kalshi Reference:** 
- [docs.kalshi.com/orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. Subscription Payload

#### Kalshi Documented Subscription Format

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):

```json
{
  "id": 1,
  "cmd": "subscribe",
  "params": {
    "channels": ["orderbook_delta"],
    "market_tickers": ["<Kalshi ticker 1>", "<Kalshi ticker 2>"]
  }
}
```

**Field Mapping:**
- `id`: Request ID (integer, auto-incrementing)
- `cmd`: Command type ("subscribe")
- `params.channels`: Array of channels to subscribe
- `params.market_tickers`: Array of market tickers

---

#### Current Implementation: `ws.py` - `subscribe_orderbooks_batch()`

```python
async def subscribe_orderbooks_batch(
    self,
    market_ids: List[str],
    *,
    chunk_size: int = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE,
) -> None:
    """Subscribe to orderbook_delta for many markets (chunked subscribe messages)."""
    uniq = sorted(set(market_ids))
    n_chunks = (len(uniq) + chunk_size - 1) // chunk_size
    
    for i in range(0, len(uniq), chunk_size):
        chunk = uniq[i : i + chunk_size]
        message = {
            "id": self._next_sub_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": chunk,
            },
        }
        payload = json.dumps(message)
        logger.info("[WS-SUBSCRIPTION-PAYLOAD] sending JSON: %s", payload)
        await self._ws.send(payload)
```

**Payload Format:**
```json
{
  "id": 1,
  "cmd": "subscribe",
  "params": {
    "channels": ["orderbook_delta"],
    "market_tickers": ["KXBTC15M-26MAY241830-30", ...]
  }
}
```

**Status:** ✅ Matches documented format exactly

**Features:**
- ✅ Chunking for large ticker lists (configurable chunk_size)
- ✅ Deduplication (sorted(set(market_ids)))
- ✅ Payload logging for debugging
- ✅ Auto-incrementing ID

**Issues:**
- ⚠️ **No validation:** Doesn't validate ticker format before sending
- ⚠️ **No rate limiting:** Sends all chunks immediately (may hit rate limits)

---

### 2. Delta Message Handling

#### Kalshi Documented Delta Format

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

#### Current Implementation: `ws.py` - `_handle_message()`

```python
elif channel == "orderbook_delta":
    # Always forward deltas
    data["type"] = "orderbook_delta"
    return data
```

**Status:** ✅ Forwards delta messages correctly

**Issues:**
- ⚠️ **No validation:** Doesn't validate delta message format
- ⚠️ **No transformation:** Assumes format matches expectations

---

#### Current Implementation: `market_state.py` - `apply_orderbook_message()`

```python
def apply_orderbook_message(self, msg: Dict[str, Any]) -> None:
    """Apply WS orderbook_snapshot or orderbook_delta message."""
    ticker = msg.get("ticker") or msg.get("market_ticker")
    
    with self._lock:
        state = self._states.get(ticker)
        
        if channel == "orderbook_delta":
            # Apply delta to orderbook
            side = msg.get("side")
            price_dollars = msg.get("price_dollars") or msg.get("price")
            delta_fp = msg.get("delta_fp") or msg.get("delta") or msg.get("size_delta")
            
            # Convert to cents
            price_cents = int(float(price_dollars) * 100) if price_dollars else None
            delta = int(delta_fp) if delta_fp else 0
            
            # Apply to book
            if side == "yes":
                state.yes_levels[price_cents] += delta
            elif side == "no":
                state.no_levels[price_cents] += delta
```

**Status:** ⚠️ Accepts multiple field name variants

**Issues:**
- 🚨 **Field name mismatch:** Accepts `price_dollars` and `price` (documented is `price`)
- 🚨 **Field name mismatch:** Accepts `delta_fp`, `delta`, and `size_delta` (documented is `delta`)
- 🚨 **Unit conversion:** Converts dollars to cents (should use adapter)
- 🚨 **No validation:** Doesn't validate price range or delta value

---

### 3. Snapshot Message Handling

#### Kalshi Documented Snapshot Format

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

#### Current Implementation: `ws.py` - `_handle_message()`

```python
elif channel == "orderbook_snapshot":
    # Forward snapshot
    data["type"] = "orderbook_snapshot"
    return data
```

**Status:** ✅ Forwards snapshot messages correctly

---

#### Current Implementation: `market_state.py` - `apply_orderbook_message()`

```python
if channel == "orderbook_snapshot":
    # Apply snapshot to orderbook
    yes_levels = msg.get("yes", [])
    no_levels = msg.get("no", [])
    
    # Convert to internal format
    for price_dollars, size in yes_levels:
        price_cents = int(float(price_dollars) * 100)
        state.yes_levels[price_cents] = int(size)
    
    for price_dollars, size in no_levels:
        price_cents = int(float(price_dollars) * 100)
        state.no_levels[price_cents] = int(size)
```

**Status:** ✅ Applies snapshot correctly

**Issues:**
- ⚠️ **Unit conversion:** Converts dollars to cents inline (should use adapter)
- ⚠️ **No validation:** Doesn't validate price range or size value

---

### 4. Delta Application Logic

#### Kalshi Documented Delta Application

From [docs.kalshi.com/orderbook_responses](https://docs.kalshi.com/getting_started/orderbook_responses):
- **Positive delta:** Add size to price level
- **Negative delta:** Remove size from price level
- **Zero delta:** Remove price level entirely

---

#### Current Implementation: `market_state.py`

```python
# Apply delta to book
if side == "yes":
    state.yes_levels[price_cents] += delta
elif side == "no":
    state.no_levels[price_cents] += delta

# Remove zero-size levels
if state.yes_levels[price_cents] <= 0:
    del state.yes_levels[price_cents]
if state.no_levels[price_cents] <= 0:
    del state.no_levels[price_cents]
```

**Status:** ✅ Implements delta application correctly

**Issues:**
- ⚠️ **No sequence checking:** Doesn't verify delta sequence order
- ⚠️ **No gap detection:** Doesn't detect missing deltas

---

### 5. Data Flow Diagram

```
WS Bridge (subscribe_orderbooks_batch)
    ↓
    {"id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_tickers": [...]}}
    ↓
Kalshi WS
    ↓
    {"type": "orderbook_delta", "market_ticker": "...", "side": "yes", "price": 0.50, "delta": 10}
    ↓
ws.py (_handle_message)
    ↓
    Forward to market_state
    ↓
market_state.py (apply_orderbook_message)
    ↓
    Accept multiple field names (price_dollars/price, delta_fp/delta/size_delta)
    ↓
    Convert dollars → cents
    ↓
    Apply to yes_levels/no_levels
```

**Issues in Flow:**
1. 🚨 **Field name mismatches:** Accepts multiple variants
2. 🚨 **Unit conversion:** Scattered conversion logic
3. 🚨 **No validation:** No format validation at any step

---

## Required Fixes

### Fix 1: Standardize Delta Field Names

**File:** `market_state.py` - `apply_orderbook_message()`

**Current:**
```python
price_dollars = msg.get("price_dollars") or msg.get("price")
delta_fp = msg.get("delta_fp") or msg.get("delta") or msg.get("size_delta")
```

**Proposed:**
```python
price = msg.get("price")  # Kalshi documented field
delta = msg.get("delta")  # Kalshi documented field

if price is None:
    raise ValueError("Delta message missing required field: price")
if delta is None:
    raise ValueError("Delta message missing required field: delta")
```

**Implementation:**
1. Use only documented field names
2. Add validation for required fields
3. Remove alternative format support

---

### Fix 2: Centralize Unit Conversion

**File:** `market_state.py` - `apply_orderbook_message()`

**Current:**
```python
price_cents = int(float(price_dollars) * 100) if price_dollars else None
```

**Proposed:**
```python
from merid.event_venues.kalshi.types import NormalizedBook

# Use adapter for conversion
price_cents = NormalizedBook.dollars_to_cents(price)
```

**Implementation:**
1. Add conversion method to NormalizedBook adapter
2. Use adapter for all conversions
3. Remove inline conversion logic

---

### Fix 3: Add Delta Validation

**File:** `market_state.py` - `apply_orderbook_message()`

**Add validation:**
```python
# Validate price range
if not (0.00 <= price <= 1.00):
    logger.warning(
        "[DELTA-VALIDATION] Invalid price %s for ticker %s (must be 0.00-1.00)",
        price, ticker
    )
    return  # Skip invalid delta

# Validate side
if side not in ("yes", "no"):
    logger.warning(
        "[DELTA-VALIDATION] Invalid side %s for ticker %s (must be yes/no)",
        side, ticker
    )
    return  # Skip invalid delta

# Validate delta is integer
if not isinstance(delta, (int, float)):
    logger.warning(
        "[DELTA-VALIDATION] Invalid delta %s for ticker %s (must be numeric)",
        delta, ticker
    )
    return  # Skip invalid delta
```

**Implementation:**
1. Add price range validation (0.00-1.00)
2. Add side validation (yes/no)
3. Add delta type validation
4. Skip invalid deltas with warning

---

### Fix 4: Add Sequence Checking

**File:** `market_state.py` - `apply_orderbook_message()`

**Add sequence tracking:**
```python
# Track sequence numbers
seq = msg.get("seq")
if seq is not None:
    if state._last_seq is not None and seq != state._last_seq + 1:
        logger.warning(
            "[DELTA-SEQUENCE] Sequence gap detected for ticker %s: expected %d, got %d",
            ticker, state._last_seq + 1, seq
        )
    state._last_seq = seq
```

**Implementation:**
1. Track sequence numbers per ticker
2. Detect sequence gaps
3. Log warnings for gaps
4. Consider requesting new snapshot on gap

---

### Fix 5: Add Subscription Validation

**File:** `ws.py` - `subscribe_orderbooks_batch()`

**Add validation:**
```python
def _validate_market_ticker(self, ticker: str) -> bool:
    """Validate ticker format matches Kalshi pattern."""
    import re
    pattern = r"^KX[A-Z]+[0-9A-Z]+-[0-9A-Z]+-[0-9]+$"
    return bool(re.match(pattern, ticker.upper()))

# In subscribe_orderbooks_batch:
valid_tickers = [t for t in uniq if self._validate_market_ticker(t)]
invalid_tickers = set(uniq) - set(valid_tickers)

if invalid_tickers:
    logger.warning(
        "[WS-SUBSCRIPTION] Skipping invalid tickers: %s",
        invalid_tickers
    )

uniq = valid_tickers
```

**Implementation:**
1. Add ticker format validation
2. Skip invalid tickers
3. Log warnings
4. Use only valid tickers for subscription

---

### Fix 6: Add Rate Limiting

**File:** `ws.py` - `subscribe_orderbooks_batch()`

**Add rate limiting:**
```python
import asyncio

# Add delay between chunks
for i in range(0, len(uniq), chunk_size):
    chunk = uniq[i : i + chunk_size]
    # ... send chunk
    
    # Add delay to avoid rate limiting
    if i + chunk_size < len(uniq):
        await asyncio.sleep(0.1)  # 100ms delay between chunks
```

**Implementation:**
1. Add delay between chunks
2. Configure delay duration
3. Monitor for rate limit errors
4. Adjust delay if needed

---

## Audit Checklist

- [ ] Document subscription payload (✅ documented)
- [ ] Document delta message format (✅ documented)
- [ ] Document snapshot message format (✅ documented)
- [ ] Identify field name mismatches (price_dollars/price, delta_fp/delta)
- [ ] Identify unit conversion issues (scattered logic)
- [ ] Identify missing validation (no format checks)
- [ ] Identify missing sequence checking (no gap detection)
- [ ] Identify missing rate limiting (immediate chunk send)
- [ ] Plan migration path (6 fixes)
- [ ] Standardize delta field names
- [ ] Centralize unit conversion
- [ ] Add delta validation
- [ ] Add sequence checking
- [ ] Add subscription validation
- [ ] Add rate limiting

---

## Next Steps

1. **Immediate:** Standardize delta field names to match docs
2. **Immediate:** Add subscription validation
3. **Short-term:** Centralize unit conversion
4. **Short-term:** Add delta validation
5. **Medium-term:** Add sequence checking
6. **Medium-term:** Add rate limiting
7. **Long-term:** Add automated delta monitoring

**Priority:** HIGH - Field name mismatches can cause incorrect delta application

**Risk:** If Kalshi changes field names or adds validation, current code may fail silently or apply deltas incorrectly.

**Note:** Subscription payload matches documented format exactly. The main issues are in delta handling (field name mismatches) and missing validation.
