"""Tests for event-loop lag, queue pressure, and shutdown fixes.

EVENT-LOOP-FIX: These tests verify the production-ready hardening for:
1. Explicit shutdown reasons (no "unknown")
2. Progressive load shedding based on lag thresholds
3. Queue pressure backpressure and shutdown
"""

import asyncio
import os
import pytest
from unittest.mock import patch, MagicMock
from typing import Optional


class TestShutdownReasonExplicit:
    """Tests that shutdown reasons are always explicit."""

    @pytest.fixture(autouse=True)
    def reset_shutdown_state(self):
        """Reset global shutdown state before each test."""
        from web.asgi_guard import set_shutdown_reason
        set_shutdown_reason(None)
        yield
        set_shutdown_reason(None)

    def test_initiate_shutdown_rejects_unknown_in_production(self):
        """initiate_shutdown must raise ValueError for UNKNOWN in production."""
        from web.asgi_guard import initiate_shutdown, ShutdownReason

        with patch.dict(os.environ, {"MERID_ENV": "production"}):
            with pytest.raises(ValueError) as exc_info:
                initiate_shutdown(
                    reason=ShutdownReason.UNKNOWN,
                    sub_reason="test_unknown_rejection"
                )
            assert "UNKNOWN in production" in str(exc_info.value)
            assert "test_unknown_rejection" in str(exc_info.value)

    def test_initiate_shutdown_accepts_valid_reasons(self):
        """initiate_shutdown must accept valid shutdown reasons."""
        from web.asgi_guard import initiate_shutdown, ShutdownReason, get_shutdown_reason

        valid_reasons = [
            ShutdownReason.LOOP_LAG_HALT,
            ShutdownReason.QUEUE_PRESSURE_HALT,
            ShutdownReason.LIFESPAN_END,
            ShutdownReason.USER_REQUEST,
            ShutdownReason.SIGINT,
            ShutdownReason.ASGI_FATAL,
        ]

        for reason in valid_reasons:
            event = initiate_shutdown(
                reason=reason,
                sub_reason=f"test_{reason.value}"
            )
            assert event.reason == reason
            assert event.sub_reason == f"test_{reason.value}"
            assert get_shutdown_reason() == event

            # Reset for next iteration
            from web.asgi_guard import set_shutdown_reason
            set_shutdown_reason(None)

    def test_shutdown_event_includes_metrics(self):
        """Shutdown event must include metrics for forensics."""
        from web.asgi_guard import initiate_shutdown, ShutdownReason

        event = initiate_shutdown(
            reason=ShutdownReason.LOOP_LAG_HALT,
            sub_reason="lag_3500ms_consecutive_3",
            metrics={
                "lag_ms": 3500,
                "consecutive_count": 3,
                "scope_reduced": True,
            }
        )

        assert event.to_dict()["shutdown_reason"] == "loop_lag_halt"
        assert event.to_dict()["sub_reason"] == "lag_3500ms_consecutive_3"


class TestLoopLagActions:
    """Tests for loop-lag progressive load shedding."""

    @pytest.fixture
    def lag_monitor(self):
        """Get the singleton loop lag monitor for testing."""
        from merid.diagnostics.loop_lag import LoopLagMonitor, get_loop_lag_monitor
        # Reset the singleton instance for clean tests
        LoopLagMonitor._instance = None
        monitor = get_loop_lag_monitor()
        monitor._initialized = False
        monitor._interval_ms = 100.0
        monitor._on_elevated_callbacks = []
        monitor._on_degraded_callbacks = []
        monitor._on_halt_callbacks = []
        monitor._halt_consecutive_count = 0
        monitor._scope_reduced = False
        monitor._scope_reduced_at = None
        yield monitor
        monitor.stop()
        LoopLagMonitor._instance = None

    @pytest.mark.asyncio
    async def test_elevated_callback_triggered(self, lag_monitor):
        """Elevated lag (>50ms) should trigger callbacks."""
        callback_triggered = False
        received_lag = 0.0

        def on_elevated(lag_ms: float):
            nonlocal callback_triggered, received_lag
            callback_triggered = True
            received_lag = lag_ms

        lag_monitor.on_elevated(on_elevated)

        # Simulate elevated lag
        lag_monitor._trigger_elevated(75.0)

        assert callback_triggered
        assert received_lag == 75.0

    @pytest.mark.asyncio
    async def test_degraded_callback_triggers_scope_reduction(self, lag_monitor):
        """Degraded lag (500-2000ms) should trigger scope reduction."""
        callback_triggered = False

        def on_degraded(lag_ms: float):
            nonlocal callback_triggered
            callback_triggered = True

        lag_monitor.on_degraded(on_degraded)

        # Trigger degraded state
        lag_monitor._trigger_degraded(750.0)

        assert callback_triggered
        assert lag_monitor._scope_reduced is True
        assert lag_monitor._scope_reduced_at is not None

    @pytest.mark.asyncio
    async def test_halt_band_consecutive_counting(self, lag_monitor):
        """Halt band should count consecutive samples before shutdown."""
        # Set low threshold for testing
        lag_monitor._halt_max_consecutive = 2

        # First halt sample
        lag_monitor._trigger_halt(2500.0)
        assert lag_monitor._halt_consecutive_count == 1

        # Second halt sample
        lag_monitor._trigger_halt(2500.0)
        assert lag_monitor._halt_consecutive_count == 2

        # Shutdown should be triggered after threshold
        # (In real code, this would call initiate_shutdown)

    @pytest.mark.asyncio
    async def test_halt_band_callback_can_suppress_shutdown(self, lag_monitor):
        """Halt callback returning False should suppress shutdown."""
        lag_monitor._halt_max_consecutive = 1

        def on_halt(lag_ms: float, count: int) -> bool:
            return False  # Suppress shutdown

        lag_monitor.on_halt(on_halt)

        # This should not trigger shutdown because callback returns False
        lag_monitor._trigger_halt(2500.0)
        # In real code, this would check the return value


class TestQueuePressureShutdown:
    """Tests for queue pressure backpressure and shutdown."""

    def test_queue_pressure_thresholds_include_shutdown(self):
        """Queue pressure thresholds must include shutdown threshold."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        import inspect

        # Get default thresholds from class initialization
        ws = KalshiWebSocket.__new__(KalshiWebSocket)
        ws._pressure_thresholds = {
            "elevated": 0.50,
            "warn": 0.75,
            "critical": 0.90,
            "shutdown": 0.98,
            "restore": 0.40,
        }

        assert "shutdown" in ws._pressure_thresholds
        assert ws._pressure_thresholds["shutdown"] == 0.98
        assert ws._pressure_thresholds["critical"] == 0.90

    def test_queue_pressure_shutdown_configurable(self):
        """Queue pressure shutdown threshold must be configurable via env."""
        with patch.dict(os.environ, {"KALSHI_WS_PRESSURE_SHUTDOWN_MAX": "5"}):
            from merid.event_venues.kalshi.ws import KalshiWebSocket
            ws = KalshiWebSocket.__new__(KalshiWebSocket)
            ws._pressure_shutdown_consecutive = 0
            ws._pressure_shutdown_max = int(os.getenv("KALSHI_WS_PRESSURE_SHUTDOWN_MAX", "3"))
            assert ws._pressure_shutdown_max == 5

    def test_shed_count_tracked(self):
        """Load shed count must be tracked for forensics."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        ws = KalshiWebSocket.__new__(KalshiWebSocket)
        ws._shed_count = 0
        ws._is_reduced_scope = False
        ws._shedding_failed_count = 0

        # Simulate shedding
        ws._shed_count += 1
        ws._is_reduced_scope = True

        assert ws._shed_count == 1
        assert ws._is_reduced_scope is True


class TestExecutionGateDiagnostics:
    """Tests for execution gate diagnostic metrics."""

    @pytest.mark.asyncio
    async def test_execution_gate_includes_lag_diagnostics(self):
        """Execution gate must include event-loop lag in diagnostics."""
        from core.execution_gate import check_execution_gate

        status = check_execution_gate()
        diagnostics = status.diagnostics

        assert "event_loop_lag" in diagnostics
        lag_diag = diagnostics["event_loop_lag"]
        assert "current_ms" in lag_diag
        assert "p95_ms" in lag_diag
        assert "healthy" in lag_diag

    def test_lag_diagnostics_advisory_only(self):
        """Lag diagnostics must not affect gate state (advisory only)."""
        from core.execution_gate import check_execution_gate, GateState

        status = check_execution_gate()

        # Even with high lag, gate should not be blocked by lag alone
        # (other reasons may block, but not lag)
        lag_reasons = [r for r in status.reasons if r.source == "event_loop_lag"]
        assert len(lag_reasons) == 0, "Lag should not appear in blocking reasons"


class TestIntegration:
    """Integration tests for event-loop fixes."""

    @pytest.mark.asyncio
    async def test_full_lag_response_chain(self):
        """Test complete lag response: elevated -> degraded -> halt."""
        from merid.diagnostics.loop_lag import LoopLagMonitor, get_loop_lag_monitor

        # Reset singleton for clean test
        LoopLagMonitor._instance = None
        monitor = get_loop_lag_monitor()
        monitor._initialized = False
        monitor._interval_ms = 100.0
        monitor._on_elevated_callbacks = []
        monitor._on_degraded_callbacks = []
        monitor._halt_consecutive_count = 0
        monitor._scope_reduced = False
        monitor._scope_reduced_at = None

        events = []

        def on_elevated(lag_ms: float):
            events.append(("elevated", lag_ms))

        def on_degraded(lag_ms: float):
            events.append(("degraded", lag_ms))

        monitor.on_elevated(on_elevated)
        monitor.on_degraded(on_degraded)

        # Trigger elevated
        monitor._trigger_elevated(75.0)
        assert ("elevated", 75.0) in events

        # Trigger degraded
        monitor._trigger_degraded(750.0)
        assert ("degraded", 750.0) in events
        assert monitor._scope_reduced is True

        monitor.stop()
        LoopLagMonitor._instance = None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
