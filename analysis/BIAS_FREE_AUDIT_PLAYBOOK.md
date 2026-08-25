# Bias-Free Audit Playbook

**Version**: 1.0  
**Date**: 2026-07-23  
**Scope**: End-to-end bias-free validation across upstream, midstream, downstream, and cross-cutting layers

---

## Overview

This playbook enumerates each upstream/midstream/downstream/cross-cutting invariant, the corresponding tests, and how to interpret failures. It serves as the authoritative guide for maintaining bias-free behavior in MERID.

---

## Layer 1: Upstream (Data, Profiles, Feeds)

### Invariant 1.1: Asset Universe is Rule-Driven

**Description**: Asset inclusion/exclusion must be rule-driven (venue flags, liquidity minima) rather than legacy handpicks. No survivorship or selection bias.

**Test**: `tests/upstream/test_asset_universe_bias.py::TestAssetUniverseBias`

**Checks**:
- `test_assets_meeting_liquidity_rules_included`: BTC, ETH, SOL, XRP, DOGE are all included
- `test_no_hardcoded_asset_exclusions`: No hardcoded asset lists in code
- `test_crypto_stack_completeness`: All 5 crypto assets present
- `test_excluded_asset_logging`: Excluded assets logged with reasons

**Failure Interpretation**:
- **Critical**: If any of the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) are missing
- **High**: If assets are excluded despite meeting criteria
- **Medium**: If excluded assets are not logged

**Remediation**:
- Critical: Restore missing asset to universe
- High: Review exclusion logic, ensure rule-based
- Medium: Add logging for excluded assets

---

### Invariant 1.2: Price Validation is Dynamic and Enabled

**Description**: Price validation must use rolling statistics and dynamic sigma bands, and must never be bypassed for production profile.

**Test**: `tests/upstream/test_price_validation_dynamic.py::TestPriceValidationDynamic`

**Checks**:
- `test_price_validation_enabled_for_production`: Validation enabled for kalshi_crypto_15m_v2
- `test_reasonable_price_moves_pass`: Normal volatility passes validation
- `test_obvious_outliers_rejected`: Extreme outliers rejected and counted
- `test_rolling_stats_tracker_integration`: Rolling stats used for validation
- `test_validation_failure_handling`: Failures logged and handled appropriately

**Failure Interpretation**:
- **Critical**: Price validation disabled for production profile
- **High**: False positives on legitimate price moves
- **Medium**: Outliers not rejected or not counted

**Remediation**:
- Critical: Re-enable price validation for production
- High: Adjust sigma bands to reduce false positives
- Medium: Fix outlier detection and counting

---

### Invariant 1.3: Synthetic Spreads are Tagged and Isolated

**Description**: Synthetic spreads must be tagged and never used for trading decisions. Only allowed for UI or simulation.

**Test**: `tests/upstream/test_synthetic_spreads_flags.py::TestSyntheticSpreadsFlags`

**Checks**:
- `test_synthetic_spreads_tagged`: spread_is_synthetic flag set
- `test_synthetic_spreads_not_used_for_trading`: Trading logic rejects synthetic spreads
- `test_synthetic_spreads_ui_only`: Synthetic spreads only in UI/simulation paths

**Failure Interpretation**:
- **Critical**: Synthetic spreads used for trading decisions
- **High**: Synthetic spreads not tagged
- **Medium**: Synthetic spreads in production paths

**Remediation**:
- Critical: Block synthetic spreads from trading logic
- High: Add spread_is_synthetic flag
- Medium: Remove synthetic spreads from production paths

---

## Layer 2: Midstream (Prediction, Correlations, Signals, Liquidity)

### Invariant 2.1: Correlations are Dynamic and Per-Asset

**Description**: Correlation matrix must adjust separately per asset based on rolling windows, not static hardcoded values.

**Test**: `tests/midstream/test_multi_asset_regime.py::TestMultiAssetRegime`

**Checks**:
- `test_correlation_matrix_adjusts_per_asset`: Each pair correlation updates independently
- `test_signal_quality_adjusts_per_asset`: Each asset quality updates independently
- `test_sizing_follows_new_regime`: Sizing uses dynamic values, not static metadata
- `test_different_regime_patterns`: Heterogeneous regime changes handled correctly

**Failure Interpretation**:
- **Critical**: Static correlations still used
- **High**: Correlations don't adapt to regime changes
- **Medium**: Cross-contamination between asset correlations

**Remediation**:
- Critical: Wire rolling correlation calculator into production
- High: Verify correlation updates trigger on regime changes
- Medium: Fix cross-contamination in correlation logic

---

### Invariant 2.2: Liquidity Thresholds are Adaptive

**Description**: Liquidity thresholds must adapt to recent depth percentiles and time-of-day, not static absolute values.

**Test**: `tests/midstream/test_liquidity_edge_cases.py::TestLiquidityEdgeCases`

**Checks**:
- `test_high_volume_window_not_killed`: High-volume windows not blocked
- `test_dead_zone_not_over_traded`: Low-volume windows not over-traded
- `test_time_of_day_adjustments`: Time-of-day multipliers work correctly
- `test_percentile_tuning`: Percentile-based thresholds avoid under/over-trading

**Failure Interpretation**:
- **Critical**: Static thresholds still used
- **High**: High-volume windows blocked (under-trading)
- **Medium**: Dead zones over-traded

**Remediation**:
- Critical: Wire adaptive liquidity calculator into production
- High: Adjust percentile tuning to avoid under-trading
- Medium: Fix time-of-day multipliers

---

### Invariant 2.3: No Look-Ahead Bias in Midstream

**Description**: Midstream components must use only past data in rolling windows. Future data must never influence decisions at time t.

**Test**: `tests/midstream/test_no_lookahead_midstream.py::TestNoLookaheadMidstream`

**Checks**:
- `test_correlation_uses_only_past_data`: Correlation uses only past prices
- `test_signal_quality_uses_only_past_outcomes`: Quality uses only past outcomes
- `test_liquidity_uses_only_past_depth`: Liquidity uses only past depth
- `test_temporal_integrity_across_components`: All components maintain temporal integrity

**Failure Interpretation**:
- **Critical**: Future data used in any midstream decision
- **High**: Rolling windows not pruning old data
- **Medium**: Temporal integrity violations

**Remediation**:
- Critical: Fix data leakage, ensure strict temporal separation
- High: Verify rolling window pruning logic
- Medium: Add temporal integrity checks

---

## Layer 3: Downstream (Execution, Fills, PnL)

### Invariant 3.1: Prediction Publisher Uses Real Data

**Description**: Prediction publisher must use only real fills, positions, and market state. Zero mock/synthetic branches in production paths.

**Test**: `tests/downstream/test_prediction_publisher_real_data.py::TestPredictionPublisherRealData`

**Checks**:
- `test_publisher_uses_real_fills_ledger`: PnL matches ledger exactly
- `test_publisher_uses_real_market_state`: Prices from market_state, not mock
- `test_publisher_uses_real_signal_history`: Confidence from signal history, not mock
- `test_no_mock_data_in_production_paths`: No random.uniform() in production API

**Failure Interpretation**:
- **Critical**: Mock data in production API responses
- **High**: PnL/prices/confidence don't match real sources
- **Medium**: Mock data not feature-flagged

**Remediation**:
- Critical: Remove all mock data from production API
- High: Wire real data sources to publisher
- Medium: Add feature flags for mock data

---

### Invariant 3.2: Health Checks Flag Missing Data

**Description**: Health checks must flag missing data sources (fills ledger, market state, signal history). Trading must halt or go into safe mode.

**Test**: `tests/downstream/test_health_checks_failures.py::TestHealthChecksFailures`

**Checks**:
- `test_missing_fills_ledger_flagged`: Missing fills ledger flagged
- `test_missing_market_state_flagged`: Missing market state flagged
- `test_missing_signal_history_flagged`: Missing signal history flagged
- `test_trading_halt_on_missing_data`: Trading halts on missing data
- `test_degraded_dashboards_on_missing_data`: Dashboards show degraded status

**Failure Interpretation**:
- **Critical**: Trading continues with missing data
- **High**: Health checks don't flag missing data
- **Medium**: Dashboards don't show degraded status

**Remediation**:
- Critical: Implement trading halt on missing data
- High: Add health checks for all data sources
- Medium: Add degraded status to dashboards

---

### Invariant 3.3: PnL and Metrics Match Ledger

**Description**: Downstream reports must match the ledger exactly. No theoretical fills, assumptions, or static fees.

**Test**: `tests/downstream/test_pnl_and_metrics_consistency.py::TestPnlAndMetricsConsistency`

**Checks**:
- `test_pnl_matches_ledger`: PnL matches ledger exactly
- `test_hit_rate_matches_ledger`: Hit rate matches ledger outcomes
- `test_edge_metrics_match_ledger`: Edge metrics match ledger calculations
- `test_no_theoretical_fills`: No theoretical fills in metrics
- `test_static_fees_not_used`: Fees computed from actual fills

**Failure Interpretation**:
- **Critical**: Theoretical fills or assumptions in metrics
- **High**: PnL/hit rate/edge don't match ledger
- **Medium**: Static fee assumptions used

**Remediation**:
- Critical: Remove all theoretical calculations
- High: Fix metric calculations to match ledger
- Medium: Use actual fee data from fills

---

## Layer 4: Cross-Cutting (Seeds, Configs, Walk-Forward)

### Invariant 4.1: Seed Reproducibility

**Description**: Same seeds must produce identical behavior. Different seeds must shift only stochastic pieces. Seed history must be logged.

**Test**: `tests/crosscutting/test_seed_reproducibility.py::TestSeedReproducibility`

**Checks**:
- `test_same_seed_identical_behavior`: Same seed produces identical results
- `test_different_seed_shifts_stochastic_only`: Different seeds change only stochastic components
- `test_seed_manager_integration`: SeedManager integrated into all paths
- `test_seed_history_api`: Seed history exposed via API

**Failure Interpretation**:
- **Critical**: Non-deterministic behavior with same seed
- **High**: Seed changes affect deterministic components
- **Medium**: Seed history not logged or exposed

**Remediation**:
- Critical: Fix non-determinism, ensure seed control
- High: Isolate seed changes to stochastic components
- Medium: Add seed history logging and API

---

### Invariant 4.2: Walk-Forward Temporal Integrity

**Description**: Train/test windows and embargo days must be strictly respected. Future data must never be touched during training. Overfitting must be detected.

**Test**: `tests/crosscutting/test_walk_forward_temporal_integrity.py::TestWalkForwardTemporalIntegrity`

**Checks**:
- `test_train_test_windows_respected`: Train/test windows strictly separated
- `test_embargo_days_respected`: Embargo period respected
- `test_future_data_never_touched_during_training`: Future data excluded from training
- `test_overfitting_flags_on_curve_fit`: Overfitting flags flip on curve-fit
- `test_production_validator_scheduled`: Production validator runs on schedule

**Failure Interpretation**:
- **Critical**: Future data used in training
- **High**: Train/test windows overlap
- **Medium**: Overfitting not detected

**Remediation**:
- Critical: Fix data leakage, ensure strict temporal separation
- High: Fix train/test window logic
- Medium: Implement overfitting detection

---

### Invariant 4.3: Config Logging on Startup

**Description**: Every major component must log config and version information on startup (correlation window, signal quality window, liquidity percentile, profile name, model code hash).

**Test**: `tests/crosscutting/test_config_logging.py::TestConfigLogging`

**Checks**:
- `test_correlation_window_logged`: Correlation window length logged
- `test_signal_quality_window_logged`: Signal quality window logged
- `test_liquidity_percentile_logged`: Liquidity percentile logged
- `test_profile_name_logged`: Profile name and version logged
- `test_model_code_hash_logged`: Model code hash logged
- `test_all_components_log_config`: All components log config

**Failure Interpretation**:
- **Critical**: Major components don't log config
- **High**: Critical parameters not logged
- **Medium**: Version information missing

**Remediation**:
- Critical: Add config logging to all major components
- High: Ensure critical parameters are logged
- Medium: Add version information to logs

---

## CI/CD Integration

### Test Markers

Use pytest markers to run layer-specific tests:

```bash
# Run all upstream tests
pytest tests/upstream -m upstream

# Run all midstream tests
pytest tests/midstream -m midstream

# Run all downstream tests
pytest tests/downstream -m downstream

# Run all cross-cutting tests
pytest tests/crosscutting -m crosscutting

# Run all bias-free tests
pytest tests/upstream tests/midstream tests/downstream tests/crosscutting -m "upstream or midstream or downstream or crosscutting"

# Run production audit tests
pytest -m production_audit
```

### Branch Policy

Any change touching prediction, feeds, or execution must add or update at least one test in the relevant suite (upstream/midstream/downstream/crosscutting).

### CI Matrix

Run all test suites for every PR and before any production deployment:

```yaml
# Example CI configuration
test_matrix:
  - name: Upstream bias-free tests
    command: pytest tests/upstream -m upstream -v
    
  - name: Midstream bias-free tests
    command: pytest tests/midstream -m midstream -v
    
  - name: Downstream bias-free tests
    command: pytest tests/downstream -m downstream -v
    
  - name: Cross-cutting bias-free tests
    command: pytest tests/crosscutting -m crosscutting -v
    
  - name: Production audit tests
    command: pytest -m production_audit -v
    
  - name: Bias-free harness
    command: pytest tests/test_bias_free_by_construction.py -v
```

### Feature Flags and Canaries

New dynamic features (alternative correlation windows, liquidity percentiles) go in behind flags. The harness + CI must show no degradation before flipping them on for live agents.

---

## Failure Interpretation Guide

### Critical Failures

**Definition**: Violations that directly compromise bias-free behavior or data integrity.

**Examples**:
- Mock data in production API
- Future data used in decisions
- Price validation disabled for production
- Static correlations/quality/liquidity still used
- Trading continues with missing data

**Action**: Block deployment, fix immediately, re-run full test suite.

### High Failures

**Definition**: Violations that introduce bias or risk but don't directly compromise data integrity.

**Examples**:
- False positives in price validation
- Correlations don't adapt to regime changes
- High-volume windows blocked (under-trading)
- Health checks don't flag missing data
- PnL/hit rate/edge don't match ledger

**Action**: Fix before next deployment, monitor for regressions.

### Medium Failures

**Definition**: Violations that affect observability or documentation but don't directly introduce bias.

**Examples**:
- Excluded assets not logged
- Outliers not counted
- Synthetic spreads not tagged
- Seed history not logged
- Config not logged on startup

**Action**: Fix in next sprint, add to backlog.

---

## Test Implementation Status

### Upstream Layer
- [ ] test_asset_universe_bias.py (stubbed, needs implementation)
- [ ] test_price_validation_dynamic.py (stubbed, needs implementation)
- [ ] test_synthetic_spreads_flags.py (stubbed, needs implementation)

### Midstream Layer
- [ ] test_multi_asset_regime.py (stubbed, needs implementation)
- [ ] test_liquidity_edge_cases.py (stubbed, needs implementation)
- [ ] test_no_lookahead_midstream.py (stubbed, needs implementation)

### Downstream Layer
- [ ] test_prediction_publisher_real_data.py (stubbed, needs implementation)
- [ ] test_health_checks_failures.py (stubbed, needs implementation)
- [ ] test_pnl_and_metrics_consistency.py (stubbed, needs implementation)

### Cross-Cutting Layer
- [ ] test_seed_reproducibility.py (stubbed, needs implementation)
- [ ] test_walk_forward_temporal_integrity.py (stubbed, needs implementation)
- [ ] test_config_logging.py (stubbed, needs implementation)

### Bias-Free Harness
- [x] test_bias_free_by_construction.py (fully implemented and passing)

---

## Next Steps

1. **Implement stubbed tests**: Replace pytest.skip() with actual test implementations
2. **Wire dynamic components**: Integrate rolling correlation, signal quality, adaptive liquidity into production
3. **Remove mock data**: Eliminate all mock/synthetic data from production paths
4. **Add health checks**: Implement data source health checks and trading halt logic
5. **Implement SeedManager**: Add seed management to all ML paths
6. **Integrate walk-forward**: Add production validator as scheduled job
7. **Add config logging**: Ensure all components log config on startup
8. **Update CI**: Add layer-specific test runs to CI matrix
9. **Run shadow mode**: Validate dynamic components with live data before full deployment
10. **Monitor**: Add new metrics and alerts for dynamic components

---

**Playbook Version**: 1.0  
**Last Updated**: 2026-07-23  
**Maintainer**: MERID Team
