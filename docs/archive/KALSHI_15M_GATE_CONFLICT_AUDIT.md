# Kalshi 15m Gate Conflict Audit

## Executive Summary

**Status**: Minor conflicts found between indicator stack and unified edge microstructure checks. No critical conflicts in spot source, regime systems, or deprecated code.

**Key Finding**: Indicator stack's spread/depth checks (8c spread, 3 depth) are redundant and overly restrictive compared to unified edge's richer microstructure checks (60c spread, depth scaling, profile-driven thresholds).

**Recommendation**: Remove indicator stack's microstructure checks, keep it purely TA-based (trend, momentum, volatility, chop).

---

## 1. Indicator Stack vs Unified Edge - Duplicate Gates

### Indicator Stack (`merid/signals/crypto_15m_indicators.py`)

**`trade_allowed` composite gate:**
```python
snap.trade_allowed = (
    snap.vol_gate_ok
    and snap.atr_move_ok
    and snap.liquidity_ok
    and snap.chop_gate_ok
    and snap.bars_available >= self.cfg.min_bars_required
)
```

**Component gates:**
- `liquidity_ok`: `spread_cents > max_spread_cents (8c)` OR `depth_at_price < min_depth_at_price (3)`
- `vol_gate_ok`: `realized_vol_annualized` in band (0.15-1.20)
- `atr_move_ok`: `ATR/price > atr_min_move_pct` (asset-specific 0.02-0.05%)
- `chop_gate_ok`: consecutive closes, MACD persistence, MACD histogram magnitude

### Unified Edge (`merid/prediction/unified_edge.py`)

**`check_edge()` gates:**
- `spread_cents > max_spread_cents (60c)` - MUCH looser than indicator stack
- `spread_pct > max_spread_pct` (dynamic by volatility regime)
- `contract_price_cents < min_price_cents (20c)` - price floor (longshot trap)
- Depth scaling with order size (microstructure trap prevention)
- Edge thresholds (profitability filter)
- Regime cooldown checks
- Edge/lag ratio checks

### Conflict Analysis

| Gate | Indicator Stack | Unified Edge | Conflict |
|------|----------------|-------------|----------|
| **Spread** | 8c (very strict) | 60c (loose) | **YES** - Indicator stack rejects almost everything unified edge would allow |
| **Depth** | 3 (static) | Profile-driven, scaling with order size | **YES** - Indicator stack's check is redundant |
| **Volatility** | `realized_vol_annualized` in band (0.15-1.20) | `classify_volatility_regime()` for dynamic thresholds | **MINOR** - Serve different purposes but could conflict |
| **Price floor** | None | 20c (longshot trap) | **NO** - Only in unified edge |
| **Chop** | Consecutive closes, MACD persistence | None | **NO** - Only in indicator stack (TA-specific) |

### Recommendation

**Remove indicator stack's microstructure checks** (spread/depth):
- Indicator stack should be purely TA-based (trend, momentum, volatility, chop)
- Unified edge handles Kalshi-specific microstructure (spread, depth, price floor, distance to strike)
- This eliminates the 8c vs 60c spread conflict
- Reduces over-filtering

**Implementation:**
```python
# In crypto_15m_indicators.py, remove:
# snap.liquidity_ok = False (based on spread/depth)
# snap.trade_allowed = ... and snap.liquidity_ok

# Keep:
# vol_gate_ok (volatility band)
# atr_move_ok (min-move gate)
# chop_gate_ok (TA-specific chop filters)
```

---

## 2. Single Spot Source - VERIFIED CLEAN

### Indicator Stack Spot Usage

**Method:** `update(price: float)` - accepts price as parameter
**No direct API calls:** No Coinbase, Coingecko, or CFB API calls in indicator stack
**References found:** Only in comments (historical documentation):
```python
# Line 16: IMPORTANT: This stack uses spot price feeds (CoinGecko/Coinbase/Binance) as PROXIES
# Line 20: Reference: https://www.cfbenchmarks.com/blog/...
```

### Agent Grid Spot Integration

**Path:** `SpotProvider` → `unified_spot_service` → `indicator_stack.update(spot_price)`
**Implementation:** In `agent_grid_15m.py` `_generate_signal()`:
```python
# Update indicator stack with latest spot price (canonical signal feature layer)
if asset and asset in self._indicator_stacks:
    self._indicator_stacks[asset].update(spot_price)
    indicator_snapshot = self._indicator_stacks[asset].snapshot()
```

**Conclusion:** Clean separation. Indicator stack is purely a TA calculator fed by SpotProvider.

---

## 3. Conflicting Regime Systems - MULTIPLE SYSTEMS FOUND

### Regime Systems in Codebase

| Module | Regime Type | Purpose | Used in 15m? |
|--------|-------------|---------|--------------|
| `agent_grid_15m.py` | `RiskRegime` (LOW/NORMAL/HIGH/EXTREME) | Sizing, depth checks, throttle | **YES - Authoritative** |
| `unified_edge.py` | `classify_volatility_regime()` (LOW/NORMAL/HIGH/EXTREME) | Edge threshold adjustments | **YES - Edge only** |
| `tte_regime.py` | `TTERegime` (NORMAL/CRITICAL/TERMINAL) | TP/SL scaling | **YES - TP/SL only** |
| `kalshi/dynamic_risk.py` | `VolatilityRegime` (LOW/MEDIUM/HIGH/EXTREME) | Dynamic risk | **NO - Kalshi general** |
| `market_regime/` | `MarketRegime` (BULL/BEAR/CHOP/SIDEWAYS) | Macro regime | **NO - Macro** |
| `kalshi/macro_models.py` | `MacroRegime`, `VolatilityRegime` | Macro overlay | **NO - Macro** |
| `prediction/risk/sentiment_vol_types.py` | `FearGreedRegime`, `VolatilityRegime`, `UncertaintyRegime` | Sentiment/vol | **NO - Sentiment** |
| `signals/ta_models.py` | `GlobalRegime` | TA-based regime | **NO - Legacy TA** |

### Conflict Analysis

**agent_grid_15m vs unified_edge:**
- `agent_grid_15m.RiskRegime`: Used for sizing, depth checks, throttle, entry limits
- `unified_edge.classify_volatility_regime()`: Used for edge threshold adjustments
- **Not the same system** but serve different purposes
- **No direct conflict** - they operate on different aspects (sizing vs edge thresholds)
- **Naming collision**: Both use LOW/NORMAL/HIGH/EXTREME but are independent enums

**Recommendation:**
- Document that `agent_grid_15m.RiskRegime` is authoritative for 15m crypto
- Consider renaming unified edge's regime to avoid confusion (e.g., `EdgeVolatilityRegime`)
- Or unify to a single regime classifier if both need the same volatility classification

---

## 4. Deprecated RTI/CFB Usage - CLEAN

### Search Results

**agent_grid_15m.py:**
- Line 4183: Comment reference to "RTI metrics" (historical)
- Line 4408-4453: Uses `SpotProvider` with `is_rti_proxy=False` flag
- No actual RTI/CFB proxy calls in 15m path

**Other modules:**
- `edge_model.py`: Imports `unified_regime_classifier` (not RTI/CFB)
- `kalshi/mm_integration.py`: Imports `unified_regime_classifier` (not RTI/CFB)
- `resting_order_monitor.py`: Imports `unified_regime_classifier` (not RTI/CFB)

**Conclusion:** Clean. No deprecated RTI/CFB usage in 15m path.

---

## 5. Dual Implementations - PRICE FLOOR CLEAN

### Price Floor

**unified_edge.py:**
```python
# Check 2.75: Minimum contract price floor (longshot trap prevention)
min_price_cents = 20  # Default fallback
from merid.risk.profiles.crypto_15m_profile import get_active_profile
min_price_cents = profile_adapter.profile.guardrails_min_contract_price_cents
```

**strategy.py:**
- Has "longshot" bias exploitation logic (behavioral, not a hard gate)
- No price floor implementation

**Conclusion:** No duplication. Price floor is only in unified edge.

### Microstructure

**Indicator stack:**
- Simple spread/depth checks (8c spread, 3 depth)
- Static thresholds

**Unified edge:**
- Richer microstructure checks (spread_pct, depth scaling, profile-driven thresholds)
- Dynamic thresholds by regime

**Conclusion:** Duplication exists. Indicator stack's checks are redundant and overly restrictive.

---

## 6. Upstream→Midstream→Downstream Consistency

### Current Flow

```
Upstream: SpotProvider → Crypto15mIndicatorStack → IndicatorSnapshot
          ↓
Midstream: Pre-edge gate (indicator_snapshot.trade_allowed)
          ↓
          UnifiedEdgeComputer.compute_edge() → EdgeResult
          ↓
          UnifiedEdgeComputer.check_edge() → EdgeCheckResult
          ↓
Downstream: Strategy layer (side choice, TP/SL, sizing)
          ↓
          Risk layer (correlation guard, caps, winrate guard)
```

### Consistency Check

| Layer | Purpose | Conflict? |
|-------|---------|-----------|
| **Indicator stack** | TA-based signal quality (trend, momentum, volatility, chop) | **Minor** - Has redundant microstructure checks |
| **Pre-edge gate** | Skip unified edge if TA says no trade | **Potential over-filtering** - 8c spread is too strict |
| **Unified edge** | Probability and market-structure guardrails | **Clean** |
| **Strategy** | Side choice, TP/SL, sizing | **Clean** |
| **Risk** | Correlation, caps, winrate | **Clean** |

### Potential Issues

**Over-filtering:**
- Indicator gate (8c spread) + unified edge (60c spread) could reject almost everything
- If most candidates die at indicator gate, unified edge never gets to evaluate
- **Solution:** Remove indicator stack's spread/depth checks

**Contradictory regimes:**
- Indicator stack has chop filter (TA-based)
- Unified edge has regime cooldown (performance-based)
- They serve different purposes (TA quality vs performance gating)
- **No conflict** - they're orthogonal

---

## 7. Strip-Level Diagnostic Recommendation

### Proposed Diagnostic Structure

```python
@dataclass
class StripDiagnostic:
    strip_id: str
    timestamp: datetime
    
    # Per-asset candidate counts
    candidates_per_asset: Dict[str, int]  # BTC: 5, ETH: 4, etc.
    
    # Rejection counts by layer
    indicator_gate_rejections: Dict[str, int]  # spread: 2, vol: 1, chop: 3
    unified_edge_rejections: Dict[str, int]    # spread_too_wide: 1, low_edge: 2
    strategy_rejections: Dict[str, int]        # correlation: 1, caps: 0
    risk_rejections: Dict[str, int]            # winrate: 0, caps: 1
    
    # Rejection reasons per asset
    rejection_details: Dict[str, List[str]]  # BTC: ["spread_8c", "chop"], ETH: ["low_edge"]
    
    # Key medians
    median_edge_pct: float
    median_spread_cents: int
    median_atr: float
```

### Implementation

Add to `agent_grid_15m.py` in the priority queue scheduler:
```python
# After collecting all candidates for a strip
diagnostic = StripDiagnostic(
    strip_id=strip_id,
    timestamp=datetime.now(timezone.utc),
    candidates_per_asset=candidates_per_asset,
    indicator_gate_rejections=indicator_rejections,
    unified_edge_rejections=edge_rejections,
    strategy_rejections=strategy_rejections,
    risk_rejections=risk_rejections,
    rejection_details=rejection_details,
    median_edge_pct=median_edge_pct,
    median_spread_cents=median_spread_cents,
    median_atr=median_atr,
)

# Log or emit to observability system
logger.info("[STRIP-DIAGNOSTIC] %s", diagnostic.to_dict())
```

### Dashboard Integration

Add to sanity dashboard:
- Strip-level rejection waterfall chart
- Per-asset rejection breakdown
- Median edge/spread/ATR over time
- Alert if indicator gate rejects >80% of candidates (over-filtering)

---

## 8. Action Items

### High Priority

1. **Remove indicator stack's microstructure checks** (spread/depth) - ✅ COMPLETED
   - File: `merid/signals/crypto_15m_indicators.py`
   - Removed: `liquidity_ok` from `trade_allowed` composite gate
   - Kept: `vol_gate_ok`, `atr_move_ok`, `chop_gate_ok` (TA-specific)
   - Added: Comment noting microstructure is now handled by unified edge
   - Rationale: Eliminates 8c vs 60c spread conflict, reduces over-filtering
   - Test: Added `test_microstructure_removed_from_trade_allowed` to verify fix

2. **Add strip-level diagnostic logging** - ✅ COMPLETED
   - File: `merid/prediction/agent_grid_15m.py`
   - Added: `StripDiagnostic` dataclass with rejection tracking by layer
   - Added: Strip-level diagnostic logging in priority queue scheduler
   - Added: Enhanced pre-edge gate rejection reason logging
   - Rationale: Makes conflicts visible in observability

### Medium Priority

3. **Document regime system separation**
   - File: `docs/KALSHI_15M_ARCHITECTURE.md`
   - Add: Section on regime systems and their purposes
   - Rationale: Prevents future confusion

4. **Consider unifying volatility regime**
   - If both indicator stack and unified edge need volatility classification
   - Use `unified_edge.classify_volatility_regime()` in both places
   - Rationale: Eliminates potential inconsistency

### Low Priority

5. **Rename unified edge's regime enum**
   - From: `LOW/NORMAL/HIGH/EXTREME` (string)
   - To: `EdgeVolatilityRegime` (enum) to avoid naming collision
   - Rationale: Clarity

---

## 9. Conclusion

**Status:** Minor conflicts found, no critical issues.

**Key Issue:** Indicator stack's 8c spread check is redundant and overly restrictive compared to unified edge's 60c spread check. This could cause over-filtering.

**Recommendation:** Remove indicator stack's microstructure checks, keep it purely TA-based. Add strip-level diagnostic logging to monitor rejection patterns.

**Next Steps:**
1. Implement indicator stack microstructure check removal
2. Add strip-level diagnostic logging
3. Monitor live window for rejection patterns
4. Adjust thresholds if over-filtering detected
