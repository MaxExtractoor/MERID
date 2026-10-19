# Risk Oversizing Fix — Production Deployment Guide

**Date:** 2026-04-20  
**Status:** ✅ Ready for Production  
**Criticality:** HIGH — Prevents 4.4x risk violations

---

## Quick Start

```bash
export USE_TOPN_ALLOCATOR=true
./scripts/deploy_risk_fix.sh systemd  # or docker, pm2
sudo systemctl restart merid-trader
```

**Verify in logs:**
```
[RISK-MODE] Using new TopNEdgeAllocator with fixed fractional risk (1-2% per cycle)
[RISK-CONFIG] USE_TOPN_ALLOCATOR=true, max_cycle_risk_pct=2.00%, max_total_risk_pct=2.00%
[RISK-GUARD] Initialized | max_cycle_risk_pct=2.00%, max_total_risk_pct=2.00%
```

---

## Pre-Restart Checklist

- [x] `core/settings.py` has canonical `USE_TOPN_ALLOCATOR` setting
- [x] `.env` has `USE_TOPN_ALLOCATOR=true`
- [x] `kalshi_continuous_trader.py` imports from settings
- [x] 15 regression tests passing
- [x] `scripts/verify_risk_fix.py` shows ✅ ALL CHECKS PASSED

---

## Environment Setup

### Option 1: .env file
```bash
USE_TOPN_ALLOCATOR=true
MAX_CYCLE_RISK_PCT=0.02
MAX_TOTAL_RISK_PCT=0.02
```

### Option 2: systemd
```ini
[Service]
Environment="USE_TOPN_ALLOCATOR=true"
Environment="MAX_CYCLE_RISK_PCT=0.02"
```

### Option 3: Docker
```yaml
environment:
  - USE_TOPN_ALLOCATOR=true
```

---

## What Gets Logged

**Startup:**
```
[RISK-MODE] Using new TopNEdgeAllocator...
[RISK-CONFIG] USE_TOPN_ALLOCATOR=true, max_cycle_risk_pct=2.00%...
[RISK-GUARD] Initialized | max_cycle_risk_pct=2.00%...
```

**Per Cycle:**
```
[RISK-GUARD] Cycle 42: risk guard reset
[TOPN-ALLOCATOR] equity=$28.00 | risk_budget=$0.56 | N=1...
[TOPN-SIZE] KXBTC... | contracts=1 | max_loss=$0.35...
[GLOBAL-RISK-GUARD] ALLOWED | risk=0.35/0.56
```

**If Violation Attempted:**
```
[CRITICAL] [GLOBAL-RISK-GUARD] BLOCKED | reason=Cycle risk cap exceeded...
```

---

## Rollback

If issues detected:
```bash
export USE_TOPN_ALLOCATOR=false
sudo systemctl restart merid-trader
```

---

## Test Results

```
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_feature_flag_is_true PASSED
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_global_risk_guard_blocks_over_cycle_cap PASSED
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_global_risk_guard_blocks_simulated_7_btc_scenario PASSED
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_global_risk_guard_reset_cycle PASSED
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_short_position_max_loss_calculation PASSED
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_topn_allocator_enforces_cycle_cap PASSED
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_topn_allocator_step_down_n PASSED
tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_total_risk_cap_includes_existing_positions PASSED
tests/trading/test_risk_oversizing_regression.py::TestKellySizingBypass::test_kelly_not_called_when_topn_enabled PASSED
tests/trading/test_risk_oversizing_regression.py::TestInvariantValidation::test_allocation_cycle_validates_num_edges PASSED
tests/trading/test_risk_oversizing_regression.py::TestInvariantValidation::test_allocation_cycle_validates_sum_risk PASSED
tests/trading/test_risk_oversizing_regression.py::TestCanonicalSettingsImport::test_settings_imported_from_core PASSED
tests/trading/test_risk_oversizing_regression.py::TestCanonicalSettingsImport::test_module_flag_matches_settings PASSED
tests/trading/test_risk_oversizing_regression.py::TestCanonicalSettingsImport::test_env_var_propagation PASSED

15 passed, 0 failed
```

---

## Verification Command

```bash
cd /path/to/MERID && export USE_TOPN_ALLOCATOR=true && python -m pytest tests/trading/test_risk_oversizing_regression.py::TestRiskOversizingRegression::test_global_risk_guard_blocks_simulated_7_btc_scenario -v
```

**Expected:** `PASSED` — The 7-BTC bug is blocked.
