# Dev vs Prod Audit Inventory

**Purpose:** Document all dev-only, legacy, and demo code paths to ensure clean separation between development and production behavior.

**Environment:** `merid.config.environment` provides `Env.DEV`, `Env.STAGING`, `Env.PROD` with `current_env()` and `require_prod_ready_config()`.

---

## Audit Table

| Layer | Component / File | Dev-only behavior? | Prod-critical? | Action |
|-------|------------------|--------------------|----------------|--------|
| **Auth** | `kalshi_config.py` API key validation | Yes (allows missing in dev) | Yes | Enforce fatal in prod via `require_prod_ready_config()` |
| **Bankroll** | `settings.py` `KALSHI_PORTFOLIO_BANKROLL_CENTS` toggle | Yes (legacy, "temporarily disabled") | No | Remove toggle, keep `bankroll_service_v2` only |
| **Risk** | `kill_switches.py` fallback `max_position_value=$100k` | No (safety fallback) | Yes | Keep but document and add tests |
| **Spot** | `data/spot_composite.py` composite spot fallback | Maybe (currently used) | Maybe | Gate behind `enable_composite_spot_fallback()` |
| **Spot** | `data/unified_spot_service.py` UnifiedSpotService | No | Yes | Normalize interface, remove legacy fallbacks |
| **MD** | `event_venues/kalshi/market_state.py` freshness, spread | No | Yes | Keep and document thresholds |
| **Infra** | `event_venues/kalshi/ws.py` asyncio Events | No | Yes | Fixed via lazy initialization |
| **Infra** | `event_venues/kalshi/client_v2.py` asyncio Locks | No | Yes | Fixed via lazy initialization |
| **Diagnostics** | Multiple files with "TEMPORARILY DISABLED" comments | Yes (legacy) | No | Delete or hide behind `if current_env() is Env.DEV` |
| **Diagnostics** | `ws_bridge.py` "fallback to composite spot" | Yes (comment says disabled for 15m) | No | Gate behind env check or delete |
| **Legacy** | `archive/legacy/` entire directory | Yes (archived) | No | Keep as archive, ensure no imports from prod code |
| **Legacy** | `trading_legacy/` directory | Yes (legacy trading) | No | Keep as archive, ensure no imports from prod code |
| **Tests** | `tests_legacy/` directory | Yes (legacy tests) | No | Keep for historical reference, gate from CI |
| **Demo** | `scripts/kalshi_demo_runner.py` | Yes (demo) | No | Gate behind env check |
| **Demo** | `core/demo_runner.py` | Yes (demo) | No | Gate behind env check |
| **Demo** | `swarm/demo/` directory | Yes (demo) | No | Gate behind env check |

---

## Detailed Findings

### 1. "TEMPORARILY DISABLED" References (17 files)

**Files with "TEMPORARILY DISABLED":**
- `web/main_15m_lean.py`
- `scripts/ci/check_test_bypasses.py`
- `merid/prediction/alerts.py`
- `merid/startup_validations.py`
- `merid/prediction/sentiment_floor_tracker.py`
- `merid/prediction/risk/sentiment_vol_service.py`
- `merid/prediction/risk/_prediction_risk.py`
- `merid/prediction/kalshi_strike_calibrator.py`
- `merid/prediction/high_performance_calibration.py`
- `merid/settings.py` (bankroll config)
- `merid/prediction/dynamic_edge_calibrator.py`
- `merid/loop.py`
- `merid/event_venues/kalshi/fills_poller.py`
- `merid/event_venues/kalshi/ws.py`
- `merid/event_venues/kalshi/ws_bridge.py`

**Action Required:**
- Review each "TEMPORARILY DISABLED" section
- Either: (a) Remove if truly obsolete, (b) Gate behind `if current_env() is Env.DEV`, or (c) Finalize for prod use

### 2. "Disabled for 15m" References (2 files)

**Files:**
- `merid/prediction/agent_grid_15m.py`
- `merid/event_venues/kalshi/cfb_spot_proxy.py`

**Action Required:**
- These are explicitly disabled for Kalshi 15m trading
- Gate behind env check or remove entirely if no longer needed

### 3. "Fallback to composite" References (1 file)

**File:**
- `merid/event_venues/kalshi/ws_bridge.py`

**Context:** Comment says "fallback to composite spot if provider fails"

**Action Required:**
- Gate behind `enable_composite_spot_fallback()` which returns `False` in prod
- Add explicit logging when fallback is used

### 4. "Demo" References (200+ files)

**Major categories:**
- Test files with demo mode
- API endpoints with demo paths
- Scripts for demo execution
- Configuration references

**Action Required:**
- Review prod-critical paths (main entrypoints, trading logic)
- Ensure demo code cannot be reached in `Env.PROD`
- Add CI check to prevent demo code in prod packages

### 5. "Synthetic data" References (50+ files)

**Major categories:**
- Test fixtures
- Fallback data generation
- Neutral fallback implementations

**Action Required:**
- Gate behind `enable_synthetic_data()` which returns `False` in prod
- Ensure no synthetic data in trading-critical paths
- Add tests asserting synthetic data never used in prod mode

### 6. "Legacy" References (200+ files)

**Major categories:**
- `archive/legacy/` directory (archived code)
- `trading_legacy/` directory (legacy trading adapters)
- `legacy/lanes/` directory (legacy lane implementations)
- Comments referencing "legacy" behavior

**Action Required:**
- Ensure no imports from legacy directories in prod code
- Add import guards to prevent accidental legacy usage
- Consider moving legacy code to separate repository

---

## Production Pipeline Requirements

### Entrypoint Checks

All production entrypoints must:

1. Call `log_environment_startup()` early
2. Call `require_prod_ready_config()` before event loop start
3. Log environment in all log records (add `env` field to formatter)

### CI/CD Enforcement

1. **Dev/staging pipeline:**
   - Allows dev flags
   - May allow demo mode
   - Runs all tests including legacy tests

2. **Prod pipeline:**
   - Only deploys from protected branch (e.g., `main`)
   - Fails build if "TEMPORARILY DISABLED" found in prod packages
   - Fails build if legacy imports detected in prod code
   - Requires all tests to pass
   - Enforces `MERID_ENV=prod` in deployment

### Static Checks

Add CI checks for:
- `TEMPORARILY DISABLED` in `merid/` (except devtools)
- `demo` references in trading-critical paths
- Legacy imports from `archive/` or `trading_legacy/`
- Missing environment checks on fallback paths

---

## Cleanup Passes

### Pass 1: Environment Infrastructure (IN PROGRESS)
- [x] Create `merid/config/environment.py`
- [ ] Add `require_prod_ready_config()` to all prod entrypoints
- [ ] Add `log_environment_startup()` to all prod entrypoints
- [ ] Add environment field to log formatter

### Pass 2: Bankroll and Config
- [ ] Remove "temporarily disabled" bankroll toggle from `settings.py`
- [ ] Ensure only `bankroll_service_v2.get_equity_for_risk_calc_sync()` used in prod
- [ ] Add fatal check for missing bankroll config in prod

### Pass 3: Spot and Fallbacks
- [ ] Gate composite spot fallback behind `enable_composite_spot_fallback()`
- [ ] Remove synthetic data from trading-critical paths
- [ ] Add explicit logging when fallbacks are used

### Pass 4: Legacy and Demo Code
- [ ] Add import guards for legacy directories
- [ ] Gate demo runners behind env checks
- [ ] Remove or gate "TEMPORARILY DISABLED" sections

### Pass 5: Asset Coverage
- [ ] Add per-asset health logging (BTC, ETH, SOL, XRP, DOGE)
- [ ] Add universe consistency checks for all 5 assets
- [ ] Add tests asserting all 5 assets present in prod mode

### Pass 6: Tests
- [ ] Add prod mode enforcement tests
- [ ] Add tests asserting fallbacks disabled in prod
- [ ] Add tests asserting legacy code unreachable in prod

---

## Success Criteria

After cleanup:

1. **Environment Explicit:** Every log line includes `env=prod/dev/staging`
2. **No Silent Fallbacks:** All fallbacks gated behind explicit env checks
3. **No Legacy Contamination:** Prod code cannot import from legacy directories
4. **Fatal Config Errors:** Missing prod config causes process exit, not warning
5. **Asset Coverage:** All 5 assets (BTC, ETH, SOL, XRP, DOGE) explicitly monitored
6. **CI Enforcement:** Prod pipeline fails if dev/legacy code detected

---

## Legacy/Demo/Fallback Code Path Tags

The following code paths have been identified and tagged for action:

### TAG: GATE_BEHIND_ENV_CHECK
**Description:** Code that should only run in DEV/STAGING, not PROD. Must be gated behind `if current_env() is not Env.PROD` or similar.

- `merid/prediction/agent_grid_15m.py` (lines 6058-6079): Composite spot fallback
- `merid/event_venues/kalshi/cfb_spot_proxy.py`: CFB spot proxy fallback
- `data/spot_composite.py`: Composite spot calculation (dev-only for 15m)
- `data/live_price_feed.py`: Composite spot integration

**Action:** Add `if enable_composite_spot_fallback():` guards around these paths.

### TAG: REMOVE_TEMPORARILY_DISABLED
**Description:** Code marked as "TEMPORARILY DISABLED" that should be either removed or finalized.

- `merid/settings.py` (bankroll config) - COMPLETED: Removed "temporarily disabled" comment
- `merid/prediction/alerts.py`
- `merid/startup_validations.py`
- `merid/prediction/sentiment_floor_tracker.py`
- `merid/prediction/risk/sentiment_vol_service.py`
- `merid/prediction/risk/_prediction_risk.py`
- `merid/prediction/kalshi_strike_calibrator.py`
- `merid/prediction/high_performance_calibration.py`
- `merid/prediction/dynamic_edge_calibrator.py`
- `merid/loop.py`
- `merid/event_venues/kalshi/fills_poller.py`
- `merid/event_venues/kalshi/ws.py`
- `merid/event_venues/kalshi/ws_bridge.py`

**Action:** Review each "TEMPORARILY DISABLED" section and either (a) remove if obsolete, (b) finalize for prod, or (c) gate behind env check.

### TAG: ARCHIVE_LEGACY
**Description:** Legacy code that should remain in archive but never be imported by prod code.

- `archive/legacy/` entire directory
- `trading_legacy/` directory
- `legacy/lanes/` directory
- `legacy/merid/agents/` directory

**Action:** Add import guards to prevent accidental imports from these directories in prod code.

### TAG: DEMO_ONLY
**Description:** Demo/test code that should never run in PROD.

- `scripts/kalshi_demo_runner.py`
- `core/demo_runner.py`
- `swarm/demo/` directory
- `scripts/kalshi_continuous_trader.py` (demo mode)

**Action:** Gate behind `if current_env() is Env.DEV` or move to separate devtools package.

### TAG: SYNTHETIC_DATA_ONLY
**Description:** Synthetic data generation that should never be used in PROD trading.

- Test fixtures with synthetic data
- Fallback data generation in various modules
- Neutral fallback implementations

**Action:** Gate behind `if enable_synthetic_data():` which returns `False` in PROD.

---

## Next Steps

1. Review this inventory with team
2. Prioritize cleanup passes based on risk
3. Implement Pass 1 (environment infrastructure) - COMPLETED
4. Add CI checks for static enforcement
5. Execute remaining passes in order
6. Verify with prod-like test run
