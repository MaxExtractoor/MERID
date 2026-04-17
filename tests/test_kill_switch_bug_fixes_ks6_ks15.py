"""Regression tests for BUG-KS6 through BUG-KS15.

BUG-KS6:  reset_daily_counters didn't reset _weighted_error_count
BUG-KS7:  reset() didn't reset _weighted_error_count
BUG-KS8:  _weighted_error_count was lazily init'd via hasattr (fragile)
BUG-KS9:  _ERROR_CLASS_SEVERITY missing INTELLIGENCE_*/TWITTER/COINBASE entries
BUG-KS10: _BUDGET_EXEMPT_CLASSES missing same 5 classes
BUG-KS11: error_budget_integration fallback called record_error() without error_hint
BUG-KS12: position_limit alias mapped to RISK_VIOLATION (should be GATE_BLOCKED)
BUG-KS13: category_cap_exceeded alias mapped to RISK_VIOLATION (should be GATE_BLOCKED)
BUG-KS14: ErrorDedupTracker extended dedup window on duplicate hits (infinite suppression)
BUG-KS15: record_error / record_error_classified hourly window reset didn't zero _weighted_error_count
"""

import time
from unittest.mock import patch

import pytest


class TestWeightedCounterReset:
    """BUG-KS6/KS7/KS8/KS15: _weighted_error_count must be properly initialized and reset."""

    def test_weighted_counter_init_in_post_init(self):
        """BUG-KS8: _weighted_error_count is initialized in __post_init__."""
        from merid.risk.kill_switches import RiskController

        rc = RiskController(error_threshold=100)
        # Must exist as a real attribute, not require hasattr fallback
        assert hasattr(rc, "_weighted_error_count")
        assert rc._weighted_error_count == 0.0

    def test_reset_daily_counters_zeros_weighted(self):
        """BUG-KS6: reset_daily_counters must zero _weighted_error_count."""
        from merid.risk.kill_switches import RiskController

        rc = RiskController(error_threshold=100)
        rc._weighted_error_count = 42.5
        rc._error_count = 10
        rc.reset_daily_counters()
        assert rc._weighted_error_count == 0.0
        assert rc._error_count == 0

    def test_reset_zeros_weighted(self):
        """BUG-KS7: reset() must zero _weighted_error_count."""
        from merid.risk.kill_switches import RiskController

        rc = RiskController(error_threshold=100)
        rc._weighted_error_count = 25.0
        rc._error_count = 5
        rc.reset(operator="test")
        assert rc._weighted_error_count == 0.0
        assert rc._error_count == 0

    def test_reset_after_kill_zeros_weighted(self):
        """BUG-KS7: reset() after a real kill also zeros _weighted_error_count."""
        from merid.risk.kill_switches import RiskController

        rc = RiskController(error_threshold=100)
        rc.emergency_stop("test_kill")
        assert rc._global_kill is True
        rc._weighted_error_count = 99.0
        rc.reset(operator="test")
        assert rc._weighted_error_count == 0.0
        assert rc._global_kill is False

    def test_hourly_window_reset_zeros_weighted_legacy(self):
        """BUG-KS15: record_error hourly window reset zeros _weighted_error_count."""
        from merid.risk.kill_switches import RiskController

        rc = RiskController(error_threshold=100)
        rc._weighted_error_count = 10.0
        rc._error_count = 5
        # Force window to be expired
        rc._error_window_start = time.time() - 3700
        rc.record_error(error_hint="auth_failed")
        # After window reset, both counters should be fresh (only the new error counted)
        assert rc._error_count == 1
        assert rc._weighted_error_count == 0.0  # legacy path doesn't add to weighted

    def test_hourly_window_reset_zeros_weighted_classified(self):
        """BUG-KS15: record_error_classified hourly window reset zeros _weighted_error_count."""
        from merid.risk.kill_switches import RiskController
        from merid.risk.error_classification import get_dedup_tracker

        get_dedup_tracker()._last_seen.clear()

        rc = RiskController(error_threshold=100)
        rc._weighted_error_count = 10.0
        rc._error_count = 5
        # Force window to be expired
        rc._error_window_start = time.time() - 3700
        rc.record_error_classified("auth_failed", context="test_ks15_window")
        # After window reset + one new classified critical error
        assert rc._error_count == 1
        assert rc._weighted_error_count == 1.0  # one CRITICAL at weight 1.0


class TestMissingSeverityAndExemption:
    """BUG-KS9/KS10: Intelligence, Twitter, Coinbase classes must be LOW + budget exempt."""

    @pytest.mark.parametrize(
        "error_code",
        [
            "intelligence_feed_failed",
            "intelligence_sentiment_failed",
            "intelligence_parse_failed",
            "twitter_auth_failed",
            "coinbase_auth_failed",
        ],
    )
    def test_severity_is_low(self, error_code):
        """BUG-KS9: These ErrorClasses must map to LOW severity."""
        from merid.risk.error_classification import classify_error, ErrorSeverity

        classification = classify_error(error_code)
        assert classification.severity == ErrorSeverity.LOW, (
            f"{error_code} has severity {classification.severity}, expected LOW"
        )

    @pytest.mark.parametrize(
        "error_code",
        [
            "intelligence_feed_failed",
            "intelligence_sentiment_failed",
            "intelligence_parse_failed",
            "twitter_auth_failed",
            "coinbase_auth_failed",
        ],
    )
    def test_budget_exempt(self, error_code):
        """BUG-KS10: These ErrorClasses must be budget exempt."""
        from merid.risk.error_classification import classify_error

        classification = classify_error(error_code)
        assert classification.counts_toward_budget is False, (
            f"{error_code} counts_toward_budget={classification.counts_toward_budget}, expected False"
        )


class TestPolicyAliasConsistency:
    """BUG-KS12/KS13: Policy rejections must map to GATE_BLOCKED, not RISK_VIOLATION."""

    def test_position_limit_is_gate_blocked(self):
        """BUG-KS12: position_limit should be GATE_BLOCKED (budget exempt)."""
        from merid.risk.error_classification import classify_error, ErrorClass

        c = classify_error("position_limit")
        assert c.error_class == ErrorClass.GATE_BLOCKED
        assert c.counts_toward_budget is False

    def test_position_limit_exceeded_is_gate_blocked(self):
        """BUG-KS12: position_limit_exceeded should be GATE_BLOCKED (budget exempt)."""
        from merid.risk.error_classification import classify_error, ErrorClass

        c = classify_error("position_limit_exceeded")
        assert c.error_class == ErrorClass.GATE_BLOCKED
        assert c.counts_toward_budget is False

    def test_category_cap_exceeded_is_gate_blocked(self):
        """BUG-KS13: category_cap_exceeded should be GATE_BLOCKED (budget exempt)."""
        from merid.risk.error_classification import classify_error, ErrorClass

        c = classify_error("category_cap_exceeded")
        assert c.error_class == ErrorClass.GATE_BLOCKED
        assert c.counts_toward_budget is False

    def test_daily_loss_limit_still_risk_violation(self):
        """Ensure true risk violations were NOT downgraded."""
        from merid.risk.error_classification import classify_error, ErrorClass

        c = classify_error("daily_loss_limit")
        assert c.error_class == ErrorClass.RISK_VIOLATION
        assert c.counts_toward_budget is True


class TestDedupWindowNotExtended:
    """BUG-KS14: Dedup tracker must NOT extend window on repeated hits."""

    def test_dedup_window_expires_naturally(self):
        """A steady trickle of errors should eventually re-count after window expires."""
        from merid.risk.error_classification import ErrorDedupTracker, ErrorClass

        tracker = ErrorDedupTracker(dedup_window_seconds=1.0)

        # First occurrence — should count
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "test_ks14") is True

        # Immediately after — should be dedup'd
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "test_ks14") is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should count again because window expired (not extended by dedup hits)
        assert tracker.should_count(ErrorClass.AUTH_ERROR, "test_ks14") is True

    def test_dedup_hit_does_not_update_timestamp(self):
        """Verify internal _last_seen is not updated on dedup hit."""
        from merid.risk.error_classification import ErrorDedupTracker, ErrorClass

        tracker = ErrorDedupTracker(dedup_window_seconds=10.0)

        # First hit
        tracker.should_count(ErrorClass.AUTH_ERROR, "test_ks14_ts")
        first_ts = tracker._last_seen[("auth_error", "test_ks14_ts")]

        time.sleep(0.05)

        # Dedup hit — should NOT update timestamp
        tracker.should_count(ErrorClass.AUTH_ERROR, "test_ks14_ts")
        second_ts = tracker._last_seen[("auth_error", "test_ks14_ts")]

        assert first_ts == second_ts, "Dedup hit must not update _last_seen timestamp"


class TestErrorBudgetFallbackHint:
    """BUG-KS11: error_budget_integration fallback must pass error_hint."""

    def test_fallback_record_error_has_hint(self):
        """The fallback path in error_budget_integration uses error_hint."""
        import ast
        from pathlib import Path

        src = Path(r"c:\Dev\MERID\merid\core\error_budget_integration.py").read_text()
        tree = ast.parse(src)

        # Find all calls to record_error() and ensure they have error_hint kwarg
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Match: risk_controller.record_error(...)
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "record_error"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "risk_controller"
                ):
                    kwarg_names = [kw.arg for kw in node.keywords]
                    assert "error_hint" in kwarg_names, (
                        f"record_error() call at line {node.lineno} missing error_hint kwarg"
                    )


class TestGetStatusReportsWeighted:
    """Verify get_error_budget_status() reports both counters correctly."""

    def test_budget_status_includes_weighted_count(self):
        from merid.risk.kill_switches import RiskController

        rc = RiskController(error_threshold=100)
        rc._weighted_error_count = 7.5
        rc._error_count = 10

        status = rc.get_error_budget_status()
        assert status["weighted_error_count"] == 7.5
        assert status["error_count"] == 10
