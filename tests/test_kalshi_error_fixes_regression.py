"""Regression tests for Kalshi error fixes (BUG-A, BUG-B, BUG-F, error threshold).

Covers:
- BUG-A: Paper/live URL mismatch no longer raises RuntimeError or logs at ERROR level
- BUG-A downstream: error_threshold filter excludes all URL mismatch variants
- BUG-B: Operator token check is deferred, placeholder detection works
- BUG-F: KillSwitchState wiring uses correct API
"""

import os
import sys
import importlib
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# BUG-A: Paper/live mismatch — no RuntimeError, no ERROR log
# ---------------------------------------------------------------------------

class TestBugA_PaperLiveMismatch:
    """Verify _get_venue_client does NOT raise or log at ERROR when paper + live URL."""

    def test_no_runtime_error_in_paper_live_mismatch(self, monkeypatch):
        """_get_venue_client should return a client, not raise, even with paper+live URL."""
        monkeypatch.setenv("KALSHI_USE_DEMO", "false")
        monkeypatch.setenv("MERID_ENV", "production")

        from merid.execution.executors.kalshi import _get_venue_client
        # Reset one-time guard so the branch is exercised
        if hasattr(_get_venue_client, '_logged_paper_live_readonly'):
            delattr(_get_venue_client, '_logged_paper_live_readonly')

        with patch("trading.trade_mode.get_trade_mode") as mock_mode:
            from trading.trade_mode import TradeMode
            mock_mode.return_value = TradeMode.PAPER

            # Should NOT raise
            client = _get_venue_client()
            assert client is not None

    def test_one_time_log_guard(self, monkeypatch):
        """Second call should NOT log again (one-time guard)."""
        monkeypatch.setenv("KALSHI_USE_DEMO", "false")
        monkeypatch.setenv("MERID_ENV", "production")

        from merid.execution.executors.kalshi import _get_venue_client
        # Reset guard by removing attribute if it exists
        if hasattr(_get_venue_client, '_logged_paper_live_readonly'):
            delattr(_get_venue_client, '_logged_paper_live_readonly')

        with patch("trading.trade_mode.get_trade_mode") as mock_mode:
            from trading.trade_mode import TradeMode
            mock_mode.return_value = TradeMode.PAPER

            # First call - this should set the attribute
            _get_venue_client()
            # Verify attribute was set by the first call
            assert hasattr(_get_venue_client, '_logged_paper_live_readonly')
            assert _get_venue_client._logged_paper_live_readonly is True

            # Second call — should NOT log again
            import logging
            with patch("merid.execution.executors.kalshi.logger") as mock_logger:
                _get_venue_client()
                # warning should NOT be called with the mismatch message
                for call in mock_logger.warning.call_args_list:
                    assert "paper/mock=True but using LIVE URL" not in str(call)


# ---------------------------------------------------------------------------
# BUG-A downstream: error threshold filter
# ---------------------------------------------------------------------------

class TestBugA_ErrorThresholdFilter:
    """Verify all paper/live mismatch message variants are excluded from error threshold."""

    @pytest.mark.parametrize("reason", [
        "Mode is paper but Kalshi client URL is live: https://external-api.kalshi.com/trade-api/v2",
        "CRITICAL: Paper/mock mode but client URL is LIVE. Refusing to create client.",
        "paper/mock=True but using LIVE URL (https://external-api.kalshi.com/trade-api/v2)",
        "Kalshi config mismatch: paper/mock=True but using LIVE URL",
        "client url is live: https://external-api.kalshi.com",
    ])
    def test_mismatch_variants_excluded(self, reason):
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        assert should_count_toward_error_threshold(reason) is False, \
            f"Expected False for: {reason!r}"

    def test_real_venue_error_still_counts(self):
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        assert should_count_toward_error_threshold("HTTP 500 Internal Server Error") is True
        assert should_count_toward_error_threshold("Connection refused") is True
        assert should_count_toward_error_threshold("Request timed out") is True


# ---------------------------------------------------------------------------
# BUG-B: Operator token deferred check
# ---------------------------------------------------------------------------

class TestBugB_OperatorToken:
    """Verify operator token check is deferred and placeholder detection works."""

    def test_deferred_check_function_exists(self):
        from web.api.operator_endpoints import _check_operator_token_once
        assert callable(_check_operator_token_once)

    def test_placeholder_detection(self, monkeypatch):
        """Placeholder token should trigger warning, not error."""
        import web.api.operator_endpoints as oep
        oep._operator_token_checked = False
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.setenv("MERID_OPERATOR_TOKEN", "merid_prod_operator_token_change_me_in_production")

        with patch.object(oep, "logger") as mock_logger:
            oep._check_operator_token_once()
            # Should warn about placeholder, not error about missing
            mock_logger.warning.assert_called_once()
            assert "placeholder" in str(mock_logger.warning.call_args).lower()
            mock_logger.error.assert_not_called()

    def test_missing_token_in_prod_errors(self, monkeypatch):
        """Missing token in production should trigger error."""
        import web.api.operator_endpoints as oep
        oep._operator_token_checked = False
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.delenv("MERID_OPERATOR_TOKEN", raising=False)

        with patch.object(oep, "logger") as mock_logger:
            oep._check_operator_token_once()
            mock_logger.error.assert_called_once()
            assert "UNPROTECTED" in str(mock_logger.error.call_args)

    def test_dev_mode_no_warning(self, monkeypatch):
        """Development mode should not warn about missing token."""
        import web.api.operator_endpoints as oep
        oep._operator_token_checked = False
        monkeypatch.setenv("MERID_ENV", "development")
        monkeypatch.delenv("MERID_OPERATOR_TOKEN", raising=False)

        with patch.object(oep, "logger") as mock_logger:
            oep._check_operator_token_once()
            mock_logger.error.assert_not_called()
            mock_logger.warning.assert_not_called()

    def test_idempotent(self, monkeypatch):
        """Multiple calls should only check once."""
        import web.api.operator_endpoints as oep
        oep._operator_token_checked = False
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.delenv("MERID_OPERATOR_TOKEN", raising=False)

        with patch.object(oep, "logger") as mock_logger:
            oep._check_operator_token_once()
            oep._check_operator_token_once()
            oep._check_operator_token_once()
            # Should only log once despite 3 calls
            assert mock_logger.error.call_count == 1


# ---------------------------------------------------------------------------
# BUG-F: KillSwitchState wiring
# ---------------------------------------------------------------------------

class TestBugF_KillSwitchStateWiring:
    """Verify KillSwitchState can be instantiated correctly."""

    def test_enum_values_exist(self):
        from merid.risk.kill_switches import KillSwitchState
        assert KillSwitchState.ACTIVE.value == "active"
        assert KillSwitchState.TRIGGERED.value == "triggered"

    def test_get_state_returns_valid_enum(self, tmp_path, monkeypatch):
        from merid.risk.kill_switches import RiskController, KillSwitchState
        monkeypatch.setenv("MERID_KILL_SWITCH_STATE_DIR", str(tmp_path))
        rc = RiskController()
        state = rc.get_state()
        assert isinstance(state, KillSwitchState)
        assert state in (KillSwitchState.ACTIVE, KillSwitchState.TRIGGERED)

    def test_wiring_script_uses_correct_api(self):
        """Verify the wiring script lambda calls risk_controller.get_state(), not KillSwitchState()."""
        with open("scripts/_verify_kalshi_wiring.py", "r") as f:
            lines = f.readlines()
        # Find the KillSwitchState singleton check line
        ks_lines = [l for l in lines if '"KillSwitchState"' in l and "lambda" in l]
        assert len(ks_lines) == 1, f"Expected exactly 1 KillSwitchState lambda line, got {len(ks_lines)}"
        assert "risk_controller.get_state()" in ks_lines[0]
        assert "get_kill_switch_state()" not in ks_lines[0]


# ---------------------------------------------------------------------------
# Compile checks — all modified files import cleanly
# ---------------------------------------------------------------------------

class TestCompileChecks:
    """Ensure all modified files compile without import errors."""

    @pytest.mark.parametrize("module", [
        "merid.execution.executors.kalshi",
        "merid.prediction.order_error_threshold",
        "web.api.operator_endpoints",
        "merid.risk.kill_switches",
        "merid.diagnostics.loop_lag",
    ])
    def test_module_imports(self, module):
        mod = importlib.import_module(module)
        assert mod is not None
