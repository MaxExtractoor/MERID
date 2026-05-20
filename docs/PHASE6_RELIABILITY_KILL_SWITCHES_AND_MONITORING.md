# Phase 6: Reliability, Kill Switches, and Monitoring

**Date:** 2026-05-12  
**Scope:** MERID Kalshi Trading System (15m BTC/ETH/SOL/XRP/DOGE)  
**Purpose:** Validate global/per-venue kill switches, strategy throttles, and monitoring/alerting

---

## Executive Summary

This document defines validation checks for reliability, kill switches, and monitoring. Kill switches must be properly implemented and tested, strategy throttles must prevent runaway execution, and monitoring/alerting must provide visibility into system health.

---

## Global Kill Switches

### Requirement 1: Global Kill Switch Implementation

**Statement:** Global kill switch must halt all trading immediately when triggered.

**Current Implementation:**
- `risk/kill_switches.py` - RiskController with global kill switch
- KillSwitchState enum (ACTIVE/TRIGGERED)
- Multiple trigger reasons (MANUAL, DAILY_LOSS, POSITION_LIMIT, ERROR_THRESHOLD, CIRCUIT_BREAKER, DEPENDENCY_HEALTH, RTI_FEED_STALE, LOOP_LAG_HALT, PORTFOLIO_INTEGRITY)
- Persistent kill switch state to disk
- Execution gate checks kill switch before trading

**Validation:**
- Global kill switch state is persisted to disk
- Kill switch state is restored on startup (fail-safe)
- Execution gate blocks trading when kill switch is TRIGGERED
- Manual trigger works immediately
- Auto-trigger works for all defined reasons
- Kill switch requires explicit operator acknowledgment to reset

**Enforcement Point:** RiskController, execution gate, persistence layer

**Violation Action:** Log critical, alert operator, block execution

---

### Requirement 2: Daily Loss Kill Switch

**Statement:** Daily loss limit must trigger kill switch when exceeded.

**Current Implementation:**
- `daily_loss_limit` in RiskController (percentage-based, 15% of equity by default)
- `record_pnl()` method tracks daily PnL
- Kill switch triggers when daily loss > daily_loss_limit
- Daily counter resets at midnight

**Validation:**
- Daily loss limit is configured correctly (percentage of equity)
- Daily PnL is tracked accurately
- Kill switch triggers when daily loss exceeds threshold
- Daily counter resets at midnight (UTC)
- Kill switch persists across restarts

**Thresholds:**
- Daily loss limit: 15% of equity (configurable via `MERID_MAX_DAILY_LOSS_PCT`)
- Alert at 10% loss
- Kill at 15% loss

**Enforcement Point:** RiskController.record_pnl(), execution gate

**Violation Action:** Log critical, alert operator, trigger kill switch

---

### Requirement 3: Position Limit Kill Switch

**Statement:** Position limit must trigger kill switch when exceeded.

**Current Implementation:**
- `max_position_value` in RiskController (default $10,000)
- Position tracking in RiskController
- Kill switch triggers when total position value > max_position_value

**Validation:**
- Position limit is configured correctly
- Total position value is tracked accurately
- Kill switch triggers when position limit exceeded
- Position limit is per-venue or global (should be global)

**Thresholds:**
- Max position value: $10,000 (configurable via `MERID_MAX_POSITION_VALUE_USD`)
- Alert at 80% of limit
- Kill at 100% of limit

**Enforcement Point:** RiskController position tracking, execution gate

**Violation Action:** Log critical, alert operator, trigger kill switch

---

### Requirement 4: Error Threshold Kill Switch

**Statement:** Error threshold must trigger kill switch when too many errors occur.

**Current Implementation:**
- `error_threshold` in RiskController (default 500)
- Error counting in RiskController
- Kill switch triggers when error count > error_threshold
- Startup grace period to prevent false positives

**Validation:**
- Error threshold is configured correctly (500, not 50)
- Only P0/P1 errors count toward threshold
- P2/P3 errors are logged but don't count
- Startup grace period is respected (5 minutes)
- Error counter resets after cooldown

**Thresholds:**
- Error threshold: 500 (configurable via `MERID_ERROR_THRESHOLD`)
- Startup grace: 5 minutes
- Cooldown: 30 minutes

**Enforcement Point:** RiskController error counting, execution gate

**Violation Action:** Log critical, alert operator, trigger kill switch

---

## Per-Venue Kill Switches

### Requirement 1: Per-Venue Circuit Breaker

**Statement:** Each venue must have a circuit breaker that halts trading to that venue when failures occur.

**Current Implementation:**
- `resilience/circuit_breaker.py` - CircuitBreaker class
- Circuit states: CLOSED, OPEN, HALF_OPEN
- Failure threshold and recovery timeout
- Used in Kalshi client and venue adapters

**Validation:**
- Circuit breaker exists for Kalshi venue
- Circuit breaker transitions: CLOSED → OPEN → HALF_OPEN → CLOSED
- Failure threshold is configured correctly (default 5)
- Recovery timeout is configured correctly (default 30s)
- Half-open allows testing recovery
- Circuit breaker state is observable

**Thresholds:**
- Failure threshold: 5 failures
- Recovery timeout: 30 seconds
- Half-open max calls: 3
- Half-open success required: 2

**Enforcement Point:** CircuitBreaker, venue client

**Violation Action:** Log warning, block venue calls, alert operator

---

### Requirement 2: Per-Venue Health Monitoring

**Statement:** Each venue must have health monitoring that detects degraded performance.

**Current Implementation:**
- `kalshi_robustness.py` - RobustKalshiClient with health monitoring
- KalshiHealthStatus dataclass
- Health checks: client, ws, order_manager, position_cache
- Health monitoring loop

**Validation:**
- Health checks run periodically
- Health status is aggregated from multiple sources
- Health status includes: connectivity, latency, error rates
- Degraded health triggers circuit breaker
- Health status is observable via API

**Enforcement Point:** Health monitoring loop, circuit breaker integration

**Violation Action:** Log warning, degrade venue, alert operator

---

### Requirement 3: Per-Venue Error Budget

**Statement:** Each venue must have an error budget that prevents error storms.

**Current Implementation:**
- `core/error_budget.py` - ErrorBudget class
- Severity levels: P0 (critical), P1 (serious), P2 (warning), P3 (info)
- Budget states: HEALTHY, DEGRADED, EXHAUSTED
- P0/P1 consume budget, P2/P3 do not

**Validation:**
- Error budget is initialized with correct thresholds
- P0 errors count fully (weight=1.0)
- P1 errors count half (weight=0.5)
- P2/P3 errors don't count (weight=0.0)
- Budget state transitions: HEALTHY → DEGRADED → EXHAUSTED
- EXHAUSTED state triggers venue kill switch

**Thresholds:**
- Max P0 events: 10
- Max P1 events (weighted): 20
- Warning threshold: 70%
- Window: 1 hour
- Dedup window: 5 minutes

**Enforcement Point:** ErrorBudget, venue kill switch

**Violation Action:** Log warning, degrade venue, alert operator

---

## Strategy Throttles

### Requirement 1: Per-Strategy Rate Limiting

**Statement:** Each strategy must have rate limiting to prevent runaway execution.

**Current Implementation:**
- Order queue limits in execution_queue.py
- Per-ticker state machine (IDLE → PENDING → OPEN → IDLE)
- Rejection of duplicate intents on same ticker
- Priority queue for validated intents

**Validation:**
- Rate limit is enforced per strategy
- Rate limit is enforced per ticker
- Duplicate intents are rejected
- Queue size is bounded
- Priority ordering is correct

**Thresholds:**
- Max queue size: 1000 intents
- Max intents per ticker per cycle: 1
- Max orders per cycle: 10

**Enforcement Point:** Execution queue, order router

**Violation Action:** Log warning, reject order, alert operator

---

### Requirement 2: Per-Strategy Position Limits

**Statement:** Each strategy must have position limits to prevent over-concentration.

**Current Implementation:**
- Position limits in risk_parameters.py
- Per-asset slice caps in hedging config
- Portfolio limits in portfolio_engine.py

**Validation:**
- Position limits are configured per strategy
- Position limits are enforced at order time
- Position limits are checked against current positions
- Position limits are checked against portfolio exposure
- Position limits are observable

**Thresholds:**
- BTC/ETH: 25% of bankroll
- SOL/XRP/DOGE: 10% of bankroll
- Max single position: 5% of bankroll

**Enforcement Point:** Position sizer, risk engine, execution gate

**Violation Action:** Log warning, reject order, alert operator

---

### Requirement 3: Per-Strategy Drawdown Limits

**Statement:** Each strategy must have drawdown limits to prevent catastrophic losses.

**Current Implementation:**
- Cycle drawdown tracking in cycle_drawdown.py
- Portfolio drawdown in portfolio_engine.py
- Kill switch triggers on daily loss

**Validation:**
- Drawdown is tracked per strategy
- Drawdown is tracked per cycle
- Drawdown is tracked per day
- Drawdown limits are enforced
- Drawdown limits are observable

**Thresholds:**
- Cycle drawdown limit: 5%
- Daily drawdown limit: 15%
- Max drawdown limit: 20%

**Enforcement Point:** Drawdown tracking, kill switch

**Violation Action:** Log warning, throttle strategy, alert operator

---

## Monitoring

### Requirement 1: System Health Monitoring

**Statement:** System health must be monitored and reported continuously.

**Current Implementation:**
- `loop_robustness.py` - RobustLoopRunner with health monitoring
- `observability/state_transitions.py` - State transition tracking
- Health checks registered in health checker
- Prometheus metrics for health

**Validation:**
- Health checks run periodically (every 30 seconds)
- Health checks cover: loop, venues, databases, dependencies
- Health status is aggregated
- Health status is observable via API
- Health status is visible in dashboard

**Enforcement Point:** Health monitoring loop, health checker

**Violation Action:** Log warning, alert operator, degrade system

---

### Requirement 2: Performance Monitoring

**Statement:** System performance must be monitored and reported continuously.

**Current Implementation:**
- Loop lag monitoring in loop_robustness.py
- Latency tracking in client.py, client_v2.py
- Tick duration tracking in RobustLoopRunner
- Prometheus metrics for performance

**Validation:**
- Loop lag is monitored (time between scheduled and actual execution)
- API latency is monitored per endpoint
- Tick duration is monitored
- Performance metrics are aggregated
- Performance metrics are observable

**Thresholds:**
- Loop lag: < 10ms normal, < 50ms warning, > 50ms critical
- API latency: < 500ms normal, < 1s warning, > 1s critical
- Tick duration: < 30s normal, < 60s warning, > 60s critical

**Enforcement Point:** Performance monitoring, kill switch

**Violation Action:** Log warning, alert operator, trigger kill switch if critical

---

### Requirement 3: Error Monitoring

**Statement:** Errors must be monitored and classified by severity.

**Current Implementation:**
- `core/error_budget.py` - Error classification (P0-P3)
- `risk/error_classification.py` - Error classification logic
- Error counting in RiskController
- Error deduplication in ErrorBudget

**Validation:**
- Errors are classified by severity (P0-P3)
- Error counts are tracked per severity
- Error deduplication prevents spam
- Error signatures are tracked
- Error rates are calculated

**Thresholds:**
- P0 rate: < 1 per hour
- P1 rate: < 5 per hour
- P2 rate: < 20 per hour
- P3 rate: < 100 per hour

**Enforcement Point:** Error budget, kill switch

**Violation Action:** Log warning, alert operator, trigger kill switch if P0/P1 rate high

---

## Alerting

### Requirement 1: Critical Alerts

**Statement:** Critical events must trigger immediate alerts.

**Current Implementation:**
- `alerts/trade_notifier.py` - Telegram notifications for trading events
- `alerts/webhook_client.py` - Webhook client for alerts
- `alerts/reconciliation_alerts.py` - Reconciliation alerts
- Session log for critical events

**Validation:**
- Kill switch triggers immediate alert
- Daily loss limit triggers immediate alert
- Position limit triggers immediate alert
- Critical discrepancy triggers immediate alert
- Alert is sent via Telegram
- Alert is logged to session log

**Enforcement Point:** Alert handlers, session log

**Violation Action:** Send alert immediately, log to session log

---

### Requirement 2: Warning Alerts

**Statement:** Warning events must trigger timely alerts.

**Current Implementation:**
- Trade notifier sends cycle digests
- Performance warnings logged
- Health degradation warnings logged

**Validation:**
- Degraded health triggers warning alert
- Performance degradation triggers warning alert
- Warning alerts are batched (not spammy)
- Warning alerts are sent via Telegram
- Warning alerts are logged

**Thresholds:**
- Health degraded: 70% of threshold
- Performance degraded: 2x baseline
- Warning batch interval: 5 minutes

**Enforcement Point:** Alert handlers, batcher

**Violation Action:** Batch warning, send alert, log

---

### Requirement 3: Info Alerts

**Statement:** Info events must be logged for observability.

**Current Implementation:**
- Structured logging in utils/logger.py
- Event logging in core/session_log.py
- Trade notifications for fills

**Validation:**
- Info events are logged
- Info events are structured (JSON)
- Info events are queryable
- Info events are not spammed
- Info events are observable

**Enforcement Point:** Logger, session log

**Violation Action:** Log info event

---

## Automated Test Plan

### Test Suite: `tests/reliability/test_reliability_kill_switches_and_monitoring.py`

**Test Classes:**

1. `TestGlobalKillSwitches`
   - Test: global kill switch implementation
   - Test: daily loss kill switch
   - Test: position limit kill switch
   - Test: error threshold kill switch
   - Test: kill switch persistence and restoration

2. `TestPerVenueKillSwitches`
   - Test: per-venue circuit breaker
   - Test: per-venue health monitoring
   - Test: per-venue error budget
   - Test: venue degradation
   - Test: venue recovery

3. `TestStrategyThrottles`
   - Test: per-strategy rate limiting
   - Test: per-strategy position limits
   - Test: per-strategy drawdown limits
   - Test: queue rejection
   - Test: priority ordering

4. `TestMonitoring`
   - Test: system health monitoring
   - Test: performance monitoring
   - Test: error monitoring
   - Test: health check aggregation
   - Test: metrics aggregation

5. `TestAlerting`
   - Test: critical alerts
   - Test: warning alerts
   - Test: info alerts
   - Test: alert batching
   - Test: alert delivery

6. `TestCircuitBreaker`
   - Test: circuit state transitions
   - Test: failure threshold
   - Test: recovery timeout
   - Test: half-open behavior
   - Test: circuit breaker observability

7. `TestErrorBudget`
   - Test: severity classification
   - Test: budget consumption
   - Test: state transitions
   - Test: deduplication
   - Test: error budget reset

8. `TestLoopRobustness`
   - Test: tick error recovery
   - Test: consecutive failure handling
   - Test: tick timeout handling
   - Test: health monitoring
   - Test: deadlock prevention

9. `TestKillSwitchIntegration`
   - Test: kill switch + execution gate
   - Test: kill switch + circuit breaker
   - Test: kill switch + error budget
   - Test: kill switch propagation
   - Test: kill switch acknowledgment

**Total Target:** 80+ reliability tests

---

## Implementation Roadmap

### Step 1: Document Current State (DONE)
- ✅ Identify kill switch implementation (risk/kill_switches.py)
- ✅ Identify circuit breaker implementation (resilience/circuit_breaker.py)
- ✅ Identify error budget implementation (core/error_budget.py)
- ✅ Identify alerting implementation (alerts/)
- ✅ Identify monitoring implementation (loop_robustness.py, observability/)
- ✅ Document current implementation

### Step 2: Define Validation Checks (DONE)
- ✅ Define global kill switch requirements
- ✅ Define per-venue kill switch requirements
- ✅ Define strategy throttle requirements
- ✅ Define monitoring requirements
- ✅ Define alerting requirements

### Step 3: Implement Global Kill Switch Enhancements (NEXT)
- [ ] Validate kill switch persistence
- [ ] Validate kill switch restoration on startup
- [ ] Add kill switch acknowledgment workflow
- [ ] Add kill switch audit logging
- [ ] Add kill switch API endpoints

### Step 4: Implement Per-Venue Kill Switch Enhancements
- [ ] Validate circuit breaker per venue
- [ ] Add per-venue health monitoring
- [ ] Add per-venue error budget
- [ ] Add venue degradation handling
- [ ] Add venue recovery automation

### Step 5: Implement Strategy Throttle Enhancements
- [ ] Add per-strategy rate limiting
- [ ] Add per-strategy position limits
- [ ] Add per-strategy drawdown limits
- [ ] Add strategy throttle API endpoints
- [ ] Add strategy throttle dashboard

### Step 6: Implement Monitoring Enhancements
- [ ] Add system health monitoring
- [ ] Add performance monitoring
- [ ] Add error monitoring
- [ ] Add monitoring API endpoints
- [ ] Add monitoring dashboard

### Step 7: Implement Alerting Enhancements
- [ ] Add critical alert handling
- [ ] Add warning alert batching
- [ ] Add info event logging
- [ ] Add alert delivery verification
- [ ] Add alert history API

### Step 8: Implement Test Suite
- [ ] Create `tests/reliability/test_reliability_kill_switches_and_monitoring.py`
- [ ] Implement all 9 test classes
- [ ] Target: 80+ tests passing
- [ ] Wire into CI pipeline

---

## Success Criteria

Phase 6 is complete when:

1. ✅ This design document is approved
2. [ ] Global kill switches are validated and tested
3. [ ] Per-venue kill switches are validated and tested
4. [ ] Strategy throttles are validated and tested
5. [ ] Monitoring is comprehensive and observable
6. [ ] Alerting is timely and reliable
7. [ ] All 80+ reliability tests are implemented and passing
8. [ ] CI pipeline includes reliability test suite
9. [ ] Kill switches work correctly in production
10. [ ] Monitoring/alerting provides visibility in production

---

## References

- `merid/risk/kill_switches.py` - Risk controller with kill switches
- `merid/resilience/circuit_breaker.py` - Circuit breaker implementation
- `merid/core/error_budget.py` - Error budget system
- `merid/loop_robustness.py` - Loop robustness layer
- `merid/alerts/trade_notifier.py` - Trade notifications
- `merid/alerts/webhook_client.py` - Webhook client
- `merid/alerts/reconciliation_alerts.py` - Reconciliation alerts
- `merid/observability/state_transitions.py` - State transition tracking
- `merid/event_venues/kalshi/kalshi_robustness.py` - Kalshi robustness layer
- `merid/execution/execution_queue.py` - Execution queue with throttling

---

**Next Phase:** Phase 7 - Test harness and broken/missing discovery (automated tests, replay, shadow trading)
