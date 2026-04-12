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
    elif "is halted" in _err_str or (
        "halted" in _err_str and "agent" in _err_str
    ):
        _err_class = "gate_blocked"
    elif (
        "live_not_enabled" in _err_str
        or "live_requires_async" in _err_str
    ):
        _err_class = "gate_blocked"
    elif "paper fill failed" in _err_str:
        _err_class = "paper_session_error"
    elif "order_group_not_found" in _err_str or (
        "order group" in _err_str and "not found" in _err_str
    ):
        _err_class = "order_group_not_found"
    elif (
        "group_triggered" in _err_str
        or "order_group_not_active" in _err_str
        or "order_group_limit_exceeded" in _err_str
        or ("order group" in _err_str and "triggered" in _err_str)
    ):
        _err_class = "order_group_triggered"
    elif (
        "market_closed" in _err_str
        or "market closed" in _err_str
        or "market is closed" in _err_str
        or "market not accepting" in _err_str
        or ("closed" in _err_str and "halted" in _err_str)
        or "quote legs failed" in _err_str
    ):
        _err_class = "market_closed"
    elif (
        "stale_snapshot" in _err_str
        or "stale snapshot" in _err_str
        or ("stale" in _err_str and "snapshot" in _err_str)
    ):
        _err_class = "stale_snapshot"
    elif "bankroll_zero" in _err_str:
        _err_class = "risk_violation"
    elif "drawdown" in _err_str and "exceed" in _err_str:
        _err_class = "risk_violation"
    elif "post-fee edge" in _err_str or "post_fee_edge" in _err_str:
        _err_class = "low_edge"
    elif "spread" in _err_str and "exceeds" in _err_str:
        _err_class = "spread_too_wide"
    elif "depth" in _err_str and "below minimum" in _err_str:
        _err_class = "depth_insufficient"
    elif "risk_check:" in _err_str or "risk_manager_unavailable" in _err_str:
        _err_class = "risk_check_blocked"
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
    elif (
        "duplicate" in _err_str
        or "client_order_id" in _err_str
        or "idempoten" in _err_str
    ):
        _err_class = "duplicate_order_rejected"
    elif "post only cross" in _err_str or "post-only" in _err_str:
        _err_class = "order_rejected"
    elif "invalid_order_size" in _err_str or "invalid order size" in _err_str:
        _err_class = "order_rejected"
    elif "ticker_mismatch" in _err_str or "ticker mismatch" in _err_str:
        _err_class = "order_rejected"

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
        # gate_blocked — halted-agent / deployment (LOW)
        ("Agent BTC1H is halted — no orders allowed", "gate_blocked"),
        ("halted agent cannot place orders", "gate_blocked"),
        ("live_not_enabled for this session", "gate_blocked"),
        ("live_requires_async context", "gate_blocked"),
        # paper_session_error — LOW
        ("paper fill failed: no fill price", "paper_session_error"),
        # order_group lifecycle — MEDIUM / LOW
        ("order_group_not_found:abc123", "order_group_not_found"),
        ("order group not found for id xyz", "order_group_not_found"),
        ("group_triggered, reset required", "order_group_triggered"),
        ("order group triggered before cancel", "order_group_triggered"),
        ("order_group_not_active: group expired", "order_group_triggered"),
        ("order_group_limit_exceeded for group g1", "order_group_triggered"),
        # market_closed — MEDIUM
        ("market_closed", "market_closed"),
        ("Market closed for trading", "market_closed"),
        ("market is closed", "market_closed"),
        ("market not accepting new orders", "market_closed"),
        ("closed and halted", "market_closed"),
        ("quote legs failed: no fills", "market_closed"),
        # stale_snapshot — MEDIUM
        ("stale_snapshot detected", "stale_snapshot"),
        ("stale snapshot age=45s", "stale_snapshot"),
        ("snapshot is stale, skipping", "stale_snapshot"),
        # risk_violation — CRITICAL
        ("bankroll_zero: cannot size order", "risk_violation"),
        ("drawdown exceeded hard limit", "risk_violation"),
        # low_edge — LOW
        ("post-fee edge 0.002 below minimum 0.005", "low_edge"),
        ("post_fee_edge too small", "low_edge"),
        # spread_too_wide — LOW
        ("spread exceeds configured maximum", "spread_too_wide"),
        # depth_insufficient — LOW
        ("depth below minimum required", "depth_insufficient"),
        # risk_check_blocked — MEDIUM
        ("risk_check: position limit exceeded", "risk_check_blocked"),
        ("risk_check:Order notional too large", "risk_check_blocked"),
        ("risk_manager_unavailable: timeout", "risk_check_blocked"),
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
        # duplicate_order_rejected — LOW (idempotency-key collision, benign)
        ("duplicate client_order_id detected", "duplicate_order_rejected"),
        ("Order rejected: duplicate", "duplicate_order_rejected"),
        ("client_order_id already exists", "duplicate_order_rejected"),
        ("idempotency key collision", "duplicate_order_rejected"),
        # order_rejected — HIGH (exchange-level rejections from place/amend)
        ("post only cross — order would match", "order_rejected"),
        ("post-only order rejected at this price", "order_rejected"),
        ("invalid_order_size: count must be > 0", "order_rejected"),
        ("invalid order size: 0 not allowed", "order_rejected"),
        ("ticker_mismatch in order routing", "order_rejected"),
        ("ticker mismatch detected", "order_rejected"),
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
            # new classes
            "Agent X is halted", "paper fill failed: no price",
            "order_group_not_active", "order_group_limit_exceeded",
            "quote legs failed", "bankroll_zero", "drawdown exceeded hard limit",
            "post-fee edge 0.001 below minimum", "spread exceeds configured maximum",
            "depth below minimum required",
            "risk_check: position limit exceeded",
            "risk_manager_unavailable",
            "generic_unknown_error",
            # order_rejected patterns
            "post only cross — order would match",
            "post-only order rejected",
            "invalid_order_size: count 0",
            "invalid order size: 0",
            "ticker_mismatch in routing",
            "ticker mismatch detected",
            # duplicate_order_rejected patterns
            "duplicate client_order_id detected",
            "client_order_id already exists",
            "idempotency key collision",
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
        # new benign classes
        "Agent BTC1H is halted — no orders allowed",
        "paper fill failed: no fill price",
        "order_group_not_active: group expired",
        "order_group_limit_exceeded for group g1",
        "quote legs failed: no fills",
        "post-fee edge 0.001 below minimum 0.005",
        "spread exceeds configured maximum 0.10",
        "depth below minimum required: only 2 contracts",
        "risk_check: position limit exceeded",
        "risk_manager_unavailable: timeout",
        # duplicate_order_rejected (benign after FIX-DEDUP)
        "duplicate client_order_id detected",
        "Order rejected: duplicate",
        "client_order_id already exists",
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
        # order_rejected — HIGH (post-only cross, invalid size, ticker mismatch)
        ("post only cross — order would match", "order_rejected", ErrorSeverity.HIGH),
        ("invalid_order_size: count must be > 0", "order_rejected", ErrorSeverity.HIGH),
        ("ticker_mismatch in order routing", "order_rejected", ErrorSeverity.HIGH),
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
