"""Tests for error severity classification, exemption, and deduplication.

Covers Phase 1 of the stabilization:
- Non-serious (MEDIUM/LOW) errors never halt trading even in large floods
- Serious (HIGH/CRITICAL) errors count toward the budget and can halt trading
- Deduplication suppresses repeated identical errors within the window
- get_error_budget_metrics() exports correct dashboard fields
- Error class taxonomy via classify_error_severity()
"""

import time

import pytest

from merid.risk.kill_switches import (
    ErrorSeverity,
    KillSwitchState,
    KillSwitchReason,
    RiskController,
    classify_error_severity,
)


# ── Error severity taxonomy ────────────────────────────────────────────


class TestErrorSeverityClassification:
    """classify_error_severity() returns the right severity for each class."""

    def test_generic_is_high(self):
        assert classify_error_severity("generic") == ErrorSeverity.HIGH

    def test_order_rejected_is_high(self):
        assert classify_error_severity("order_rejected") == ErrorSeverity.HIGH

    def test_api_error_is_high(self):
        assert classify_error_severity("api_error") == ErrorSeverity.HIGH

    def test_rate_limit_is_medium(self):
        assert classify_error_severity("rate_limit") == ErrorSeverity.MEDIUM

    def test_stale_cache_is_medium(self):
        assert classify_error_severity("stale_cache") == ErrorSeverity.MEDIUM

    def test_feed_timeout_is_medium(self):
        assert classify_error_severity("feed_timeout") == ErrorSeverity.MEDIUM

    def test_consensus_timeout_is_medium(self):
        assert classify_error_severity("consensus_timeout") == ErrorSeverity.MEDIUM

    def test_spot_stale_is_medium(self):
        assert classify_error_severity("spot_stale") == ErrorSeverity.MEDIUM

    def test_min_notional_is_low(self):
        assert classify_error_severity("min_notional") == ErrorSeverity.LOW

    def test_ws_reconnect_is_low(self):
        assert classify_error_severity("ws_reconnect") == ErrorSeverity.LOW

    def test_loop_lag_is_low(self):
        assert classify_error_severity("loop_lag") == ErrorSeverity.LOW

    def test_gate_blocked_is_low(self):
        assert classify_error_severity("gate_blocked") == ErrorSeverity.LOW

    def test_unknown_class_defaults_to_high(self):
        """Unknown error classes default to HIGH (budget-consuming)."""
        assert classify_error_severity("totally_unknown_class_xyz") == ErrorSeverity.HIGH

    def test_risk_violation_is_critical(self):
        assert classify_error_severity("risk_violation") == ErrorSeverity.CRITICAL

    def test_mispriced_contract_is_critical(self):
        assert classify_error_severity("mispriced_contract") == ErrorSeverity.CRITICAL


# ── Non-serious error floods don't halt trading ────────────────────────


class TestNonSeriousErrorsDoNotHalt:
    """A flood of low/medium severity errors must not exhaust the budget."""

    TRANSIENT_CLASSES = [
        "rate_limit",
        "stale_cache",
        "feed_timeout",
        "consensus_timeout",
        "spot_stale",
        "min_notional",
        "ws_reconnect",
        "loop_lag",
        "gate_blocked",
    ]

    @pytest.fixture
    def controller(self):
        return RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=5,
            dedup_window_secs=0,
        )

    @pytest.mark.parametrize("error_class", TRANSIENT_CLASSES)
    def test_100x_transient_error_never_halts(self, controller, error_class):
        """100 identical transient errors must not halt trading."""
        for _ in range(100):
            controller.record_error(error_class=error_class)

        assert controller.can_trade() is True, (
            f"Trading was halted after 100x '{error_class}' errors — "
            "this class must be exempt from the error budget."
        )
        assert controller.get_state() == KillSwitchState.ACTIVE
        assert controller.get_status()["error_count"] == 0

    def test_mixed_transient_flood_never_halts(self, controller):
        """Mix of different transient classes in a flood must not halt."""
        for _ in range(50):
            for cls in self.TRANSIENT_CLASSES:
                controller.record_error(error_class=cls)

        assert controller.can_trade() is True
        assert controller.get_status()["error_count"] == 0

    def test_transient_flood_does_not_block_genuine_kill(self, controller):
        """Transient flood doesn't prevent a genuine manual kill."""
        for _ in range(200):
            controller.record_error(error_class="rate_limit")

        assert controller.can_trade() is True  # still running

        controller.emergency_stop("critical risk event")
        assert controller.can_trade() is False
        assert controller.get_state() == KillSwitchState.TRIGGERED


# ── Serious error floods DO halt trading ──────────────────────────────


class TestSeriousErrorsHaltTrading:
    """Serious (HIGH) errors at runaway rate must halt trading."""

    @pytest.fixture
    def controller(self):
        return RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=5,
            dedup_window_secs=0,
        )

    def test_runaway_generic_errors_halt_trading(self, controller):
        """≥150% of error threshold in generic errors triggers a halt."""
        runaway = int(controller.error_threshold * 1.6)  # 8 errors (>150% of 5)
        for _ in range(runaway):
            controller.record_error(error_class="generic")

        assert controller.can_trade() is False
        assert controller.get_state() == KillSwitchState.TRIGGERED
        assert controller.get_status()["kill_reason"] == "error_threshold"

    def test_multi_signal_generic_errors_halt_trading(self, controller):
        """Error breach + position breach together trigger halt (multi-signal)."""
        # First signal: soft position breach
        controller.update_position_value(10500.0)  # 105% of 10000
        assert controller.can_trade() is True

        # Second signal: error threshold reached
        for _ in range(controller.error_threshold):
            controller.record_error(error_class="generic")

        assert controller.can_trade() is False

    def test_generic_errors_increment_budget(self, controller):
        """Each unique generic error increments the error budget counter."""
        for i in range(3):
            controller.record_error(error_class="generic")

        assert controller.get_status()["error_count"] == 3

    def test_order_rejected_increments_budget(self, controller):
        """order_rejected errors count toward the budget."""
        for i in range(3):
            controller.record_error(error_class="order_rejected")

        assert controller.get_status()["error_count"] == 3


# ── Error deduplication ────────────────────────────────────────────────


class TestErrorDeduplication:
    """Deduplication groups repeated identical errors within the window."""

    @pytest.fixture
    def controller_with_dedup(self):
        """Controller with 1-second dedup window for fast testing."""
        return RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=5,
            dedup_window_secs=1.0,
        )

    @pytest.fixture
    def controller_no_dedup(self):
        """Controller with dedup disabled."""
        return RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=5,
            dedup_window_secs=0,
        )

    def test_dedup_suppresses_repeated_same_class(self, controller_with_dedup):
        """Multiple rapid same-class errors count as one within the window."""
        c = controller_with_dedup
        for _ in range(10):
            c.record_error(error_class="generic")

        # Only the first occurrence consumes the budget
        status = c.get_status()
        assert status["error_count"] == 1
        assert status["dedup_suppressed_counts"].get("generic", 0) == 9

    def test_dedup_allows_count_after_window_expires(self, controller_with_dedup):
        """After the dedup window expires, a new error from the same class is counted."""
        c = controller_with_dedup
        c.record_error(error_class="generic")
        assert c.get_status()["error_count"] == 1

        # Wait for the 1-second window to expire
        time.sleep(1.1)

        c.record_error(error_class="generic")
        assert c.get_status()["error_count"] == 2

    def test_dedup_different_classes_each_counted(self, controller_with_dedup):
        """Different error classes have independent dedup windows."""
        c = controller_with_dedup
        c.record_error(error_class="generic")
        c.record_error(error_class="order_rejected")
        c.record_error(error_class="api_error")

        # Three different classes → all three counted
        assert c.get_status()["error_count"] == 3

    def test_no_dedup_all_counted(self, controller_no_dedup):
        """With dedup_window_secs=0, every error is counted independently."""
        c = controller_no_dedup
        for _ in range(4):
            c.record_error(error_class="generic")

        assert c.get_status()["error_count"] == 4

    def test_dedup_state_cleared_on_reset(self, controller_with_dedup):
        """After reset(), dedup tracking is cleared so errors count fresh."""
        c = controller_with_dedup
        c.record_error(error_class="generic")
        assert c.get_status()["error_count"] == 1

        # Force a kill then reset
        c.emergency_stop("test")
        c.reset(operator="test")

        # After reset, a new generic error should be counted (no dedup residue)
        c.record_error(error_class="generic")
        assert c.get_status()["error_count"] == 1


# ── Error budget metrics ───────────────────────────────────────────────


class TestErrorBudgetMetrics:
    """get_error_budget_metrics() exports correct dashboard fields."""

    @pytest.fixture
    def controller(self):
        return RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=10,
            dedup_window_secs=0,
        )

    def test_budget_fields_present(self, controller):
        """Required fields are all present in the metrics dict."""
        metrics = controller.get_error_budget_metrics()
        for field in (
            "error_count", "error_threshold", "budget_used_pct",
            "budget_remaining", "error_class_counts", "dedup_suppressed_counts",
            "exempt_classes", "tier", "active_breaches", "sliding_window_seconds",
        ):
            assert field in metrics, f"Missing field: {field}"

    def test_budget_used_pct_correct(self, controller):
        """budget_used_pct reflects current error count / threshold."""
        for _ in range(4):
            controller.record_error()

        metrics = controller.get_error_budget_metrics()
        assert metrics["error_count"] == 4
        assert metrics["budget_used_pct"] == 40.0
        assert metrics["budget_remaining"] == 6

    def test_budget_remaining_floors_at_zero(self, controller):
        """budget_remaining never goes negative."""
        # Send enough to hit runaway (>150%)
        for _ in range(20):
            controller.record_error()

        metrics = controller.get_error_budget_metrics()
        assert metrics["budget_remaining"] >= 0

    def test_exempt_classes_listed(self, controller):
        """Exempt classes are listed in metrics."""
        metrics = controller.get_error_budget_metrics()
        assert "gate_blocked" in metrics["exempt_classes"]
        assert "rate_limit" in metrics["exempt_classes"]
        assert "min_notional" in metrics["exempt_classes"]

    def test_dedup_suppressed_counts_in_metrics(self):
        """Dedup suppressed counts appear in metrics."""
        c = RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=10,
            dedup_window_secs=60.0,
        )
        for _ in range(5):
            c.record_error(error_class="generic")

        metrics = c.get_error_budget_metrics()
        assert metrics["dedup_suppressed_counts"].get("generic", 0) == 4
