"""Circuit breaker and kill switch tests for MERID safety systems.

Tests automatic lockdown triggers, recovery flows, and emergency stop functionality.
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from trading.guards.trading_guard import (
    TradingGuard,
    TradingGuardConfig,
    GuardDecision,
    GuardDecisionStatus,
    CircuitBreakerState,
)
from trading.adapters.base import TradeRequest
from trading.config.runtime_config import (
    GlobalTradingMode,
    TradingRuntimeConfig,
)


@pytest.fixture
def test_venue_config():
    """Create a valid test venue configuration."""
    config = TradingRuntimeConfig()
    config.update_global_mode(mode="live", spectator_mode=False, allow_live_trades=True)
    config.upsert_venue(
        "test_venue",
        {
            "label": "Test Venue",
            "mode": "live",
            "max_notional_usd": 50000.0,
        },
    )
    return config


@pytest.fixture
def base_request():
    """Create a base trade request."""
    return TradeRequest(
        venue="test_venue",
        symbol="BTC-USD",
        side="buy",
        quantity=0.1,
        price=50000.0,
        notional_usd=5000.0,
        live=True,
        metadata={},
    )


class TestCircuitBreakerTrigger:
    """Test circuit breaker activation conditions."""

    def test_breaker_opens_after_error_threshold(self, test_venue_config, base_request):
        """Verify breaker opens after consecutive errors exceed threshold."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=3,
            circuit_breaker_window_seconds=60.0,
            circuit_breaker_cooldown_seconds=300.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Circuit starts closed
        assert guard.circuit_state == CircuitBreakerState.CLOSED

        # Record errors below threshold
        guard.record_error()
        guard.record_error()
        assert guard.circuit_state == CircuitBreakerState.CLOSED

        # Third error trips the breaker
        guard.record_error()
        assert guard.circuit_state == CircuitBreakerState.OPEN

        # Requests should now be blocked
        decision = guard.evaluate(base_request, vpn_connected=True)
        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Circuit breaker open" in decision.reason
        assert decision.metadata["circuit_state"] == "open"

    def test_breaker_remains_closed_below_threshold(self, test_venue_config, base_request):
        """Verify breaker stays closed when errors below threshold."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=5,
            circuit_breaker_window_seconds=60.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Record some errors but below threshold
        for _ in range(3):
            guard.record_error()

        assert guard.circuit_state == CircuitBreakerState.CLOSED

        # Request should still be allowed
        decision = guard.evaluate(base_request, vpn_connected=True)
        assert decision.status == GuardDecisionStatus.ALLOW

    def test_breaker_closes_after_recovery_period(self, test_venue_config, base_request):
        """Verify breaker closes after cooldown period."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=2,
            circuit_breaker_window_seconds=60.0,
            circuit_breaker_cooldown_seconds=0.1,  # Short for testing
            circuit_breaker_half_open_max=1,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Trip the breaker
        guard.record_error()
        guard.record_error()
        assert guard.circuit_state == CircuitBreakerState.OPEN

        # Wait for cooldown
        time.sleep(0.15)

        # Next request should transition to half-open and be allowed
        decision = guard.evaluate(base_request, vpn_connected=True)
        assert guard.circuit_state == CircuitBreakerState.HALF_OPEN
        assert decision.status == GuardDecisionStatus.ALLOW

        # Record success to close the circuit
        guard.record_success()
        assert guard.circuit_state == CircuitBreakerState.CLOSED


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    def test_half_open_allows_limited_requests(self, test_venue_config, base_request):
        """Verify half-open state allows limited probe requests."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=2,
            circuit_breaker_window_seconds=60.0,
            circuit_breaker_cooldown_seconds=0.0,  # Immediate half-open
            circuit_breaker_half_open_max=2,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Trip the breaker
        guard.record_error()
        guard.record_error()
        assert guard.circuit_state == CircuitBreakerState.OPEN

        # Force transition to half-open by checking circuit
        time.sleep(0.01)
        guard._check_circuit_for_request(time.time())
        assert guard.circuit_state == CircuitBreakerState.HALF_OPEN

        # First probe request allowed
        decision = guard.evaluate(base_request, vpn_connected=True)
        assert decision.status == GuardDecisionStatus.ALLOW
        guard.record_success()

        # Second probe request allowed
        decision = guard.evaluate(base_request, vpn_connected=True)
        assert decision.status == GuardDecisionStatus.ALLOW
        guard.record_success()

        # Circuit should now be closed
        assert guard.circuit_state == CircuitBreakerState.CLOSED

    def test_half_open_error_reopens_circuit(self, test_venue_config, base_request):
        """Verify error in half-open state reopens the circuit."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=2,
            circuit_breaker_window_seconds=60.0,
            circuit_breaker_cooldown_seconds=0.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Trip the breaker
        guard.record_error()
        guard.record_error()
        assert guard.circuit_state == CircuitBreakerState.OPEN

        # Transition to half-open
        time.sleep(0.01)
        guard._check_circuit_for_request(time.time())
        assert guard.circuit_state == CircuitBreakerState.HALF_OPEN

        # Error in half-open should reopen
        guard.record_error()
        assert guard.circuit_state == CircuitBreakerState.OPEN

    def test_error_window_cleanup(self, test_venue_config):
        """Verify old errors are cleaned up from the window."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=3,
            circuit_breaker_window_seconds=0.1,  # Very short window for testing
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Record errors
        now = time.time()
        guard.record_error(now)
        guard.record_error(now)
        guard.record_error(now)

        # Should be open
        assert guard.circuit_state == CircuitBreakerState.OPEN

        # Wait for window to expire
        time.sleep(0.15)

        # Recording a new error should clean up old ones
        guard.record_error(time.time())

        # Should still be closed since old errors expired
        assert len(guard._error_timestamps) == 1


class TestKillSwitch:
    """Test emergency kill switch functionality via enable_trading_suite flag."""

    def test_kill_switch_blocks_all_trades(self, test_venue_config, base_request):
        """Verify kill switch (trading_suite disabled) blocks all new trades."""
        config = TradingGuardConfig(
            enable_trading_suite=False,  # Kill switch
            allow_live_trades=True,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        decision = guard.evaluate(base_request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Trading suite disabled" in decision.reason

    def test_kill_switch_can_be_deactivated(self, test_venue_config, base_request):
        """Verify kill switch can be deactivated to resume trading."""
        # Start with kill switch on
        config = TradingGuardConfig(
            enable_trading_suite=False,
            allow_live_trades=True,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        decision = guard.evaluate(base_request, vpn_connected=True)
        assert decision.status == GuardDecisionStatus.BLOCK

        # Create new guard with kill switch off
        config2 = TradingGuardConfig(
            enable_trading_suite=True,
            allow_live_trades=True,
        )
        guard2 = TradingGuard(config=config2, runtime_config=test_venue_config)

        decision = guard2.evaluate(base_request, vpn_connected=True)
        assert decision.status == GuardDecisionStatus.ALLOW


class TestAutomaticLockdown:
    """Test automatic lockdown on critical conditions."""

    def test_daily_loss_lockdown(self, test_venue_config, base_request):
        """Verify lockdown when daily loss exceeds limit."""
        from merid.execution.portfolio import PortfolioAggregator

        config = TradingGuardConfig(
            allow_live_trades=True,
            max_daily_loss_usd=10000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)
        portfolio = PortfolioAggregator()

        # Record a big loss
        portfolio.record_trade_pnl(-15000.0)

        decision = guard.evaluate(base_request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Daily loss limit exceeded" in decision.reason

    def test_circuit_breaker_lockdown(self, test_venue_config, base_request):
        """Verify automatic lockdown when circuit breaker trips."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=1,
            circuit_breaker_window_seconds=60.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Single error trips breaker with threshold=1
        guard.record_error()

        decision = guard.evaluate(base_request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Circuit breaker open" in decision.reason


class TestSafetyMonitoring:
    """Test safety monitoring and alerting."""

    def test_circuit_state_reported_in_metadata(self, test_venue_config, base_request):
        """Verify circuit state is reported in decision metadata."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=2,
            circuit_breaker_window_seconds=60.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Trip the breaker
        guard.record_error()
        guard.record_error()

        decision = guard.evaluate(base_request, vpn_connected=True)

        assert decision.metadata["circuit_state"] == "open"
        assert "errors_in_window" in decision.metadata

    def test_error_count_tracked(self, test_venue_config):
        """Verify error count is tracked correctly."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            circuit_breaker_threshold=5,
            circuit_breaker_window_seconds=60.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        assert len(guard._error_timestamps) == 0

        guard.record_error()
        assert len(guard._error_timestamps) == 1

        guard.record_error()
        guard.record_error()
        assert len(guard._error_timestamps) == 3
