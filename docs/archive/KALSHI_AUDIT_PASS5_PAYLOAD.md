# Kalshi API Audit - Pass 5.1: Order Routing Payload

**Objective:** Compare order routing payload to Kalshi's POST /portfolio/orders endpoint.

**Kalshi Reference:** 
- [docs.kalshi.com/orders](https://docs.kalshi.com/getting_started/orders)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. Order Placement Endpoint

#### Kalshi Documented Endpoint

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Endpoint:** `POST /portfolio/orders`
- **Purpose:** Place a new order
- **Authentication:** Required (RSA signature)

---

#### Current Implementation: `client.py` - `place_order_result()`

```python
async def place_order_result(
    self, order: VenueOrder, order_group_id: Optional[str] = None, self_trade_prevention_type: Optional[str] = None
) -> OperationResult[Optional[PlacedOrder]]:
    """Place order with explicit result.

    Kalshi order format:
      POST /portfolio/orders
      {ticker, side, action, type, count, {side}_price, time_in_force, client_order_id}
    """
    # Build order payload
    kalshi_order: Dict[str, Any] = {
        "ticker": ticker,
        "action": order.side,           # "buy" or "sell"
        "side": outcome,                # "yes" or "no"
        "count": int(order.size),
        "type": order.order_type,       # "limit" or "market"
        "client_order_id": order.client_order_id or f"merid_{timestamp}",
    }
    
    # Add price field
    if order.price is not None:
        _price_cents = int(order.price * 100)
        price_field = f"{outcome}_price"  # yes_price or no_price
        kalshi_order[price_field] = _price_cents
    
    # Add time_in_force
    kalshi_order["time_in_force"] = merid_time_in_force_to_kalshi_api(
        getattr(order, "time_in_force", None) or "GTC"
    )
    
    # Add optional fields
    if order_group_id:
        kalshi_order["order_group_id"] = order_group_id
    if self_trade_prevention_type:
        kalshi_order["self_trade_prevention_type"] = self_trade_prevention_type
    if getattr(order, "post_only", False):
        kalshi_order["post_only"] = True
    
    result = await self._request_with_resilience(
        "POST", "/portfolio/orders", json_data=kalshi_order, operation_name="place_order"
    )
```

**Endpoint Used:** `POST /portfolio/orders`

**Status:** ✅ Matches documented endpoint

---

### 2. Order Payload Schema

#### Kalshi Documented Payload

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
```json
{
  "ticker": "KXBTC15M-26MAY241830-30",
  "action": "buy",
  "side": "yes",
  "count": 10,
  "type": "limit",
  "yes_price": 50,  // or no_price for NO side
  "time_in_force": "good_till_canceled",
  "client_order_id": "my-order-123"
}
```

**Field Mapping:**
- `ticker`: Market identifier
- `action`: "buy" or "sell"
- `side`: "yes" or "no"
- `count`: Number of contracts
- `type`: "limit" or "market"
- `{side}_price`: Price in cents (yes_price or no_price)
- `time_in_force`: "good_till_canceled", "immediate_or_cancel", "fill_or_kill"
- `client_order_id`: Optional client-specified ID

**Optional Fields:**
- `order_group_id`: For aggregate limits
- `self_trade_prevention_type`: STP mode
- `post_only`: Post-only flag

---

#### Current Implementation Payload

```python
kalshi_order: Dict[str, Any] = {
    "ticker": ticker,                          # ✅ Correct
    "action": order.side,                     # ✅ "buy" or "sell"
    "side": outcome,                          # ✅ "yes" or "no"
    "count": int(order.size),                 # ✅ Contracts
    "type": order.order_type,                 # ✅ "limit" or "market"
    "client_order_id": order.client_order_id or f"merid_{timestamp}",  # ✅ Optional
    f"{outcome}_price": _price_cents,         # ✅ yes_price or no_price (cents)
    "time_in_force": "good_till_canceled",    # ✅ Converted from GTC
    "order_group_id": order_group_id,         # ✅ Optional
    "self_trade_prevention_type": stp_type,   # ✅ Optional
    "post_only": True,                        # ✅ Optional
}
```

**Status:** ✅ Matches documented schema

**Features:**
- ✅ All required fields present
- ✅ Optional fields handled correctly
- ✅ Price in cents (not dollars)
- ✅ Time-in-force conversion (GTC → good_till_canceled)
- ✅ Client order ID generation if not provided

---

### 3. Price Field Handling

#### Kalshi Documented Price Fields

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Required:** Exactly one price field
- **Options:** `yes_price`, `no_price`, `yes_price_dollars`, `no_price_dollars`
- **Units:** Cents (integer) or dollars (float)
- **Note:** Even market orders require a price field (ignored by Kalshi)

---

#### Current Implementation

```python
# Price field selection
if order.price is not None:
    _price_cents = int(order.price * 100)
    price_field = f"{outcome}_price"  # yes_price or no_price
    kalshi_order[price_field] = _price_cents
else:
    # Fallback to default midpoint
    from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
    price_field = f"{outcome}_price"
    kalshi_order[price_field] = DEFAULT_KALSHI_PRICE_CENTS

# Validation: exactly one price field
price_fields = ["yes_price", "no_price", "yes_price_dollars", "no_price_dollars"]
set_prices = [f for f in price_fields if f in kalshi_order]
if len(set_prices) != 1:
    return OperationResult.fail("Invalid order: exactly one price field required")
```

**Status:** ✅ Correct price field handling

**Issues:**
- ⚠️ **Default fallback:** Uses DEFAULT_KALSHI_PRICE_CENTS if no price provided
- ⚠️ **Cents only:** Only uses cents format, not dollars

---

### 4. Time-in-Force Conversion

#### Kalshi Documented Values

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- `good_till_canceled` (GTC)
- `immediate_or_cancel` (IOC)
- `fill_or_kill` (FOK)

---

#### Current Implementation

```python
def merid_time_in_force_to_kalshi_api(tif: str) -> str:
    """Convert internal time-in-force to Kalshi API format."""
    mapping = {
        "GTC": "good_till_canceled",
        "IOC": "immediate_or_cancel",
        "FOK": "fill_or_kill",
    }
    return mapping.get(tif, "good_till_canceled")
```

**Status:** ✅ Correct conversion

---

### 5. Validation Layers

#### Pre-Send Validation

```python
# Ticker validation
valid, error_msg = await _validate_ticker_exists(ticker)
if not valid:
    return OperationResult.fail(f"Invalid ticker: {ticker}")

# Price validation
if _price_cents <= 0:
    return OperationResult.fail(f"Invalid order price: {_price_cents} cents (must be > 0)")

# Price field validation
if len(set_prices) != 1:
    return OperationResult.fail("Invalid order: exactly one price field required")

# Global execution guard
_allowed, _reason = _guard.check_order(...)
if not _allowed:
    return OperationResult.fail(f"Global execution guard blocked: {_reason}")
```

**Status:** ✅ Multiple validation layers

**Features:**
- ✅ Ticker existence check
- ✅ Price validation
- ✅ Price field validation
- ✅ Global execution guard

**Issues:**
- ⚠️ **Multiple guards:** Global guard + local validation
- ⚠️ **Blocking behavior:** Fail-closed on any validation failure

---

### 6. Data Flow: Order Placement

```
Agent Grid / Trading Agent
    ↓
    VenueOrder (market_id, side, size, price, order_type, ...)
    ↓
    client.place_order_result(order)
    ↓
    Global execution guard check
    ↓
    Ticker validation (exists in catalog)
    ↓
    Build Kalshi order payload
    ↓
    Price validation (positive)
    ↓
    Price field validation (exactly one)
    ↓
    Time-in-force conversion
    ↓
    POST /portfolio/orders
    ↓
    Kalshi API
    ↓
    PlacedOrder response
    ↓
    Return to caller
```

**Status:** ✅ Clear data flow

**Issues:**
- ⚠️ **Multiple validation points:** Guard + pre-send validation
- ⚠️ **Blocking behavior:** Fail-closed at multiple points

---

## Required Fixes

### Fix 1: Remove Default Price Fallback

**File:** `client.py` - `place_order_result()`

**Current:**
```python
if order.price is not None:
    _price_cents = int(order.price * 100)
    price_field = f"{outcome}_price"
    kalshi_order[price_field] = _price_cents
else:
    # Fallback to default midpoint
    from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS
    logger.warning("No price provided, using default fallback")
    price_field = f"{outcome}_price"
    kalshi_order[price_field] = DEFAULT_KALSHI_PRICE_CENTS
```

**Proposed:**
```python
if order.price is None:
    return OperationResult.fail(
        f"Order price is required for {order.order_type} order on {ticker}",
        latency_ms=0.0,
        retries=0,
    )

_price_cents = int(order.price * 100)
if _price_cents <= 0:
    return OperationResult.fail(
        f"Invalid order price: {_price_cents} cents (must be > 0)",
        latency_ms=0.0,
        retries=0,
    )

price_field = f"{outcome}_price"
kalshi_order[price_field] = _price_cents
```

**Implementation:**
1. Remove default fallback
2. Require price for all orders
3. Fail fast if price missing
4. Document that market orders also require price (per Kalshi spec)

---

### Fix 2: Support Dollar Price Fields

**File:** `client.py` - `place_order_result()`

**Current:**
```python
# Only uses cents format
price_field = f"{outcome}_price"  # yes_price or no_price
kalshi_order[price_field] = _price_cents
```

**Proposed:**
```python
# Support both cents and dollars formats
# Prefer cents for precision
price_field = f"{outcome}_price"  # yes_price or no_price
kalshi_order[price_field] = _price_cents

# Optionally support dollars (documented but not used)
# kalshi_order[f"{outcome}_price_dollars"] = order.price
```

**Implementation:**
1. Keep cents as primary format
2. Document dollar format support
3. Add configuration option if needed
4. Keep validation for exactly one price field

---

### Fix 3: Consolidate Validation Layers

**File:** `client.py` - `place_order_result()`

**Current:** Global guard + pre-send validation

**Proposed:** Single validation function

```python
async def _validate_order(self, order: VenueOrder) -> Tuple[bool, Optional[str]]:
    """Validate order before sending to Kalshi.
    
    Consolidates all validation logic into one place.
    """
    # Ticker validation
    valid, error_msg = await _validate_ticker_exists(order.market_id)
    if not valid:
        return False, error_msg
    
    # Price validation
    if order.price is None:
        return False, "Order price is required"
    
    _price_cents = int(order.price * 100)
    if _price_cents <= 0:
        return False, f"Invalid order price: {_price_cents} cents (must be > 0)"
    
    # Size validation
    if order.size <= 0:
        return False, f"Invalid order size: {order.size} (must be > 0)"
    
    # Global execution guard
    try:
        from merid.guards.global_execution_guard import get_global_execution_guard
        _guard = get_global_execution_guard()
        _allowed, _reason = _guard.check_order(...)
        if not _allowed:
            return False, f"Global execution guard blocked: {_reason}"
    except ImportError:
        pass  # Guard not available
    
    return True, None
```

**Implementation:**
1. Create single validation function
2. Call once before building payload
3. Remove scattered validation
4. Document all validation rules

---

### Fix 4: Add Order Payload Validation

**File:** `client.py` - `place_order_result()`

**Add:**
```python
def _validate_order_payload(kalshi_order: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate order payload matches Kalshi schema."""
    required_fields = ["ticker", "action", "side", "count", "type"]
    
    for field in required_fields:
        if field not in kalshi_order:
            return False, f"Missing required field: {field}"
    
    # Validate action
    if kalshi_order["action"] not in ("buy", "sell"):
        return False, f"Invalid action: {kalshi_order['action']} (must be buy/sell)"
    
    # Validate side
    if kalshi_order["side"] not in ("yes", "no"):
        return False, f"Invalid side: {kalshi_order['side']} (must be yes/no)"
    
    # Validate type
    if kalshi_order["type"] not in ("limit", "market"):
        return False, f"Invalid type: {kalshi_order['type']} (must be limit/market)"
    
    # Validate exactly one price field
    price_fields = ["yes_price", "no_price", "yes_price_dollars", "no_price_dollars"]
    set_prices = [f for f in price_fields if f in kalshi_order]
    if len(set_prices) != 1:
        return False, f"Invalid price fields: {set_prices} (exactly one required)"
    
    # Validate time_in_force
    valid_tif = ["good_till_canceled", "immediate_or_cancel", "fill_or_kill"]
    if kalshi_order.get("time_in_force") not in valid_tif:
        return False, f"Invalid time_in_force: {kalshi_order.get('time_in_force')}"
    
    return True, None
```

**Implementation:**
1. Add payload validation function
2. Validate all required fields
3. Validate field values
4. Call before sending to API

---

### Fix 5: Document Order Payload Schema

**File:** `client.py` - `place_order_result()`

**Add:**
```python
"""
Kalshi Order Payload Schema:
----------------------------
Required Fields:
- ticker: Market identifier (e.g., "KXBTC15M-26MAY241830-30")
- action: "buy" or "sell"
- side: "yes" or "no"
- count: Number of contracts (integer > 0)
- type: "limit" or "market"
- {side}_price: Price in cents (yes_price or no_price, integer > 0)
  - Alternative: {side}_price_dollars (float, 0.00-1.00)
  - Exactly one price field required
- time_in_force: "good_till_canceled", "immediate_or_cancel", "fill_or_kill"

Optional Fields:
- client_order_id: Client-specified order ID (string)
- order_group_id: Order group ID for aggregate limits (string)
- self_trade_prevention_type: STP mode (e.g., "taker_at_cross")
- post_only: Post-only flag (boolean)

Notes:
- Even market orders require a price field (ignored by Kalshi)
- Price must be positive (> 0)
- Count must be positive (> 0)
- Ticker must exist in Kalshi catalog
"""
```

**Implementation:**
1. Add module-level documentation
2. Document required fields
3. Document optional fields
4. Document constraints

---

## Audit Checklist

- [ ] Document order endpoint (✅ documented)
- [ ] Document order payload schema (✅ documented)
- [ ] Document price field handling (✅ documented)
- [ ] Document time-in-force conversion (✅ documented)
- [ ] Document validation layers (✅ documented)
- [ ] Identify default price fallback (⚠️ uses DEFAULT_KALSHI_PRICE_CENTS)
- [ ] Identify cents-only format (⚠️ no dollar support)
- [ ] Identify multiple validation layers (⚠️ guard + pre-send)
- [ ] Identify blocking behavior (⚠️ fail-closed)
- [ ] Plan migration path (5 fixes)
- [ ] Remove default price fallback
- [ ] Support dollar price fields
- [ ] Consolidate validation layers
- [ ] Add order payload validation
- [ ] Document order payload schema

---

## Next Steps

1. **Immediate:** Remove default price fallback
2. **Immediate:** Add order payload validation
3. **Short-term:** Consolidate validation layers
4. **Short-term:** Support dollar price fields
5. **Medium-term:** Document order payload schema
6. **Medium-term:** Add automated order validation monitoring
7. **Long-term:** Add order payload testing

**Priority:** MEDIUM - Order payload matches documented schema but has defensive fallbacks

**Risk:** Default price fallback may send orders at incorrect prices. Multiple validation layers create complexity.

**Note:** Order payload matches Kalshi documentation exactly. The main issues are defensive fallbacks (default price) and multiple validation layers.
