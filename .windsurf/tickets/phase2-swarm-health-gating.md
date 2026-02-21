# Phase 2: Swarm Health Gating Integration

**Priority:** Medium  
**Baseline:** Commit `c25d2702` - Kalshi WS bridge + explainability integration  
**Component:** `merid/prediction/trading_agent.py`, `web/api/explainability.py`, `core/session_guard.py`

## Summary

Integrate swarm health checks into trading decisions and dashboard APIs to enforce the requirement that all agents and swarms must be online, synchronized, and at 100% health before approving trades or serving dashboard data.

## Acceptance Criteria

### 1. Trading Agent Health Gate

- [ ] Mock `get_session_guard()` to return degraded health status (<100%)
- [ ] Attempt to place order via `KalshiTradingAgent`
- [ ] Verify trading agent refuses order placement
- [ ] Assert explainability record emitted with swarm health block reason
- [ ] Test multiple degradation scenarios:
  - Consensus engine at 50%
  - Risk manager unavailable
  - Event bus disconnected

### 2. Dashboard API Health Gate

- [ ] Mock degraded agent health in orchestrator
- [ ] Call `/api/v1/explainability/decisions`
- [ ] Verify response includes warning: `⚠️ Data unverified — swarm health degraded`
- [ ] Option 1: Return partial data with clear health warning metadata
- [ ] Option 2: Block output entirely with 503 Service Unavailable + health status
- [ ] Test portfolio endpoints (`/api/portfolio/summary`) with degraded state

### 3. Health Status Propagation

- [ ] Verify explainability records capture swarm health state snapshot
- [ ] Health metadata includes:
  - Component name (e.g., "consensus_engine")
  - Current health score (0.0 - 1.0)
  - Required minimum threshold (typically 1.0)
  - Timestamp of health check
- [ ] Dashboard displays health warnings prominently in UI

### 4. Recovery Behavior

- [ ] Test health recovery: degraded → healthy transition
- [ ] Verify trading agent resumes normal operation after health restored
- [ ] Confirm dashboard APIs clear warnings when health returns to 100%
- [ ] Test rapid health fluctuations don't cause race conditions

## Test File Location

`tests/integration/test_swarm_health_gating.py`

## Implementation Notes

- Use `core.session_guard.SessionGuard` for health checks
- Mock health status via dependency injection or test fixtures
- Consider circuit breaker pattern for repeated health check failures
- Ensure health checks don't introduce significant latency (<10ms)

## Definition of Done

- [ ] Trading agent blocks orders when health < 100%
- [ ] Dashboard APIs surface health warnings or block output
- [ ] Explainability records include health state context
- [ ] Recovery path validated
- [ ] CI green
