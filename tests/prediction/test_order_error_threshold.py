"""order_error_threshold: ERROR_THRESHOLD classification for KalshiTradingAgent."""

import pytest

from merid.prediction.order_error_threshold import (
    normalize_order_failure_reason,
    should_count_toward_error_threshold,
)


@pytest.mark.parametrize(
    "reason,expected_count",
    [
        ("sanity_check:min_order_notional_usd", False),
        ("Order rejected: sanity_check:min_order_notional_usd", False),
        ("sanity_check_error:ZeroDivisionError", True),
        ("kill_switch:active", False),
        ("YES: Order rejected: sanity_check:x; NO: ok", False),
        ("live_not_enabled", False),
        ("risk_check:max contracts", False),
        ("execution_gate_blocked:loop lag", False),
        ("routing_exception:timeout", True),
        ("", True),
    ],
)
def test_should_count(reason: str, expected_count: bool) -> None:
    assert should_count_toward_error_threshold(reason) is expected_count


def test_normalize_strips_tool_wrapper() -> None:
    assert normalize_order_failure_reason(
        "Order rejected: sanity_check:foo",
    ).startswith("sanity_check:")
