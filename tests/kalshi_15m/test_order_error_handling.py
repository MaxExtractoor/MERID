"""Tests for Kalshi order-entry error code handling.

Verifies that error codes from Kalshi API are correctly handled and logged.
"""

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
    KalshiKillSwitchError,
    KalshiRiskCheckError,
    KalshiDailyLossLimitError,
    KalshiDrawdownHaltError,
    KalshiPositionLimitError,
    KalshiCircuitBreakerError,
    KalshiLiveNotEnabledError,
    KalshiLiveExecutionError,
    KalshiOrderGroupLimitError,
    raise_for_order_status,
    is_retryable_error,
    get_user_message,
    get_error_breakdown,
)


@pytest.mark.kalshi_15m
class TestKalshiOrderErrorCode:
    """Test KalshiOrderErrorCode enum and metadata."""

    def test_error_code_metadata(self):
        """Verify all error codes have required metadata (severity, category, description, is_retryable)."""
        for code in KalshiOrderErrorCode:
            assert hasattr(code, "severity"), f"{code.name} missing severity"
            assert hasattr(code, "category"), f"{code.name} missing category"
            assert hasattr(code, "description"), f"{code.name} missing description"
            assert hasattr(code, "is_retryable"), f"{code.name} missing is_retryable"
            assert code.severity in ("critical", "warning", "info"), f"{code.name} has invalid severity: {code.severity}"
            assert code.category in (
                "risk", "validation", "market", "system", "funds", "auth", "order_group"
            ), f"{code.name} has invalid category: {code.category}"
            assert isinstance(code.is_retryable, bool), f"{code.name} is_retryable must be bool"

    def test_error_code_from_string(self):
        """Test KalshiOrderErrorCode.from_string() conversion."""
        # Valid codes
        assert KalshiOrderErrorCode.from_string("kill_switch") == KalshiOrderErrorCode.KILL_SWITCH
        assert KalshiOrderErrorCode.from_string("rate_limit") == KalshiOrderErrorCode.RATE_LIMIT
        assert KalshiOrderErrorCode.from_string("insufficient_funds") == KalshiOrderErrorCode.INSUFFICIENT_FUNDS

        # Invalid codes default to UNKNOWN
        assert KalshiOrderErrorCode.from_string("invalid_code") == KalshiOrderErrorCode.UNKNOWN
        assert KalshiOrderErrorCode.from_string(None) == KalshiOrderErrorCode.UNKNOWN
        assert KalshiOrderErrorCode.from_string("") == KalshiOrderErrorCode.UNKNOWN

    def test_critical_errors_not_retryable(self):
        """Verify critical errors are marked as not retryable."""
        critical_codes = [
            KalshiOrderErrorCode.KILL_SWITCH,
            KalshiOrderErrorCode.CIRCUIT_BREAKER,
            KalshiOrderErrorCode.DAILY_LOSS_LIMIT,
            KalshiOrderErrorCode.DRAWDOWN_HALT,
            KalshiOrderErrorCode.CATEGORY_CAP_EXCEEDED,
        ]
        for code in critical_codes:
            assert code.severity == "critical", f"{code.name} should be critical"
            assert not code.is_retryable, f"{code.name} should not be retryable"

    def test_system_errors_retryable(self):
        """Verify system errors are marked as retryable."""
        system_codes = [
            KalshiOrderErrorCode.EXCHANGE_ERROR,
            KalshiOrderErrorCode.RATE_LIMIT,
            KalshiOrderErrorCode.WEBSOCKET_UNAVAILABLE,
            KalshiOrderErrorCode.RISK_CONTROLLER_UNAVAILABLE,
            KalshiOrderErrorCode.RISK_MANAGER_UNAVAILABLE,
        ]
        for code in system_codes:
            assert code.category == "system", f"{code.name} should be system category"
            assert code.is_retryable, f"{code.name} should be retryable"


@pytest.mark.kalshi_15m
class TestRaiseForOrderStatus:
    """Test raise_for_order_status() function maps status codes to exceptions."""

    def test_400_validation_error(self):
        """Test 400 Bad Request raises KalshiValidationError."""
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(400, "Invalid order parameter", {"message": "Invalid order parameter"})
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == KalshiOrderErrorCode.INVALID_ORDER

    def test_400_kill_switch(self):
        """Test 400 with kill switch message raises KalshiKillSwitchError (mapped to 403)."""
        with pytest.raises(KalshiKillSwitchError) as exc_info:
            raise_for_order_status(400, "Kill switch is active", {"message": "Kill switch is active"})
        assert exc_info.value.status_code == 403  # Kill switch errors are 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.KILL_SWITCH

    def test_400_position_limit(self):
        """Test 400 with position limit message raises KalshiPositionLimitError (mapped to 403)."""
        with pytest.raises(KalshiPositionLimitError) as exc_info:
            raise_for_order_status(400, "Position limit would be exceeded", {"message": "Position limit would be exceeded"})
        assert exc_info.value.status_code == 403  # Position limit errors are 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.POSITION_LIMIT

    def test_400_insufficient_funds(self):
        """Test 400 with insufficient funds message raises KalshiInsufficientFundsError (mapped to 422)."""
        with pytest.raises(KalshiInsufficientFundsError) as exc_info:
            raise_for_order_status(400, "Insufficient funds", {"message": "Insufficient funds"})
        assert exc_info.value.status_code == 422  # Insufficient funds errors are 422
        assert exc_info.value.error_code == KalshiOrderErrorCode.INSUFFICIENT_FUNDS

    def test_400_market_closed(self):
        """Test 400 with market closed message raises KalshiMarketClosedError."""
        with pytest.raises(KalshiMarketClosedError) as exc_info:
            raise_for_order_status(400, "Market is closed", {"message": "Market is closed"})
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == KalshiOrderErrorCode.MARKET_CLOSED

    def test_401_auth_error(self):
        """Test 401 Unauthorized raises KalshiAuthError."""
        with pytest.raises(KalshiAuthError) as exc_info:
            raise_for_order_status(401, "Authentication failed", {"message": "Authentication failed"})
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == KalshiOrderErrorCode.AUTH_FAILED

    def test_403_kill_switch(self):
        """Test 403 with kill switch message raises KalshiKillSwitchError."""
        with pytest.raises(KalshiKillSwitchError) as exc_info:
            raise_for_order_status(403, "Kill switch is active", {"message": "Kill switch is active"})
        assert exc_info.value.status_code == 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.KILL_SWITCH

    def test_403_daily_loss_limit(self):
        """Test 403 with daily loss message raises KalshiDailyLossLimitError."""
        with pytest.raises(KalshiDailyLossLimitError) as exc_info:
            raise_for_order_status(403, "Daily loss limit reached", {"message": "Daily loss limit reached"})
        assert exc_info.value.status_code == 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.DAILY_LOSS_LIMIT

    def test_403_drawdown_halt(self):
        """Test 403 with drawdown message raises KalshiDrawdownHaltError."""
        with pytest.raises(KalshiDrawdownHaltError) as exc_info:
            raise_for_order_status(403, "Max drawdown exceeded", {"message": "Max drawdown exceeded"})
        assert exc_info.value.status_code == 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.DRAWDOWN_HALT

    def test_403_live_not_enabled(self):
        """Test 403 with live not enabled message raises KalshiLiveNotEnabledError."""
        with pytest.raises(KalshiLiveNotEnabledError) as exc_info:
            raise_for_order_status(403, "Live trading not enabled", {"message": "Live trading not enabled"})
        assert exc_info.value.status_code == 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.LIVE_NOT_ENABLED

    def test_403_forbidden(self):
        """Test 403 without specific message raises KalshiAuthError with FORBIDDEN code."""
        with pytest.raises(KalshiAuthError) as exc_info:
            raise_for_order_status(403, "Access forbidden", {"message": "Access forbidden"})
        assert exc_info.value.status_code == 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.FORBIDDEN

    def test_404_order_group_not_found(self):
        """Test 404 with order group message raises KalshiOrderGroupLimitError."""
        with pytest.raises(KalshiOrderGroupLimitError) as exc_info:
            raise_for_order_status(404, "Order group not found", {"message": "Order group not found"})
        assert exc_info.value.status_code == 404

    def test_404_market_not_found(self):
        """Test 404 with market message raises KalshiValidationError with MARKET_NOT_FOUND code (mapped to 400)."""
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(404, "Market not found", {"message": "Market not found"})
        assert exc_info.value.status_code == 400  # ValidationError uses 400 by default
        assert exc_info.value.error_code == KalshiOrderErrorCode.MARKET_NOT_FOUND

    def test_409_order_group_triggered(self):
        """Test 409 with order group message raises KalshiOrderGroupLimitError with TRIGGERED code."""
        with pytest.raises(KalshiOrderGroupLimitError) as exc_info:
            raise_for_order_status(409, "Order group already triggered", {"message": "Order group already triggered"})
        assert exc_info.value.status_code == 409
        assert exc_info.value.error_code == KalshiOrderErrorCode.ORDER_GROUP_TRIGGERED

    def test_422_insufficient_funds(self):
        """Test 422 with insufficient funds message raises KalshiInsufficientFundsError."""
        with pytest.raises(KalshiInsufficientFundsError) as exc_info:
            raise_for_order_status(422, "Insufficient funds", {"message": "Insufficient funds"})
        assert exc_info.value.status_code == 422
        assert exc_info.value.error_code == KalshiOrderErrorCode.INSUFFICIENT_FUNDS

    def test_422_position_limit(self):
        """Test 422 with limit/cap message raises KalshiPositionLimitError (mapped to 403)."""
        with pytest.raises(KalshiPositionLimitError) as exc_info:
            raise_for_order_status(422, "Position limit exceeded", {"message": "Position limit exceeded"})
        assert exc_info.value.status_code == 403  # Position limit errors are 403
        assert exc_info.value.error_code == KalshiOrderErrorCode.POSITION_LIMIT

    def test_429_rate_limit(self):
        """Test 429 raises KalshiRateLimitError."""
        with pytest.raises(KalshiRateLimitError) as exc_info:
            raise_for_order_status(429, "Rate limit exceeded", {"message": "Rate limit exceeded", "retry_after": 60})
        assert exc_info.value.status_code == 429
        assert exc_info.value.error_code == KalshiOrderErrorCode.RATE_LIMIT
        assert exc_info.value.retry_after == 60

    def test_503_circuit_breaker(self):
        """Test 503 with circuit message raises KalshiCircuitBreakerError."""
        with pytest.raises(KalshiCircuitBreakerError) as exc_info:
            raise_for_order_status(503, "Circuit breaker is open", {"message": "Circuit breaker is open"})
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == KalshiOrderErrorCode.CIRCUIT_BREAKER

    def test_503_exchange_error(self):
        """Test 503 without circuit message raises KalshiExchangeError."""
        with pytest.raises(KalshiExchangeError) as exc_info:
            raise_for_order_status(503, "Service unavailable", {"message": "Service unavailable"})
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == KalshiOrderErrorCode.EXCHANGE_ERROR

    def test_500_exchange_error(self):
        """Test 500 raises KalshiExchangeError."""
        with pytest.raises(KalshiExchangeError) as exc_info:
            raise_for_order_status(500, "Internal server error", {"message": "Internal server error"})
        assert exc_info.value.status_code == 500
        assert exc_info.value.error_code == KalshiOrderErrorCode.EXCHANGE_ERROR

    def test_unknown_status_code(self):
        """Test unknown status code raises KalshiOrderError with UNKNOWN code."""
        with pytest.raises(KalshiOrderError) as exc_info:
            raise_for_order_status(418, "I'm a teapot", {"message": "I'm a teapot"})
        assert exc_info.value.status_code == 418
        assert exc_info.value.error_code == KalshiOrderErrorCode.UNKNOWN

    def test_error_code_from_response_json(self):
        """Test error_code from response JSON is parsed and used."""
        response_json = {"error_code": "rate_limit", "message": "Rate limit exceeded"}
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(400, "Rate limit exceeded", response_json)
        # Since it's 400 without rate_limit keyword, it should be ValidationError but with parsed error_code
        assert exc_info.value.error_code == KalshiOrderErrorCode.RATE_LIMIT

    def test_error_context_in_details(self):
        """Test error_context is included in details['context']."""
        error_context = {"market_id": "KXBTC15M-24JAN20-100", "side": "yes"}
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(400, "Invalid order", {"message": "Invalid order"}, error_context)
        assert "context" in exc_info.value.details
        assert exc_info.value.details["context"] == error_context


@pytest.mark.kalshi_15m
class TestErrorUtilities:
    """Test utility functions for error handling."""

    def test_is_retryable_error(self):
        """Test is_retryable_error() function."""
        retryable_error = KalshiRateLimitError("Rate limit")
        assert is_retryable_error(retryable_error) is True

        non_retryable_error = KalshiKillSwitchError("Kill switch")
        assert is_retryable_error(non_retryable_error) is False

        exchange_error = KalshiExchangeError("Exchange error")
        assert is_retryable_error(exchange_error) is True

    def test_get_user_message(self):
        """Test get_user_message() returns user-friendly messages."""
        validation_error = KalshiValidationError("Invalid order")
        assert "validation failed" in get_user_message(validation_error).lower()

        auth_error = KalshiAuthError("Authentication failed")
        assert "authentication" in get_user_message(auth_error).lower()

        funds_error = KalshiInsufficientFundsError("Insufficient funds")
        assert "insufficient funds" in get_user_message(funds_error).lower()

        market_error = KalshiMarketClosedError("Market closed")
        assert "market unavailable" in get_user_message(market_error).lower()

        risk_error = KalshiRiskCheckError("Risk check failed")
        assert "risk check" in get_user_message(risk_error).lower()

        system_error = KalshiExchangeError("System error")
        assert "system error" in get_user_message(system_error).lower()

    def test_get_error_breakdown(self):
        """Test get_error_breakdown() aggregates error codes."""
        codes = [
            "kill_switch",
            "rate_limit",
            "kill_switch",
            KalshiOrderErrorCode.INSUFFICIENT_FUNDS,
            "rate_limit",
        ]

        by_code, by_severity, by_category = get_error_breakdown(codes)

        # Check by_code
        assert by_code["kill_switch"] == 2
        assert by_code["rate_limit"] == 2
        assert by_code["insufficient_funds"] == 1

        # Check by_severity
        assert by_severity["critical"] == 2  # kill_switch x2
        assert by_severity["warning"] == 3  # rate_limit x2 + insufficient_funds
        assert by_severity["info"] == 0

        # Check by_category
        assert "kill_switch" in by_category["risk"]
        assert "rate_limit" in by_category["system"]
        assert "insufficient_funds" in by_category["funds"]


@pytest.mark.kalshi_15m
class TestErrorToDict:
    """Test KalshiOrderError.to_dict() method."""

    def test_to_dict_includes_all_fields(self):
        """Test to_dict() includes all error metadata."""
        error = KalshiValidationError(
            "Invalid order",
            details={"market_id": "KXBTC15M-24JAN20-100"},
            error_code=KalshiOrderErrorCode.INVALID_PRICE,
        )
        error_dict = error.to_dict()

        assert error_dict["error_code"] == "invalid_price"
        assert error_dict["message"] == "Invalid order"
        assert error_dict["status_code"] == 400
        assert error_dict["severity"] == "warning"
        assert error_dict["category"] == "validation"
        assert error_dict["error_type"] == "validation"
        assert error_dict["is_retryable"] is False
        assert "description" in error_dict
        assert error_dict["details"]["market_id"] == "KXBTC15M-24JAN20-100"


@pytest.mark.kalshi_15m
class TestErrorStringRepresentation:
    """Test error string representations."""

    def test_str_includes_status_code(self):
        """Test __str__ includes status code when present."""
        error = KalshiValidationError("Invalid order")
        error_str = str(error)
        assert "400" in error_str
        assert "invalid_order" in error_str

    def test_str_without_status_code(self):
        """Test __str__ works without status code."""
        error = KalshiOrderError("Generic error", status_code=None)
        error_str = str(error)
        assert "unknown" in error_str
        assert "Generic error" in error_str
