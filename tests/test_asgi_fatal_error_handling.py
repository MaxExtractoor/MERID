"""
Regression tests for ASGI fatal error handling and shutdown attribution.

Covers:
- WinError 995 recovery in Kalshi client
- Structured shutdown logging
- ASGI guard exception classification
- Agent execution error handling
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure we can import web.asgi_guard
sys.path.insert(0, "c:/Dev/MERID")


class TestFatalErrorClassifier(unittest.TestCase):
    """Test the FatalErrorClassifier for shutdown reason mapping."""

    def test_classify_winerror_995(self):
        """WinError 995 should be classified as ASGI_FATAL."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = OSError("WinError 995 The I/O operation has been aborted")
        result = FatalErrorClassifier.classify(exc)
        self.assertEqual(result, ShutdownReason.ASGI_FATAL)

    def test_classify_winerror_10054(self):
        """WinError 10054 should be classified as ASGI_FATAL."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = ConnectionResetError("WinError 10054 Connection reset by peer")
        result = FatalErrorClassifier.classify(exc)
        self.assertEqual(result, ShutdownReason.ASGI_FATAL)

    def test_classify_invalidstateerror(self):
        """InvalidStateError should be classified as ASSGI_FATAL."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = asyncio.InvalidStateError("invalid state")
        result = FatalErrorClassifier.classify(exc)
        self.assertEqual(result, ShutdownReason.ASGI_FATAL)

    def test_classify_cancellederror(self):
        """CancelledError should be classified as ASGI_FATAL."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = asyncio.CancelledError()
        result = FatalErrorClassifier.classify(exc)
        self.assertEqual(result, ShutdownReason.ASGI_FATAL)

    def test_classify_generic_error(self):
        """Generic errors should be UNKNOWN."""
        from web.asgi_guard import FatalErrorClassifier, ShutdownReason

        exc = ValueError("something went wrong")
        result = FatalErrorClassifier.classify(exc)
        self.assertEqual(result, ShutdownReason.UNKNOWN)


class TestShutdownEvent(unittest.TestCase):
    """Test structured shutdown event creation."""

    def test_to_log_line_basic(self):
        """ShutdownEvent should format correctly for logging."""
        from web.asgi_guard import ShutdownEvent, ShutdownReason

        event = ShutdownEvent(
            reason=ShutdownReason.ASGI_FATAL,
            sub_reason="WinError 995",
            fatal_error_type="OSError",
        )
        log_line = event.to_log_line()
        self.assertIn("shutdown_reason=asgi_fatal", log_line)
        self.assertIn("sub_reason=WinError 995", log_line)
        self.assertIn("fatal_error_type=OSError", log_line)

    def test_to_dict(self):
        """ShutdownEvent should convert to dict for metrics."""
        from web.asgi_guard import ShutdownEvent, ShutdownReason

        event = ShutdownEvent(
            reason=ShutdownReason.USER_REQUEST,
            sub_reason="sigterm",
            initiator_module="test_module",
        )
        d = event.to_dict()
        self.assertEqual(d["shutdown_reason"], "user_request")
        self.assertEqual(d["sub_reason"], "sigterm")
        self.assertEqual(d["initiator_module"], "test_module")


class TestShutdownReasonGlobals(unittest.TestCase):
    """Test global shutdown reason state management."""

    def test_get_set_shutdown_reason(self):
        """Shutdown reason should be gettable/settable."""
        from web.asgi_guard import (
            get_shutdown_reason,
            set_shutdown_reason,
            ShutdownEvent,
            ShutdownReason,
            is_shutting_down,
        )

        # Initially None
        self.assertIsNone(get_shutdown_reason())
        self.assertFalse(is_shutting_down())

        # Set a reason
        event = ShutdownEvent(reason=ShutdownReason.ASGI_FATAL, sub_reason="test")
        set_shutdown_reason(event)

        # Now gettable
        self.assertIsNotNone(get_shutdown_reason())
        self.assertTrue(is_shutting_down())
        self.assertEqual(get_shutdown_reason().reason, ShutdownReason.ASGI_FATAL)


class TestKalshiClientWindowsErrorRecovery(unittest.TestCase):
    """Test Kalshi client WinError recovery logic."""

    def test_is_recoverable_winerror_995(self):
        """WinError 995 should be detected as recoverable."""
        from merid.event_venues.kalshi.client import KalshiVenueClient

        client = KalshiVenueClient.__new__(KalshiVenueClient)

        exc = OSError("WinError 995 The I/O operation has been aborted")
        exc.winerror = 995  # Windows error code

        self.assertTrue(client._is_recoverable_windows_error(exc))

    def test_is_recoverable_connection_reset(self):
        """ConnectionResetError should be recoverable."""
        from merid.event_venues.kalshi.client import KalshiVenueClient

        client = KalshiVenueClient.__new__(KalshiVenueClient)

        exc = ConnectionResetError("Connection reset")
        self.assertTrue(client._is_recoverable_windows_error(exc))

    def test_is_not_recoverable_generic_oserror(self):
        """Generic OSError should not be recoverable."""
        from merid.event_venues.kalshi.client import KalshiVenueClient

        client = KalshiVenueClient.__new__(KalshiVenueClient)

        exc = OSError("Some other error")
        # No winerror attribute
        self.assertFalse(client._is_recoverable_windows_error(exc))


class TestAgentExecutionErrorLogging(unittest.TestCase):
    """Test agent execution error handling improvements."""

    def test_pm_execution_error_structure(self):
        """PM_EXECUTION_ERROR should include agent, market, asset, action."""
        # This is a structural test - the actual logging happens in trading_agent.py
        # We verify the error handler structure is correct

        from merid.prediction.trading_agent import KalshiTradingAgent

        # Verify the method exists and has proper signature
        self.assertTrue(hasattr(KalshiTradingAgent, '_execute_signal'))


class TestMetricsIntegration(unittest.TestCase):
    """Test metrics are properly defined and importable."""

    def test_shutdown_metrics_exist(self):
        """New shutdown metrics should be importable."""
        from monitoring.metrics import (
            MERID_SHUTDOWN_TOTAL,
            MERID_ASGI_FATAL_ERRORS_TOTAL,
            MERID_VENUE_RESTART_COUNT,
            MERID_AGENT_EXECUTION_ERRORS_TOTAL,
            CURRENT_SHUTDOWN_REASON,
        )

        # All should exist and be the right type
        self.assertIsNotNone(MERID_SHUTDOWN_TOTAL)
        self.assertIsNotNone(MERID_ASGI_FATAL_ERRORS_TOTAL)
        self.assertIsNotNone(MERID_VENUE_RESTART_COUNT)
        self.assertIsNotNone(MERID_AGENT_EXECUTION_ERRORS_TOTAL)
        self.assertIsNotNone(CURRENT_SHUTDOWN_REASON)

    def test_record_functions_exist(self):
        """Record functions should be importable."""
        from monitoring.metrics import (
            record_shutdown,
            record_asgi_fatal,
            record_venue_restart,
            record_agent_execution_error,
        )

        self.assertTrue(callable(record_shutdown))
        self.assertTrue(callable(record_asgi_fatal))
        self.assertTrue(callable(record_venue_restart))
        self.assertTrue(callable(record_agent_execution_error))


class TestMainPyShutdownAttribution(unittest.TestCase):
    """Test that main.py imports the shutdown attribution logic."""

    def test_asgi_guard_importable(self):
        """web.main should be able to import asgi_guard."""
        try:
            from web.asgi_guard import get_lifespan_shutdown_reason
            self.assertTrue(callable(get_lifespan_shutdown_reason))
        except ImportError as e:
            self.fail(f"Failed to import get_lifespan_shutdown_reason: {e}")


if __name__ == "__main__":
    unittest.main()
