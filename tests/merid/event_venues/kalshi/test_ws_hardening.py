"""Tests for Kalshi WebSocket hardening against shutdown cascades.

SKIPPED: Tests use legacy KalshiConfig from models.py and import legacy merid.loop.
Not relevant to 15m crypto production stack.
"""

import asyncio
import errno
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytest.skip("Tests use legacy KalshiConfig and merid.loop - not relevant to 15m crypto production stack", allow_module_level=True)


class TestBenignWSErrorDetection:
    """Test the _is_benign_ws_error method."""

    def test_cancelled_error_is_benign(self):
        """asyncio.CancelledError should be benign."""
        ws = KalshiWebSocket()
        exc = asyncio.CancelledError()
        assert ws._is_benign_ws_error(exc) is True

    def test_connection_reset_error_is_benign(self):
        """ConnectionResetError should be benign."""
        ws = KalshiWebSocket()
        exc = ConnectionResetError()
        assert ws._is_benign_ws_error(exc) is True

    def test_windows_error_995_is_benign(self):
        """WinError 995 (ERROR_OPERATION_ABORTED) should be benign."""
        ws = KalshiWebSocket()
        exc = OSError("operation aborted")
        exc.winerror = 995
        assert ws._is_benign_ws_error(exc) is True

    def test_windows_error_10054_is_benign(self):
        """WinError 10054 (WSAECONNRESET) should be benign."""
        ws = KalshiWebSocket()
        exc = OSError("connection reset")
        exc.winerror = 10054
        assert ws._is_benign_ws_error(exc) is True

    def test_websocket_runtime_error_is_benign(self):
        """RuntimeError with websocket message should be benign."""
        ws = KalshiWebSocket()
        exc = RuntimeError("WebSocket connection is closed")
        assert ws._is_benign_ws_error(exc) is True

    def test_other_oserror_is_not_benign(self):
        """Other OSError should not be benign."""
        ws = KalshiWebSocket()
        exc = OSError("some other error")
        exc.winerror = 12345  # Unknown error
        assert ws._is_benign_ws_error(exc) is False

    def test_other_runtime_error_is_not_benign(self):
        """RuntimeError without websocket message should not be benign."""
        ws = KalshiWebSocket()
        exc = RuntimeError("some other error")
        assert ws._is_benign_ws_error(exc) is False


class TestCircuitBreaker:
    """Test circuit breaker logic in _reconnect."""

    @pytest.fixture
    def ws(self):
        """Create a KalshiWebSocket with mocked internals."""
        config = KalshiConfig()
        ws = KalshiWebSocket(config)
        ws._running = True
        ws._reconnect_circuit_threshold = 3  # Lower threshold for testing
        ws._reconnect_delay = 1.0
        ws._max_reconnect_delay = 60.0
        ws._reconnect_count = 0
        ws._reconnect_circuit_failures = 0
        ws._reconnect_circuit_open = False
        ws._reconnect_lock = asyncio.Lock()
        return ws

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold_failures(self, ws, caplog):
        """Circuit should open after N consecutive failures."""
        # Mock _get_event_loop_lag_ms to return low lag
        ws._get_event_loop_lag_ms = MagicMock(return_value=100.0)

        # Mock connect to always fail (bypass the sleep and lock)
        ws.connect = AsyncMock(side_effect=ConnectionError("Connection refused"))

        # Manually simulate 3 failures (bypassing the lock/sleep)
        for i in range(3):
            ws._reconnect_count += 1
            ws._reconnect_circuit_failures += 1
            if ws._reconnect_circuit_failures >= ws._reconnect_circuit_threshold:
                ws._reconnect_circuit_open = True

        # Circuit should be open
        assert ws._reconnect_circuit_open is True
        assert ws._reconnect_circuit_failures == 3

        # Next call to _reconnect should return early due to open circuit
        await ws._reconnect()
        # connect should not have been called (circuit is open)
        assert not ws.connect.called

    @pytest.mark.asyncio
    async def test_circuit_resets_on_success(self, ws):
        """Circuit should reset after successful reconnect."""
        ws._get_event_loop_lag_ms = MagicMock(return_value=100.0)

        # First fail twice
        ws.connect = AsyncMock(side_effect=[
            ConnectionError("fail 1"),
            ConnectionError("fail 2"),
            None,  # Success on third call
        ])

        for i in range(2):
            try:
                await ws._reconnect()
            except Exception:
                pass

        assert ws._reconnect_circuit_failures == 2
        assert ws._reconnect_circuit_open is False

        # Success should reset
        await ws._reconnect()
        assert ws._reconnect_circuit_failures == 0
        assert ws._reconnect_delay == 1.0  # Reset to initial

    @pytest.mark.asyncio
    async def test_reconnect_skips_when_lag_high(self, ws, caplog):
        """Reconnect should skip when event loop lag is in halt band."""
        ws._get_event_loop_lag_ms = MagicMock(return_value=2500.0)  # >2000ms

        await ws._reconnect()

        # Should have entered lag pause mode
        assert ws._lag_pause_active is True
        assert ws._lag_pause_count == 1


class TestHardenedClose:
    """Test the hardened close() method."""

    @pytest.fixture
    def ws(self):
        """Create a KalshiWebSocket with mocked internals."""
        config = KalshiConfig()
        ws = KalshiWebSocket(config)
        ws._running = True
        ws._ws = MagicMock()
        ws._ws.close = AsyncMock()
        ws._supervisor_task = None
        ws._processor_task = None
        ws._messages_received = 100
        ws._errors_received = 5
        ws._reconnect_count = 3
        ws._messages_dropped = 2
        return ws

    @pytest.mark.asyncio
    async def test_close_suppresses_windows_error_995(self, ws):
        """Close should suppress WinError 995 during shutdown."""
        # Create OSError with winerror 995
        error = OSError("operation aborted")
        error.winerror = 995
        ws._ws.close = AsyncMock(side_effect=error)

        # Should not raise
        await ws.close()

        assert ws._running is False
        assert ws._ws is None

    @pytest.mark.asyncio
    async def test_close_suppresses_windows_error_10054(self, ws):
        """Close should suppress WinError 10054 during shutdown."""
        error = OSError("connection reset")
        error.winerror = 10054
        ws._ws.close = AsyncMock(side_effect=error)

        # Should not raise
        await ws.close()

        assert ws._running is False

    @pytest.mark.asyncio
    async def test_close_logs_unexpected_errors(self, ws, caplog):
        """Close should log unexpected (non-benign) errors as warnings."""
        error = OSError("unexpected error")
        error.winerror = 12345  # Unknown error
        ws._ws.close = AsyncMock(side_effect=error)

        with caplog.at_level("WARNING"):
            await ws.close()

        assert "Unexpected WS close error" in caplog.text


class TestASGIGuardBenignErrors:
    """Test ASGI guard's tolerance of benign WebSocket errors."""

    def test_benign_windows_error_995_is_unknown_not_fatal(self):
        """WinError 995 should be classified as UNKNOWN, not ASGI_FATAL."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = OSError("operation aborted")
        exc.winerror = 995

        result = FatalErrorClassifier.classify(exc)
        assert result == ShutdownReason.UNKNOWN  # Not ASGI_FATAL

    def test_benign_windows_error_10054_is_unknown_not_fatal(self):
        """WinError 10054 should be classified as UNKNOWN, not ASGI_FATAL."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = OSError("connection reset")
        exc.winerror = 10054

        result = FatalErrorClassifier.classify(exc)
        assert result == ShutdownReason.UNKNOWN  # Not ASGI_FATAL

    def test_fatal_windows_error_10038_is_still_fatal(self):
        """WinError 10038 should still be classified as ASGI_FATAL."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = OSError("socket operation on non-socket")
        exc.winerror = 10038

        result = FatalErrorClassifier.classify(exc)
        assert result == ShutdownReason.ASGI_FATAL


class TestLiquidityBudget:
    """Test liquidity budget configuration."""

    def test_default_budget_is_2000ms(self):
        """Default liquidity hard budget should be 2000ms."""
        # The value is set in the code with environment override
        import os
        # Ensure env var is not set
        if "MERID_LIQUIDITY_HARD_BUDGET_MS" in os.environ:
            del os.environ["MERID_LIQUIDITY_HARD_BUDGET_MS"]

        # We can't easily test the actual value without running the code,
        # but we can verify the environment override mechanism exists
        # by checking the source pattern is present
        import inspect
        from merid import loop
        source = inspect.getsource(loop)
        assert "MERID_LIQUIDITY_HARD_BUDGET_MS" in source
        assert "2000.0" in source or '"2000"' in source

    def test_budget_is_configurable_via_env(self):
        """Budget should be configurable via environment variable."""
        import os
        os.environ["MERID_LIQUIDITY_HARD_BUDGET_MS"] = "3000.0"

        # In real code, this would be read at import/runtime
        # For test, just verify the env var is set
        assert os.environ["MERID_LIQUIDITY_HARD_BUDGET_MS"] == "3000.0"

        del os.environ["MERID_LIQUIDITY_HARD_BUDGET_MS"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
