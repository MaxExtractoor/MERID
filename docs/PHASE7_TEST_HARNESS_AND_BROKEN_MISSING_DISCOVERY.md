# Phase 7: Test Harness and Broken/Missing Discovery

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Validate automated tests, replay capabilities, and shadow trading for broken/missing discovery

---

## Executive Summary

This document defines validation checks for test harness, replay, and shadow trading. Automated tests must be comprehensive and fast, replay must accurately reproduce historical scenarios, and shadow trading must enable safe experimentation and broken/missing discovery.

---

## Automated Tests

### Requirement 1: Test Coverage

**Statement:** Test coverage must be comprehensive across all critical components.

**Current Implementation:**
- `tests/` directory with 373+ test files
- Test files for: core, event_venues/kalshi, prediction, risk, backtesting, etc.
- pytest for test execution
- Coverage tracking via pytest-cov

**Validation:**
- Unit test coverage > 80% for critical components
- Integration test coverage for all major workflows
- End-to-end test coverage for critical paths
- Test coverage report generated on CI
- Coverage trends monitored (no regressions)

**Thresholds:**
- Unit test coverage: > 80%
- Integration test coverage: > 60%
- E2E test coverage: > 40%
- Critical path coverage: 100%

**Enforcement Point:** CI pipeline, coverage reporting

**Violation Action:** Log warning, block merge if coverage drops

---

### Requirement 2: Test Speed

**Statement:** Tests must be fast enough to run frequently.

**Current Implementation:**
- pytest for parallel test execution
- Test fixtures for setup/teardown
- Mocking for external dependencies

**Validation:**
- Full test suite runs in < 10 minutes
- Unit test suite runs in < 5 minutes
- Integration test suite runs in < 5 minutes
- E2E test suite runs in < 10 minutes
- Test execution time is monitored

**Thresholds:**
- Full suite: < 10 minutes
- Unit suite: < 5 minutes
- Integration suite: < 5 minutes
- E2E suite: < 10 minutes

**Enforcement Point:** CI pipeline, test execution monitoring

**Violation Action:** Log warning, investigate slow tests, optimize

---

### Requirement 3: Test Reliability

**Statement:** Tests must be reliable and deterministic.

**Current Implementation:**
- Test fixtures for deterministic state
- Mocking for external dependencies
- Test isolation (no shared state between tests)

**Validation:**
- Flaky test rate < 1%
- Tests are deterministic (same result on same code)
- Tests are isolated (no cross-test dependencies)
- Tests are reproducible (can reproduce failures)
- Test failures have clear error messages

**Thresholds:**
- Flaky test rate: < 1%
- Determinism: 100%
- Isolation: 100%
- Reproducibility: 100%

**Enforcement Point:** CI pipeline, flaky test detection

**Violation Action:** Log warning, fix flaky test, block merge if flaky rate high

---

### Requirement 4: Test Organization

**Statement:** Tests must be well-organized and discoverable.

**Current Implementation:**
- `tests/` directory structure mirrors source
- Test files named `test_*.py`
- Test classes named `Test*`
- Test methods named `test_*`

**Validation:**
- Test structure mirrors source structure
- Test files follow naming conventions
- Test classes follow naming conventions
- Test methods follow naming conventions
- Tests are documented (docstrings)

**Enforcement Point:** Code review, linting rules

**Violation Action:** Log warning, fix naming, block merge if not compliant

---

## Replay

### Requirement 1: Event Replay

**Statement:** Historical events must be replayable for incident analysis.

**Current Implementation:**
- `testing/replay_harness.py` - Replay harness for LLM decisions
- `backtesting/replayer.py` - Deterministic replay helpers
- `merid/event_venues/kalshi/incidents/replayer.py` - Incident replay for Kalshi
- Event storage in archive/S3

**Validation:**
- Historical events are stored with timestamps
- Events can be replayed in order
- Replay produces same decisions as original (deterministic)
- Replay detects drift from original decisions
- Replay results are comparable to original

**Thresholds:**
- Event storage: 100% of events
- Replay determinism: 100%
- Drift detection: < 5% drift acceptable
- Replay accuracy: > 95%

**Enforcement Point:** Replay harness, drift detection

**Violation Action:** Log warning, investigate drift, fix non-determinism

---

### Requirement 2: Incident Replay

**Statement:** Incident scenarios must be replayable for root cause analysis.

**Current Implementation:**
- `KalshiIncidentReplayer` for Kalshi stress scenarios
- Incident scenario loading from JSON
- Metrics replay (latency, WS events, CB events)
- Report generation for comparison

**Validation:**
- Incident scenarios are captured (orders, fills, metrics)
- Scenarios can be loaded and replayed
- Replay reproduces incident conditions
- Report compares replay vs original
- Divergences are detected and reported

**Thresholds:**
- Scenario capture: 100% of incidents
- Replay accuracy: > 95%
- Divergence detection: 100%

**Enforcement Point:** Incident capture, replay harness

**Violation Action:** Log warning, investigate divergence, fix replay

---

### Requirement 3: Deterministic Replay

**Statement:** Replay must be deterministic (same input → same output).

**Current Implementation:**
- `backtesting/replayer.py` - Deterministic replay helpers
- Energy cloning for replay
- Validation entry replay
- Match detection (approved, consensus)

**Validation:**
- Replay produces same decisions as original
- Replay is repeatable (same result on same input)
- Replay is isolated (no external state)
- Replay is fast (can replay many events quickly)

**Thresholds:**
- Determinism: 100%
- Repeat rate: 100%
- Isolation: 100%
- Replay speed: > 100 events/second

**Enforcement Point:** Replay harness, determinism validation

**Violation Action:** Log warning, fix non-determinism, block merge if not deterministic

---

### Requirement 4: Drift Detection

**Statement:** Drift between replayed and original decisions must be detected.

**Current Implementation:**
- `DriftDetector` in replay_harness.py
- Severity levels: NONE, MINOR, MODERATE, SIGNIFICANT, CRITICAL
- Comparison of direction, score, confidence
- Drift details reporting

**Validation:**
- Drift is detected when decisions differ
- Drift severity is classified correctly
- Drift details are reported
- Critical drift triggers alert
- Drift trends are monitored

**Thresholds:**
- Drift detection: 100%
- Severity classification: > 95% accuracy
- Critical drift alert: immediate

**Enforcement Point:** Drift detector, alerting

**Violation Action:** Log warning, alert operator, investigate drift

---

## Shadow Trading

### Requirement 1: Shadow Instance

**Statement:** Shadow instance must run in parallel with production.

**Current Implementation:**
- `simulation/shadow_merid.py` - Shadow MERID simulation
- Shadow portfolio tracking
- Shadow execution history
- Price cache sync from production

**Validation:**
- Shadow instance runs continuously
- Shadow instance receives all production intents
- Shadow instance executes in simulation mode
- Shadow instance never touches real capital
- Shadow instance state is observable

**Thresholds:**
- Shadow uptime: > 99%
- Intent mirroring: 100%
- Simulation mode: 100%
- Capital safety: 100%

**Enforcement Point:** Shadow instance, execution gate

**Violation Action:** Log critical, alert operator, stop shadow if unsafe

---

### Requirement 2: Shadow Execution

**Statement:** Shadow execution must mirror production execution.

**Current Implementation:**
- Shadow portfolio tracking
- Shadow position tracking
- Shadow PnL tracking
- Divergence detection from production

**Validation:**
- Shadow executes all production intents
- Shadow uses realistic slippage model
- Shadow uses realistic latency model
- Shadow portfolio state is tracked
- Shadow PnL is tracked

**Thresholds:**
- Intent mirroring: 100%
- Slippage model: realistic (5 bps default)
- Latency model: realistic (50ms default)
- Portfolio tracking: 100%
- PnL tracking: 100%

**Enforcement Point:** Shadow execution, portfolio tracking

**Violation Action:** Log warning, investigate divergence, fix shadow

---

### Requirement 3: Divergence Detection

**Statement:** Divergence between shadow and production must be detected.

**Current Implementation:**
- Divergence tracking in ShadowMERID
- Divergence threshold: 5% default
- Divergence callbacks
- Divergence details reporting

**Validation:**
- Divergence is detected when shadow vs production differ
- Divergence threshold is configurable
- Divergence triggers callback
- Divergence details are reported
- Divergence trends are monitored

**Thresholds:**
- Divergence detection: 100%
- Divergence threshold: 5% default
- Divergence alert: immediate

**Enforcement Point:** Divergence detector, alerting

**Violation Action:** Log warning, alert operator, investigate divergence

---

### Requirement 4: Shadow Promotion

**Statement:** Shadow instance must be promotable to production on failure.

**Current Implementation:**
- `recovery/shadow_promotion.py` - Shadow promotion manager
- SystemRole enum (PRIMARY, SHADOW, STANDBY, PROMOTING, DEMOTING, OFFLINE)
- PromotionReason enum (PRIMARY_FAILURE, SCHEDULED_MAINTENANCE, etc.)
- Promotion event tracking
- Health monitoring

**Validation:**
- Shadow can be promoted to primary
- Promotion is controlled (manual or auto)
- Promotion verifies state sync
- Promotion is tracked in history
- Promotion is reversible (demotion)

**Thresholds:**
- Promotion success: > 95%
- State sync verification: 100%
- Promotion tracking: 100%
- Reversibility: 100%

**Enforcement Point:** Promotion manager, health monitoring

**Violation Action:** Log critical, alert operator, block promotion if unsafe

---

## Broken/Missing Discovery

### Requirement 1: Broken Link Detection

**Statement:** Broken links between components must be detected.

**Current Implementation:**
- Integration tests for component wiring
- End-to-end tests for critical paths
- Dependency injection validation
- API endpoint validation

**Validation:**
- All component links are tested
- All API endpoints are tested
- All dependencies are validated
- Broken links are detected in CI
- Broken links are fixed before merge

**Thresholds:**
- Link coverage: 100%
- Endpoint coverage: 100%
- Dependency validation: 100%
- Detection rate: 100%

**Enforcement Point:** Integration tests, E2E tests

**Violation Action:** Log warning, fix broken link, block merge

---

### Requirement 2: Missing Component Detection

**Statement:** Missing components must be detected and reported.

**Current Implementation:**
- Codebase audit scripts
- Module import validation
- Configuration validation
- Deployment validation

**Validation:**
- All required components are present
- All required modules are importable
- All required config keys are set
- All required deployment artifacts are present
- Missing components are detected in CI

**Thresholds:**
- Component presence: 100%
- Import success: 100%
- Config completeness: 100%
- Deployment completeness: 100%

**Enforcement Point:** Audit scripts, CI validation

**Violation Action:** Log warning, add missing component, block merge

---

### Requirement 3: Invariant Violation Detection

**Statement:** Invariant violations must be detected and reported.

**Current Implementation:**
- `tests/test_invariants_hypothesis.py` - Invariant testing with Hypothesis
- `tests/test_zero_trust_invariants.py` - Zero-trust invariants
- `tests/test_cross_view_invariants.py` - Cross-view invariants
- Invariant checks in production code

**Validation:**
- All invariants are tested
- Invariant violations are detected
- Invariant violations are reported
- Invariant violations trigger alerts
- Invariant violations are fixed

**Thresholds:**
- Invariant coverage: 100%
- Detection rate: 100%
- Alert rate: 100%
- Fix rate: 100%

**Enforcement Point:** Invariant tests, production checks

**Violation Action:** Log critical, alert operator, fix invariant

---

### Requirement 4: Data Consistency Detection

**Statement:** Data consistency violations must be detected and reported.

**Current Implementation:**
- Reconciliation checks (position, cash, PnL)
- Cross-system consistency checks
- Data validation checks
- Drift detection

**Validation:**
- All data stores are reconciled
- All cross-system checks pass
- All data validation passes
- All drift is within tolerance
- Consistency violations trigger alerts

**Thresholds:**
- Reconciliation coverage: 100%
- Cross-system checks: 100%
- Data validation: 100%
- Drift tolerance: < 1%

**Enforcement Point:** Reconciliation, consistency checks

**Violation Action:** Log warning, alert operator, fix consistency issue

---

## Automated Test Plan

### Test Suite: `tests/test_harness/test_test_harness_and_broken_missing_discovery.py`

**Test Classes:**

1. `TestAutomatedTests`
   - Test: test coverage
   - Test: test speed
   - Test: test reliability
   - Test: test organization
   - Test: test execution

2. `TestReplay`
   - Test: event replay
   - Test: incident replay
   - Test: deterministic replay
   - Test: drift detection
   - Test: replay reporting

3. `TestShadowTrading`
   - Test: shadow instance
   - Test: shadow execution
   - Test: divergence detection
   - Test: shadow promotion
   - Test: shadow safety

4. `TestBrokenMissingDiscovery`
   - Test: broken link detection
   - Test: missing component detection
   - Test: invariant violation detection
   - Test: data consistency detection
   - Test: discovery reporting

5. `TestReplayHarness`
   - Test: event replay
   - Test: decision comparison
   - Test: drift detection
   - Test: replay session
   - Test: drift detector

6. `TestShadowMERID`
   - Test: shadow initialization
   - Test: shadow execution
   - Test: portfolio tracking
   - Test: divergence detection
   - Test: shadow safety

7. `TestShadowPromotion`
   - Test: instance registration
   - Test: health monitoring
   - Test: promotion logic
   - Test: demotion logic
   - Test: promotion history

8. `TestKalshiIncidentReplayer`
   - Test: scenario loading
   - Test: order replay
   - Test: metrics replay
   - Test: CB event replay
   - Test: report generation

9. `TestDeterministicReplay`
   - Test: energy cloning
   - Test: replay execution
   - Test: match detection
   - Test: determinism
   - Test: isolation

**Total Target:** 80+ test harness tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify test harness implementation (testing/replay_harness.py)
- ✅ Identify replay implementation (backtesting/replayer.py, incidents/replayer.py)
- ✅ Identify shadow trading implementation (simulation/shadow_merid.py)
- ✅ Identify shadow promotion implementation (recovery/shadow_promotion.py)
- ✅ Document current implementation

### Step 2: Define Validation Checks (DONE)
- ✅ Define automated test requirements
- ✅ Define replay requirements
- ✅ Define shadow trading requirements
- ✅ Define broken/missing discovery requirements

### Step 3: Implement Automated Test Enhancements (NEXT)
- [ ] Add test coverage reporting
- [ ] Add test speed monitoring
- [ ] Add flaky test detection
- [ ] Add test organization validation
- [ ] Add test execution optimization

### Step 4: Implement Replay Enhancements
- [ ] Add event replay validation
- [ ] Add incident replay validation
- [ ] Add deterministic replay validation
- [ ] Add drift detection enhancement
- [ ] Add replay reporting enhancement

### Step 5: Implement Shadow Trading Enhancements
- [ ] Add shadow instance validation
- [ ] Add shadow execution validation
- [ ] Add divergence detection enhancement
- [ ] Add shadow promotion validation
- [ ] Add shadow safety validation

### Step 6: Implement Broken/Missing Discovery Enhancements
- [ ] Add broken link detection
- [ ] Add missing component detection
- [ ] Add invariant violation detection
- [ ] Add data consistency detection
- [ ] Add discovery reporting

### Step 7: Implement Test Suite
- [ ] Create `tests/test_harness/test_test_harness_and_broken_missing_discovery.py`
- [ ] Implement all 9 test classes
- [ ] Target: 80+ tests passing
- [ ] Wire into CI pipeline

---

## Success Criteria

Phase 7 is complete when:

1. ✅ This design document is approved
2. [ ] Automated tests are comprehensive and fast
3. [ ] Replay is accurate and deterministic
4. [ ] Shadow trading is safe and observable
5. [ ] Broken/missing discovery is automated
6. [ ] All 80+ test harness tests are implemented and passing
7. [ ] CI pipeline includes test harness test suite
8. [ ] Replay is used for incident analysis
9. [ ] Shadow trading is used for experimentation
10. [ ] Broken/missing discovery catches issues before production

---

## References

- `testing/replay_harness.py` - Replay harness for LLM decisions
- `backtesting/replayer.py` - Deterministic replay helpers
- `simulation/shadow_merid.py` - Shadow MERID simulation
- `merid/event_venues/kalshi/incidents/replayer.py` - Kalshi incident replay
- `recovery/shadow_promotion.py` - Shadow promotion manager
- `tests/test_invariants_hypothesis.py` - Invariant testing
- `tests/test_zero_trust_invariants.py` - Zero-trust invariants
- `tests/test_cross_view_invariants.py` - Cross-view invariants
- `tests/replay_grading.py` - Replay grading tests
- `tests/event_venues/kalshi/test_snapshot_replay.py` - Snapshot replay tests

---

**Phase 7 Complete: All 7 phases of the forensic audit are now documented.**

## Summary of All Phases

1. **Phase 1: Source of Truth and Invariants** - Canonical data stores, write permissions, invariant tests
2. **Phase 2A: Data Integrity and Alignment** - Candle/orderbook validation, drift checks, Kalshi metadata verification
3. **Phase 2B: Signal Correctness and Determinism** - Offline recompute, cross-asset/timeframe sync, signal diff job
4. **Phase 3: Edge/Contract/Sizing Audit** - Venue specs registry, sizing correctness, portfolio limits, drawdown limits
5. **Phase 4: Execution Layer and Kalshi Integration** - API validation, latency/slippage profiling, venue health dashboard
6. **Phase 5: PnL, Attribution, and Performance Truth** - Canonical PnL engine, reconciliation, strategy attribution
7. **Phase 6: Reliability, Kill Switches, and Monitoring** - Global/per-venue kill switches, strategy throttles, monitoring/alerting
8. **Phase 7: Test Harness and Broken/Missing Discovery** - Automated tests, replay, shadow trading

All design documents are now available in `docs/` directory for implementation.
