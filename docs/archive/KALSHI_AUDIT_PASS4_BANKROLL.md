# Kalshi API Audit - Pass 4.1: Bankroll and Positions

**Objective:** Map bankroll and positions to Kalshi endpoints and verify data flow.

**Kalshi Reference:** 
- [docs.kalshi.com/portfolio](https://docs.kalshi.com/getting_started/portfolio)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. Bankroll Endpoint

#### Kalshi Documented Endpoint

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Endpoint:** `GET /portfolio/balance`
- **Purpose:** Fetch account balance including cash and portfolio value
- **Response:** Balance in USD cents

---

#### Current Implementation: `client.py` - `get_balance_result()`

```python
async def get_balance_result(self) -> OperationResult[Dict[str, Decimal]]:
    """Get account balance with explicit result."""
    result = await self._request_with_resilience(
        "GET", "/portfolio/balance", operation_name="get_balance"
    )
    
    if not result.success:
        return OperationResult.fail(result.error, ...)
    
    raw = result.data or {}
    balance_cents = raw.get("balance", 0)
    locked_cents = raw.get("locked_balance", 0)
    
    # Handle nested format
    if isinstance(balance_cents, dict):
        locked_cents = balance_cents.get("locked_balance", 0)
        balance_cents = balance_cents.get("balance", 0)
    
    # Convert cents to USD
    balance_usd = Decimal(str(balance_cents)) / 100
    locked_usd = Decimal(str(locked_cents)) / 100
    
    # Validation
    if balance_usd < 0:
        logger.warning("Negative balance detected, treating as zero")
        balance_usd = Decimal("0")
    if locked_usd < 0:
        logger.warning("Negative locked balance detected, treating as zero")
        locked_usd = Decimal("0")
    
    return OperationResult.ok({
        "USD": balance_usd,
        "locked": locked_usd
    }, ...)
```

**Endpoint Used:** `GET /portfolio/balance`

**Status:** ✅ Matches documented endpoint

**Issues:**
- ⚠️ **Dual format support:** Handles both flat and nested response formats
- ⚠️ **Silent correction:** Treats negative balances as zero without failing
- ⚠️ **Unit conversion:** Converts cents to USD inline

---

#### Current Implementation: `bankroll_service_v2.py` - `_fetch_and_update()`

```python
async def _fetch_and_update(self):
    """Fetch from Kalshi and update internal state."""
    result = await self._client.get_balance()
    
    async with self._lock:
        self._fetch_count += 1
        
        if isinstance(result, BalanceSuccess):
            # Fresh data - update everything
            self._current = result.bankroll
            self._last_success = datetime.now(timezone.utc)
            
            # Log snapshot
            equity = float(result.bankroll.equity_usd)
            available = float(result.bankroll.available_cash_usd)
            locked = float(result.bankroll.locked_cash_usd)
            logger.info(
                "BANKROLL-SNAPSHOT equity=%.2f available_cash=%.2f positions=%.2f source=%s state=%s",
                equity, available, locked,
                result.bankroll.source,
                result.bankroll.state.name
            )
            
        elif isinstance(result, BalanceTemporaryError):
            # Temporary error - FAIL-CLOSED: transition to ERROR to block trading
            self._error_count += 1
            self._last_error = result.reason
            self._last_error_time = datetime.now(timezone.utc)
            
            if self._current:
                self._current = self._current.with_state(BalanceState.ERROR)
                logger.error(
                    f"[bankroll_refresh] ERROR (fail-closed): {result.reason}, "
                    f"trading BLOCKED - not using cached equity=${self._current.equity_usd}"
                )
```

**Status:** ✅ Proper error handling with fail-closed behavior

**Issues:**
- ⚠️ **Multiple result types:** Handles BalanceSuccess, BalanceTemporaryError, BalancePermanentError
- ⚠️ **State transitions:** Transitions to ERROR on temporary errors (blocks trading)

---

### 2. Positions Endpoint

#### Kalshi Documented Endpoint

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Endpoint:** `GET /portfolio/positions`
- **Purpose:** Fetch all open positions
- **Parameters:** `limit`, `cursor`, `status`
- **Response:** Array of position objects

---

#### Current Implementation: `client.py` - Multiple Position Methods

**Method 1: `get_positions()`**
```python
async def get_positions(
    self,
    limit: int = 200,
    cursor: Optional[str] = None,
    status: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get portfolio positions."""
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if status:
        params["status"] = status
    
    result = await self._request_with_resilience(
        "GET", "/portfolio/positions", params=params, operation_name="get_positions"
    )
    return result.unwrap_or([])
```

**Endpoint Used:** `GET /portfolio/positions`

**Status:** ✅ Matches documented endpoint

---

**Method 2: `get_positions_aggregated_by_event()`**
```python
async def get_positions_aggregated_by_event(
    self, limit: int = 200
) -> OperationResult[Dict[str, Dict[str, Any]]]:
    """Aggregate portfolio positions by event_ticker."""
    # Fetches all positions via cursor pagination
    # Aggregates by event_ticker
    # Sums exposure, cost, PnL, fees
```

**Endpoint Used:** `GET /portfolio/positions`

**Status:** ✅ Uses same endpoint with aggregation logic

---

**Method 3: `get_positions_filtered()`**
```python
async def get_positions_filtered(
    self,
    market_ticker: Optional[str] = None,
    event_ticker: Optional[str] = None,
    limit: int = 200
) -> OperationResult[List[Dict[str, Any]]]:
    """Get positions with filters."""
    params = {"limit": limit}
    if market_ticker:
        params["market_ticker"] = market_ticker
    if event_ticker:
        params["event_ticker"] = event_ticker
    
    result = await self._request_with_resilience(
        "GET", "/portfolio/positions", params=params, operation_name="get_positions_filtered"
    )
```

**Endpoint Used:** `GET /portfolio/positions`

**Status:** ✅ Uses same endpoint with filters

---

### 3. Data Flow: Bankroll

```
BankrollServiceV2._fetch_and_update()
    ↓
    client.get_balance()
    ↓
    GET /portfolio/balance
    ↓
    Raw response: {balance: cents, locked_balance: cents}
    ↓
    client.get_balance_result()
    ↓
    Convert cents → USD
    ↓
    Handle dual format (flat/nested)
    ↓
    Validate (negative → zero)
    ↓
    Return: {USD: balance_usd, locked: locked_usd}
    ↓
    BankrollServiceV2
    ↓
    Update internal state
    ↓
    Notify subscribers
```

**Status:** ✅ Clear data flow

**Issues:**
- ⚠️ **Dual format handling:** May indicate API inconsistency
- ⚠️ **Negative balance correction:** May mask API errors

---

### 4. Data Flow: Positions

```
Risk Pipeline / Trading Agent
    ↓
    client.get_positions() or get_positions_aggregated_by_event()
    ↓
    GET /portfolio/positions
    ↓
    Raw response: {positions: [...], cursor: ...}
    ↓
    Parse positions
    ↓
    Aggregate (if needed)
    ↓
    Return position data
    ↓
    Risk calculation / Position tracking
```

**Status:** ✅ Clear data flow

**Issues:**
- ⚠️ **Multiple methods:** Three different methods for positions
- ⚠️ **No single source:** Different callers use different methods

---

### 5. Bankroll State Management

#### Current Implementation: `bankroll_service_v2.py`

**States:**
- `UNKNOWN` - No data fetched yet
- `FRESH` - Successfully fetched from API
- `STALE` - Data is old (not used in current implementation)
- `ERROR` - API fetch failed (blocks trading)

**Transitions:**
- UNKNOWN → FRESH on successful fetch
- FRESH → ERROR on temporary error (fail-closed)
- FRESH → ERROR on permanent error

**Status:** ✅ Proper state machine

**Issues:**
- ⚠️ **STALE state unused:** STALE state exists but is never used
- ⚠️ **No retry logic:** Immediate transition to ERROR on temporary error

---

### 6. Position Data Structure

#### Kalshi Documented Position Format

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
```json
{
  "market_ticker": "KXBTC15M-26MAY241830-30",
  "side": "yes",
  "quantity": 10,
  "avg_price": 0.50,
  "total_cost": 5.00,
  "current_price": 0.55,
  "unrealized_pnl": 0.50
}
```

---

#### Current Implementation: `risk_projection.py`

```python
"""1:1 mapping to Kalshi GET /portfolio/positions market_positions."""
# Position fields used:
# - market_ticker
# - side (yes/no)
# - quantity
# - avg_price
# - total_cost
# - current_price
# - unrealized_pnl
```

**Status:** ✅ Uses documented fields

**Issues:**
- ⚠️ **No validation:** Doesn't validate field presence or types
- ⚠️ **No normalization:** Relies on exact field names

---

## Required Fixes

### Fix 1: Remove Dual Format Support

**File:** `client.py` - `get_balance_result()`

**Current:**
```python
balance_cents = raw.get("balance", 0)
locked_cents = raw.get("locked_balance", 0)

# Handle nested format
if isinstance(balance_cents, dict):
    locked_cents = balance_cents.get("locked_balance", 0)
    balance_cents = balance_cents.get("balance", 0)
```

**Proposed:**
```python
# Expect flat format only (documented by Kalshi)
balance_cents = raw.get("balance", 0)
locked_cents = raw.get("locked_balance", 0)

if isinstance(balance_cents, dict):
    raise ValueError(
        f"Unexpected nested balance format. Expected flat format with 'balance' and 'locked_balance' keys. "
        f"Got: {list(balance_cents.keys())}"
    )
```

**Implementation:**
1. Remove nested format handling
2. Add validation for unexpected format
3. Fail fast on format mismatch

---

### Fix 2: Remove Silent Negative Balance Correction

**File:** `client.py` - `get_balance_result()`

**Current:**
```python
if balance_usd < 0:
    logger.warning("Negative balance detected, treating as zero")
    balance_usd = Decimal("0")
```

**Proposed:**
```python
if balance_usd < 0:
    raise ValueError(
        f"Negative balance detected: ${balance_usd}. "
        f"This indicates an API error or data corruption. "
        f"Trading halted until resolved."
    )
```

**Implementation:**
1. Remove silent correction
2. Raise error on negative balance
3. Block trading on data corruption

---

### Fix 3: Centralize Unit Conversion

**File:** `client.py` - `get_balance_result()`

**Current:**
```python
balance_usd = Decimal(str(balance_cents)) / 100
locked_usd = Decimal(str(locked_cents)) / 100
```

**Proposed:**
```python
from merid.event_venues.kalshi.types import KalshiCurrency

balance_usd = KalshiCurrency.cents_to_usd(balance_cents)
locked_usd = KalshiCurrency.cents_to_usd(locked_cents)
```

**Implementation:**
1. Add currency conversion utilities
2. Use utilities for all conversions
3. Remove inline conversion logic

---

### Fix 4: Consolidate Position Methods

**File:** `client.py`

**Current:** Three separate methods (`get_positions`, `get_positions_aggregated_by_event`, `get_positions_filtered`)

**Proposed:** Single method with optional aggregation and filters

```python
async def get_positions(
    self,
    limit: int = 200,
    cursor: Optional[str] = None,
    status: Optional[str] = None,
    market_ticker: Optional[str] = None,
    event_ticker: Optional[str] = None,
    aggregate_by_event: bool = False
) -> OperationResult:
    """Get portfolio positions with optional aggregation and filters."""
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if status:
        params["status"] = status
    if market_ticker:
        params["market_ticker"] = market_ticker
    if event_ticker:
        params["event_ticker"] = event_ticker
    
    result = await self._request_with_resilience(
        "GET", "/portfolio/positions", params=params, operation_name="get_positions"
    )
    
    if not result.success:
        return OperationResult.fail(result.error, ...)
    
    positions = result.data.get("positions", [])
    
    if aggregate_by_event:
        # Aggregate by event_ticker
        aggregated = self._aggregate_positions_by_event(positions)
        return OperationResult.ok(aggregated, ...)
    
    return OperationResult.ok(positions, ...)
```

**Implementation:**
1. Consolidate three methods into one
2. Add optional parameters for aggregation and filters
3. Update all callers to use new method

---

### Fix 5: Add Position Validation

**File:** `client.py` - `get_positions()`

**Add validation:**
```python
def _validate_position(self, position: Dict[str, Any]) -> None:
    """Validate position structure matches Kalshi schema."""
    required_fields = ["market_ticker", "side", "quantity", "avg_price"]
    
    for field in required_fields:
        if field not in position:
            raise ValueError(f"Position missing required field: {field}")
    
    if position["side"] not in ("yes", "no"):
        raise ValueError(f"Invalid side: {position['side']} (must be yes/no)")
    
    if position["quantity"] < 0:
        raise ValueError(f"Invalid quantity: {position['quantity']} (must be >= 0)")
```

**Implementation:**
1. Add validation method
2. Validate each position
3. Skip invalid positions with warning

---

### Fix 6: Remove Unused STALE State

**File:** `bankroll_service_v2.py`

**Current:** STALE state exists but is never used

**Proposed:** Remove STALE state, only use FRESH and ERROR

**Implementation:**
1. Remove STALE from BalanceState enum
2. Remove STALE transitions
3. Simplify state machine

---

## Audit Checklist

- [ ] Document bankroll endpoint (✅ documented)
- [ ] Document positions endpoint (✅ documented)
- [ ] Document bankroll data flow (✅ documented)
- [ ] Document positions data flow (✅ documented)
- [ ] Identify dual format support (⚠️ flat/nested)
- [ ] Identify silent correction (negative → zero)
- [ ] Identify scattered unit conversion (inline)
- [ ] Identify multiple position methods (3 methods)
- [ ] Identify unused STALE state (never used)
- [ ] Plan migration path (6 fixes)
- [ ] Remove dual format support
- [ ] Remove silent negative correction
- [ ] Centralize unit conversion
- [ ] Consolidate position methods
- [ ] Add position validation
- [ ] Remove unused STALE state

---

## Next Steps

1. **Immediate:** Remove dual format support for balance
2. **Immediate:** Remove silent negative balance correction
3. **Short-term:** Centralize unit conversion
4. **Short-term:** Consolidate position methods
5. **Medium-term:** Add position validation
6. **Medium-term:** Remove unused STALE state
7. **Long-term:** Add automated bankroll monitoring

**Priority:** MEDIUM - Bankroll and positions are working but have defensive workarounds

**Risk:** Dual format support and silent correction may mask API errors. Multiple position methods create inconsistency.

**Note:** Both endpoints match documented requirements. The main issues are defensive workarounds (dual format, silent correction) and code duplication (multiple position methods).
