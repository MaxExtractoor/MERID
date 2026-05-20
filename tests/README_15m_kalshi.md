# Kalshi 15-Minute Crypto Test Documentation

## Overview

This document describes the test suite for Kalshi 15-minute crypto trading (BTC/ETH/SOL/XRP/DOGE). The 15m Kalshi path is autonomous and guarded against regression by startup validations and smoke tests.

## Authoritative Tests (Must Pass for Deployment)

### Smoke Tests: `tests/event_venues/kalshi/test_15m_smoke.py`

**Purpose:** High-value, fast-running tests that validate the 15m Kalshi path is correctly wired end-to-end.

**Tests:**
- `Test15mAgentLoadSanity::test_only_5_kalshi_15m_agents_active` - Asserts exactly 5 Kalshi 15m crypto agents are active
- `Test15mAgentLoadSanity::test_agent_names_match_expected` - Asserts agent names match BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
- `Test15mAgentLoadSanity::test_each_agent_has_15m_series_tickers` - Asserts each agent has series_tickers set to 15M series (KXBTC15M, etc.)
- `Test15mAgentLoadSanity::test_no_extra_agents_active` - Asserts no extra agents (HOURLY, WEEKLY, etc.) are active
- `Test15mCatalogAgentWiring::test_catalog_contains_all_5_series` - Asserts catalog contains all 5 expected 15m series
- `Test15mCatalogAgentWiring::test_catalog_contains_exactly_5_markets` - Asserts catalog contains exactly 5 markets (one per asset)
- `Test15mCatalogAgentWiring::test_each_market_has_correct_series_ticker` - Asserts each market has correct series_ticker field
- `Test15mCatalogAgentWiring::test_agent_sees_its_markets_in_window` - Asserts each agent sees its markets in 2-30 minute window
- `Test15mCatalogAgentWiring::test_markets_outside_window_excluded` - Asserts markets outside 2-30 minute window are excluded
- `Test15mRiskExecutionDryRun::test_trade_request_generated_for_positive_edge` - Asserts trade request generated when edge is above threshold
- `Test15mRiskExecutionDryRun::test_trade_passes_risk_under_profile_config` - Asserts trade passes risk checks with profile config
- `Test15mRiskExecutionDryRun::test_trade_has_non_zero_risk_limits` - Asserts profile config provides non-zero risk limits
- `Test15mRiskExecutionDryRun::test_trade_reaches_execution_gate` - Asserts trade reaches execution gate and would route to Kalshi

**Status:** 13/13 passing ✓

**CI Requirement:** These tests must pass before any deployment to production.

## Startup Validations: `merid/startup_validations.py`

**Purpose:** Startup guardrails that validate the 15m Kalshi configuration before the system is considered healthy.

**Validations:**
- `validate_profile_combination()` - Checks allowed MERID_PM_PROFILE + MERID_PROFILE combinations
- `check_single_risk_config()` - Ensures only venue KalshiRiskConfig is used (not PM version)
- `validate_profile_backtest_eligibility()` - Cross-validates profile config meets backtest requirements
- `validate_15m_series_availability()` - Verifies Kalshi API has active 15m markets for all 5 series

**Status:** All validations implemented and wired into `validate_all()`.

**CI Requirement:** `validate_all()` must run during startup in dev/stage environments.

## Test Fixtures: `tests/fixtures/kalshi_15m_markets.py`

**Purpose:** Synthetic 15m market fixtures for BTC/ETH/SOL/XRP/DOGE used in tests.

**Exports:**
- `KalshiMarketFixture` - Dataclass for synthetic market
- `get_15m_market_fixtures()` - Returns 5 synthetic markets (one per asset)
- `EXPECTED_15M_SERIES` - List of expected 15M series tickers
- `EXPECTED_15M_AGENTS` - List of expected 15M agent names
- `SERIES_TO_AGENT` - Mapping of series ticker to agent name
- `AGENT_TO_SERIES` - Mapping of agent name to series tickers

## Legacy Tests (Not in 15m Kalshi Gate)

### Micro-Scalping Tests: `tests/test_micro_scalping_44_bankroll.py`

**Status:** Known-failing legacy - config drift from current 15m prod profile.

**Issues:**
- `test_risk_engine_min_edge_aligned_with_strategy` - Config value mismatch (expects 0.04, actual 0.05)
- `test_fee_edge_multipliers_not_blocking_micro_scalping` - Config value mismatch (expects ≤1.5, actual 2.0)
- `test_strike_selector_uses_correct_timeframe` - Config value mismatch (expects ≥0.35, actual 0.18)

**Resolution:** These tests are strategy-specific and not aligned with the current `kalshi_crypto_15m_v2` production profile. They should be:
1. Marked with `@pytest.mark.xfail(reason="Micro scalping config drift; not aligned with current 15m prod profile")`
2. Or moved to `tests_legacy/` directory excluded from CI's "must pass" set
3. Addressed under a separate workstream when micro-scalping is actively worked on again

**Ticket:** TBD - Create ticket for micro-scalping config tuning when needed

### Fills Ledger Tests: `tests/test_fills_ledger_risk_separation.py`

**Status:** Known-failing legacy - event loop closure issues.

**Issues:**
- Event loop closure errors in async fixture teardown
- Not related to 15m Kalshi structural changes

**Resolution:** These tests require async fixture cleanup fixes. They are not blocking 15m Kalshi deployment as the fills ledger logic is independent of the 15m series ticker changes.

**Ticket:** TBD - Create ticket for async fixture cleanup

## Series Ticker Migration

**Base Ticker → 15M Ticker:**
- KXBTC → KXBTC15M
- KXETH → KXETH15M
- KXSOL → KXSOL15M
- KXXRP → KXXRP15M
- KXDOGE → KXDOGE15M

**Agent Mapping:**
- BTC_15M → KXBTC15M
- ETH_15M → KXETH15M
- SOL_15M → KXSOL15M
- XRP_15M → KXXRP15M
- DOGE_15M → KXDOGE15M

## Risk Config Migration

**Deprecated:** `merid.prediction.risk.kalshi_risk_engine.KalshiRiskConfig` (PM-specific config)

**Canonical:** `merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig` (venue config)

**Note:** The PM config is kept for backward compatibility and test usage. A deprecation warning is emitted when imported. Live code paths must use the venue config.

## Profile Configuration

**Production Profile:** `kalshi_crypto_15m_v2`

**Profile Config File:** `config/profiles/env.prod.kalshi-crypto-15m.yaml`

**Risk Config:** Single source of truth via profile YAML, not via `kalshi_15m_crypto_config.py` constants

## CI Requirements

For any deployment affecting Kalshi 15m crypto:

1. Run startup validations:
   ```bash
   python -c "from merid.startup_validations import validate_all; validate_all()"
   ```

2. Run smoke tests:
   ```bash
   pytest tests/event_venues/kalshi/test_15m_smoke.py -v
   ```

Both must pass before deployment.

## Future Work (Low Priority)

- TEST1A-C: Prune/archive tests using base tickers (KXBTC, etc.) without 15M suffix
- TEST1B: Prune/archive tests using legacy profiles (kalshi_crypto_live, kalshi_crypto_paper)
- TEST1C: Prune/archive tests expecting deprecated PM KalshiRiskConfig as canonical

These are opportunistic cleanup tasks to prevent drift, but not required for the 15m Kalshi path to be production-ready.
