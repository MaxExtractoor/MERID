# EV Tracking and Price Buckets Audit Report

**Date:** 2026-07-15  
**Scope:** End-to-end audit of EV tracking and price buckets across all assets (BTC, ETH, SOL, XRP, DOGE)  
**Objective:** Identify flaws, discrepancies, and misalignments in how EV and price buckets are defined, calculated, and used throughout the system.

---

## Executive Summary

This audit reveals **critical misalignments** in price bucket definitions and EV tracking across the MERID codebase. The most significant issue is the existence of **multiple incompatible price bucket definitions** that are not aligned with each other or with the canonical 10c-75c trading range. Additionally, the realized edge tracking system is not consistently integrated with the 15m production trading flow.

---

## Critical Findings

### 1. Price Bucket Definition Misalignment (CRITICAL)

**Issue:** Multiple incompatible price bucket definitions exist in the codebase.

**Details:**

- **pnl_bucket_audit.py** (lines 24-31) defines PRICE_BANDS as:
  ```python
  PRICE_BANDS = [
      (0.00, 0.20, "below_20c"),  # Below price floor
      (0.20, 0.35, "20c_35c"),
      (0.35, 0.50, "35c_50c"),
      (0.50, 0.75, "50c_75c"),
      (0.75, 1.00, "75c_1d"),
      (1.00, float('inf'), "above_1d"),
  ]
  ```

- **agent_grid_15m.py** (lines 7500-7538) defines different price buckets for EV tracking:
  ```python
  if 10 <= price_cents <= 14:
      price_bucket = "10-14c"
  elif 15 <= price_cents <= 19:
      price_bucket = "15-19c"
  elif 20 <= price_cents <= 24:
      price_bucket = "20-24c"
  elif 25 <= price_cents <= 29:
      price_bucket = "25-29c"
  elif 30 <= price_cents <= 39:
      price_bucket = "30-39c"
  elif 40 <= price_cents <= 49:
      price_bucket = "40-49c"
  elif 50 <= price_cents <= 65:
      price_bucket = "50-65c"
  elif 66 <= price_cents <= 70:
      price_bucket = "66-70c"
  else:
      price_bucket = f"{price_cents}c"
  ```

- **Canonical trading range** (enforced in strategy.py, agent_grid_15m.py, kalshi_tools.py, loop_15m.py): 10c-75c

**Misalignment:**
- pnl_bucket_audit uses a "below_20c" band, but the canonical range starts at 10c
- The agent_grid_15m buckets are more granular (5c ranges) and don't align with pnl_bucket_audit ranges
- pnl_bucket_audit has bands above 75c (75c_1d, above_1d) which are outside the canonical trading range
- The agent_grid_15m buckets stop at 70c, missing the 71-75c range that is valid per canonical range

**Impact:** PnL analysis and EV tracking use incompatible bucket definitions, making cross-referencing and consistent analysis impossible.

**Recommendation:** Establish a single canonical price bucket definition that aligns with the 10c-75c trading range and is used consistently across all components.

---

### 2. Distance Band Calculation Non-Functional (HIGH)

**Issue:** Distance bands are defined but not calculated due to missing spot price data.

**Details:**

- **pnl_bucket_audit.py** (lines 33-37) defines DISTANCE_BANDS:
  ```python
  DISTANCE_BANDS = [
      (0.0, 0.5, "0_0.5pct"),
      (0.5, 1.0, "0.5_1.0pct"),
      (1.0, 2.0, "1.0_2.0pct"),
      (2.0, float('inf'), "above_2.0pct"),
  ]
  ```

- However, line 185 sets: `distance_band = "unknown"` with a comment indicating spot price data is needed

**Impact:** Distance-based analysis is completely non-functional. All trades are categorized as "unknown" distance band, rendering the DISTANCE_BANDS definition useless.

**Recommendation:** Integrate spot price data into the pnl_bucket_audit script to enable actual distance band calculation.

---

### 3. EV Calculation Inconsistencies (MEDIUM)

**Issue:** Multiple EV calculation methods with different formulas.

**Details:**

- **Crypto15mIndicatorStack.compute_ev_cents** (crypto_15m_indicators.py, lines 1321-1356):
  ```python
  # YES: ev = model_prob * (100 - price - fee) - (1 - model_prob) * (price + fee)
  # NO: ev = (1 - model_prob) * (price - fee) - model_prob * (100 - price + fee)
  ```

- **web/api/kalshi_api.py** (line 5309):
  ```python
  ev_cents = round((model_prob - implied_prob) * 100, 1)
  ```

- **web/api/kalshi_crypto_signals_api.py** (line 44):
  ```python
  ev_cents = (model - implied) * 100
  ```

- **RealizedEdgeStore** uses: `est_edge = p_model - p_implied` (line 240)

**Impact:** Different components calculate EV differently, leading to inconsistent values being reported and used for decision-making.

**Recommendation:** Standardize on a single EV calculation formula across all components, preferably the fee-aware version from Crypto15mIndicatorStack.

---

### 4. Realized Edge Tracking Not Integrated with 15m Production Flow (HIGH)

**Issue:** The RealizedEdgeStore exists but is not consistently called by the 15m trading system.

**Details:**

- **RealizedEdgeStore** (merid/metrics/realized_edge.py) provides comprehensive edge tracking with:
  - `record_trade_entry()` to log edge estimates at trade time
  - `resolve_trade()` to compare estimated vs realized edge after settlement
  - Aggregated statistics per (forecaster_id, bucket)

- **Known gap** (from tmp_agent_B_backend_pnl.txt): kalshi_continuous_trader.py never calls `record_trade_entry()`, leaving OutcomeResolver with nothing to resolve

- **API endpoint** `get_edge_snapshots` in kalshi_agent_grid_api.py references a function that doesn't exist in agent_grid_15m.py

- **Bucket parameter:** Most calls use `bucket="crypto"` as a generic category, not asset-specific buckets

**Impact:** The sophisticated edge tracking infrastructure exists but is not consistently used, limiting visibility into actual vs estimated edge performance.

**Recommendation:** 
1. Integrate `record_trade_entry()` calls in the 15m trading flow (loop_15m.py or agent_grid_15m.py)
2. Implement or remove the `get_edge_snapshots` function
3. Consider using asset-specific buckets (BTC, ETH, SOL, XRP, DOGE) instead of generic "crypto"

---

### 5. Per-Asset Edge Thresholds Not Reflected in EV Tracking (MEDIUM)

**Issue:** Per-asset edge thresholds exist but EV tracking doesn't differentiate by asset.

**Details:**

- **GlobalSlotAllocator** (merid/risk/profiles/global_allocator.py, lines 95-102) defines per-asset edge thresholds:
  ```python
  self.per_asset_min_edge_pct = {
      "BTC": 1.75,
      "ETH": 2.0,
      "SOL": 2.5,
      "XRP": 3.0,
      "DOGE": 3.5,
  }
  ```

- **RealizedEdgeStore** uses `bucket="crypto"` for all assets, not asset-specific buckets

- **Profile YAML** (kalshi_crypto_15m_v2.yaml) has asset-specific configurations but EV tracking doesn't leverage this

**Impact:** Cannot analyze edge performance per asset, even though the system has different edge thresholds per asset.

**Recommendation:** Use asset-specific buckets in RealizedEdgeStore (BTC, ETH, SOL, XRP, DOGE) to enable per-asset edge analysis.

---

### 6. Edge Calculation for Velocity-Based Signals (MEDIUM)

**Issue:** Velocity-based signals use different edge calculation logic.

**Details:**

- **tests/test_2026_edge_calculation_fixes.py** documents that for momentum signals:
  ```python
  edge_pct = abs(velocity) * 100.0
  ```

- **tests/prediction/test_velocity_edge_validation.py** confirms velocity signals skip probability-based edge validation

- **tests/event_venues/kalshi/test_order_router_guardrails.py** shows velocity orders require minimum 3% edge

**Impact:** Velocity-based signals have a different edge definition (velocity magnitude) than probability-based signals (model_prob - implied_prob), but this is not consistently tracked or labeled in the edge tracking system.

**Recommendation:** Add an `edge_type` field to edge tracking to distinguish between probability-based and velocity-based edges.

---

## Cross-Asset Consistency Check

### Per-Asset Configuration

The system has per-asset configurations in **kalshi_crypto_15m_v2.yaml**:

- **Rolling PnL limits** (lines 660-680):
  - BTC/ETH: 4% (1h), 7% (4h) - more stable
  - SOL/XRP: 6% (1h), 9% (4h) - moderate volatility
  - DOGE: 8% (1h), 12% (4h) - most volatile

- **Order Book Imbalance thresholds** (lines 713-718):
  - BTC/ETH: 70% strong threshold
  - SOL/XRP/DOGE: 65% strong threshold (thinner books)

- **Edge thresholds** (via GlobalSlotAllocator):
  - BTC: 1.75%
  - ETH: 2.0%
  - SOL: 2.5%
  - XRP: 3.0%
  - DOGE: 3.5%

**Assessment:** Per-asset configurations are well-defined and aligned with asset volatility profiles. However, these are not reflected in EV/edge tracking which uses generic "crypto" bucket.

---

## Data Flow Analysis

### Upstream Data Sources

1. **Signal Generation:**
   - Crypto15mIndicatorStack computes EV with fee awareness
   - Edge metrics set via `set_edge_metrics()` (edge_bp in basis points)
   - Multiple signal types: probability-based, velocity-based, price-based

2. **Market Data:**
   - KalshiMarketStateStore provides implied probabilities
   - LivePriceFeed provides spot prices (for distance calculation)
   - MarketSnapshot includes edge estimates in `edges` list

### Midstream Processing

1. **Agent Grid (agent_grid_15m.py):**
   - Generates candidates with edge_pct
   - Applies per-asset edge thresholds
   - Uses own price bucket definition for logging (lines 7500-7538)
   - Price range validation: 10c-75c

2. **Strategy (strategy.py):**
   - Uses EdgeEstimate with net_edge calculation
   - Price selection within 10c-75c canonical range
   - Kelly sizing based on edge

3. **Global Allocator:**
   - Filters by per-asset edge thresholds
   - Enforces $1 exposure cap
   - Price range validation: 10c-75c

### Downstream Execution

1. **Order Router (order_router.py):**
   - Price clamping: 10c-75c
   - Edge validation via signal validation
   - Fill tracking via FillsLedger

2. **Realized Edge Tracking:**
   - RealizedEdgeStore exists but not consistently integrated
   - Should record trade entry and resolve on settlement
   - Currently uses generic "crypto" bucket

---

## Recommendations Summary

### Critical Priority

1. **Standardize price bucket definitions** - Create single canonical definition aligned with 10c-75c range
2. **Integrate spot price data** - Enable distance band calculation in pnl_bucket_audit
3. **Integrate RealizedEdgeStore** - Add record_trade_entry() calls in 15m trading flow

### High Priority

4. **Standardize EV calculation** - Use consistent formula across all components
5. **Implement asset-specific buckets** - Use BTC/ETH/SOL/XRP/DOGE instead of generic "crypto"
6. **Add edge_type field** - Distinguish probability-based vs velocity-based edges

### Medium Priority

7. **Implement or remove get_edge_snapshots** - Currently references non-existent function
8. **Align agent_grid_15m price buckets** - Make consistent with canonical definition
9. **Add distance band to candidate** - Include in signal generation for downstream use

---

## Files Reviewed

### Core Trading Logic
- merid/prediction/strategy.py
- merid/prediction/agent_grid_15m.py
- merid/prediction/kalshi_tools.py
- merid/loop_15m.py

### Risk & Configuration
- merid/risk/profiles/global_allocator.py
- merid/risk/profiles/crypto_15m_profile.py
- merid/event_venues/kalshi/risk_parameters.py
- config/profiles/kalshi_crypto_15m_v2.yaml

### Metrics & Tracking
- merid/metrics/realized_edge.py
- merid/event_venues/kalshi/fills_ledger.py
- pnl_bucket_audit.py

### Signal Generation
- merid/signals/crypto_15m_indicators.py
- merid/prediction/model.py

### API Endpoints
- web/api/kalshi_api.py
- web/api/kalshi_crypto_signals_api.py
- web/api/kalshi_agent_grid_api.py
- web/api/kalshi_metrics_api.py

### Tests
- tests/test_metrics.py
- tests/test_crypto_15m_indicators.py
- tests/test_2026_edge_calculation_fixes.py
- tests/prediction/test_velocity_edge_validation.py
- tests/test_global_allocator.py

---

## Conclusion

The MERID system has a sophisticated infrastructure for EV tracking and price bucket analysis, but suffers from **critical misalignments** that reduce its effectiveness:

1. **Multiple incompatible price bucket definitions** prevent consistent analysis
2. **Distance band calculation is non-functional** due to missing spot data integration
3. **Realized edge tracking is not integrated** with the production 15m trading flow
4. **EV calculations vary across components** leading to inconsistent metrics
5. **Asset-specific configurations exist** but are not reflected in tracking buckets

Addressing these issues will significantly improve the system's ability to track, analyze, and optimize edge performance across all assets (BTC, ETH, SOL, XRP, DOGE).
