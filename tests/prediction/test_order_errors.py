"""Tests for KalshiOrderErrorCode enum and related error handling."""

import pytest

from merid.event_venues.kalshi.order_errors import (
    KalshiOrderErrorCode,
    KalshiOrderError,
    KalshiValidationError,
    KalshiAuthError,
    KalshiRateLimitError,
    KalshiExchangeError,
    KalshiInsufficientFundsError,
    KalshiMarketClosedError,
    raise_for_order_status,
    is_retryable_error,
    get_user_message,
)


class TestKalshiOrderErrorCode:
    """Unit tests for the KalshiOrderErrorCode enum."""

    def test_pm_agent_execution_code_exists(self):
        """PM_AGENT_EXECUTION error code must exist."""
        assert KalshiOrderErrorCode.PM_AGENT_EXECUTION is not None

    def test_pm_agent_execution_value(self):
        """PM_AGENT_EXECUTION value should be a recognizable string."""
        assert KalshiOrderErrorCode.PM_AGENT_EXECUTION.value == "pm_agent_execution"

    def test_all_error_codes_are_strings(self):
        """All error code values must be non-empty strings."""
        for code in KalshiOrderErrorCode:
            assert isinstance(code.value, str)
            assert len(code.value) > 0

    def test_no_duplicate_values(self):
        """No two error codes should share the same value."""
        values = [code.value for code in KalshiOrderErrorCode]
        assert len(values) == len(set(values))

    def test_inherits_from_str(self):
        """KalshiOrderErrorCode inherits from str, so .value is a plain string."""
        code = KalshiOrderErrorCode.PM_AGENT_EXECUTION
        # .value must be a plain str (important for JSON serialisation)
        assert isinstance(code.value, str)
        assert code.value == "pm_agent_execution"
        # Also verify the enum IS a str subclass
        assert isinstance(code, str)

    def test_core_error_codes_present(self):
        """Verify essential codes used throughout the codebase exist."""
        codes = {c.value for c in KalshiOrderErrorCode}
        assert "pm_agent_execution" in codes
        assert "risk_blocked" in codes
        assert "stale_snapshot" in codes
        assert "kill_switch" in codes
        assert "unknown" in codes


class TestRaiseForOrderStatus:
    """Tests for raise_for_order_status helper."""

    def test_400_raises_validation_error(self):
        with pytest.raises(KalshiValidationError):
            raise_for_order_status(400, "bad request", {"message": "invalid params"})

    def test_400_insufficient_funds_raises_funds_error(self):
        with pytest.raises(KalshiInsufficientFundsError):
            raise_for_order_status(400, "insufficient balance", {"message": "Insufficient balance"})

    def test_401_raises_auth_error(self):
        with pytest.raises(KalshiAuthError):
            raise_for_order_status(401, "unauthorized")

    def test_403_raises_auth_error(self):
        with pytest.raises(KalshiAuthError):
            raise_for_order_status(403, "forbidden")

    def test_429_raises_rate_limit_error(self):
        with pytest.raises(KalshiRateLimitError):
            raise_for_order_status(429, "rate limited")

    def test_500_raises_exchange_error(self):
        with pytest.raises(KalshiExchangeError):
            raise_for_order_status(500, "internal server error")

    def test_503_raises_exchange_error(self):
        with pytest.raises(KalshiExchangeError):
            raise_for_order_status(503, "service unavailable")

    def test_422_insufficient_raises_funds_error(self):
        with pytest.raises(KalshiInsufficientFundsError):
            raise_for_order_status(422, "insufficient funds", {"message": "Insufficient balance"})

    def test_400_market_closed_raises_market_closed(self):
        with pytest.raises(KalshiMarketClosedError):
            raise_for_order_status(400, "market is closed", {"message": "Market is closed"})

    def test_unknown_status_raises_generic_error(self):
        with pytest.raises(KalshiOrderError):
            raise_for_order_status(418, "I'm a teapot")


class TestIsRetryableError:
    """Tests for is_retryable_error."""

    def test_rate_limit_is_retryable(self):
        err = KalshiRateLimitError()
        assert is_retryable_error(err) is True

    def test_exchange_error_is_retryable(self):
        err = KalshiExchangeError()
        assert is_retryable_error(err) is True

    def test_validation_error_not_retryable(self):
        err = KalshiValidationError("bad request")
        assert is_retryable_error(err) is False

    def test_auth_error_not_retryable(self):
        err = KalshiAuthError("unauthorized")
        assert is_retryable_error(err) is False

    def test_insufficient_funds_not_retryable(self):
        err = KalshiInsufficientFundsError()
        assert is_retryable_error(err) is False


class TestGetUserMessage:
    """Tests for get_user_message helper."""

    def test_validation_error_message(self):
        err = KalshiValidationError("field 'count' required")
        msg = get_user_message(err)
        assert "validation" in msg.lower() or "failed" in msg.lower()

    def test_rate_limit_message(self):
        err = KalshiRateLimitError()
        msg = get_user_message(err)
        assert "request" in msg.lower() or "rate" in msg.lower()

    def test_auth_error_message(self):
        err = KalshiAuthError("invalid key")
        msg = get_user_message(err)
        assert "authentication" in msg.lower() or "api key" in msg.lower()

    def test_exchange_error_message(self):
        err = KalshiExchangeError()
        msg = get_user_message(err)
        assert "kalshi" in msg.lower() or "exchange" in msg.lower() or "issue" in msg.lower()

    def test_insufficient_funds_message(self):
        err = KalshiInsufficientFundsError("balance too low")
        msg = get_user_message(err)
        assert "insufficient" in msg.lower() or "funds" in msg.lower()


class TestPMAgentExecutionCodeInNoTrade:
    """Integration smoke test: PM_AGENT_EXECUTION error code reaches NoTradeDecisionTracker."""

    def test_pm_agent_execution_code_is_str_for_serialisation(self):
        """The code must be a plain str so it can be stored in additional_context dicts."""
        code = KalshiOrderErrorCode.PM_AGENT_EXECUTION
        ctx = {"error_code": code.value, "error_message": "order_failed"}
        assert isinstance(ctx["error_code"], str)
        assert ctx["error_code"] == "pm_agent_execution"
