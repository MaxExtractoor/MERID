# Hedging System Audit Checklist
## MERID 15M Kalshi Crypto Trading System

**Created:** 2026-07-07  
**Purpose:** Comprehensive verification guide for hedging system compliance and risk guard integrity.

---

## Overview

This checklist provides a comprehensive verification guide to ensure the MERID 15M Kalshi crypto trading system's hedging components comply with risk guard requirements and best practices. Use this checklist after any changes to hedging configuration, logic, or integration.

---

## Phase 1: Offset Hedging Verification

### Offset Hedging Status

**Location:** `config/profiles/kalshi_crypto_15m_v2.yaml`

**Verification Steps:**
- [ ] Profile YAML has `offset_hedging.enabled: false` for crypto
- [ ] Profile YAML has `offset_hedging.hedge_ratio: 0.30` (if enabled)
- [ ] Profile comment explains why offset hedging is disabled for crypto
- [ ] No code path attempts offset hedging for crypto 15m
- [ ] Offset hedging disable decision is documented in architecture doc

**Evidence:**
- Profile YAML review
- Grep search for offset hedging usage in 15m path
- Architecture documentation review

---

### Profile Adapter Mapping

**Location:** `merid/risk/profiles/crypto_15m_profile.py`

**Verification Steps:**
- [ ] Profile adapter correctly maps `offset_hedging_enabled` from YAML
- [ ] Profile adapter default value matches YAML value (False)
- [ ] No hardcoded override of offset hedging flag
- [ ] Profile adapter logs offset hedging status on load

**Evidence:**
- Code review of profile adapter
- Test results from profile adapter tests
- Log entries showing offset hedging status

---

### Risk Envelope Integration

**Location:** `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Verification Steps:**
- [ ] Risk envelope does not use offset hedging in calculations
- [ ] Risk envelope enforces window-based limits independently
- [ ] No hedge ratio applied to position sizing
- [ ] Window-based risk tracking works without offset hedging

**Evidence:**
- Code review of risk envelope
- Test results from risk envelope tests
- Window limit enforcement logs

---

### Unified Sizing Compliance

**Location:** `merid/prediction/unified_sizing.py`

**Verification Steps:**
- [ ] Unified sizing does not incorporate hedge ratios
- [ ] Position sizing based solely on risk percentages from profile
- [ ] No scaling multipliers interfere with window limits
- [ ] Dynamic, regime, and TTE sizing are disabled

**Evidence:**
- Code review of unified sizing
- Test results from sizing tests
- Position size calculation logs

---

## Phase 2: CryptoHedgeEngine Verification

### Hedge Engine Configuration

**Location:** `config/kalshi_crypto_hedging.yaml`

**Verification Steps:**
- [ ] Hedge config YAML exists and is valid
- [ ] `hedging.enabled` matches operational intent
- [ ] `use_cross_asset_hedging` is false (same-asset only)
- [ ] Asset slices are defined for all 5 assets (BTC, ETH, SOL, XRP, DOGE)
- [ ] Timeframe rules are defined for 15m
- [ ] Cross-asset hedging is disabled
- [ ] Take profit configuration is defined per asset
- [ ] Auto-exit configuration is enabled

**Evidence:**
- Hedge config YAML review
- Config validation test results
- Asset slice coverage verification

---

### Hedge Config Loader

**Location:** `merid/hedging/config.py`

**Verification Steps:**
- [ ] `load_hedge_config()` loads from correct path
- [ ] Returns `HedgeConfig(enabled=False)` on error (fail-safe)
- [ ] Thread-safe singleton accessor works correctly
- [ ] Fallback defaults match config YAML values
- [ ] Config load errors are logged

**Evidence:**
- Code review of config loader
- Test results from config loader tests
- Config load error logs

---

### Hedge Engine Implementation

**Location:** `merid/hedging/engine.py`

**Verification Steps:**
- [ ] `CryptoHedgeEngine` is deterministic (same inputs → same outputs)
- [ ] Thread-safe implementation (all state in arguments)
- [ ] Uses dedicated strategy group (`HEDGE_STRATEGY_GROUP = "hedge"`)
- [ ] Hedge orders tagged with `HEDGE_` prefix for dedup
- [ ] `agent_id = "hedge_engine"` for all hedge orders
- [ ] Respects `config.enabled` flag (returns empty if disabled)
- [ ] Handles missing market catalog gracefully

**Evidence:**
- Code review of hedge engine
- Test results from hedge engine tests
- Determinism test results

---

### Hedge Engine API Endpoints

**Location:** `web/api/prediction.py`

**Verification Steps:**
- [ ] `POST /api/v1/prediction/hedge/enable` - Enable engine
- [ ] `POST /api/v1/prediction/hedge/disable` - Disable engine
- [ ] `POST /api/v1/prediction/hedge/propose` - Propose hedge position
- [ ] `GET /api/v1/prediction/hedge/positions` - Get active positions
- [ ] `POST /api/v1/prediction/hedge/positions/{id}/activate` - Activate position
- [ ] `POST /api/v1/prediction/hedge/positions/{id}/close` - Close position
- [ ] All endpoints have proper error handling
- [ ] All endpoints log operations

**Evidence:**
- API endpoint test results
- API logs showing hedge operations
- API documentation review

---

### Hedge Engine Startup Integration

**Location:** `web/main_15m_lean.py`

**Verification Steps:**
- [ ] Auto-exit loop started if `hedge_config.enabled`
- [ ] Auto-exit loop started if `hedge_config.auto_exit.enabled`
- [ ] Auto-exit loop startup errors are logged (non-fatal)
- [ ] Hedge config loaded on startup
- [ ] No hedge order generation in agent cycle (manual only)

**Evidence:**
- Startup logs showing hedge engine status
- Auto-exit loop health logs
- Code review of startup integration

---

## Phase 3: Risk Guard Compliance

### Window Limit Enforcement

**Location:** `merid/event_venues/kalshi/order_gate.py`

**Verification Steps:**
- [ ] Hedge orders pass through order gate checks
- [ ] Window limit check applies to hedge orders (3% per agent, 5% total)
- [ ] Hedge orders use dedicated strategy group to avoid lease collisions
- [ ] Hedge exposure tracked in window accounting
- [ ] Hedge order rejection refunds window exposure

**Evidence:**
- Code review of order gate
- Test results from order gate tests
- Window limit enforcement logs

---

### Lease Collision Prevention

**Location:** `merid/hedging/engine.py`

**Verification Steps:**
- [ ] Hedge orders use `HEDGE_STRATEGY_GROUP = "hedge"`
- [ ] Alpha orders use different strategy groups
- [ ] No lease collisions between hedge and alpha orders
- [ ] Strategy group isolation is documented

**Evidence:**
- Code review of strategy group usage
- Test results from lease collision tests
- Lease system logs

---

### Price Guard Compliance

**Location:** `merid/event_venues/kalshi/order_gate.py`

**Verification Steps:**
- [ ] Hedge orders pass price guard check (deep OTM rejection)
- [ ] Hedge orders pass price repeat check (prevent same-price execution)
- [ ] Hedge orders pass duplicate prevention check
- [ ] Hedge orders pass fill awareness check

**Evidence:**
- Code review of price guard checks
- Test results from price guard tests
- Price guard rejection logs

---

### Position Closure Tracking

**Location:** `merid/event_venues/kalshi/position_cache.py`

**Verification Steps:**
- [ ] Hedge position closures reduce window exposure
- [ ] Hedge position closures decremented in risk envelope
- [ ] Hedge position closures logged
- [ ] Window exposure accounting is accurate

**Evidence:**
- Code review of position closure tracking
- Test results from position closure tests
- Window exposure tracking logs

---

## Phase 4: Architecture Verification

### Dual Hedging System Documentation

**Location:** `docs/HEDGING_SYSTEM_ARCHITECTURE.md`

**Verification Steps:**
- [ ] Architecture document exists and is up to date
- [ ] Offset hedging vs CryptoHedgeEngine distinction is clear
- [ ] Why offset hedging is disabled for crypto is documented
- [ ] When to use each system is documented
- [ ] Risk guard interaction is documented
- [ ] Integration points are documented

**Evidence:**
- Architecture document review
- Documentation completeness check
- Cross-reference verification

---

### Auto-Integration Assessment

**Location:** `docs/CRYPTOHEDGE_ENGINE_AUTO_INTEGRATION_ASSESSMENT.md`

**Verification Steps:**
- [ ] Auto-integration assessment document exists
- [ ] Recommendation (keep manual) is documented
- [ ] Rationale for recommendation is clear
- [ ] When to reconsider auto-integration is documented

**Evidence:**
- Assessment document review
- Recommendation clarity check
- Rationale completeness check

---

### Config Consolidation Review

**Location:** `docs/HEDGE_CONFIG_CONSOLIDATION_REVIEW.md`

**Verification Steps:**
- [ ] Config consolidation review document exists
- [ ] Recommendation (keep separate) is documented
- [ ] Rationale for recommendation is clear
- [ ] When to reconsider consolidation is documented

**Evidence:**
- Consolidation review document review
- Recommendation clarity check
- Rationale completeness check

---

## Phase 5: Integration Verification

### No Hedging Logic Bypass

**Location:** All hedging-related code

**Verification Steps:**
- [ ] No code path bypasses window limits for hedging
- [ ] No code path bypasses price guards for hedging
- [ ] No code path bypasses duplicate prevention for hedging
- [ ] No code path bypasses lease system for hedging
- [ ] All hedge orders go through order gate

**Evidence:**
- Grep search for bypass patterns
- Code review of all hedging paths
- Integration test results

---

### No Risk Guard Overrides

**Location:** All hedging-related code

**Verification Steps:**
- [ ] No code overrides window limit enforcement
- [ ] No code overrides price guard enforcement
- [ ] No code overrides duplicate prevention
- [ ] No code overrides lease system
- [ ] No code overrides risk envelope calculations

**Evidence:**
- Grep search for override patterns
- Code review of all risk guard paths
- Risk guard test results

---

### No Unnecessary Hedging

**Location:** All hedging-related code

**Verification Steps:**
- [ ] No hedging "just for the sake of it"
- [ ] All hedging has justified risk logic
- [ ] No hedging without clear purpose
- [ ] No hedging that conflicts with exit policies
- [ ] No hedging that conflicts with window limits

**Evidence:**
- Code review of all hedging logic
- Hedging purpose documentation
- Hedging vs exit policy analysis

---

## Phase 6: Test Verification

### Unit Tests

- [ ] `tests/hedging/test_crypto_hedge_engine.py` - All tests passing
- [ ] `tests/hedging/test_hedge_auto_exit_startup.py` - All tests passing
- [ ] `tests/hedging/test_scalping_tp_audit.py` - All tests passing
- [ ] `tests/test_hedge_50c_minimum.py` - All tests passing
- [ ] `tests/test_momentum_hedge_integration.py` - All tests passing

### Integration Tests

- [ ] `tests/integration/test_hedge_order_flow.py` - All tests passing
- [ ] `tests/integration/test_hedge_risk_guard_compliance.py` - All tests passing

### Chaos Tests

- [ ] `tests/chaos/test_hedge_engine_resilience.py` - All tests passing

### Test Coverage

- [ ] Hedging code coverage ≥ 80%
- [ ] No coverage regression from baseline

**Evidence:**
- Test execution reports
- Coverage reports
- CI/CD test results

---

## Phase 7: Configuration Verification

### Profile YAML

- [ ] `config/profiles/kalshi_crypto_15m_v2.yaml` is up to date
- [ ] `offset_hedging.enabled` is false
- [ ] No stale comments about offset hedging
- [ ] Values match risk envelope defaults
- [ ] Values match profile adapter defaults

### Hedge Config YAML

- [ ] `config/kalshi_crypto_hedging.yaml` is up to date
- [ ] All 5 assets have asset slices defined
- [ ] 15m timeframe rules are defined
- [ ] Take profit configuration is complete
- [ ] Auto-exit configuration is complete

**Evidence:**
- Config file review
- Code review of config loaders
- Test results from config tests

---

## Phase 8: Runtime Verification

### Startup Verification

- [ ] System starts without hedging errors
- [ ] Hedge config loads successfully
- [ ] Hedge engine auto-exit loop starts (if enabled)
- [ ] No startup warnings related to hedging
- [ ] Hedge engine status logged correctly

### Hedge Order Flow Verification

- [ ] Hedge proposals can be created via API
- [ ] Hedge positions can be activated via API
- [ ] Hedge positions can be closed via API
- [ ] Hedge orders pass order gate checks
- [ ] Hedge orders are routed correctly

### Hedge Position Management Verification

- [ ] Hedge TP/SL triggers fire correctly
- [ ] Hedge auto-exit loop is healthy
- [ ] Hedge position closures are tracked
- [ ] Hedge exposure is accounted correctly

**Evidence:**
- Startup logs
- Hedge order flow logs
- Hedge position management logs
- Runtime metrics

---

## Phase 9: Documentation Verification

### Code Documentation

- [ ] All hedging functions have docstrings
- [ ] Hedging architecture is documented in code comments
- [ ] Risk guard interaction is documented
- [ ] Fallback behavior is documented

### Architecture Documentation

- [ ] `docs/HEDGING_SYSTEM_ARCHITECTURE.md` is up to date
- [ ] `docs/CRYPTOHEDGE_ENGINE_AUTO_INTEGRATION_ASSESSMENT.md` is up to date
- [ ] `docs/HEDGE_CONFIG_CONSOLIDATION_REVIEW.md` is up to date
- [ ] `docs/HEDGING_SYSTEM_AUDIT_CHECKLIST.md` is up to date

### Runbook Documentation

- [ ] Hedge engine troubleshooting guide exists
- [ ] Hedge config change procedure exists
- [ ] Hedge position failure recovery procedure exists

**Evidence:**
- Documentation review
- Runbook validation

---

## Phase 10: Security Verification

### Access Control

- [ ] Hedge config files have appropriate permissions
- [ ] Hedge API endpoints have appropriate access controls
- [ ] Hedge engine enable/disable requires authorization

### Audit Trail

- [ ] All hedge engine enable/disable events are logged
- [ ] All hedge order proposals are logged
- [ ] All hedge position activations are logged
- [ ] All hedge position closures are logged
- [ ] All hedge config changes are logged

**Evidence:**
- File permission review
- Audit log review
- API access control review

---

## Phase 11: Disaster Recovery Verification

### Backup and Restore

- [ ] Profile YAML is backed up
- [ ] Hedge config YAML is backed up
- [ ] Hedge engine logs are backed up
- [ ] Restore procedure is documented

### Failure Scenarios

- [ ] Hedge config load failure recovery is tested
- [ ] Hedge engine failure recovery is tested
- [ ] Hedge order routing failure recovery is tested
- [ ] Hedge position corruption recovery is tested

**Evidence:**
- Backup verification
- Disaster recovery test results

---

## Phase 12: Sign-off

### Engineering Sign-off

- [ ] Lead engineer review complete
- [ ] Code review approved
- [ ] Test results approved
- [ ] Documentation approved

### Operations Sign-off

- [ ] Monitoring configuration approved
- [ ] Alerting configuration approved
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
- [ ] COMPLIANT - Hedging system operating correctly
- [ ] PARTIALLY COMPLIANT - Address pending items
- [ ] NON-COMPLIANT - Critical issues must be resolved

**Blockers:**
- List any critical blockers that must be resolved

**Recommendations:**
- List any recommendations for improvement

---

## Next Steps

After completing this checklist:
1. Address any pending items
2. Resolve any blockers
3. Implement recommendations
4. Schedule follow-up audit
5. Monitor hedging system metrics

---

## Appendix: Reference Documents

- `docs/HEDGING_SYSTEM_ARCHITECTURE.md` - Dual hedging system overview
- `docs/CRYPTOHEDGE_ENGINE_AUTO_INTEGRATION_ASSESSMENT.md` - Auto-integration assessment
- `docs/HEDGE_CONFIG_CONSOLIDATION_REVIEW.md` - Config consolidation review
- `config/profiles/kalshi_crypto_15m_v2.yaml` - Profile configuration
- `config/kalshi_crypto_hedging.yaml` - Hedge engine configuration
- `merid/hedging/engine.py` - CryptoHedgeEngine implementation
- `merid/hedging/config.py` - Hedge config loader
- `merid/event_venues/kalshi/order_gate.py` - Order gate with risk checks
- `merid/position_management/position_monitor.py` - Position monitoring logic
