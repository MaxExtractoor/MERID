"""Tests for the error-string → error_class classification logic in trading_agent.py.

The function under test lives inside _execute_trade_signal() in trading_agent.py.
We extract the classification logic into a helper here so it can be tested in
isolation without instantiating the full KalshiTradingAgent.

Tests verify:
  - Every known benign error pattern maps to an exempt (MEDIUM/LOW) class
  - Known serious patterns map to HIGH/CRITICAL classes
  - Fallback to "generic" for unrecognised strings
  - All mapped classes are known in _ERROR_CLASS_SEVERITY
"""

import pytest

from merid.risk.kill_switches import (
    ErrorSeverity,
    classify_error_severity,
    _ERROR_CLASS_SEVERITY,
)


# ---------------------------------------------------------------------------
# Replicate the classification logic from trading_agent.py so we can unit-test
# it independently.  Keep in sync with the block in trading_agent.py.
# ---------------------------------------------------------------------------

def _classify_error_str(result_error) -> str:
    """Mirror of the classification block in trading_agent._execute_trade_signal.

    Maps an error string to a kill-switch error_class.  Must be kept in sync
    with merid/prediction/trading_agent.py (search for _err_class).
    """
    _err_class = "generic"
    _err_str = str(result_error).lower() if result_error else ""

    if (
        "kill switch" in _err_str
        or "execution gate" in _err_str
        or "gate blocked" in _err_str
        or "kill_switch" in _err_str
    ):
        _err_class = "gate_blocked"
    elif "order_group_not_found" in _err_str or (
        "order group" in _err_str and "not found" in _err_str
    ):
        _err_class = "order_group_not_found"
    elif "group_triggered" in _err_str or (
        "order group" in _err_str and "triggered" in _err_str
    ):
        _err_class = "order_group_triggered"
    elif (
        "market_closed" in _err_str
        or "market closed" in _err_str
        or "market is closed" in _err_str
        or "market not accepting" in _err_str
        or ("closed" in _err_str and "halted" in _err_str)
    ):
        _err_class = "market_closed"
    elif (
        "stale_snapshot" in _err_str
        or "stale snapshot" in _err_str
        or ("stale" in _err_str and "snapshot" in _err_str)
    ):
        _err_class = "stale_snapshot"
    elif "notional" in _err_str:
        _err_class = "min_notional"
    elif "reconnect" in _err_str or "ws_disconnect" in _err_str:
        _err_class = "ws_reconnect"
    elif "429" in _err_str or "rate limit" in _err_str or "too many" in _err_str:
        _err_class = "rate_limit"
    elif (
        "401" in _err_str
        or "403" in _err_str
        or "unauthorized" in _err_str
        or "auth_error" in _err_str
        or "authentication" in _err_str
    ):
        _err_class = "auth_error"
    elif (
        "exchange_error" in _err_str
        or "500" in _err_str
        or "502" in _err_str
        or "503" in _err_str
        or "504" in _err_str
        or ("exchange" in _err_str and "error" in _err_str)
    ):
        _err_class = "exchange_error"
    elif "timeout" in _err_str and ("feed" in _err_str or "spot" in _err_str):
        _err_class = "feed_timeout"
    elif (
        "network_timeout" in _err_str
        or "connection timeout" in _err_str
        or "read timeout" in _err_str
        or "timed out" in _err_str
    ):
        _err_class = "network_timeout"
    elif (
        "connection_error" in _err_str
        or "connection refused" in _err_str
        or "connection reset" in _err_str
        or "connectionerror" in _err_str
    ):
        _err_class = "connection_error"
    elif "stale" in _err_str and "cache" in _err_str:
        _err_class = "stale_cache"
    elif "consensus" in _err_str and ("timeout" in _err_str or "unavailable" in _err_str):
        _err_class = "consensus_timeout"
    elif "spot_stale" in _err_str or ("spot" in _err_str and "stale" in _err_str):
        _err_class = "spot_stale"
    elif (
        "insufficient_funds" in _err_str
        or "insufficient funds" in _err_str
        or "insufficient balance" in _err_str
    ):
        _err_class = "insufficient_funds"
    elif "no open orders" in _err_str or "no orders" in _err_str:
        _err_class = "no_open_orders"
    elif "no position" in _err_str or "position not found" in _err_str:
        _err_class = "no_position"

    return _err_class


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestErrorStringClassification:
    """Error strings map to the correct error_class."""

    @pytest.mark.parametrize("msg,expected", [
        # gate_blocked — LOW
        ("kill switch active", "gate_blocked"),
        ("execution gate blocked", "gate_blocked"),
        ("gate blocked: risk check", "gate_blocked"),
        ("kill_switch triggered", "gate_blocked"),
        # order_group lifecycle — MEDIUM / LOW
        ("order_group_not_found:abc123", "order_group_not_found"),
        ("order group not found for id xyz", "order_group_not_found"),
        ("group_triggered, reset required", "order_group_triggered"),
        ("order group triggered before cancel", "order_group_triggered"),
        # market_closed — MEDIUM
        ("market_closed", "market_closed"),
        ("Market closed for trading", "market_closed"),
        ("market is closed", "market_closed"),
        ("market not accepting new orders", "market_closed"),
        ("closed and halted", "market_closed"),
        # stale_snapshot — MEDIUM
        ("stale_snapshot detected", "stale_snapshot"),
        ("stale snapshot age=45s", "stale_snapshot"),
        ("snapshot is stale, skipping", "stale_snapshot"),
        # min_notional — LOW
        ("order below min notional", "min_notional"),
        ("notional too small", "min_notional"),
        # ws_reconnect — LOW
        ("ws_disconnect detected", "ws_reconnect"),
        ("reconnect attempt 3", "ws_reconnect"),
        # rate_limit — MEDIUM
        ("429 too many requests", "rate_limit"),
        ("rate limit exceeded", "rate_limit"),
        ("too many requests", "rate_limit"),
        # auth_error — CRITICAL
        ("401 unauthorized", "auth_error"),
        ("403 forbidden", "auth_error"),
        ("authentication failed", "auth_error"),
        ("auth_error: bad key", "auth_error"),
        ("Unauthorized access", "auth_error"),
        # exchange_error — MEDIUM
        ("exchange_error: internal", "exchange_error"),
        ("500 internal server error", "exchange_error"),
        ("502 bad gateway", "exchange_error"),
        ("503 service unavailable", "exchange_error"),
        ("504 gateway timeout", "exchange_error"),
        ("kalshi exchange error", "exchange_error"),
        # feed_timeout — MEDIUM
        ("feed timeout after 5s", "feed_timeout"),
        ("spot timeout exceeded", "feed_timeout"),
        # network_timeout — MEDIUM
        ("network_timeout", "network_timeout"),
        ("connection timeout reached", "network_timeout"),
        ("read timeout on socket", "network_timeout"),
        ("request timed out", "network_timeout"),
        # connection_error — MEDIUM
        ("connection_error: refused", "connection_error"),
        ("connection refused by server", "connection_error"),
        ("connection reset by peer", "connection_error"),
        ("ConnectionError: failed", "connection_error"),
        # stale_cache — MEDIUM
        ("stale cache detected", "stale_cache"),
        # consensus_timeout — MEDIUM
        ("consensus timeout", "consensus_timeout"),
        ("consensus unavailable", "consensus_timeout"),
        # spot_stale — MEDIUM
        ("spot_stale: age 120s", "spot_stale"),
        ("spot data is stale", "spot_stale"),
        # insufficient_funds — HIGH
        ("insufficient_funds", "insufficient_funds"),
        ("insufficient funds for order", "insufficient_funds"),
        ("insufficient balance in account", "insufficient_funds"),
        # no_open_orders — LOW
        ("no open orders to cancel", "no_open_orders"),
        ("no orders found", "no_open_orders"),
        # no_position — LOW
        ("no position for market", "no_position"),
        ("position not found", "no_position"),
    ])
    def test_known_pattern_maps_correctly(self, msg, expected):
        assert _classify_error_str(msg) == expected, (
            f"'{msg}' should map to '{expected}' but got '{_classify_error_str(msg)}'"
        )

    def test_none_maps_to_generic(self):
        assert _classify_error_str(None) == "generic"

    def test_empty_string_maps_to_generic(self):
        assert _classify_error_str("") == "generic"

    def test_unrecognised_message_maps_to_generic(self):
        assert _classify_error_str("some_completely_unknown_error_xyz") == "generic"

    def test_all_mapped_classes_known_in_severity_table(self):
        """Every error_class returned by the classifier must exist in _ERROR_CLASS_SEVERITY."""
        test_messages = [
            "kill switch active", "order_group_not_found:x", "group_triggered",
            "market_closed", "stale_snapshot", "notional", "reconnect",
            "429", "401", "500", "feed timeout", "network_timeout",
            "connection refused", "stale cache", "consensus timeout",
            "spot_stale", "insufficient_funds", "no open orders", "no position",
            "generic_unknown_error",
        ]
        for msg in test_messages:
            cls = _classify_error_str(msg)
            assert cls in _ERROR_CLASS_SEVERITY, (
                f"'{msg}' → '{cls}' but '{cls}' is missing from _ERROR_CLASS_SEVERITY"
            )


class TestBenignClassificationDoesNotHalt:
    """Errors that should be benign must not exhaust the kill-switch budget."""

    from merid.risk.kill_switches import RiskController

    BENIGN_MESSAGES = [
        "market_closed",
        "stale_snapshot",
        "no open orders to cancel",
        "no position for market",
        "connection refused by server",
        "request timed out",
        "503 service unavailable",
        "order_group_not_found:abc",
        "group_triggered, reset required",
        "kill switch active",
    ]

    @pytest.fixture
    def controller(self):
        from merid.risk.kill_switches import RiskController
        return RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=5,
            dedup_window_secs=0,
        )

    @pytest.mark.parametrize("msg", BENIGN_MESSAGES)
    def test_100x_benign_message_never_halts(self, controller, msg):
        """100 occurrences of a benign error message must not halt trading."""
        err_class = _classify_error_str(msg)
        for _ in range(100):
            controller.record_error(error_class=err_class)

        assert controller.can_trade() is True, (
            f"Trading halted after 100x '{msg}' (class='{err_class}') — "
            "this must be exempt from the error budget."
        )


class TestSeriousClassificationCounts:
    """Errors classified as HIGH/CRITICAL must count toward the budget."""

    SERIOUS_MESSAGES = [
        ("401 unauthorized — bad API key", "auth_error", ErrorSeverity.CRITICAL),
        ("insufficient_funds for order size", "insufficient_funds", ErrorSeverity.HIGH),
        ("some_completely_unknown_error_xyz", "generic", ErrorSeverity.HIGH),
    ]

    @pytest.fixture
    def controller(self):
        from merid.risk.kill_switches import RiskController
        return RiskController(
            daily_loss_limit=1000.0,
            max_position_value=10000.0,
            error_threshold=50,
            dedup_window_secs=0,
        )

    @pytest.mark.parametrize("msg,expected_class,expected_sev", SERIOUS_MESSAGES)
    def test_serious_error_increments_budget(self, controller, msg, expected_class, expected_sev):
        err_class = _classify_error_str(msg)
        assert err_class == expected_class
        assert classify_error_severity(err_class) == expected_sev
        controller.record_error(error_class=err_class)
        assert controller.get_status()["error_count"] == 1
