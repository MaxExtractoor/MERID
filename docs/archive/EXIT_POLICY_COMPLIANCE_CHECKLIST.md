# Exit Policy Compliance Checklist
## MERID 15M Kalshi Crypto Trading System

**Created:** 2026-07-06  
**Purpose:** Final checklist for "No Trade Without Exit" compliance.

---

## Overview

This checklist provides a comprehensive verification guide to ensure the MERID 15M Kalshi crypto trading system complies with the "No Trade Without Exit" invariant. Use this checklist before production deployment and after any changes to the exit policy pipeline.

---

## Phase 1: Invariant Verification

### Invariant #1: Risk Contract Linkage

**Location:** `merid/event_venues/kalshi/order_router.py:_validate_risk_contract_linkage()`

**Verification Steps:**
- [ ] Entry orders require `window_resolution_id`
- [ ] Entry orders require `exit_policy_id`
- [ ] Entry orders require `risk_tier`
- [ ] Entry orders require `max_hold_seconds`
- [ ] Exit orders require `exit_policy_id`
- [ ] Non-crypto markets are exempt from these requirements
- [ ] Order router calls `_validate_risk_contract_linkage()` before submission
- [ ] Orders missing required fields are rejected with clear error messages
- [ ] Test coverage for all validation scenarios

**Evidence:**
- Log entries showing rejected orders with missing fields
- Test results from `tests/test_risk_contract_linkage.py`

---

### Invariant #2: Exit Policy Resolution

**Location:** `merid/event_venues/kalshi/order_router.py:resolve_exit_policy()`

**Verification Steps:**
- [ ] `sl_cents` is computed from entry and SL prices (not hardcoded to 5)
- [ ] TP/SL values come from dynamic risk engine
- [ ] Trailing parameters come from profile config
- [ ] Time exit parameters come from profile config
- [ ] No hardcoded magic numbers in exit policy resolution
- [ ] Profile config is the single source of truth
- [ ] Fallback values match profile config

**Evidence:**
- Code review of `resolve_exit_policy()` function
- Profile YAML values match runtime behavior
- Test results from `tests/test_exit_policy_resolution.py`

---

### Invariant #3: Exit Metadata Attachment

**Location:** `merid/event_venues/kalshi/position_cache.py:register_tp_targets()`

**Verification Steps:**
- [ ] All fills register TP/SL targets before monitoring
- [ ] Positions without TP/SL are rejected or flagged as unhealthy
- [ ] No fallback values for missing TP/SL (strict enforcement)
- [ ] Unhealthy positions are tracked and logged
- [ ] Unhealthy positions are skipped in monitoring loop

**Evidence:**
- Log entries showing rejected fills without TP/SL
- Unhealthy position tracking logs
- Test results from position cache tests

---

### Invariant #4: Exit Intent Callback

**Location:** `merid/position_management/position_monitor.py:_emit_exit_intent()`

**Verification Steps:**
- [ ] All exit triggers use callback mechanism
- [ ] No direct `route_order_async()` calls from monitoring loops
- [ ] Staged exit logic is disabled in `position_cache.py`
- [ ] Callback is registered on startup
- [ ] Callback errors are logged and handled

**Evidence:**
- Code review of `_emit_exit_intent()` function
- Log entries showing callback invocations
- Test results from position monitor tests

---

### Invariant #5: Monitoring Loop Health

**Location:** `merid/event_venues/kalshi/position_cache.py:_monitor_positions_loop()`

**Verification Steps:**
- [ ] Monitoring loop is running on startup
- [ ] Loop tick interval is consistent (within 20% variance)
- [ ] Loop errors are logged with stack traces
- [ ] Health alerts are emitted on loop degradation
- [ ] Trading halt is triggered on persistent loop failures
- [ ] Loop uptime is tracked and reported

**Evidence:**
- Monitoring loop health metrics
- Health alert logs
- Trading halt logs (if triggered)
- Test results from chaos tests

---

### Invariant #6: Risk Guard Exit Policy Check

**Location:** `merid/event_venues/kalshi/order_gate.py:PreTradeGate.check()`

**Verification Steps:**
- [ ] Pre-trade gate validates exit policy metadata
- [ ] Entry orders require all risk contract fields
- [ ] Exit orders require `exit_policy_id`
- [ ] Orders without exit policy metadata are rejected
- [ ] Non-crypto markets are exempt from this check

**Evidence:**
- Code review of `PreTradeGate.check()` function
- Log entries showing gate rejections
- Test results from pre-trade gate tests

---

### Invariant #7: No Magic Numbers

**Location:** All exit-related code

**Verification Steps:**
- [ ] No hardcoded `sl_cents=5` in `order_router.py`
- [ ] No hardcoded fallback SL in `kalshi_api.py`
- [ ] No hardcoded policy resolution in `main_15m_lean.py`
- [ ] No hardcoded fallback SL in `position_cache.py`
- [ ] No hardcoded `sl_cents_map` in `dynamic_risk.py`
- [ ] All exit parameters come from config or are computed
- [ ] Profile YAML is the single source of truth

**Evidence:**
- Code review of all exit-related files
- Grep search for hardcoded values
- Profile YAML values match runtime behavior

---

### Invariant #8: Exit Trigger Precedence

**Location:** `merid/position_management/position_monitor.py:_check_position()`

**Verification Steps:**
- [ ] EXTREME_PROFIT fires first (highest priority)
- [ ] DYNAMIC_TAKE_PROFIT fires second
- [ ] RATCHET_PROFIT_FLOOR fires third
- [ ] STOP_LOSS fires fourth
- [ ] TAKE_PROFIT fires fifth
- [ ] BREAK_EVEN fires sixth (non-terminal)
- [ ] SCALE_OUT fires seventh (non-terminal)
- [ ] TRAILING fires eighth
- [ ] ExitPolicy fires ninth (lowest priority)

**Evidence:**
- Code review of `_check_position()` function
- Test results from exit trigger precedence tests

---

### Invariant #9: Position Closure Tracking

**Location:** `merid/event_venues/kalshi/position_cache.py:close_position()`

**Verification Steps:**
- [ ] Position is removed from position cache
- [ ] Position is removed from PositionMonitor
- [ ] Window exposure is decremented in risk envelope
- [ ] Per-asset notional is decremented in KalshiRiskManager
- [ ] All four tracking mechanisms are implemented
- [ ] Closure tracking is logged

**Evidence:**
- Log entries showing position closure tracking
- Test results from position closure tests

---

### Invariant #10: Test Logic Bypass Prevention

**Location:** All test files

**Verification Steps:**
- [ ] Tests that bypass invariants have `@pytest.mark.bypass_invariant` marker
- [ ] No unmarked bypasses in test code
- [ ] CI check warns about unmarked bypasses
- [ ] Bypass tests are reviewed and approved

**Evidence:**
- Grep search for unmarked bypasses
- Test marker review
- CI configuration for bypass detection

---

## Phase 2: Code Changes Verification

### P0 Changes (Critical)

- [ ] #1: Remove hardcoded `sl_cents=5` in `order_router.py`
- [ ] #2: Remove hardcoded fallback SL in `kalshi_api.py`
- [ ] #3: Remove hardcoded policy resolution in `main_15m_lean.py`
- [ ] #4: Remove hardcoded fallback SL in `position_cache.py`
- [ ] #5: Add exit policy validation to `PreTradeGate.check()`
- [ ] #6: Refactor `sl_cents_map` in `dynamic_risk.py` to use config

### P1 Changes (High)

- [ ] #7: Add monitoring loop health alerts
- [ ] #8: Add unhealthy position tracking

### P2 Changes (Medium)

- [ ] #9: Add bypass invariant markers to tests
- [ ] #10: Add exit policy compliance test

**Evidence:**
- Git commits for all changes
- Code review approval
- Test results for all changes

---

## Phase 3: Test Verification

### Unit Tests

- [ ] `tests/test_exit_policy_resolution.py` - All tests passing
- [ ] `tests/test_risk_contract_linkage.py` - All tests passing
- [ ] `tests/test_position_monitor.py` - All tests passing
- [ ] `tests/test_pre_trade_gate.py` - All tests passing

### Integration Tests

- [ ] `tests/integration/test_exit_policy_flow.py` - All tests passing

### Chaos Tests

- [ ] `tests/chaos/test_exit_policy_resilience.py` - All tests passing

### Performance Tests

- [ ] `tests/performance/test_monitoring_loop_performance.py` - All tests passing

### Test Coverage

- [ ] Exit policy code coverage ≥ 90%
- [ ] No coverage regression from baseline

**Evidence:**
- Test execution reports
- Coverage reports
- CI/CD test results

---

## Phase 4: Telemetry Verification

### Metrics

- [ ] Exit policy resolution metrics are collected
- [ ] Risk contract validation metrics are collected
- [ ] Position monitoring metrics are collected
- [ ] Exit trigger metrics are collected
- [ ] Unhealthy position metrics are collected
- [ ] Monitoring loop health metrics are collected

### Alerting

- [ ] Critical alerts configured (P0)
- [ ] Warning alerts configured (P1)
- [ ] Alert thresholds are appropriate
- [ ] Alert notifications are working

### Logging

- [ ] Critical logs are enabled
- [ ] Debug logs are enabled for troubleshooting
- [ ] Log format is consistent
- [ ] Log retention is configured

### Dashboards

- [ ] Exit policy dashboard is created
- [ ] Dashboard shows all required metrics
- [ ] Dashboard is accessible to ops team

**Evidence:**
- Metrics registry output
- Alert configuration files
- Log samples
- Dashboard screenshots

---

## Phase 5: Configuration Verification

### Profile YAML

- [ ] `config/profiles/kalshi_crypto_15m_v2.yaml` is up to date
- [ ] All exit policy parameters are defined
- [ ] No stale comments
- [ ] Values match risk envelope defaults
- [ ] Values match profile adapter defaults

### Risk Envelope

- [ ] `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py` defaults match profile
- [ ] Window-based risk tracking is implemented
- [ ] Per-agent window limit (3%) is enforced
- [ ] Total venue window limit (5%) is enforced

### Profile Adapter

- [ ] `merid/risk/profiles/crypto_15m_profile.py` defaults match profile
- [ ] All exit policy fields are mapped
- [ ] Fallback values match profile config

**Evidence:**
- Config file review
- Code review of risk envelope and profile adapter
- Test results from config tests

---

## Phase 6: Runtime Verification

### Startup Verification

- [ ] System starts without errors
- [ ] Position cache monitoring loop starts
- [ ] Position monitor is initialized
- [ ] Exit intent callback is registered
- [ ] No startup warnings related to exit policy

### Order Flow Verification

- [ ] Entry orders with exit policy are accepted
- [ ] Entry orders without exit policy are rejected
- [ ] Exit orders with exit_policy_id are accepted
- [ ] Exit orders without exit_policy_id are rejected
- [ ] TP/SL targets are registered on fill
- [ ] Positions are added to monitoring loop

### Exit Trigger Verification

- [ ] EXTREME_PROFIT trigger fires at 99c
- [ ] STOP_LOSS trigger fires at SL level
- [ ] TAKE_PROFIT trigger fires at TP level
- [ ] TRAILING trigger activates after min profit
- [ ] Exit intents are emitted correctly
- [ ] Exit orders are submitted correctly

### Monitoring Loop Verification

- [ ] Loop is running and healthy
- [ ] Loop tick interval is consistent
- [ ] Positions are checked on each tick
- [ ] Unhealthy positions are skipped
- [ ] Health alerts are emitted on issues

**Evidence:**
- Startup logs
- Order flow logs
- Exit trigger logs
- Monitoring loop logs
- Runtime metrics

---

## Phase 7: Documentation Verification

### Code Documentation

- [ ] All exit policy functions have docstrings
- [ ] Invariants are documented in code comments
- [ ] Magic number removal is documented
- [ ] Fallback behavior is documented

### Architecture Documentation

- [ ] `docs/EXIT_POLICY_INVARIANT_DEFINITION.md` is up to date
- [ ] `docs/EXIT_POLICY_CODE_CHANGES.md` is up to date
- [ ] `docs/EXIT_POLICY_TEST_TELEMETRY.md` is up to date
- [ ] `docs/EXIT_POLICY_COMPLIANCE_CHECKLIST.md` is up to date

### Runbook Documentation

- [ ] Exit policy troubleshooting guide exists
- [ ] Monitoring loop failure runbook exists
- [ ] Unhealthy position handling runbook exists

**Evidence:**
- Documentation review
- Runbook validation

---

## Phase 8: Security Verification

### Access Control

- [ ] Exit policy config files have appropriate permissions
- [ ] Risk envelope config files have appropriate permissions
- [ ] Profile YAML has appropriate permissions

### Audit Trail

- [ ] All exit policy changes are logged
- [ ] All exit triggers are logged
- [ ] All monitoring loop events are logged
- [ ] All config changes are logged

**Evidence:**
- File permission review
- Audit log review

---

## Phase 9: Disaster Recovery Verification

### Backup and Restore

- [ ] Profile YAML is backed up
- [ ] Risk envelope config is backed up
- [ ] Exit policy logs are backed up
- [ ] Restore procedure is documented

### Failure Scenarios

- [ ] Monitoring loop failure recovery is tested
- [ ] Config load failure recovery is tested
- [ ] Callback failure recovery is tested
- [ ] Position cache corruption recovery is tested

**Evidence:**
- Backup verification
- Disaster recovery test results

---

## Phase 10: Sign-off

### Engineering Sign-off

- [ ] Lead engineer review complete
- [ ] Code review approved
- [ ] Test results approved
- [ ] Documentation approved

### Operations Sign-off

- [ ] Monitoring configuration approved
- [ ] Alerting configuration approved
- [ ] Dashboard configuration approved
- [ ] Runbook review complete

### Security Sign-off

- [ ] Access control review complete
- [ ] Audit trail review complete
- [ ] Security assessment complete

### Management Sign-off

- [ ] Risk assessment approved
- [ ] Deployment plan approved
- [ ] Rollback plan approved

**Evidence:**
- Sign-off signatures
- Approval emails
- Meeting minutes

---

## Compliance Summary

**Total Checklist Items:** 100+  
**Items Completed:** ___  
**Items Pending:** ___  
**Compliance Percentage:** ___%

**Overall Status:**
- [ ] COMPLIANT - Ready for production deployment
- [ ] PARTIALLY COMPLIANT - Address pending items before deployment
- [ ] NON-COMPLIANT - Critical issues must be resolved

**Blockers:**
- List any critical blockers that must be resolved before deployment

**Recommendations:**
- List any recommendations for improvement

---

## Next Steps

After completing this checklist:
1. Address any pending items
2. Resolve any blockers
3. Implement recommendations
4. Schedule deployment
5. Monitor post-deployment metrics

---

## Appendix: Reference Documents

- `docs/EXIT_POLICY_INVARIANT_DEFINITION.md` - Invariant definitions
- `docs/EXIT_POLICY_CODE_CHANGES.md` - Code and config changes
- `docs/EXIT_POLICY_TEST_TELEMETRY.md` - Test and telemetry plan
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Profile configuration
- `merid/event_venues/kalshi/order_router.py` - Order routing logic
- `merid/position_management/position_monitor.py` - Position monitoring logic
- `merid/event_venues/kalshi/position_cache.py` - Position cache logic
- `merid/event_venues/kalshi/order_gate.py` - Pre-trade gate logic
