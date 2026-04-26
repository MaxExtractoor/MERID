# Kalshi Bankroll v2 Migration Guide

## The Problem (Why We're Doing This)

The legacy bankroll code had a fatal design flaw: **errors were silently converted to 0**, causing:
- UI showing one balance while backend thought bankroll was 0
- Agents refusing to trade due to "insufficient bankroll"
- Silent assertion failures in Kalshi client
- Confusing "locked bankroll" vs "effective bankroll" concepts

## The Solution (v2 Architecture)

### Core Principles

1. **NO assertions on external data** - Kalshi client returns typed results
2. **NO error -> 0 mapping** - Errors are explicit states (FRESH/STALE/ERROR)
3. **Single source of truth** - BankrollServiceV2 is the ONLY store
4. **Explicit risk behavior** - Policy defines what happens in each state
5. **Clean domain model** - RawVenueBalance -> InternalBankroll, no "locked" nonsense

### New Module Structure

```
kalshi/
├── types.py                    # Domain types (BalanceState, InternalBankroll, etc.)
├── client_v2.py               # No-assertion client with typed results
├── bankroll_service_v2.py     # Unified store (the ONE source of truth)
├── risk_policy.py             # Explicit risk behavior per state
├── bankroll_adapter.py        # Legacy compatibility bridge
└── legacy/
    └── bankroll_service.py    # OLD - moved here, do not use
```

## Quick Start (New Code)

```python
from merid.event_venues.kalshi import (
    BalanceState, InternalBankroll, BankrollServiceV2,
    get_bankroll_service, get_default_policy
)

# Get the global service (starts background refresh)
service = await get_bankroll_service(max_riskable_frac=Decimal("0.02"))

# Check current state
summary = await service.get_summary()
print(f"Equity: {summary.display_equity} ({summary.state.value})")

# Use for position sizing
if summary.is_tradable:
    max_position = summary.max_position_usd
    # ... trade with max_position
else:
    logger.error(f"Trading blocked: {summary.last_error_reason}")

# Check explicit risk policy
policy = get_default_policy()
allowance = policy.evaluate(summary)
print(f"Can trade: {allowance.allow_new_positions}")
print(f"Max position: ${allowance.max_position_usd}")
print(f"Reason: {allowance.reason}")
```

## Migration Path (Existing Code)

### Option 1: Use Adapter (Minimal Changes)

```python
from merid.event_venues.kalshi import get_legacy_bankroll_service

# This returns an adapter that looks like the old service
adapter = await get_legacy_bankroll_service()

# Legacy API still works
result = await adapter.get_balance()
if result.success:
    print(f"Balance: ${result.total_value_usd}")
else:
    print(f"Error: {result.error}")

# But you can also access v2 features
summary = await adapter.v2_service.get_summary()
```

### Option 2: Full Migration (Recommended)

Replace this legacy pattern:
```python
# OLD - BAD
from merid.event_venues.kalshi import get_bankroll_service
service = get_bankroll_service()
result = await service.fetch_live_bankroll_async()
if not result.success:
    # This silently sets bankroll to 0 - BAD!
    bankroll = Decimal("0")
else:
    bankroll = Decimal(result.total_value_usd)
```

With this v2 pattern:
```python
# NEW - GOOD
from merid.event_venues.kalshi import get_bankroll_service, BalanceState
from merid.event_venues.kalshi.risk_policy import check_trade_allowed

service = await get_bankroll_service()
summary = await service.get_summary()

if summary.state == BalanceState.FRESH:
    bankroll = summary.equity_usd  # Known good
elif summary.state == BalanceState.STALE:
    bankroll = summary.equity_usd  # Degraded but usable
    logger.warning("Using stale bankroll - reduced position size")
else:
    # ERROR or UNKNOWN - no lying with 0
    raise TradingBlocked(f"Bankroll unavailable: {summary.last_error_reason}")

# Or use the policy helper
allowed, reason = await check_trade_allowed(summary, proposed_notional=Decimal("100"))
if not allowed:
    raise TradingBlocked(reason)
```

## State Machine

```
UNKNOWN (initial state, no data yet)
    ↓ fetch succeeds
FRESH (equity known, normal trading)
    ↓ fetch fails temporarily
STALE (using cached equity, reduced risk)
    ↓ fetch succeeds
FRESH (back to normal)
    ↓ permanent error (auth, account disabled)
ERROR (trading blocked, alert sent)
```

## Result Types (No More Booleans)

### Old (Bad)
```python
@dataclass
class BankrollResult:
    success: bool  # What does False mean?
    balance_cents: int  # 0 on error? or actual 0?
    error: Optional[str]  # Set when success=False
```

### New (Good)
```python
# Union type - three explicit cases
BalanceResult = BalanceSuccess | BalanceTemporaryError | BalancePermanentError

@dataclass(frozen=True)
class BalanceSuccess:
    bankroll: InternalBankroll  # Canonical representation
    raw: RawVenueBalance        # Original Kalshi response
    latency_ms: float

@dataclass(frozen=True)
class BalanceTemporaryError:
    reason: str
    last_known: Optional[InternalBankroll]  # Use this if available
    retry_after_seconds: int

@dataclass(frozen=True)
class BalancePermanentError:
    reason: str
    alert_immediately: bool
```

## Configuration

Environment variables for v2:
- `KALSHI_API_URL` - API endpoint
- `KALSHI_API_KEY_ID` - Auth key ID
- `KALSHI_PRIVATE_KEY_PATH` - Path to signing key
- `MERID_KALSHI_RISK_FRACTION` - Default 0.02 (2% per position)
- `MERID_KALSHI_REFRESH_INTERVAL` - Default 30 seconds
- `MERID_KALSHI_STALE_THRESHOLD` - Default 120 seconds

## Testing

```python
import pytest
from merid.event_venues.kalshi.types import (
    BalanceState, InternalBankroll, BalanceSuccess
)

@pytest.mark.asyncio
async def test_bankroll_service_v2():
    service = await get_bankroll_service()
    summary = await service.get_summary()
    
    # Initial state should be UNKNOWN
    assert summary.state == BalanceState.UNKNOWN
    assert summary.equity_usd is None
    
    # Force a refresh
    result = await service.force_refresh()
    
    # After refresh, should be one of the valid states
    summary = await service.get_summary()
    assert summary.state in (
        BalanceState.FRESH,
        BalanceState.STALE,
        BalanceState.ERROR,
    )
```

## Rollout Plan

1. **Phase 1**: Deploy v2 modules alongside legacy (done)
2. **Phase 2**: Update one agent to use v2 directly (feature flag)
3. **Phase 3**: Migrate all agents using adapter
4. **Phase 4**: Remove legacy code entirely

## Checklist for Migration

- [ ] Replace `get_bankroll_service()` with `await get_bankroll_service()`
- [ ] Replace `.fetch_live_bankroll_async()` with `.get_summary()`
- [ ] Replace `result.success` checks with `summary.state` checks
- [ ] Replace `Decimal("0")` on error with proper exception handling
- [ ] Remove any "locked bankroll" logic
- [ ] Test with both FRESH and STALE states
- [ ] Test ERROR state handling

## FAQ

**Q: Why not just fix the legacy code?**
A: The "error -> 0" pattern is deeply embedded. Trying to patch it incrementally has failed multiple times. A clean rewrite with explicit types is the only way to be sure.

**Q: Will this break existing agents?**
A: Not if you use the adapter. The adapter provides the legacy API surface while internally using v2.

**Q: What happens if Kalshi API is down?**
A: 
- Short outage (< 2 min): Service transitions to STALE, uses cached equity with reduced risk
- Long outage (> 2 min): Service transitions to ERROR, blocks new trading
- UI shows "--" instead of lying with 0

**Q: Can I mix v1 and v2 code?**
A: Yes, but be careful. The v2 service is a singleton, so state changes in v2 will be visible to v1 code. The adapter bridges the gap.
