# Exit Policy Test and Telemetry Plan
## MERID 15M Kalshi Crypto Trading System

**Created:** 2026-07-06  
**Purpose:** Comprehensive test and telemetry plan for exit policy validation to ensure "No Trade Without Exit" compliance.

---

## Test Strategy Overview

**Testing Layers:**
1. **Unit Tests:** Test individual components in isolation
2. **Integration Tests:** Test component interactions
3. **End-to-End Tests:** Test full trading flow
4. **Invariant Tests:** Test compliance with exit policy invariants
5. **Chaos Tests:** Test failure modes and recovery
6. **Performance Tests:** Test monitoring loop performance under load

**Test Coverage Goals:**
- 100% coverage of exit policy validation logic
- 100% coverage of monitoring loop exit triggers
- 100% coverage of risk contract linkage checks
- 90%+ coverage of edge cases and failure modes

---

## Unit Tests

### Test Suite: `tests/test_exit_policy_resolution.py`

**Purpose:** Test exit policy resolution logic

**Test Cases:**

```python
class TestExitPolicyResolution:
    """Test exit policy resolution from configuration."""
    
    def test_resolve_exit_policy_uses_config(self):
        """Exit policy must be resolved from config, not hardcoded."""
        from merid.event_venues.kalshi.order_router import resolve_exit_policy
        
        result = resolve_exit_policy(
            edge_result={"edge_pct": 0.03},
            asset="BTC",
            regime="normal"
        )
        
        # Verify TP/SL are computed, not hardcoded
        assert result.tp_price_cents is not None
        assert result.sl_price_cents is not None
        assert result.sl_cents == abs(result.entry_price_cents - result.sl_price_cents)
    
    def test_resolve_exit_policy_sl_cents_computed(self):
        """sl_cents must be computed from entry and SL prices."""
        from merid.event_venues.kalshi.order_router import resolve_exit_policy
        
        result = resolve_exit_policy(
            edge_result={"edge_pct": 0.03},
            asset="BTC",
            regime="normal"
        )
        
        # Verify sl_cents is computed (not hardcoded to 5)
        expected_sl_cents = abs(result.entry_price_cents - result.sl_price_cents)
        assert result.sl_cents == expected_sl_cents
    
    def test_resolve_exit_policy_trailing_from_config(self):
        """Trailing parameters must come from config."""
        from merid.event_venues.kalshi.order_router import resolve_exit_policy
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile = get_active_profile().profile
        result = resolve_exit_policy(
            edge_result={"edge_pct": 0.03},
            asset="BTC",
            regime="normal"
        )
        
        # Verify trailing matches config
        assert result.trailing_enabled == profile.trailing_stop_enabled
        assert result.trailing_distance_cents == profile.trailing_stop_trailing_distance_cents
    
    def test_resolve_exit_policy_time_exit_from_config(self):
        """Time exit parameters must come from config."""
        from merid.event_venues.kalshi.order_router import resolve_exit_policy
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile = get_active_profile().profile
        result = resolve_exit_policy(
            edge_result={"edge_pct": 0.03},
            asset="BTC",
            regime="normal"
        )
        
        # Verify time exit matches config
        expected_max_hold = profile.time_exit_max_hold_minutes * 60
        assert result.max_hold_seconds == expected_max_hold
```

---

### Test Suite: `tests/test_risk_contract_linkage.py`

**Purpose:** Test risk contract linkage validation

**Test Cases:**

```python
class TestRiskContractLinkage:
    """Test risk contract linkage validation."""
    
    def test_entry_order_requires_all_fields(self):
        """Entry orders must have all risk contract fields."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _validate_risk_contract_linkage
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id="15m",
            exit_policy_id="standard",
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert valid, f"Valid intent should pass: {reason}"
    
    def test_entry_order_missing_window_resolution_rejected(self):
        """Entry orders without window_resolution_id are rejected."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _validate_risk_contract_linkage
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id=None,
            exit_policy_id="standard",
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert not valid
        assert "window_resolution_id" in reason
    
    def test_entry_order_missing_exit_policy_rejected(self):
        """Entry orders without exit_policy_id are rejected."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _validate_risk_contract_linkage
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id="15m",
            exit_policy_id=None,
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert not valid
        assert "exit_policy_id" in reason
    
    def test_exit_order_requires_exit_policy_id(self):
        """Exit orders must have exit_policy_id for tracking."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _validate_risk_contract_linkage
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="sell",
            price_cents=50,
            count=5,
            exit_policy_id="standard",
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert valid, f"Exit order with exit_policy_id should pass: {reason}"
    
    def test_exit_order_missing_exit_policy_rejected(self):
        """Exit orders without exit_policy_id are rejected."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _validate_risk_contract_linkage
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="sell",
            price_cents=50,
            count=5,
            exit_policy_id=None,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert not valid
        assert "exit_policy_id" in reason
    
    def test_non_crypto_markets_exempt(self):
        """Non-crypto markets are exempt from exit policy requirements."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _validate_risk_contract_linkage
        
        intent = OrderIntent(
            ticker="KXTEST-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
        )
        
        valid, reason = _validate_risk_contract_linkage(intent)
        assert valid, f"Non-crypto markets should be exempt: {reason}"
```

---

### Test Suite: `tests/test_position_monitor.py`

**Purpose:** Test position monitoring and exit triggers

**Test Cases:**

```python
class TestPositionMonitor:
    """Test position monitoring and exit triggers."""
    
    @pytest.fixture
    def monitor(self):
        from merid.position_management.position_monitor import get_position_monitor
        return get_position_monitor()
    
    @pytest.fixture
    def sample_position(self):
        from merid.position_management.position import Position, PositionSide
        return Position(
            position_id="test-position-1",
            market_id="KXBTC15M-26JUL051900-00",
            side=PositionSide.YES,
            size=5,
            avg_entry_price_cents=50,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
        )
    
    def test_extreme_profit_trigger(self, monitor, sample_position):
        """Extreme profit trigger fires at 99c YES."""
        from merid.position_management.exit_policy import ExitReason
        
        # Simulate price at 99c
        monitor._check_position(sample_position, 99)
        
        # Verify exit intent was emitted
        assert sample_position.exit_reason == ExitReason.EXTREME_PROFIT
        assert sample_position.exit_price_cents == 99
    
    def test_stop_loss_trigger(self, monitor, sample_position):
        """Stop loss trigger fires when price hits SL."""
        from merid.position_management.exit_policy import ExitReason
        
        # Simulate price at SL (45c)
        monitor._check_position(sample_position, 45)
        
        # Verify exit intent was emitted
        assert sample_position.exit_reason == ExitReason.STOP_LOSS
        assert sample_position.exit_price_cents == 45
    
    def test_take_profit_trigger(self, monitor, sample_position):
        """Take profit trigger fires when price hits TP."""
        from merid.position_management.exit_policy import ExitReason
        
        # Simulate price at TP (60c)
        monitor._check_position(sample_position, 60)
        
        # Verify exit intent was emitted
        assert sample_position.exit_reason == ExitReason.TAKE_PROFIT
        assert sample_position.exit_price_cents == 60
    
    def test_trailing_stop_activation(self, monitor, sample_position):
        """Trailing stop activates after minimum profit threshold."""
        # Simulate price at 65c (15c profit, above 12c threshold)
        monitor._check_position(sample_position, 65)
        
        # Verify trailing was activated
        assert sample_position.trailing_activated is True
    
    def test_exit_trigger_precedence(self, monitor, sample_position):
        """Exit triggers fire in correct precedence order."""
        from merid.position_management.exit_policy import ExitReason
        
        # Set up position that would trigger multiple exits
        sample_position.take_profit_price_cents = 60
        sample_position.stop_loss_price_cents = 45
        
        # Simulate price at 99c (extreme profit should fire first)
        monitor._check_position(sample_position, 99)
        
        # Verify extreme profit fired (highest priority)
        assert sample_position.exit_reason == ExitReason.EXTREME_PROFIT
    
    def test_position_without_tp_sl_rejected(self, monitor):
        """Positions without TP/SL are rejected or flagged as unhealthy."""
        from merid.position_management.position import Position, PositionSide
        
        position = Position(
            position_id="test-position-2",
            market_id="KXBTC15M-26JUL051900-00",
            side=PositionSide.YES,
            size=5,
            avg_entry_price_cents=50,
            take_profit_price_cents=None,  # Missing
            stop_loss_price_cents=None,  # Missing
        )
        
        # Verify position is flagged as unhealthy
        assert monitor.is_position_healthy(position.position_id) is False
```

---

### Test Suite: `tests/test_pre_trade_gate.py`

**Purpose:** Test pre-trade gate exit policy validation

**Test Cases:**

```python
class TestPreTradeGate:
    """Test pre-trade gate exit policy validation."""
    
    @pytest.fixture
    def gate(self):
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        return PreTradeGate()
    
    def test_entry_order_without_exit_policy_rejected(self, gate):
        """Entry orders without exit policy metadata are rejected."""
        verdict = gate.check(
            agent_id="BTC_15M",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            target_count=5,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id=None,  # Missing
            window_resolution_id=None,  # Missing
            risk_tier=None,  # Missing
            max_hold_seconds=None,  # Missing
        )
        
        assert verdict.allowed is False
        assert "exit_policy_id" in verdict.reason
    
    def test_exit_order_without_exit_policy_rejected(self, gate):
        """Exit orders without exit_policy_id are rejected."""
        verdict = gate.check(
            agent_id="BTC_15M",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL051900-00",
            side="yes",
            action="sell",
            target_count=5,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id=None,  # Missing
        )
        
        assert verdict.allowed is False
        assert "exit_policy_id" in verdict.reason
    
    def test_entry_order_with_exit_policy_allowed(self, gate):
        """Entry orders with exit policy metadata are allowed."""
        verdict = gate.check(
            agent_id="BTC_15M",
            strategy_group="btc_15m",
            contract_id="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            target_count=5,
            price_cents=50,
            decision_ts=time.time(),
            exit_policy_id="standard",
            window_resolution_id="15m",
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        # Assuming other checks pass
        # assert verdict.allowed is True
```

---

## Integration Tests

### Test Suite: `tests/integration/test_exit_policy_flow.py`

**Purpose:** Test end-to-end exit policy flow

**Test Cases:**

```python
class TestExitPolicyFlow:
    """Test end-to-end exit policy flow."""
    
    @pytest.mark.asyncio
    async def test_order_with_exit_policy_routes_successfully(self):
        """Order with exit policy routes successfully."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id="15m",
            exit_policy_id="standard",
            risk_tier="moderate",
            max_hold_seconds=900,
        )
        
        result = await route_order_async(intent)
        
        # Verify order was routed (in paper mode)
        assert result.status in ["filled", "submitted"]
    
    @pytest.mark.asyncio
    async def test_order_without_exit_policy_rejected(self):
        """Order without exit policy is rejected."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL051900-00",
            side="yes",
            action="buy",
            price_cents=50,
            count=5,
            window_resolution_id=None,  # Missing
            exit_policy_id=None,  # Missing
            risk_tier=None,  # Missing
            max_hold_seconds=None,  # Missing
        )
        
        result = await route_order_async(intent)
        
        # Verify order was rejected
        assert result.status == "rejected"
        assert "exit_policy_id" in result.reason
    
    @pytest.mark.asyncio
    async def test_fill_registers_tp_sl_targets(self):
        """Fill registers TP/SL targets with position cache."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        cache = get_position_cache()
        
        # Simulate fill
        await cache.handle_fill(
            market_id="KXBTC15M-26JUL051900-00",
            side="yes",
            price_cents=50,
            contracts=5,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
        )
        
        # Verify TP/SL were registered
        position = cache.get_position("KXBTC15M-26JUL051900-00")
        assert position.take_profit_price_cents == 60
        assert position.stop_loss_price_cents == 45
    
    @pytest.mark.asyncio
    async def test_position_monitor_triggers_exit(self):
        """Position monitor triggers exit when conditions are met."""
        from merid.position_management.position_monitor import get_position_monitor
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        monitor = get_position_monitor()
        cache = get_position_cache()
        
        # Add position
        await cache.handle_fill(
            market_id="KXBTC15M-26JUL051900-00",
            side="yes",
            price_cents=50,
            contracts=5,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
        )
        
        # Simulate price hitting TP
        # (This would require mocking market state)
        # monitor._check_position(...)
        
        # Verify exit intent was emitted
        # assert exit_intent_callback_called is True
```

---

## Chaos Tests

### Test Suite: `tests/chaos/test_exit_policy_resilience.py`

**Purpose:** Test exit policy system under failure conditions

**Test Cases:**

```python
class TestExitPolicyResilience:
    """Test exit policy system resilience."""
    
    @pytest.mark.asyncio
    async def test_monitoring_loop_recovers_from_transient_error(self):
        """Monitoring loop recovers from transient errors."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        cache = get_position_cache()
        
        # Simulate transient error in monitoring loop
        # (This would require mocking the loop)
        
        # Verify loop recovers and continues monitoring
        assert cache._monitoring_enabled is True
    
    @pytest.mark.asyncio
    async def test_monitoring_loop_halts_on_persistent_failure(self):
        """Monitoring loop halts after persistent failures."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        cache = get_position_cache()
        
        # Simulate persistent errors (5+ consecutive)
        # (This would require mocking the loop)
        
        # Verify loop halts and triggers trading halt
        assert cache._monitoring_enabled is False
    
    @pytest.mark.asyncio
    async def test_position_without_tp_sl_flagged_unhealthy(self):
        """Position without TP/SL is flagged as unhealthy."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        cache = get_position_cache()
        
        # Add position without TP/SL
        await cache.handle_fill(
            market_id="KXBTC15M-26JUL051900-00",
            side="yes",
            price_cents=50,
            contracts=5,
            take_profit_price_cents=None,  # Missing
            stop_loss_price_cents=None,  # Missing
        )
        
        # Verify position is flagged as unhealthy
        assert cache.is_position_healthy("KXBTC15M-26JUL051900-00") is False
    
    @pytest.mark.asyncio
    async def test_config_load_failure_uses_safe_defaults(self):
        """Config load failure uses safe defaults."""
        from merid.event_venues.kalshi.dynamic_risk import DynamicRiskEngine
        
        engine = DynamicRiskEngine()
        
        # Simulate config load failure
        # (This would require mocking the config loader)
        
        # Verify safe defaults are used
        # assert engine.sl_cents_map == {VolatilityRegime.NORMAL: 8}
```

---

## Performance Tests

### Test Suite: `tests/performance/test_monitoring_loop_performance.py`

**Purpose:** Test monitoring loop performance under load

**Test Cases:**

```python
class TestMonitoringLoopPerformance:
    """Test monitoring loop performance."""
    
    @pytest.mark.asyncio
    async def test_monitoring_loop_handles_100_positions(self):
        """Monitoring loop handles 100 positions within interval."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        import time
        
        cache = get_position_cache()
        
        # Add 100 positions
        for i in range(100):
            await cache.handle_fill(
                market_id=f"KXBTC15M-26JUL051900-{i}",
                side="yes",
                price_cents=50,
                contracts=5,
                take_profit_price_cents=60,
                stop_loss_price_cents=45,
            )
        
        # Measure loop tick time
        start_time = time.time()
        # Trigger one loop iteration
        # (This would require triggering the loop manually)
        end_time = time.time()
        
        # Verify loop completes within interval (5s)
        assert (end_time - start_time) < 5.0
    
    @pytest.mark.asyncio
    async def test_monitoring_loop_tick_interval_consistent(self):
        """Monitoring loop tick interval is consistent."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        import time
        
        cache = get_position_cache()
        
        # Measure multiple tick intervals
        intervals = []
        for _ in range(10):
            start_time = time.time()
            # Trigger one loop iteration
            # (This would require triggering the loop manually)
            end_time = time.time()
            intervals.append(end_time - start_time)
        
        # Verify intervals are consistent (within 20% variance)
        avg_interval = sum(intervals) / len(intervals)
        for interval in intervals:
            assert abs(interval - avg_interval) / avg_interval < 0.2
```

---

## Telemetry Plan

### Metrics to Collect

**Exit Policy Metrics:**

1. **Exit Policy Resolution Metrics:**
   - `merid_exit_policy_resolution_total` - Total exit policy resolutions
   - `merid_exit_policy_resolution_success_total` - Successful resolutions
   - `merid_exit_policy_resolution_failure_total` - Failed resolutions
   - `merid_exit_policy_resolution_duration_seconds` - Resolution duration

2. **Risk Contract Validation Metrics:**
   - `merid_risk_contract_validation_total` - Total validations
   - `merid_risk_contract_validation_success_total` - Successful validations
   - `merid_risk_contract_validation_failure_total` - Failed validations
   - `merid_risk_contract_validation_failure_reason` - Failure reason (label)

3. **Position Monitoring Metrics:**
   - `merid_position_monitor_loop_tick_total` - Total loop ticks
   - `merid_position_monitor_loop_error_total` - Total loop errors
   - `merid_position_monitor_loop_duration_seconds` - Loop duration
   - `merid_position_monitor_positions_monitored` - Positions monitored per tick

4. **Exit Trigger Metrics:**
   - `merid_exit_trigger_total` - Total exit triggers
   - `merid_exit_trigger_success_total` - Successful exit triggers
   - `merid_exit_trigger_failure_total` - Failed exit triggers
   - `merid_exit_trigger_reason` - Exit reason (label: EXTREME_PROFIT, STOP_LOSS, TAKE_PROFIT, etc.)

5. **Unhealthy Position Metrics:**
   - `merid_unhealthy_position_total` - Total unhealthy positions
   - `merid_unhealthy_position_by_reason` - Unhealthy reason (label: MISSING_TP, MISSING_SL, etc.)

6. **Monitoring Loop Health Metrics:**
   - `merid_monitoring_loop_health_alerts_total` - Total health alerts
   - `merid_monitoring_loop_health_alerts_total` - Health alert type (label: slow, error)
   - `merid_monitoring_loop_uptime_seconds` - Loop uptime

### Alerting Rules

**Critical Alerts (P0):**
- Exit policy resolution failure rate > 5%
- Risk contract validation failure rate > 5%
- Monitoring loop stopped
- Monitoring loop error rate > 10%
- Unhealthy position count > 0

**Warning Alerts (P1):**
- Exit policy resolution duration > 1s
- Monitoring loop tick duration > 2s
- Monitoring loop tick interval variance > 50%

### Logging

**Critical Logs:**
- Exit policy resolution failures with full context
- Risk contract validation failures with missing fields
- Monitoring loop errors with stack trace
- Exit trigger failures with position details
- Unhealthy position detection with market_id

**Debug Logs:**
- Exit policy resolution parameters
- Risk contract validation details
- Monitoring loop tick timing
- Exit trigger evaluation details
- Position state changes

### Dashboards

**Exit Policy Dashboard:**
1. Exit policy resolution success rate
2. Risk contract validation success rate
3. Monitoring loop health (uptime, error rate, tick duration)
4. Exit trigger breakdown by reason
5. Unhealthy position count
6. Exit policy resolution duration histogram

---

## Test Execution Plan

**CI/CD Integration:**
1. Run unit tests on every commit
2. Run integration tests on every PR
3. Run chaos tests nightly
4. Run performance tests weekly

**Test Coverage:**
- Target: 90%+ coverage for exit policy code
- Report coverage in CI
- Block PRs with coverage regression

**Test Data:**
- Use synthetic test data for unit tests
- Use anonymized production data for integration tests (if available)
- Mock external dependencies (Kalshi API, market state)

---

## Validation Checklist

After implementing test and telemetry plan:
- [ ] All unit tests implemented and passing
- [ ] All integration tests implemented and passing
- [ ] All chaos tests implemented and passing
- [ ] All performance tests implemented and passing
- [ ] Metrics collection implemented
- [ ] Alerting rules configured
- [ ] Logging enhanced
- [ ] Dashboards created
- [ ] CI/CD integration complete
- [ ] Test coverage target met
- [ ] Documentation updated

---

## Next Steps

See `docs/EXIT_POLICY_COMPLIANCE_CHECKLIST.md` for final compliance checklist.
