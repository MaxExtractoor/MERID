"""Tests for error classification and WS hardening fixes."""

import asyncio
import errno
import os
import sys

# Ensure we can import from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestErrorClassification:
    """Test error classification for WS/Win995/MarketState errors."""

    def test_ws_disconnect_is_budget_exempt(self):
        """WebSocket disconnect errors should not count toward kill switch."""
        from merid.risk.error_classification import (
            classify_error,
            ErrorClass,
            ErrorSeverity,
            _BUDGET_EXEMPT_CLASSES,
        )

        classification = classify_error("ws_disconnect", context="test")

        assert classification.error_class == ErrorClass.WS_DISCONNECT
        assert classification.error_class in _BUDGET_EXEMPT_CLASSES
        assert classification.counts_toward_budget is False
        assert classification.severity == ErrorSeverity.LOW
        assert classification.is_transient is True

    def test_win995_is_budget_exempt(self):
        """WinError 995 should not count toward kill switch."""
        from merid.risk.error_classification import (
            classify_error,
            ErrorClass,
            ErrorSeverity,
            _BUDGET_EXEMPT_CLASSES,
        )

        classification = classify_error("winerror_995", context="test")

        assert classification.error_class == ErrorClass.ASYNCIO_WIN995
        assert classification.error_class in _BUDGET_EXEMPT_CLASSES
        assert classification.counts_toward_budget is False
        assert classification.severity == ErrorSeverity.LOW

    def test_invalid_state_is_budget_exempt(self):
        """Asyncio InvalidStateError should not count toward kill switch."""
        from merid.risk.error_classification import (
            classify_error,
            ErrorClass,
            _BUDGET_EXEMPT_CLASSES,
        )

        classification = classify_error("invalid_state", context="test")

        assert classification.error_class == ErrorClass.ASYNCIO_INVALID_STATE
        assert classification.error_class in _BUDGET_EXEMPT_CLASSES
        assert classification.counts_toward_budget is False

    def test_market_state_is_budget_exempt(self):
        """Market state errors (closed/not tradeable) should not count."""
        from merid.risk.error_classification import (
            classify_error,
            ErrorClass,
            _BUDGET_EXEMPT_CLASSES,
        )

        classification = classify_error("market_closed", context="test")

        assert classification.error_class == ErrorClass.MARKET_STATE
        assert classification.error_class in _BUDGET_EXEMPT_CLASSES
        assert classification.counts_toward_budget is False

    def test_auth_error_counts_toward_budget(self):
        """Auth errors should still count toward kill switch."""
        from merid.risk.error_classification import (
            classify_error,
            ErrorClass,
            ErrorSeverity,
            _BUDGET_EXEMPT_CLASSES,
        )

        classification = classify_error("auth_failed", context="test")

        assert classification.error_class == ErrorClass.AUTH_ERROR
        assert classification.error_class not in _BUDGET_EXEMPT_CLASSES
        assert classification.counts_toward_budget is True
        assert classification.severity == ErrorSeverity.CRITICAL


class TestWSBenignErrorDetection:
    """Test the WebSocket benign error detection helper."""

    def test_is_benign_ws_error_cancelled(self):
        """CancelledError should be detected as benign."""
        from web.main import _is_benign_ws_error

        exc = asyncio.CancelledError()
        assert _is_benign_ws_error(exc) is True

    def test_is_benign_ws_error_connection_reset(self):
        """ConnectionResetError should be detected as benign."""
        from web.main import _is_benign_ws_error

        exc = ConnectionResetError()
        assert _is_benign_ws_error(exc) is True

    def test_is_benign_ws_error_win995(self):
        """WinError 995 should be detected as benign."""
        from web.main import _is_benign_ws_error

        # Create an OSError with winerror 995
        exc = OSError("The I/O operation has been aborted")
        exc.winerror = 995
        assert _is_benign_ws_error(exc) is True

    def test_is_benign_ws_error_invalid_state(self):
        """InvalidStateError should be detected as benign."""
        from web.main import _is_benign_ws_error

        exc = asyncio.InvalidStateError("invalid state")
        assert _is_benign_ws_error(exc) is True

    def test_is_benign_ws_error_regular_oserror(self):
        """Regular OSError should NOT be detected as benign."""
        from web.main import _is_benign_ws_error

        exc = OSError("Some other error")
        assert _is_benign_ws_error(exc) is False

    def test_is_benign_ws_error_regular_exception(self):
        """Regular exceptions should NOT be detected as benign."""
        from web.main import _is_benign_ws_error

        assert _is_benign_ws_error(ValueError("test")) is False
        assert _is_benign_ws_error(RuntimeError("test")) is False


class TestKillSwitchRecordError:
    """Test that record_error with error_hint properly classifies errors."""

    def _create_fresh_controller(self):
        """Create a fresh RiskController without loading persisted kill switch state."""
        from merid.risk.kill_switches import RiskController
        import tempfile
        import os

        # Use a temp file for kill switch persistence to avoid loading the real state
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{"active": false}')
            temp_path = f.name

        old_env = os.environ.get("MERID_RISK_KS_FILE")
        try:
            os.environ["MERID_RISK_KS_FILE"] = temp_path
            controller = RiskController(error_threshold=10)
            # Force reset the kill switch state
            controller._global_kill = False
            controller._kill_reason = None
            controller._error_count = 0
            controller._error_window_start = __import__('time').time()
            return controller
        finally:
            if old_env is not None:
                os.environ["MERID_RISK_KS_FILE"] = old_env
            else:
                os.environ.pop("MERID_RISK_KS_FILE", None)
            try:
                os.unlink(temp_path)
            except:
                pass

    def test_record_error_skips_budget_exempt_errors(self):
        """record_error with budget-exempt hint should not increment counter."""
        controller = self._create_fresh_controller()

        # Record a budget-exempt error
        result = controller.record_error(error_hint="ws_disconnect")

        # Should return True (trading can continue)
        assert result is True
        # Error count should not have incremented
        assert controller._error_count == 0

    def test_record_error_counts_critical_errors(self):
        """record_error with critical hint should increment counter."""
        controller = self._create_fresh_controller()

        # Record a critical error
        result = controller.record_error(error_hint="auth_failed")

        # Should return True (trading can continue, threshold not reached)
        assert result is True
        # Error count should have incremented
        assert controller._error_count == 1

    def test_record_error_legacy_behavior_without_hint(self):
        """record_error without hint should use legacy behavior (count all)."""
        controller = self._create_fresh_controller()

        # Record error without hint (legacy behavior)
        result = controller.record_error(error_hint="")

        # Should return True (trading can continue)
        assert result is True
        # Error count should have incremented (legacy behavior)
        assert controller._error_count == 1


if __name__ == "__main__":
    # Run tests with pytest if available
    try:
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        # Fallback to simple assertion testing
        print("pytest not available, running basic assertions...")

        test_classes = [
            TestErrorClassification(),
            TestWSBenignErrorDetection(),
            TestKillSwitchRecordError(),
        ]

        for test_class in test_classes:
            for name in dir(test_class):
                if name.startswith("test_"):
                    try:
                        getattr(test_class, name)()
                        print(f"  PASS: {name}")
                    except Exception as e:
                        print(f"  FAIL: {name} - {e}")
                        sys.exit(1)

        print("\nAll tests passed!")
