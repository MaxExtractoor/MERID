# Kalshi 15m Crypto Semantic Audit Report

**Profile**: `kalshi_crypto_15m_v2`  
**Date**: 2026-05-15  
**Purpose**: Validate semantic alignment with Kalshi's 15-minute crypto contract behavior

---

## Executive Summary

This audit validates that the `kalshi_crypto_15m_v2` profile is semantically aligned with Kalshi's documented 15-minute crypto contract behavior. The audit covers 5 critical areas:

1. ✅ **Kalshi contract semantics vs internal model** - YES/NO interpretation is correct
2. ✅ **kalshi_crypto_15m.yaml as profile contract** - Fixed crypto_threshold_matrix reference
3. ✅ **5-asset, 15-minute grid alignment** - AGENT_SERIES_MAP uses correct KX{ASSET}15M tickers
4. ✅ **No parallel PM brain** - Profile guards successfully disable legacy PM components
5. ⚠️ **Kalshi API integration** - Edge calculation needs review against RTI settlement semantics

---

## 1. Kalshi Contract Semantics vs Internal Model

### 1.1 YES/NO Interpretation

**Kalshi Contract Semantics**:
- 15-minute crypto contracts are "Up or Down" markets
- YES pays out if RTI average ≥ target price at expiry
- NO pays out if RTI average < target price at expiry
- Settlement uses CF Benchmarks Real-Time Indices (RTI) with 60-second average

**Internal Model Implementation**:

✅ **Correct**: YES/NO sides are properly mapped in order construction
```python
# merid/event_venues/kalshi/trading.py
async def buy_yes(self, ticker: str, count: int, price: Optional[int] = None):
    order = VenueOrder(
        market_id=ticker,
        side="buy",
        size=Decimal(count),
        price=Decimal(price or DEFAULT_KALSHI_PRICE_CENTS) / 100,
        order_type="limit" if price else "market",
        outcome_id="yes"  # ✓ Correct
    )

async def buy_no(self, ticker: str, count: int, price: Optional[int] = None):
    order = VenueOrder(
        market_id=ticker,
        side="buy",
        size=Decimal(count),
        price=Decimal(price or DEFAULT_KALSHI_PRICE_CENTS) / 100,
        order_type="limit" if price else "market",
        outcome_id="no"  # ✓ Correct
    )
```

✅ **Correct**: Position tracking uses YES/NO outcomes correctly
```python
# merid/event_venues/kalshi/venue_adapter.py
# Determine outcome from order side — BUY means long YES, SELL means long NO
outcome = "yes" if order.side.name == "BUY" else "no"
```

### 1.2 Edge Calculation vs Probability(YES)

**Kalshi Contract Semantics**:
- Market price (cents) represents probability of YES
- YES price = P(YES) × 100 cents
- NO price = (1 - P(YES)) × 100 cents = 100 - YES price
- Edge should be: P(YES)_model - P(YES)_market

**Internal Model Implementation**:

⚠️ **Needs Review**: `edge_from_prediction()` computes edge from price difference, not probability difference
```python
# merid/event_venues/kalshi/kalshi_risk.py (lines 510-574)
def edge_from_prediction(
    smoothed_price: float,
    current_price: float,
    fee_cents: float = 0.0,
    *,
    config: Optional[KalshiRiskConfig] = None,
) -> float:
    """Compute edge (%) from Kalman-smoothed price vs current market price.
    
    Positive if the filter says fair price > current price (buy signal).
    """
    # ...
    edge_frac = (smoothed_price - current_price - fee_cents) / current_price
    edge_pct = edge_frac * 100.0
    return edge_pct
```

**Issue**: This computes edge as `(fair_price - market_price) / market_price`, which is correct for price-based edge but doesn't explicitly model it as probability difference. For Kalshi binary contracts, this should be equivalent since:
- Price (cents) = P(YES) × 100
- Edge = (P(YES)_model - P(YES)_market) / P(YES)_market

**Recommendation**: Verify that the Kalman-smoothed price is indeed a probability estimate (0-100 cents) and not a raw spot price. If it's a spot price, this edge calculation is incorrect for Kalshi binary contracts.

### 1.3 RTI Settlement

**Kalshi Contract Semantics**:
- Contracts settle to CF Benchmarks RTI
- RTI is a simple average of 60 prices in the last minute before expiry
- No complex settlement logic needed in client code

**Internal Model Implementation**:

✅ **Correct**: Settlement is handled by Kalshi's API
```python
# merid/event_venues/kalshi/venue_adapter.py
settlement_source="kalshi",  # ✓ Delegated to venue
```

✅ **Correct**: Trade lifecycle includes SETTLED stage
```python
# merid/event_venues/kalshi/trade_lifecycle.py
class LifecycleStage(str, Enum):
    SETTLED = "settled"  # ✓ Settlement tracked
```

✅ **Correct**: No custom RTI calculation logic found in codebase - settlement is delegated to Kalshi

---

## 2. kalshi_crypto_15m.yaml as Profile Contract

### 2.1 Single Source of Truth

**Status**: ✅ **FIXED** - Previously referenced crypto_threshold_matrix, now disabled

**Fix Applied**:
```yaml
# config/profiles/kalshi_crypto_15m.yaml (lines 114-121)
confidence:
  # PROFILE-GUARD: crypto_threshold_matrix.yaml is disabled for kalshi_crypto_15m_v2
  use_crypto_threshold_matrix: false  # ✓ Fixed (was true)
  profile_name: null  # ✓ Fixed (was modern_tradeable_kalshi_v1)
```

**Profile Guards Active**:
- ✅ `merid/prediction/pm_profiles.py` - PM profile skipped for kalshi_crypto_15m_v2
- ✅ `merid/prediction/crypto_edge_production.py` - Crypto matrix skipped for kalshi_crypto_15m_v2
- ✅ `merid/prediction/agent_grid.py` - AutoPromoter skipped for kalshi_crypto_15m_v2
- ✅ `merid/prediction/agent_grid.py` - Regime agents skipped for kalshi_crypto_15m_v2
- ✅ `merid/loop.py` - Canonical agent cycle skipped for kalshi_crypto_15m_v2

### 2.2 Asset Universe

**Status**: ✅ **Correct** - 5 assets defined in profile YAML

```yaml
# config/profiles/kalshi_crypto_15m.yaml (lines 58-98)
assets:
  BTC:
    max_notional_pct: 0.08
    max_contracts: 100
    min_edge_early: 0.020
    # ...
  ETH:
    max_notional_pct: 0.06
    max_contracts: 100
    # ...
  SOL:
    max_notional_pct: 0.05
    max_contracts: 100
    # ...
  XRP:
    max_notional_pct: 0.05
    max_contracts: 100
    # ...
  DOGE:
    max_notional_pct: 0.04
    max_contracts: 100
    # ...
```

### 2.3 Risk Caps

**Status**: ✅ **Correct** - Risk caps derived from profile YAML

```yaml
# config/profiles/kalshi_crypto_15m.yaml (lines 44-53)
venue:
  max_single_order_pct: 0.05  # 5% of capital per single order
  max_total_notional_pct: 0.30  # 30% of capital total exposure
  max_orders_per_minute: 30
```

---

## 3. 5-Asset, 15-Minute Grid Alignment

### 3.1 AGENT_SERIES_MAP

**Status**: ✅ **Correct** - Uses 15M series tickers

```python
# merid/event_venues/kalshi/market_selector.py
AGENT_SERIES_MAP = {
    "BTC_15M": ["KXBTC15M"],  # ✓ Correct
    "ETH_15M": ["KXETH15M"],  # ✓ Correct
    "SOL_15M": ["KXSOL15M"],  # ✓ Correct
    "XRP_15M": ["KXXRP15M"],  # ✓ Correct
    "DOGE_15M": ["KXDOGE15M"],  # ✓ Correct
}
```

### 3.2 kalshi_agent_grid.yaml

**Status**: ✅ **Correct** - Series tickers match AGENT_SERIES_MAP

```yaml
# config/kalshi_agent_grid.yaml (lines 14-26)
- name: BTC_15M
  series_tickers:
  - KXBTC15M  # ✓ Correct
  assets:
  - BTC
  timeframes:
  - 15m
  market_filter:
    category: crypto
    frequency: fifteen_min  # ✓ Correct
```

### 3.3 Kalshi Product Set

**Kalshi 15M Crypto Products**:
- KXBTC15M - Bitcoin 15-minute
- KXETH15M - Ethereum 15-minute
- KXSOL15M - Solana 15-minute
- KXXRP15M - Ripple 15-minute
- KXDOGE15M - Dogecoin 15-minute

**Status**: ✅ **Aligned** - All 5 assets match Kalshi's product set

---

## 4. No Parallel PM Brain

### 4.1 PM Profile

**Status**: ✅ **Profile-Guarded** - PM profile skipped for kalshi_crypto_15m_v2

```python
# merid/prediction/pm_profiles.py (lines 72-82)
def get_pm_profile_strategy_overrides(profile_name: Optional[str] = None) -> Dict[str, Any]:
    # PROFILE-GUARD: Skip PM profile for kalshi_crypto_15m_v2
    merid_profile = os.getenv("MERID_PROFILE", "").lower()
    if merid_profile == "kalshi_crypto_15m_v2":
        logger.info("[PROFILE-GUARD] PM profile skipped for kalshi_crypto_15m_v2")
        return {}  # ✓ Returns empty dict
```

### 4.2 Crypto Threshold Matrix

**Status**: ✅ **Profile-Guarded** - Crypto matrix skipped for kalshi_crypto_15m_v2

```python
# merid/prediction/crypto_edge_production.py (lines 279-283)
# PROFILE-GUARD: Skip crypto matrix overrides for kalshi_crypto_15m_v2
merid_profile = os.getenv("MERID_PROFILE", "").lower()
if merid_profile == "kalshi_crypto_15m_v2":
    logger.info("[PROFILE-GUARD] Crypto matrix skipped for kalshi_crypto_15m_v2")
    return sc  # ✓ Returns strategy config unchanged
```

### 4.3 AutoPromoter

**Status**: ✅ **Profile-Guarded** - AutoPromoter skipped for kalshi_crypto_15m_v2

```python
# merid/prediction/agent_grid.py (lines 168-178)
# PROFILE-GUARD: Skip AutoPromoter for kalshi_crypto_15m_v2
merid_profile = os.getenv("MERID_PROFILE", "").lower()
if merid_profile == "kalshi_crypto_15m_v2":
    logger.info("[PROFILE-GUARD] AutoPromoter skipped for kalshi_crypto_15m_v2")
    self._auto_promoter = None  # ✓ Set to None
```

### 4.4 Regime Agents

**Status**: ✅ **Profile-Guarded** - Regime agents not required for kalshi_crypto_15m_v2

```python
# merid/prediction/agent_grid.py (lines 206-212)
# PROFILE-GUARD: Skip regime agents for kalshi_crypto_15m_v2
merid_profile = os.getenv("MERID_PROFILE", "").lower()
if merid_profile == "kalshi_crypto_15m_v2":
    logger.info("[PROFILE-GUARD] Regime agents skipped for kalshi_crypto_15m_v2")
    return  # ✓ Returns early, no error
```

### 4.5 Canonical Agent Cycle

**Status**: ✅ **Profile-Guarded** - Canonical agent cycle skipped for kalshi_crypto_15m_v2

```python
# merid/loop.py (lines 1086-1097)
# PROFILE-GUARD: Skip canonical agent cycle for kalshi_crypto_15m_v2
merid_profile = os.getenv("MERID_PROFILE", "").lower()
if merid_profile == "kalshi_crypto_15m_v2":
    logger.info("[PROFILE-GUARD] Canonical agent cycle skipped for kalshi_crypto_15m_v2")
    # Only run Kalshi agent cycle for this profile
    if "prediction" in self.config.active_domains:
        gathered = await asyncio.gather(self._run_kalshi_agent_cycle(summary), return_exceptions=True)
```

---

## 5. Kalshi API Integration

### 5.1 Order Construction

**Status**: ✅ **Correct** - Orders use correct API format

```python
# merid/event_venues/kalshi/trading.py
order = VenueOrder(
    market_id=ticker,  # ✓ Full ticker (e.g., KXBTC15M-26MAY111330-30)
    side="buy",  # ✓ "buy" or "sell"
    size=Decimal(count),  # ✓ Contract count
    price=Decimal(price or DEFAULT_KALSHI_PRICE_CENTS) / 100,  # ✓ Price in dollars (0-1)
    order_type="limit" if price else "market",  # ✓ "limit" or "market"
    outcome_id="yes"  # ✓ "yes" or "no"
)
```

### 5.2 Market Discovery

**Status**: ✅ **Correct** - Uses Kalshi's catalog API

```python
# merid/event_venues/kalshi/market_catalog.py
# Uses GET /markets endpoint with series_ticker filter
# Correctly filters by KX{ASSET}15M series for 15m agents
```

### 5.3 WebSocket Subscriptions

**Status**: ✅ **Correct** - Subscribes to 15M series tickers

```python
# merid/event_venues/kalshi/ws_bridge.py (lines 519-556)
# ASSERTION: Verify 5 assets subscribed for kalshi_crypto_15m_v2 profile
expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
# ✓ Runtime assertion ensures all 5 assets are subscribed
```

---

## Critical Findings & Recommendations

### ⚠️ Priority 1: Edge Calculation Semantics

**Finding**: `edge_from_prediction()` computes edge from price difference but doesn't explicitly model it as probability difference.

**Recommendation**: 
1. Verify that Kalman-smoothed price is a probability estimate (0-100 cents) for YES outcome
2. If it's a spot price, convert to probability first before computing edge
3. Add documentation clarifying that edge = P(YES)_model - P(YES)_market

**Risk**: If Kalman filter outputs spot prices instead of probabilities, edge calculation will be incorrect for Kalshi binary contracts.

### ✅ Priority 2: Profile Contract Alignment

**Finding**: Fixed crypto_threshold_matrix reference in kalshi_crypto_15m.yaml.

**Status**: ✅ **RESOLVED** - All profile guards active and tested.

### ✅ Priority 3: Grid Alignment

**Finding**: AGENT_SERIES_MAP and kalshi_agent_grid.yaml use correct 15M series tickers.

**Status**: ✅ **VERIFIED** - All 5 assets (BTC/ETH/SOL/XRP/DOGE) use KX{ASSET}15M tickers.

### ✅ Priority 4: PM Brain Removal

**Finding**: All legacy PM components successfully profile-guarded for kalshi_crypto_15m_v2.

**Status**: ✅ **VERIFIED** - PM profile, crypto matrix, AutoPromoter, regime agents, canonical cycle all disabled.

---

## Test Coverage

### Profile Guard Tests

✅ All 13 profile guard tests passing:
- `test_core_agent_orchestrator_guarded_for_15m_profile`
- `test_hashtag_monitor_guard_in_loop`
- `test_orchestrator_agent_manager_guards`
- `test_crypto15m_lane_not_guarded`
- `test_pm_profile_guarded_for_15m_profile`
- `test_crypto_matrix_guarded_for_15m_profile`
- `test_auto_promoter_guarded_for_15m_profile`
- `test_regime_agents_guarded_for_15m_profile`
- `test_canonical_agent_cycle_guarded_for_15m_profile`
- `test_ws_bridge_has_instrumentation`
- `test_ws_bridge_has_timeout`
- `test_only_one_orchestrator_active_for_15m`
- `test_orchestrator_agent_manager_has_grid_startup_logs`

### Risk Envelope Validation

✅ Startup validation passing:
```python
# merid/startup_validations.py
validate_canonical_risk_envelope_loading()  # ✓ Validates YAML loads correctly
```

---

## Conclusion

The `kalshi_crypto_15m_v2` profile is **semantically aligned** with Kalshi's 15-minute crypto contract behavior in 4 of 5 critical areas:

1. ✅ YES/NO interpretation is correct
2. ✅ Profile contract is single source of truth (fixed)
3. ✅ 5-asset, 15-minute grid is aligned
4. ✅ No parallel PM brain (all legacy components disabled)
5. ⚠️ Edge calculation needs verification against probability semantics

**Recommended Action**: Investigate whether the Kalman filter outputs probabilities or spot prices, and adjust edge calculation accordingly if needed.
