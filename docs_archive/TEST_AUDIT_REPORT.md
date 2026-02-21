# MERID Test Suite Audit Report

## Executive Summary

**Current State**: ~76 test files across unit/integration/E2E with 14 pytest markers. **Critical Gap**: Risk/trading flow coverage insufficient for production trading.

## 1. Test Inventory (76 files)

| Category | Count | Key Files |
|----------|-------|-----------|
| Unit | 2 | `test_execution_router.py`, `test_trade_executor.py` |
| Integration | 9 | `test_full_cycle.py`, `test_prediction_arbitrage*.py`, `test_resilience_gates.py` |
| Risk | 10 | `test_multi_venue_router.py`, `test_acl_policies.py`, `test_venue_onboarding.py` |
| Safety | 2 | `test_exposure_limits.py`, `test_execution_mev.py` |
| Swarm | 67 | Agent/orchestration tests |
| Core | 3 | `test_consensus_gate.py`, `test_adversarial_hardening.py` |

**Markers Defined**: `safety_critical`, `risk_core`, `prod_integration`, `stress_core`, `e2e`, `cross_mode`

## 2. Critical Coverage Gaps

| Domain | Risk Level | Missing Coverage |
|--------|-----------|------------------|
| **Risk Limits** | CRITICAL | No tests for daily loss limits, per-symbol caps, kill switches |
| **Venue Adapters** | CRITICAL | No tests for Kalshi/Polymarket failure modes (timeouts, partial fills) |
| **Circuit Breakers** | HIGH | No tests for lockdown triggers or recovery flows |
| **Order Lifecycle** | HIGH | Missing: retry logic, idempotency, reconciliation |
| **Persistence** | MEDIUM | No DB failure/recovery tests |
| **Observability** | MEDIUM | No incident logging path tests |

## 3. Critical Flow Audit

| Flow | Status | Test File | Gaps |
|------|--------|-----------|------|
| Signal→Risk→Order | PARTIAL | `test_execution_router.py` | No failure mode tests |
| Daily P&L Limits | MISSING | - | No enforcement tests |
| Circuit Breaker | MISSING | - | No trigger/recovery tests |
| Exchange Outage | MISSING | - | No timeout/stale data tests |
| Dashboard API | PARTIAL | `test_prediction_arbitrage_ui.py` | No intervention tests |

## 4. New Test Skeletons

### Priority 1: Risk Enforcement

**File**: `tests/risk/test_risk_limits.py`

```python
@pytest.mark.risk_core
async def test_blocks_order_when_daily_loss_exceeded():
    """Verify orders blocked when daily loss limit hit."""
    router = ExecutionRouter()
    # Seed with loss at limit
    router._portfolio_aggregator.record_pnl(-24999)  # $25k limit
    
    result = await router.submit_trade(
        trader=mock_trader,
        venue_id="kalshi",
        symbol="BTC-USD",
        side="buy",
        size=1000,
    )
    assert result.success is False
    assert "daily loss limit" in result.error.lower()
```

### Priority 2: Venue Failure Modes

**File**: `tests/integration/test_venue_failure_modes.py`

```python
@pytest.mark.integration
async def test_kalshi_timeout_fallback():
    """Verify graceful handling of Kalshi API timeout."""
    executor = KalshiExecutor(timeout=0.001)  # Force timeout
    result = await executor.execute_trade(
        symbol="BTC-USD", side="buy", amount=100
    )
    assert result.success is False
    assert result.error is not None
```

### Priority 3: Circuit Breaker

**File**: `tests/safety/test_circuit_breaker.py`

```python
@pytest.mark.safety_critical
async def test_circuit_breaker_triggers_on_error_spike():
    """Verify breaker opens after error threshold."""
    guard = TradingGuard()
    # Simulate error burst
    for _ in range(10):
        guard.record_error()
    
    decision = guard.evaluate(mock_request)
    assert decision.status == GuardDecisionStatus.BLOCK
    assert "circuit breaker" in decision.reason.lower()
```

## 5. Test Suite Improvements

1. **Fixtures**: Add session-scoped DB and venue stubs in `conftest.py`
2. **Markers**: Add `@pytest.mark.risk_limits`, `@pytest.mark.venue_failure`
3. **Coverage**: Set threshold at 80% for `merid/execution`, `trading/guards`
4. **CI**: Fast unit on PR, full integration nightly

## 6. Prioritized Roadmap

### Blockers (Before Real Money)
1. `tests/risk/test_risk_limits.py` - Daily loss, per-symbol caps
2. `tests/integration/test_venue_failure_modes.py` - All venue adapters
3. `tests/safety/test_circuit_breaker.py` - Lockdown + recovery

### High Value (Next Sprint)
4. `tests/integration/test_order_reconciliation.py` - Idempotency, replay
5. `tests/core/test_persistence_failures.py` - DB recovery
6. `tests/safety/test_kill_switch.py` - Emergency stop

### Nice-to-Have
7. Property-based tests for P&L calculations
8. Chaos engineering tests for exchange outages

---
**Total Estimated Effort**: 3-4 weeks for blockers, 6-8 weeks for complete coverage.
