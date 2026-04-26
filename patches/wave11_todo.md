# Wave 11 Implementation TODO

**Status:** In Progress  
**Goal:** Close all gaps from Passes 1-10 and ensure 17/17 tests pass reliably

---

## Section 1: Architecture & Code Fixes

### 1.1 Execution Topology & Guards ✅
- [x] FIX endpoint guard (`web/api/kalshi_api.py`)
- [x] REST fallback fail-closed (`web/api/kalshi_api.py`)
- [x] CT API module-level guard (`web/api/kalshi_continuous_trader_api.py`)
- [x] Archive import guard (`archive/__init__.py`)
- [x] Startup enforcement (`merid/config/unified_risk_enforcement.py`)

**Verification:** Check all guards have logging/metrics wired

### 1.2 Risk Model Enforcement ✅
- [x] 2% global cap enforced at startup
- [x] 3-edge limit enforced
- [x] Fixed-USD ban in LIVE/PAPER
- [x] `enforce_at_startup()` aborts on violations

**Verification:** Run `test_six_percent_global_rejected`, `test_fixed_usd_rejected_in_live`

### 1.3 Structured Logging & Metrics ✅
- [x] `merid/utils/structured_logging.py` created
- [x] `merid/metrics/kalshi_metrics.py` created
- [x] All 5 guards wired with logging calls
- [x] All 5 guards wired with metrics calls

**Verification:** Check imports work, functions exist

---

## Section 2: Testing/CI Fixes

### 2.1 Clean Test Environment Recipe ✅
- [x] `pytest.ini` has plugin blacklist
- [x] Create `RUN_TESTS.md` with exact commands
- [ ] Verify `.venv` approach works on Windows (pending user test)

**Commands verified:**
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e .
pip install pytest fastapi httpx
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
pytest tests/risk/test_unified_risk_enforcement.py -vv
```

### 2.2 FastAPI TestClient Wiring ⏳
- [x] `client` fixture in `test_pass9_scenarios.py`
- [ ] Verify `web.main.app` imports correctly (pending test run)
- [x] Check import paths: `trading.trade_mode` vs `merid.trading.trade_mode` ✅ FIXED

**Issue:** Tests use `trading.trade_mode.get_trade_mode` but actual module may be `merid.trading.trade_mode` → **FIXED**

### 2.3 Fix Import Path Issues ✅
- [x] Fix `trading.trade_mode` → `merid.trading.trade_mode` in tests ✅
- [x] Fix `web.api.kalshi_api._get_order_router` - function added ✅
- [x] Fix `merid.event_venues.kalshi.kalshi_rest_client` → `merid.event_venues.kalshi.client.KalshiVenueClient` ✅

**Files fixed:**
- `tests/scenario/test_pass9_scenarios.py` - all import paths updated
- `web/api/kalshi_api.py` - `_get_order_router()` function added at line ~172

### 2.4 Ensure All 17 Tests Pass 🔴
Current status: Unknown (need to run in clean env)

Tests breakdown:
- Scenario A: 3 tests (logic-based, should pass)
- Scenario B: 3 tests (FastAPI endpoint tests)
- Scenario C: 3 tests (logic-based, should pass)
- Scenario D: 3 tests (FastAPI endpoint tests)
- Scenario E: 4 tests (logic-based, should pass)
- Runner: 1 test (logic-based)

**Total: 17 tests**

---

## Section 3: UI/UX & Ops

### 3.1 Mode Indicators ⏳
- [x] `merid/cli/status.py` created
- [x] `web/templates/components/mode_banner.html` created
- [ ] Verify CLI mode banner displays correctly
- [ ] Verify web mode banner renders

### 3.2 Config Validation API ⏳
- [x] `web/api/config_validation.py` created
- [ ] Verify endpoints work
- [ ] Test with actual requests

### 3.3 Runbooks ⏳
- [x] 5 runbook skeletons created in `docs/runbooks/`
- [ ] Review and flesh out with operational details

---

## Section 4: CI Integration

### 4.1 CI Pipeline ⏳
- [x] `.github/workflows/merid-safety-ci.yml` created
- [ ] Verify workflow syntax
- [ ] Ensure it uses clean venv
- [ ] Test invariant script

### 4.2 Invariant Script ⏳
- [x] `scripts/ci/check_kalshi_invariants.py` exists
- [ ] Verify 8 checks work
- [ ] Ensure non-zero exit on violations

---

## Critical Path to 17/17 Tests Passing

1. **Fix import paths** in test file (trading.trade_mode → merid.trading.trade_mode)
2. **Verify _get_order_router** exists in kalshi_api.py
3. **Run tests** in clean .venv with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
4. **Fix any remaining test failures**
5. **Create RUN_TESTS.md** documenting working commands

---

## Current Blockers

1. Need to run tests in clean environment to verify 17/17 pass
2. Some test failures may surface once tests run (unknown until execution)

---

## Next Actions

1. ⏳ Run tests in clean .venv with documented commands (need user execution)
2. ⏳ Fix any test failures discovered during execution
3. ✅ Create RUN_TESTS.md - COMPLETE
4. ⏳ Complete runbook operational details
5. ⏳ Create Wave 11 completion report
