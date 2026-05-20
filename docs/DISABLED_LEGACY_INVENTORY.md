# DISABLED and Legacy Code Inventory

**Date:** 2026-05-12  
**Purpose:** Classification of DISABLED and legacy code for risk review and cleanup

---

## Summary

**Total files with markers:** 20+ files  
**Files with DISABLED markers:** 10  
**Files with _legacy markers:** 15  
**Files containing risk logic:** 8 (HIGH PRIORITY)

---

## Category A: Dead Infrastructure (Safe to Delete)

These files are not wired into production and contain no risk logic. Safe to delete after confirmation.

### Files

1. **`web/api/agents.py`** (line 173)
   - **Reason:** "DISABLED - No simulated activity. Use real agent mesh only."
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Delete - simulation endpoint replaced by real agent mesh

2. **`web/api/trading.py`** (lines 10, 548, 579, 616)
   - **Reason:** "LEGACY: Perps trading endpoints moved to _legacy/", "LEGACY: Polymarket support moved to _legacy/"
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Delete - endpoints moved to _legacy/ folder

---

## Category B: Parking-Lot Features (Review Before Deletion)

These features are not currently used but might be revived. Add explicit comments before deletion.

### Files

1. **`web/main.py`** (line 2501)
   - **Reason:** "Legacy crypto publishers DISABLED — Kalshi has its own data pipeline."
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Keep with comment - may be needed for multi-venue support

2. **`web/main.py`** (line 2880-2882)
   - **Reason:** "Phase 2: Prediction markets (DISABLED — Kalshi-only mode)", "Legacy crypto prediction aggregator disabled"
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Keep with comment - may be revived for multi-PM support

3. **`web/main.py`** (line 3807)
   - **Reason:** "Continuous miner (DISABLED — legacy simulation, not needed for Kalshi)"
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Keep with comment - simulation infrastructure

4. **`web/main.py`** (line 3863)
   - **Reason:** "Whale listener (DISABLED — Solana-specific, not needed for Kalshi)"
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Keep with comment - Solana-specific code

5. **`web/main.py`** (line 4066)
   - **Reason:** "Terminal telemetry loop DISABLED — was printing synthetic crypto trades/portfolio"
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Keep with comment - debug infrastructure

6. **`web/api/operator_endpoints.py`** (lines 847, 865, 871, 885, 887)
   - **Reason:** Legacy governance/promotion endpoints
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Keep with comment - historical governance endpoints

7. **`web/api/kalshi_api.py`** (line 2505)
   - **Reason:** `_get_fills_legacy()` function
   - **Risk Logic:** No
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** Keep with comment - legacy fills endpoint

---

## Category C: Historical Risk Logic (REQUIRES EXPLICIT RISK REVIEW)

These files contain risk logic and require explicit review before deletion or re-enablement.

### Files

1. **`web/main.py`** (line 2672-2681)
   - **Reason:** "SENTIMENT_ISOLATION_AUDIT: Assert sentiment voting is disabled in production"
   - **Risk Logic:** **YES** - Sentiment isolation audit
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **KEEP** - Critical risk control for sentiment isolation

2. **`web/api/arbitrage.py`** (lines 291-332)
   - **Reason:** "Arbitrage execution disabled via API"
   - **Risk Logic:** **YES** - Arbitrage execution gate
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **KEEP** - Risk control for arbitrage execution

3. **`web/api/fvg_api.py`** (lines 42, 148)
   - **Reason:** "FVG analysis is disabled"
   - **Risk Logic:** **YES** - FVG (Fair Value Gap) analysis gate
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **KEEP** - Risk control for FVG analysis

4. **`web/api/kalshi_api.py`** (line 3200)
   - **Reason:** "Risk pre-check failed — live trading disabled until checks succeed"
   - **Risk Logic:** **YES** - Risk pre-check for live trading
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **KEEP** - Critical risk control for live trading

5. **`web/api/kalshi_api.py`** (line 6588)
   - **Reason:** "FIX protocol disabled in mode"
   - **Risk Logic:** **YES** - FIX protocol gate
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **KEEP** - Risk control for FIX protocol

6. **`trading/_legacy/`** (entire directory)
   - **Reason:** Legacy perp trading code
   - **Risk Logic:** **YES** - Legacy execution logic
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **REVIEW** - Add env guard before deletion

7. **`trading/integrations/__init__.py`** (line 8)
   - **Reason:** "LEGACY: Additional integrations preserved in _legacy folder"
   - **Risk Logic:** **YES** - Legacy integration logic
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **REVIEW** - Add env guard before deletion

8. **`trading/adapters/__init__.py`** (line 13)
   - **Reason:** "LEGACY: Additional adapters preserved in _legacy folder"
   - **Risk Logic:** **YES** - Legacy adapter logic
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **REVIEW** - Add env guard before deletion

---

## Category D: Unknown (Manual Review Needed)

These files require manual review to determine classification.

### Files

1. **`web/api/agents_real.py`** (lines 34, 107)
   - **Reason:** "Agent mesh disabled in validation mode"
   - **Risk Logic:** Unknown
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **REVIEW** - Determine if this is a risk control or feature gate

2. **`web/api/degraded.py`** (line 4)
   - **Reason:** "Provides graceful degradation for missing or disabled services"
   - **Risk Logic:** Unknown
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **REVIEW** - Determine if this is risk infrastructure

3. **`web/api/kalshi_dashboard_api.py`** (lines 99, 128-129, 141, 183, 193, 439, 518)
   - **Reason:** Market disabled statistics
   - **Risk Logic:** Unknown
   - **Last Modified:** Unknown
   - **Owner:** TBD
   - **Recommendation:** **REVIEW** - Determine if this is observability or risk control

4. **Test files with legacy markers**
   - `tests/test_agent_grid_audit.py` (line 94)
   - `tests/regression/test_no_silent_except_in_scalper_slice.py` (line 77)
   - `tests/prediction/test_pm_ct_policy.py` (line 52)
   - `tests/pipeline/test_instruments.py` (line 189)
   - `tests/test_betting_layer.py` (multiple lines)
   - **Risk Logic:** No (tests)
   - **Recommendation:** Keep - test infrastructure

---

## Recommendations

### Immediate Actions (High Priority)

1. **Add env guards to legacy execution code:**
   - `trading/_legacy/` - Add `MERID_ALLOW_LEGACY_EXECUTION` guard
   - `trading/integrations/__init__.py` - Add env guard
   - `trading/adapters/__init__.py` - Add env guard

2. **Review Category C files for risk logic:**
   - Confirm all risk controls are still active
   - Document why each is disabled
   - Add re-enablement criteria

3. **Delete Category A files:**
   - `web/api/agents.py` - Simulation endpoint
   - `web/api/trading.py` - Moved endpoints

### Medium Priority Actions

4. **Add explicit comments to Category B files:**
   - "NOT WIRED TO PROD – for future feature X only"
   - Document conditions for re-enablement

5. **Review Category D files:**
   - Determine if they are risk controls or feature gates
   - Classify appropriately

### Low Priority Actions

6. **Clean up test files:**
   - Remove obsolete legacy test methods
   - Update test documentation

---

## Next Steps

1. Run the inventory script to generate CSV: `python scripts/audit_inventory_disabled_legacy.py --output inventory.csv`
2. Fill in owner field for each file
3. Manual review and re-classification as needed
4. Implement env guards for legacy execution code
5. Delete Category A files after confirmation
6. Document re-enablement criteria for Category B files
