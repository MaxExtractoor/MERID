# Kalshi API Audit - Pass 4.2: Limits and Fee Schedule

**Objective:** Align fee calculations and position limits with Kalshi's documented formulas.

**Kalshi Reference:** 
- [docs.kalshi.com/fees](https://docs.kalshi.com/getting_started/fees)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. Fee Formula

#### Kalshi Documented Fee Formula

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Taker fee:** `fee_cents = ceil(0.07 * C * P * (1 - P))`
- **Maker fee:** `fee_cents = ceil(0.0175 * C * P * (1 - P))`
- **Where:**
  - `C` = number of contracts
  - `P` = contract price in dollars (0.01 to 0.99)
- **Maximum fee:** At P = 0.5
  - Taker: 1.75¢ per contract
  - Maker: 0.4375¢ per contract

---

#### Current Implementation: `parabolic_fees.py`

**Taker Fee:**
```python
def kalshi_taker_fee_cents_parabolic(
    price_dollars: float,
    contracts: int,
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
) -> int:
    """Calculate Kalshi taker fee in cents using parabolic formula.

    Formula: fee_cents = ceil(0.07 * C * P * (1 - P))
    """
    if contracts <= 0:
        return 0
    
    sched = schedule or get_active_fee_schedule()
    P = _validate_price(price_dollars)
    C = int(contracts)
    
    # Use Decimal to avoid float boundary errors
    p = Decimal(str(P))
    c = Decimal(C)
    rate = Decimal(str(sched.taker_rate))
    parabolic_term = p * (Decimal("1") - p)
    fee_cents_exact = rate * c * parabolic_term * Decimal("100")
    fee_cents = int(fee_cents_exact.to_integral_value(rounding=ROUND_CEILING))
    return max(0, fee_cents)
```

**Status:** ✅ Matches documented formula exactly

**Features:**
- ✅ Correct parabolic formula
- ✅ Decimal arithmetic for precision
- ✅ Ceil rounding
- ✅ Price validation (0.01 to 0.99)
- ✅ Returns 0 for invalid inputs

---

**Maker Fee:**
```python
def kalshi_maker_fee_cents(
    price_dollars: float,
    contracts: int,
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
) -> int:
    """Calculate Kalshi maker fee in cents using parabolic formula.

    Formula: fee_cents = ceil(0.0175 * C * P * (1 - P))
    """
    # Same implementation as taker, but with maker_rate
    rate = Decimal(str(sched.maker_rate))
    # ... rest same as taker
```

**Status:** ✅ Matches documented formula exactly

**Features:**
- ✅ Correct parabolic formula
- ✅ Maker rate is 25% of taker rate (0.0175 / 0.07 = 0.25)
- ✅ Same precision and validation as taker

---

### 2. Fee Constants

#### Kalshi Documented Constants

From `risk_parameters.py`:
```python
TAKER_FEE_RATE: Final[float] = 0.07
MAKER_FEE_RATE: Final[float] = 0.0175
FEE_MIN_PRICE_DOLLARS: Final[float] = 0.01
FEE_MAX_PRICE_DOLLARS: Final[float] = 0.99
MAX_TAKER_FEE_PER_CONTRACT_CENTS: Final[float] = 1.75
MAX_MAKER_FEE_PER_CONTRACT_CENTS: Final[float] = 0.4375
```

**Status:** ✅ Matches documented constants

---

### 3. Tiered vs Parabolic Fees

#### Legacy Tiered Fee System

From `risk_parameters.py`:
```python
# Fee tier boundaries (contract counts)
FEE_TIER_SMALL_MIN: Final[int] = 0
FEE_TIER_SMALL_MAX: Final[int] = 100
FEE_TIER_MEDIUM_MIN: Final[int] = 100
FEE_TIER_MEDIUM_MAX: Final[int] = 1000
FEE_TIER_LARGE_MIN: Final[int] = 1000
FEE_TIER_LARGE_MAX: Final[int] = 999999999

# Fee tier rates
FEE_RATE_SMALL: Final[float] = 0.07
FEE_RATE_MEDIUM: Final[float] = 0.05
FEE_RATE_LARGE: Final[float] = 0.03
```

**Status:** ⚠️ Legacy tiered system exists but is deprecated

**Issues:**
- ⚠️ **Dual systems:** Both tiered and parabolic exist
- ⚠️ **Confusion:** Unclear which is used where
- ⚠️ **Deprecated:** Tiered system marked as deprecated

---

#### Current Usage

From `position_sizer.py`:
```python
# Fee calculations — delegated to unified fees module
# These functions are now thin wrappers around the unified fees module

def kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Compute total Kalshi fee in cents for a trade.
    
    DELEGATED to unified fees module: merid.event_venues.kalshi.fees
    """
    return calculate_kalshi_fee_cents(contracts, price_cents)
```

**Status:** ✅ Delegates to unified fees module (parabolic)

---

### 4. Position Limits

#### Kalshi Documented Limits

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Maximum position size:** 10,000 contracts per market
- **Maximum order size:** 10,000 contracts per order
- **Maximum open positions:** 100 markets

---

#### Current Implementation: `risk_parameters.py`

```python
# Position limits
MAX_POSITION_CONTRACTS: Final[int] = 10000
MAX_ORDER_CONTRACTS: Final[int] = 10000
MAX_OPEN_POSITIONS: Final[int] = 100
```

**Status:** ✅ Matches documented limits

---

### 5. Fee Validation

#### Current Implementation: `policy_sanity_harness.py`

```python
# Regression table for fee validation (from canonical spec)
FEE_REGRESSION_TABLE = {
    # (price_dollars, contracts) -> (expected_taker_fee, expected_maker_fee)
    (0.01, 1): (0, 0),  # Minimum price
    (0.50, 1): (2, 1),  # Maximum fee point
    (0.99, 1): (0, 0),  # Maximum price
    # ... more entries
}

def _validate_fee(
    self,
    price_cents: int,
    contracts: int,
    actual_role: Literal["taker", "maker"],
    fee_cents: Optional[int],
) -> Tuple[bool, Optional[int]]:
    """Validate fee against regression table."""
    if fee_cents is None:
        return False, None
    
    price_dollars = price_cents / 100.0
    expected_taker, expected_maker = FEE_REGRESSION_TABLE.get(
        (price_dollars, contracts), (None, None)
    )
    
    expected_fee = expected_maker if actual_role == "maker" else expected_taker
    deviation = fee_cents - expected_fee
    
    # Allow 1 cent tolerance for rounding
    return abs(deviation) <= 1, deviation
```

**Status:** ✅ Validates fees against regression table

**Features:**
- ✅ Regression table for known test cases
- ✅ 1 cent tolerance for rounding
- ✅ Logs deviations

**Issues:**
- ⚠️ **Limited coverage:** Only validates specific price/contract combinations
- ⚠️ **No continuous validation:** Doesn't validate all possible inputs

---

### 6. Data Flow: Fee Calculation

```
Position Sizer
    ↓
    kalshi_fee_per_contract_cents(price_cents, contracts)
    ↓
    calculate_kalshi_fee_per_contract_cents(contracts, price_cents)
    ↓
    kalshi_fee_cents_parabolic(price_dollars, contracts, role)
    ↓
    Decimal arithmetic
    ↓
    fee_cents = ceil(rate * C * P * (1 - P) * 100)
    ↓
    Return fee in cents
    ↓
    Risk calculation (includes fee in risk_per_contract)
```

**Status:** ✅ Clear data flow

**Issues:**
- ⚠️ **Multiple layers:** Position sizer → unified fees → parabolic fees
- ⚠️ **Unit conversion:** Cents → dollars → cents

---

## Required Fixes

### Fix 1: Remove Legacy Tiered Fee System

**File:** `risk_parameters.py`

**Remove:**
```python
# Fee tier boundaries (contract counts)
FEE_TIER_SMALL_MIN: Final[int] = 0
FEE_TIER_SMALL_MAX: Final[int] = 100
FEE_TIER_MEDIUM_MIN: Final[int] = 100
FEE_TIER_MEDIUM_MAX: Final[int] = 1000
FEE_TIER_LARGE_MIN: Final[int] = 1000
FEE_TIER_LARGE_MAX: Final[int] = 999999999

# Fee tier rates
FEE_RATE_SMALL: Final[float] = 0.07
FEE_RATE_MEDIUM: Final[float] = 0.05
FEE_RATE_LARGE: Final[float] = 0.03
```

**Implementation:**
1. Remove tiered fee constants
2. Remove tiered fee calculation functions
3. Update all references to use parabolic fees
4. Add deprecation notice if any external usage

---

### Fix 2: Centralize Fee Calculation

**File:** `position_sizer.py`

**Current:** Multiple fee calculation functions
**Target:** Single canonical function

**Proposed:**
```python
# Use only parabolic fees
from merid.event_venues.kalshi.parabolic_fees import (
    kalshi_fee_cents_parabolic,
    estimate_fee_for_sizing,
)

# Remove legacy wrappers
# kalshi_fee_cents() -> use kalshi_fee_cents_parabolic
# kalshi_fee_per_contract_cents() -> use estimate_fee_for_sizing
```

**Implementation:**
1. Remove legacy wrapper functions
2. Use parabolic fees directly
3. Update all callers
4. Document unit conversion (cents ↔ dollars)

---

### Fix 3: Expand Fee Validation

**File:** `policy_sanity_harness.py`

**Add:**
```python
def _validate_fee_continuous(
    self,
    price_cents: int,
    contracts: int,
    actual_role: Literal["taker", "maker"],
    fee_cents: Optional[int],
) -> Tuple[bool, Optional[int]]:
    """Validate fee by recalculating with parabolic formula.
    
    Instead of using regression table, recalculate fee and compare.
    This validates all possible inputs, not just test cases.
    """
    if fee_cents is None:
        return False, None
    
    from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_parabolic
    
    price_dollars = price_cents / 100.0
    expected_fee = kalshi_fee_cents_parabolic(
        price_dollars, contracts, role=actual_role
    )
    
    deviation = fee_cents - expected_fee
    return deviation == 0, deviation
```

**Implementation:**
1. Add continuous validation function
2. Recalculate fee using parabolic formula
3. Compare with actual fee
4. Use instead of regression table

---

### Fix 4: Add Fee Schedule Configuration

**File:** `config/kalshi_fee_schedule.py`

**Add:**
```python
@dataclass(frozen=True)
class KalshiFeeSchedule:
    """Kalshi fee schedule configuration.
    
    Allows customization of fee rates for testing or special accounts.
    """
    taker_rate: float = 0.07
    maker_rate: float = 0.0175
    min_price_dollars: float = 0.01
    max_price_dollars: float = 0.99
    
    @classmethod
    def default(cls) -> "KalshiFeeSchedule":
        """Return default Kalshi fee schedule."""
        return cls()

def get_active_fee_schedule() -> KalshiFeeSchedule:
    """Get the active fee schedule.
    
    Currently returns default schedule.
    Can be extended to read from config or environment.
    """
    return KalshiFeeSchedule.default()
```

**Implementation:**
1. Add fee schedule dataclass
2. Add default schedule
3. Add getter function
4. Use in parabolic fee calculations

---

### Fix 5: Document Fee Calculation Invariants

**File:** `parabolic_fees.py`

**Add:**
```python
"""
Kalshi Fee Calculation Invariants:
----------------------------------
1. Formula: fee_cents = ceil(rate * C * P * (1 - P) * 100)
   - rate: 0.07 for taker, 0.0175 for maker
   - C: number of contracts (integer >= 0)
   - P: price in dollars (0.01 <= P <= 0.99)
   - 100: converts dollars to cents

2. Rounding: Always use ceil, never floor or round
   - Kalshi rounds up to favor the exchange

3. Precision: Use Decimal arithmetic
   - Float boundary errors can break ceil invariants
   - Example: 175.0 -> 175.0000000003 -> ceil -> 176 (incorrect)

4. Maximum fee: At P = 0.5
   - Taker: 1.75¢ per contract
   - Maker: 0.4375¢ per contract

5. Edge cases:
   - P < 0.01 or P > 0.99: clamp to valid range
   - C <= 0: return 0
   - Invalid inputs: return 0 (defensive)
"""
```

**Implementation:**
1. Add module-level documentation
2. Document invariants
3. Document edge cases
4. Document precision requirements

---

## Audit Checklist

- [ ] Document fee formula (✅ documented)
- [ ] Document fee constants (✅ documented)
- [ ] Document tiered vs parabolic (✅ documented)
- [ ] Document position limits (✅ documented)
- [ ] Document fee validation (✅ documented)
- [ ] Identify dual fee systems (⚠️ tiered + parabolic)
- [ ] Identify multiple layers (position sizer → unified → parabolic)
- [ ] Identify unit conversion (cents ↔ dollars)
- [ ] Identify limited validation (regression table only)
- [ ] Plan migration path (5 fixes)
- [ ] Remove legacy tiered system
- [ ] Centralize fee calculation
- [ ] Expand fee validation
- [ ] Add fee schedule configuration
- [ ] Document fee calculation invariants

---

## Next Steps

1. **Immediate:** Remove legacy tiered fee system
2. **Immediate:** Centralize fee calculation to parabolic only
3. **Short-term:** Expand fee validation to continuous
4. **Short-term:** Add fee schedule configuration
5. **Medium-term:** Document fee calculation invariants
6. **Medium-term:** Add automated fee monitoring
7. **Long-term:** Add fee schedule testing

**Priority:** MEDIUM - Fee calculation is correct but has legacy code

**Risk:** Dual fee systems create confusion. Legacy tiered system is deprecated but still present.

**Note:** Parabolic fee formula matches Kalshi documentation exactly. The main issue is the presence of legacy tiered fee code that should be removed.
