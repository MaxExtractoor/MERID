# Canonical Price Range Constants

**Document Version**: 2026-07-16  
**Purpose**: Define the single source of truth for price range constants in the 15m Kalshi crypto trading system.

## Overview

The 15m Kalshi crypto trading system uses a canonical price range of 10-75c for order execution. All price range constants must be defined in a single location: `merid/event_venues/kalshi/risk_parameters.py`.

## Single Source of Truth

**File**: `merid/event_venues/kalshi/risk_parameters.py`

**Canonical Constants**:
```python
CANONICAL_MIN_PRICE_CENTS: Final[int] = 10  # Lower bound of canonical range
CANONICAL_MAX_PRICE_CENTS: Final[int] = 75  # Upper bound of canonical range
```

**Legacy Aliases** (for backwards compatibility):
```python
DEEP_OTM_CHEAP_CENTS: Final[int] = CANONICAL_MIN_PRICE_CENTS
DEEP_OTM_EXPENSIVE_CENTS: Final[int] = CANONICAL_MAX_PRICE_CENTS
MAX_OPEN_PRICE_CENTS: Final[int] = CANONICAL_MAX_PRICE_CENTS
```

## Usage Guidelines

### Correct Usage

```python
from merid.event_venues.kalshi.risk_parameters import (
    CANONICAL_MIN_PRICE_CENTS,
    CANONICAL_MAX_PRICE_CENTS,
)

# Clamp price to canonical range
price_cents = max(CANONICAL_MIN_PRICE_CENTS, min(CANONICAL_MAX_PRICE_CENTS, raw_price_cents))
```

### Incorrect Usage

```python
# DO NOT define price range constants locally
MIN_PRICE = 10
MAX_PRICE = 75

# DO NOT use magic numbers
price_cents = max(10, min(75, raw_price_cents))
```

## Historical Context

- **2026-07-10**: Initial 10-50c range established
- **2026-07-12**: Expanded to 10-75c for current market conditions
- **2026-07-16**: Consolidated to single source of truth in `risk_parameters.py`

## Rationale for 10-75c Range

1. **Market Conditions**: YES prices consistently 60-97c in current market conditions
2. **Dynamic Take-Profit Zones**: Matches dynamic_take_profit zones (25-70c)
3. **Fixed $1 Exposure Model**: Cheaper entries enable easier loss recovery
4. **Optimal Sizing**: Sweet spot for optimal sizing is 10c-75c

## Crisis Regime (Not Canonical Range)

The system has a crisis regime that expands to 5-95c. This is a separate multiplier in `merid/event_venues/kalshi/regime_detector.py`:

```python
price_range_multiplier: 1.9  # 10-75c → 5-95c (expanded range during crisis)
```

This should NOT be changed when updating the canonical range.

## Profile YAML vs Code Defaults

- **Profile YAML** (`config/profiles/kalshi_crypto_15m_v2.yaml`): Source of truth for production
- **Code Defaults** (`merid/risk/profiles/crypto_15m_profile.py`): Should match YAML
- **Risk Parameters** (`merid/event_venues/kalshi/risk_parameters.py`): Canonical constants for all code

## Files Using Canonical Price Range

The following files must import from `risk_parameters.py`:

### Core Trading Logic
- `merid/prediction/strategy.py`
- `merid/prediction/agent_grid_15m.py`
- `merid/prediction/kalshi_tools.py`
- `merid/loop_15m.py`

### Risk & Profile Configuration
- `merid/risk/profiles/crypto_15m_profile.py`
- `merid/event_venues/kalshi/market_filter.py`
- `merid/risk/profiles/global_allocator.py`

### Execution Pipeline
- `merid/event_venues/kalshi/order_router.py`
- `merid/event_venues/kalshi/dynamic_risk.py`
- `merid_core/kalshi/execution_pipeline.py`
- `merid_core/schemas/intent.py`

### Configuration Files
- `config/profiles/kalshi_crypto_15m_v2.yaml`

## Verification

To verify price range consistency:

```python
from merid.event_venues.kalshi.risk_parameters import (
    CANONICAL_MIN_PRICE_CENTS,
    CANONICAL_MAX_PRICE_CENTS,
)

assert CANONICAL_MIN_PRICE_CENTS == 10
assert CANONICAL_MAX_PRICE_CENTS == 75
```

## Future Updates

When updating the price range in the future:

1. Update `CANONICAL_MIN_PRICE_CENTS` and `CANONICAL_MAX_PRICE_CENTS` in `risk_parameters.py`
2. Update profile YAML (`config/profiles/kalshi_crypto_15m_v2.yaml`)
3. Update code defaults in `crypto_15m_profile.py` to match YAML
4. Run all price range tests
5. Update this documentation

## Grep Patterns for Future Updates

When updating the price range, use these grep patterns to find all references:

- `10.*50` (old 10-50c range)
- `10.*75` (current 10-75c range)
- `10c.*50c` (old format)
- `10c.*75c` (current format)
- `min_price_cents.*=.*10`
- `max_price_cents.*=.*[0-9]+`

## References

- `merid/event_venues/kalshi/risk_parameters.py` - Single source of truth
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Production profile
- `docs/CANONICAL_RISK_CHECK_ORDER.md` - Risk check order documentation
