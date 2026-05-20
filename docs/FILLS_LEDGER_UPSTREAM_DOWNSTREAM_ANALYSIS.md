# Fills Ledger - Upstream/Downstream Analysis & High-Leverage Tasks

## Executive Summary
Analysis of `merid/event_venues/kalshi/fills_ledger.py` dependencies, new surface area review, and hardcoded data audit.

---

## Upstream Dependencies (What fills_ledger.py depends on)

### 1. **utils.logger** (`from utils.logger import get_logger`)
- **Status**: Core infrastructure, production-ready
- **Risk**: Low

### 2. **Standard Library** (asyncio, sqlite3, dataclasses, etc.)
- **Status**: Python stdlib, no risk

---

## Downstream Dependencies (What depends on fills_ledger.py)

### Critical Files Using fills_ledger:

| File | Usage Pattern | Integration Gap |
|------|--------------|-----------------|
| `fills_poller.py` | HTTP/WebSocket fill ingestion | ✅ Integrated |
| `position_cache.py` | `on_fill()` callback | ⚠️ Needs hedge detection wiring |
| `hedging/engine.py` | Exposure calculation | ⚠️ Uses exposure.py, not direct |
| `hedging/exposure.py` | `build_exposure_snapshot()` | ✅ Uses KalshiFillsLedger |

---

## New Surface Area - Production Readiness Review

### ✅ Production Ready

| Component | Status | Notes |
|-----------|--------|-------|
| `fills_ledger.py` hedge tagging | ✅ | Auto-detection of HEDGE_ prefix |
| `fills_ledger.py` DB indexes | ✅ | Partial indexes for fill_source, hedge_reason |
| `exposure.py` hedge fields | ✅ | Separate tracking for alpha/hedge exposure |
| `trade_notifier.py` hedge alerts | ✅ | Differentiated formatting with emoji |
| `fills_ledger.py` query methods | ✅ | `get_hedge_fills()`, `get_alpha_fills()` |

### ⚠️ Issues Found - Needs Fixes

| Issue | Location | Severity | Fix Required |
|-------|----------|----------|--------------|
| Hardcoded CRYPTO_BASKET_ASSETS | `exposure.py:133` | **HIGH** | Load from config |
| Hardcoded basket_assets in dashboard_queries | `dashboard_queries.py:145, 264` | **HIGH** | Use shared config |
| Hardcoded asset map in _extract_asset_from_ticker | `dashboard_queries.py:359` | **MEDIUM** | Use market catalog |
| Missing ledger integration in position_cache | `position_cache.py` | **CRITICAL** | Wire fills_ledger to on_fill |
| PnL tracker not integrated with fill lifecycle | `pnl_tracker.py` | **HIGH** | Wire to ledger callbacks |
| Hedge persistence not auto-triggered | `fills_persistence.py` | **MEDIUM** | Add periodic save |

---

## Hardcoded Fallback Data Audit

### CRITICAL: Hardcoded Asset Lists (Must Fix for Production)

```python
# exposure.py - Line 133
CRYPTO_BASKET_ASSETS = ["BTC", "ETH", "SOL"]  # ❌ HARDCODED

# dashboard_queries.py - Line 145, 264
basket_assets = ["BTC", "ETH", "SOL"]  # ❌ HARDCODED

# dashboard_queries.py - Lines 359-365
asset_map = {  # ❌ HARDCODED - should query market catalog
    "BTC": "BTC",
    "ETH": "ETH", 
    "SOL": "SOL",
    "XRP": "XRP",
    "DOGE": "DOGE",
}
```

**Production Impact**: If Kalshi adds new crypto markets (e.g., LTC, ADA), the hedge system will ignore them.

### HIGH: Hardcoded Thresholds

```python
# exposure.py - Line 277
def get_basket_hedge_efficiency(...):
    "is_neutral": abs(net_exposure) < 1000  # ❌ 1000¢ hardcoded

# dashboard_queries.py - Line 317
"is_neutral": abs(net_exposure) < 1000  # ❌ Same hardcoded value

# pnl_tracker.py - Line 263
coverage = min(hedge_exposure / alpha_exposure, 2.0)  # ❌ 2.0 cap hardcoded

# dashboard_queries.py - Line 240
coverage = min(hedge / alpha, 2.0)  # ❌ 2.0 cap hardcoded
```

### MEDIUM: Time Intervals

```python
# fills_persistence.py - Line 18
PERSISTENCE_DIR = Path.home() / ".merid" / "hedge_data"  # ⚠️ Hardcoded path

# fills_persistence.py - Line 124
def cleanup_old_backups(max_age_days: int = 7):  # ⚠️ Default 7 days

# pnl_tracker.py - Line 255
lookback_days: int = 7  # ⚠️ Default 7 days

# dashboard_queries.py - Line 64
hours_lookback: int = 24  # ⚠️ Default 24 hours
```

---

## 10 High-Leverage Tasks

### P0 - CRITICAL (Must Fix Before Production)

#### Task 1: Fix Hardcoded CRYPTO_BASKET_ASSETS
**Location**: `exposure.py:133`, `dashboard_queries.py:145,264`
**Issue**: Asset lists hardcoded; won't adapt to new markets
**Fix**: Load from `kalshi_constants.ACTIVE_CRYPTO_ASSETS` or config
**Estimated Impact**: Prevents missed hedges when new markets launch

#### Task 2: Wire fills_ledger to position_cache.on_fill()
**Location**: `position_cache.py:73-130`
**Issue**: position_cache creates positions but doesn't query fills_ledger for fill_source
**Fix**: Add fills_ledger dependency and query fill metadata
**Estimated Impact**: Enables proper hedge fill recognition in position cache

#### Task 3: Fix _extract_asset_from_ticker() Hardcoded Map
**Location**: `dashboard_queries.py:338-367`
**Issue**: Asset mapping hardcoded; won't handle new tickers
**Fix**: Use `kalshi_market_utils.extract_asset()` or parse dynamically
**Estimated Impact**: Supports new market formats automatically

#### Task 4: Wire PnL Tracker to Ledger Fill Callbacks
**Location**: `pnl_tracker.py`, `fills_ledger.py`
**Issue**: PnL tracker exists but isn't called when fills occur
**Fix**: Add `record_hedge_fill()` call in fills_ledger's hedge fill tagging
**Estimated Impact**: Enables real-time hedge PnL tracking

### P1 - HIGH (Should Fix Soon)

#### Task 5: Fix Hardcoded Neutral Threshold (1000¢)
**Location**: `exposure.py:277`, `dashboard_queries.py:317`
**Issue**: $10 neutral threshold hardcoded
**Fix**: Config parameter `HEDGE_NEUTRAL_THRESHOLD_CENTS`
**Estimated Impact**: Allows tuning for different portfolio sizes

#### Task 6: Fix Hardcoded Coverage Cap (2.0x)
**Location**: `exposure.py:238`, `dashboard_queries.py:240`, `pnl_tracker.py:263`
**Issue**: 200% coverage cap hardcoded
**Fix**: Config parameter `MAX_HEDGE_COVERAGE_RATIO`
**Estimated Impact**: Prevents over-hedging scenarios

#### Task 7: Add Auto-Save Trigger to Fills Ledger
**Location**: `fills_persistence.py`, `fills_ledger.py`
**Issue**: Persistence exists but isn't triggered automatically
**Fix**: Add `HedgePersistenceManager` integration in `record_hedge_fill()`
**Estimated Impact**: Prevents data loss on crashes

#### Task 8: Fix Hardcoded Persistence Path
**Location**: `fills_persistence.py:18`
**Issue**: Path hardcoded to `~/.merid/hedge_data`
**Fix**: Use `os.environ.get('MERID_DATA_DIR', default_path)`
**Estimated Impact**: Supports containerized deployments

#### Task 9: Add Hedge Order Submission Integration
**Location**: `hedging/engine.py`, `fills_ledger.py`
**Issue**: Hedge orders submitted but fill tracking not wired back
**Fix**: Ensure client_order_id with HEDGE_ prefix flows through fills_ledger
**Estimated Impact**: Closes the loop: hedge order → fill → tracking

#### Task 10: Fix Missing Hedge Order Intent Tags
**Location**: `hedging/engine.py`, fills ingestion
**Issue**: Hedge intents may not have 'hedge' tag when created
**Fix**: Ensure all hedge intents get tagged with `{'hedge': True, 'hedge_reason': ...}`
**Estimated Impact**: Reliable hedge fill detection via intent tags

---

## Detailed Fix Requirements

### Fix 1: Config-Driven Asset Lists

```python
# TODO: Create merid/config/hedge_config.py
from dataclasses import dataclass
from typing import List

@dataclass
class HedgeBasketConfig:
    assets: List[str]
    primary_hedge_asset: str  # "BTC" for crypto basket
    coverage_threshold: float  # 1.0 = 100%
    neutral_threshold_cents: int  # Replace hardcoded 1000
    max_coverage_ratio: float  # Replace hardcoded 2.0

# Load from YAML or environment
CRYPTO_BASKET = HedgeBasketConfig(
    assets=os.environ.get('HEDGE_CRYPTO_ASSETS', 'BTC,ETH,SOL').split(','),
    primary_hedge_asset=os.environ.get('HEDGE_PRIMARY_ASSET', 'BTC'),
    coverage_threshold=float(os.environ.get('HEDGE_COVERAGE_THRESHOLD', '1.0')),
    neutral_threshold_cents=int(os.environ.get('HEDGE_NEUTRAL_THRESHOLD_CENTS', '1000')),
    max_coverage_ratio=float(os.environ.get('HEDGE_MAX_COVERAGE_RATIO', '2.0')),
)
```

### Fix 2: Wire Ledger to Position Cache

```python
# In position_cache.py
from merid.event_venues.kalshi.fills_ledger import get_fills_ledger

class PositionCache:
    def __init__(self):
        self._fills_ledger = get_fills_ledger()  # Add dependency
    
    async def on_fill(self, ...):
        # Query fill_source from ledger instead of detecting
        fill = self._fills_ledger.get_fill_by_id(fill_id)
        if fill:
            fill_source = fill.fill_source  # "alpha" or "hedge"
            # ... rest of logic
```

### Fix 3: Dynamic Asset Extraction

```python
# Replace hardcoded asset_map with:
def _extract_asset_from_ticker(ticker: str) -> str:
    """Extract asset from Kalshi ticker format."""
    if not ticker:
        return "UNKNOWN"
    
    # Remove KX prefix
    if ticker.startswith("KX"):
        ticker = ticker[2:]
    
    # Extract base asset (everything before first non-alpha)
    match = re.match(r'^([A-Za-z]+)', ticker)
    if match:
        return match.group(1).upper()
    
    return "UNKNOWN"
```

---

## Integration Test Requirements

Before production deploy, verify:

1. **Hedge Fill Detection**: Submit order with `client_order_id=HEDGE_test_123` → Verify `fill_source='hedge'` in ledger
2. **Position Cache Recognition**: Verify `CachedPosition.fill_source='hedge'` after hedge fill
3. **Exposure Separation**: Verify `alpha_net_delta_cents` != `hedged_exposure_cents`
4. **PnL Tracking**: Create hedge record → Exit hedge → Verify effectiveness ratio calculated
5. **Persistence**: Kill process → Restart → Verify hedge fills restored
6. **Cross-Asset Hedge**: SOL alpha + BTC hedge → Verify coverage ratio calculated
7. **Dashboard Query**: Verify `get_hedge_dashboard_metrics()` returns accurate data

---

## Deployment Checklist

- [ ] Fix all hardcoded CRYPTO_BASKET_ASSETS
- [ ] Fix all hardcoded threshold values (1000¢, 2.0x)
- [ ] Wire fills_ledger to position_cache
- [ ] Wire PnL tracker to fill callbacks
- [ ] Fix asset extraction to use dynamic parsing
- [ ] Add environment variable support for paths
- [ ] Verify hedge order → fill → tracking end-to-end
- [ ] Run integration tests
- [ ] Deploy to staging
- [ ] Monitor hedge fill detection accuracy
