"""Tests for Kalshi order error handling taxonomy.

This test suite ensures the error code taxonomy remains a stable contract
for the rest of the system, covering:
- Enum metadata (severity, category, description, retryability)
- Exception hierarchy and serialization
- Error aggregation utilities
- HTTP status code mapping
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
    KalshiOrderGroupDeleteError,
    KalshiOrderGroupLimitError,
    KalshiKillSwitchError,
    KalshiRiskCheckError,
    KalshiDailyLossLimitError,
    KalshiDrawdownHaltError,
    KalshiPositionLimitError,
    KalshiCircuitBreakerError,
    KalshiLiveNotEnabledError,
    KalshiLiveExecutionError,
    raise_for_order_status,
    is_retryable_error,
    get_user_message,
    get_error_breakdown,
)


class TestKalshiOrderErrorCodeMetadata:
    """Test error code metadata properties (severity, category, description, retryability)."""

    def test_critical_severity_codes(self):
        """Critical severity codes are correctly identified."""
        critical_codes = [
            KalshiOrderErrorCode.KILL_SWITCH,
            KalshiOrderErrorCode.CIRCUIT_BREAKER,
            KalshiOrderErrorCode.DAILY_LOSS_LIMIT,
            KalshiOrderErrorCode.DRAWDOWN_HALT,
            KalshiOrderErrorCode.CATEGORY_CAP_EXCEEDED,
            KalshiOrderErrorCode.EXCHANGE_ERROR,
            KalshiOrderErrorCode.RISK_CONTROLLER_UNAVAILABLE,
            KalshiOrderErrorCode.RISK_MANAGER_UNAVAILABLE,
        ]
        for code in critical_codes:
            assert code.severity == "critical", f"{code.value} should be critical"

    def test_warning_severity_codes(self):
        """Warning severity codes are correctly identified."""
        warning_codes = [
            KalshiOrderErrorCode.RATE_LIMIT,
            KalshiOrderErrorCode.INVALID_PRICE,
            KalshiOrderErrorCode.INSUFFICIENT_FUNDS,
            KalshiOrderErrorCode.MARKET_CLOSED,
            KalshiOrderErrorCode.INVALID_TICKER,
            KalshiOrderErrorCode.POSITION_LIMIT,
            KalshiOrderErrorCode.MAX_COST_EXCEEDED,
            KalshiOrderErrorCode.WEBSOCKET_UNAVAILABLE,
            KalshiOrderErrorCode.LIVE_EXECUTION_ERROR,
            KalshiOrderErrorCode.ORDER_GROUP_TRIGGERED,
        ]
        for code in warning_codes:
            assert code.severity == "warning", f"{code.value} should be warning"

    def test_info_severity_codes(self):
        """Info severity codes are correctly identified."""
        info_codes = [
            KalshiOrderErrorCode.INVALID_ORDER,
            KalshiOrderErrorCode.NON_POSITIVE_SIZE,
            KalshiOrderErrorCode.AUTH_FAILED,
            KalshiOrderErrorCode.UNKNOWN,
        ]
        for code in info_codes:
            assert code.severity == "info", f"{code.value} should be info"

    def test_risk_category_codes(self):
        """Risk category codes are correctly identified."""
        risk_codes = [
            KalshiOrderErrorCode.KILL_SWITCH,
            KalshiOrderErrorCode.DAILY_LOSS_LIMIT,
            KalshiOrderErrorCode.DRAWDOWN_HALT,
            KalshiOrderErrorCode.CATEGORY_CAP_EXCEEDED,
            KalshiOrderErrorCode.POSITION_LIMIT,
            KalshiOrderErrorCode.CORRELATED_STACK_CAP,
            KalshiOrderErrorCode.RISK_CHECK_FAILED,
            KalshiOrderErrorCode.SANITY_CHECK_FAILED,
            KalshiOrderErrorCode.CIRCUIT_BREAKER,
        ]
        for code in risk_codes:
            assert code.category == "risk", f"{code.value} should be risk category"

    def test_validation_category_codes(self):
        """Validation category codes are correctly identified."""
        validation_codes = [
            KalshiOrderErrorCode.INVALID_ORDER,
            KalshiOrderErrorCode.NON_POSITIVE_SIZE,
            KalshiOrderErrorCode.INVALID_PRICE,
            KalshiOrderErrorCode.INVALID_TICKER,
            KalshiOrderErrorCode.INVALID_SIDE,
            KalshiOrderErrorCode.INVALID_ACTION,
            KalshiOrderErrorCode.UNSUPPORTED_MODE,
            KalshiOrderErrorCode.SYNC_ROUTE_UNSUPPORTED,
        ]
        for code in validation_codes:
            assert code.category == "validation", f"{code.value} should be validation category"

    def test_market_category_codes(self):
        """Market category codes are correctly identified."""
        market_codes = [
            KalshiOrderErrorCode.MARKET_CLOSED,
            KalshiOrderErrorCode.MARKET_NOT_FOUND,
            KalshiOrderErrorCode.MARKET_NOT_TRADEABLE,
            KalshiOrderErrorCode.SPREAD_TOO_WIDE,
            KalshiOrderErrorCode.PRICE_OUTSIDE_RANGE,
            KalshiOrderErrorCode.VOLUME_TOO_LOW,
            KalshiOrderErrorCode.MARKET_CONDITION_UNFAVORABLE,
        ]
        for code in market_codes:
            assert code.category == "market", f"{code.value} should be market category"

    def test_system_category_codes(self):
        """System category codes are correctly identified."""
        system_codes = [
            KalshiOrderErrorCode.EXCHANGE_ERROR,
            KalshiOrderErrorCode.RATE_LIMIT,
            KalshiOrderErrorCode.WEBSOCKET_UNAVAILABLE,
            KalshiOrderErrorCode.LIVE_EXECUTION_ERROR,
            KalshiOrderErrorCode.RISK_CONTROLLER_UNAVAILABLE,
            KalshiOrderErrorCode.RISK_MANAGER_UNAVAILABLE,
            KalshiOrderErrorCode.UNKNOWN,
            KalshiOrderErrorCode.ROUTING_EXCEPTION,
        ]
        for code in system_codes:
            assert code.category == "system", f"{code.value} should be system category"

    def test_funds_category_codes(self):
        """Funds category codes are correctly identified."""
        funds_codes = [
            KalshiOrderErrorCode.INSUFFICIENT_FUNDS,
            KalshiOrderErrorCode.MAX_COST_EXCEEDED,
            KalshiOrderErrorCode.LIVE_NOT_ENABLED,
        ]
        for code in funds_codes:
            assert code.category == "funds", f"{code.value} should be funds category"

    def test_auth_category_codes(self):
        """Auth category codes are correctly identified."""
        auth_codes = [
            KalshiOrderErrorCode.AUTH_FAILED,
            KalshiOrderErrorCode.API_KEY_INVALID,
            KalshiOrderErrorCode.FORBIDDEN,
        ]
        for code in auth_codes:
            assert code.category == "auth", f"{code.value} should be auth category"

    def test_order_group_category_codes(self):
        """Order group category codes are correctly identified."""
        group_codes = [
            KalshiOrderErrorCode.ORDER_GROUP_NOT_FOUND,
            KalshiOrderErrorCode.ORDER_GROUP_INVALID_LIMIT,
            KalshiOrderErrorCode.ORDER_GROUP_TRIGGERED,
        ]
        for code in group_codes:
            assert code.category == "order_group", f"{code.value} should be order_group category"

    def test_descriptions_are_present(self):
        """All critical/warning codes have human-readable descriptions."""
        codes_with_descriptions = [
            KalshiOrderErrorCode.KILL_SWITCH,
            KalshiOrderErrorCode.CIRCUIT_BREAKER,
            KalshiOrderErrorCode.DAILY_LOSS_LIMIT,
            KalshiOrderErrorCode.DRAWDOWN_HALT,
            KalshiOrderErrorCode.CATEGORY_CAP_EXCEEDED,
            KalshiOrderErrorCode.RATE_LIMIT,
            KalshiOrderErrorCode.INVALID_PRICE,
            KalshiOrderErrorCode.INSUFFICIENT_FUNDS,
            KalshiOrderErrorCode.MARKET_CLOSED,
            KalshiOrderErrorCode.POSITION_LIMIT,
        ]
        for code in codes_with_descriptions:
            assert code.description, f"{code.value} should have a description"
            assert len(code.description) > 5, f"{code.value} description should be meaningful"

    def test_retryable_codes(self):
        """Retryable codes are correctly identified based on category."""
        # System and rate_limit categories should be retryable
        assert KalshiOrderErrorCode.EXCHANGE_ERROR.is_retryable is True
        assert KalshiOrderErrorCode.RATE_LIMIT.is_retryable is True
        assert KalshiOrderErrorCode.WEBSOCKET_UNAVAILABLE.is_retryable is True

        # Risk and validation should NOT be retryable
        assert KalshiOrderErrorCode.KILL_SWITCH.is_retryable is False
        assert KalshiOrderErrorCode.INVALID_ORDER.is_retryable is False
        assert KalshiOrderErrorCode.INSUFFICIENT_FUNDS.is_retryable is False


class TestKalshiOrderErrorCodeFromString:
    """Test the from_string factory method for safe string conversion."""

    def test_from_string_valid_codes(self):
        """Valid code strings are converted correctly."""
        assert KalshiOrderErrorCode.from_string("kill_switch") == KalshiOrderErrorCode.KILL_SWITCH
        assert KalshiOrderErrorCode.from_string("rate_limit") == KalshiOrderErrorCode.RATE_LIMIT
        assert KalshiOrderErrorCode.from_string("invalid_order") == KalshiOrderErrorCode.INVALID_ORDER
        assert KalshiOrderErrorCode.from_string("unknown") == KalshiOrderErrorCode.UNKNOWN

    def test_from_string_invalid_codes_default_to_unknown(self):
        """Invalid code strings default to UNKNOWN."""
        assert KalshiOrderErrorCode.from_string("not_a_real_code") == KalshiOrderErrorCode.UNKNOWN
        assert KalshiOrderErrorCode.from_string("") == KalshiOrderErrorCode.UNKNOWN
        assert KalshiOrderErrorCode.from_string("random_string") == KalshiOrderErrorCode.UNKNOWN

    def test_from_string_preserves_enum_properties(self):
        """Codes from from_string have correct metadata."""
        code = KalshiOrderErrorCode.from_string("kill_switch")
        assert code.severity == "critical"
        assert code.category == "risk"
        assert code.is_retryable is False


class TestKalshiOrderErrorExceptions:
    """Test exception hierarchy and properties."""

    def test_base_exception_properties(self):
        """Base KalshiOrderError has correct properties."""
        err = KalshiOrderError(
            message="Test error",
            status_code=500,
            error_code=KalshiOrderErrorCode.EXCHANGE_ERROR,
            details={"extra": "info"},
        )
        assert err.message == "Test error"
        assert err.status_code == 500
        assert err.error_code == KalshiOrderErrorCode.EXCHANGE_ERROR
        assert err.severity == "critical"
        assert err.category == "system"
        assert err.is_retryable is True
        assert err.details == {"extra": "info"}

    def test_exception_str_representation(self):
        """String representation includes code and status."""
        err = KalshiOrderError("Test", status_code=400, error_code=KalshiOrderErrorCode.INVALID_ORDER)
        str_repr = str(err)
        assert "invalid_order" in str_repr
        assert "400" in str_repr
        assert "Test" in str_repr

    def test_validation_error_defaults(self):
        """KalshiValidationError has correct defaults."""
        err = KalshiValidationError("Invalid params")
        assert err.status_code == 400
        assert err.error_code == KalshiOrderErrorCode.INVALID_ORDER
        assert err.category == "validation"

    def test_auth_error_defaults(self):
        """KalshiAuthError has correct defaults."""
        err = KalshiAuthError("Auth failed")
        assert err.status_code == 401
        assert err.error_code == KalshiOrderErrorCode.AUTH_FAILED
        assert err.category == "auth"

    def test_rate_limit_error_has_retry_after(self):
        """KalshiRateLimitError has retry_after attribute."""
        err = KalshiRateLimitError("Rate limited", retry_after=30)
        assert err.status_code == 429
        assert err.error_code == KalshiOrderErrorCode.RATE_LIMIT
        assert err.retry_after == 30

    def test_exchange_error_defaults(self):
        """KalshiExchangeError has correct defaults."""
        err = KalshiExchangeError("Exchange down", status_code=503)
        assert err.status_code == 503
        assert err.error_code == KalshiOrderErrorCode.EXCHANGE_ERROR
        assert err.category == "system"
        assert err.is_retryable is True

    def test_insufficient_funds_error(self):
        """KalshiInsufficientFundsError has correct defaults."""
        err = KalshiInsufficientFundsError("Not enough funds")
        assert err.status_code == 422
        assert err.error_code == KalshiOrderErrorCode.INSUFFICIENT_FUNDS
        assert err.category == "funds"

    def test_kill_switch_error(self):
        """KalshiKillSwitchError has correct defaults."""
        err = KalshiKillSwitchError("Kill switch active")
        assert err.status_code == 403
        assert err.error_code == KalshiOrderErrorCode.KILL_SWITCH
        assert err.severity == "critical"
        assert err.category == "risk"

    def test_daily_loss_limit_error(self):
        """KalshiDailyLossLimitError has correct defaults."""
        err = KalshiDailyLossLimitError("Daily limit reached")
        assert err.status_code == 403
        assert err.error_code == KalshiOrderErrorCode.DAILY_LOSS_LIMIT
        assert err.severity == "critical"

    def test_drawdown_halt_error(self):
        """KalshiDrawdownHaltError has correct defaults."""
        err = KalshiDrawdownHaltError("Max drawdown exceeded")
        assert err.status_code == 403
        assert err.error_code == KalshiOrderErrorCode.DRAWDOWN_HALT
        assert err.severity == "critical"

    def test_position_limit_error(self):
        """KalshiPositionLimitError has correct defaults."""
        err = KalshiPositionLimitError("Position too large")
        assert err.status_code == 403
        assert err.error_code == KalshiOrderErrorCode.POSITION_LIMIT
        assert err.severity == "warning"

    def test_circuit_breaker_error(self):
        """KalshiCircuitBreakerError has correct defaults."""
        err = KalshiCircuitBreakerError("Circuit open")
        assert err.status_code == 503
        assert err.error_code == KalshiOrderErrorCode.CIRCUIT_BREAKER
        assert err.severity == "critical"

    def test_live_not_enabled_error(self):
        """KalshiLiveNotEnabledError has correct defaults."""
        err = KalshiLiveNotEnabledError("Live not enabled")
        assert err.status_code == 403
        assert err.error_code == KalshiOrderErrorCode.LIVE_NOT_ENABLED
        assert err.category == "funds"

    def test_order_group_limit_error(self):
        """KalshiOrderGroupLimitError has correct defaults."""
        err = KalshiOrderGroupLimitError("Invalid limit", group_id="grp_123")
        assert err.status_code == 400
        assert err.error_code == KalshiOrderErrorCode.ORDER_GROUP_INVALID_LIMIT
        assert err.group_id == "grp_123"


class TestKalshiOrderErrorToDict:
    """Test exception serialization to dictionary."""

    def test_to_dict_contains_all_fields(self):
        """to_dict includes all expected fields."""
        err = KalshiOrderError(
            message="Test error",
            status_code=500,
            error_code=KalshiOrderErrorCode.EXCHANGE_ERROR,
            details={"context": {"ticker": "BTC"}},
        )
        d = err.to_dict()
        assert d["error_code"] == "exchange_error"
        assert d["message"] == "Test error"
        assert d["status_code"] == 500
        assert d["severity"] == "critical"
        assert d["category"] == "system"
        assert d["error_type"] == "system"
        assert d["is_retryable"] is True
        assert d["details"] == {"context": {"ticker": "BTC"}}
        assert d["description"] == "Exchange error occurred"

    def test_to_dict_for_unknown_error(self):
        """to_dict works for unknown errors."""
        err = KalshiOrderError("Unknown issue")
        d = err.to_dict()
        assert d["error_code"] == "unknown"
        assert d["severity"] == "info"
        assert d["description"] == "Unknown error occurred"


class TestErrorUtilityFunctions:
    """Test is_retryable_error and get_user_message utilities."""

    def test_is_retryable_error_with_retryable(self):
        """is_retryable_error returns True for retryable errors."""
        err = KalshiRateLimitError("Rate limited")
        assert is_retryable_error(err) is True

        err = KalshiExchangeError("Exchange down")
        assert is_retryable_error(err) is True

    def test_is_retryable_error_with_non_retryable(self):
        """is_retryable_error returns False for non-retryable errors."""
        err = KalshiValidationError("Invalid params")
        assert is_retryable_error(err) is False

        err = KalshiKillSwitchError("Kill switch active")
        assert is_retryable_error(err) is False

    def test_get_user_message_by_category(self):
        """get_user_message returns category-appropriate messages."""
        validation_err = KalshiValidationError("Bad params")
        assert "validation failed" in get_user_message(validation_err).lower()

        auth_err = KalshiAuthError("Auth failed", status_code=401)
        assert "authentication" in get_user_message(auth_err).lower()

        funds_err = KalshiInsufficientFundsError("No money")
        assert "insufficient funds" in get_user_message(funds_err).lower()

        market_err = KalshiMarketClosedError("Market closed")
        assert "market unavailable" in get_user_message(market_err).lower()

        risk_err = KalshiKillSwitchError("Kill switch")
        assert "risk check" in get_user_message(risk_err).lower()


class TestGetErrorBreakdown:
    """Test the get_error_breakdown aggregation function."""

    def test_get_error_breakdown_basic(self):
        """Breakdown aggregates by code, severity, and category."""
        codes = [
            "kill_switch",
            "rate_limit",
            "rate_limit",
            "invalid_price",
            "unknown",
        ]
        by_code, by_severity, by_category = get_error_breakdown(codes)

        # By code
        assert by_code["kill_switch"] == 1
        assert by_code["rate_limit"] == 2
        assert by_code["invalid_price"] == 1
        assert by_code["unknown"] == 1

        # By severity
        assert by_severity["critical"] == 1  # kill_switch
        assert by_severity["warning"] == 3   # rate_limit x2 + invalid_price
        assert by_severity["info"] == 1      # unknown

        # By category
        assert "kill_switch" in by_category["risk"]
        assert "rate_limit" in by_category["system"]
        assert "invalid_price" in by_category["validation"]

    def test_get_error_breakdown_with_enum_values(self):
        """Breakdown works with actual enum values, not just strings."""
        codes = [
            KalshiOrderErrorCode.KILL_SWITCH,
            KalshiOrderErrorCode.RATE_LIMIT,
            KalshiOrderErrorCode.INVALID_PRICE,  # Changed from EXCHANGE_ERROR to INVALID_PRICE
        ]
        by_code, by_severity, by_category = get_error_breakdown(codes)

        assert by_code["kill_switch"] == 1
        assert by_code["rate_limit"] == 1
        assert by_code["invalid_price"] == 1
        assert by_severity["critical"] == 1  # kill_switch
        assert by_severity["warning"] == 2   # rate_limit + invalid_price

    def test_get_error_breakdown_empty_list(self):
        """Breakdown handles empty list gracefully."""
        by_code, by_severity, by_category = get_error_breakdown([])
        assert by_code == {}
        assert by_severity == {"critical": 0, "warning": 0, "info": 0}
        assert by_category == {}

    def test_get_error_breakdown_invalid_codes(self):
        """Breakdown handles invalid codes by treating them as UNKNOWN."""
        codes = ["not_real", "also_fake"]
        by_code, by_severity, by_category = get_error_breakdown(codes)

        assert by_code["unknown"] == 2
        assert by_severity["info"] == 2


class TestRaiseForOrderStatus:
    """Test HTTP status code to exception mapping."""

    def test_raise_for_400_insufficient_funds(self):
        """400 with insufficient funds message raises KalshiInsufficientFundsError."""
        with pytest.raises(KalshiInsufficientFundsError):
            raise_for_order_status(400, "Insufficient balance", {"message": "Insufficient balance for order"})

    def test_raise_for_400_market_closed(self):
        """400 with closed message raises KalshiMarketClosedError."""
        with pytest.raises(KalshiMarketClosedError):
            raise_for_order_status(400, "Market is closed", {"message": "Market is closed"})

    def test_raise_for_400_kill_switch(self):
        """400 with kill switch message raises KalshiKillSwitchError."""
        with pytest.raises(KalshiKillSwitchError):
            raise_for_order_status(400, "Kill switch active", {"message": "Kill switch is active"})

    def test_raise_for_400_position_limit(self):
        """400 with position limit message raises KalshiPositionLimitError."""
        with pytest.raises(KalshiPositionLimitError):
            raise_for_order_status(400, "Position limit", {"message": "Position limit would be exceeded"})

    def test_raise_for_400_default_validation(self):
        """400 without specific pattern raises KalshiValidationError."""
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(400, "Bad request", {"message": "Bad request"})
        assert exc_info.value.error_code == KalshiOrderErrorCode.INVALID_ORDER

    def test_raise_for_401_auth_error(self):
        """401 raises KalshiAuthError with AUTH_FAILED code."""
        with pytest.raises(KalshiAuthError) as exc_info:
            raise_for_order_status(401, "Unauthorized", {"message": "Unauthorized"})
        assert exc_info.value.error_code == KalshiOrderErrorCode.AUTH_FAILED

    def test_raise_for_403_kill_switch(self):
        """403 with kill switch message raises KalshiKillSwitchError."""
        with pytest.raises(KalshiKillSwitchError):
            raise_for_order_status(403, "Kill switch active", {"message": "Kill switch is active"})

    def test_raise_for_403_daily_loss(self):
        """403 with daily loss message raises KalshiDailyLossLimitError."""
        with pytest.raises(KalshiDailyLossLimitError):
            raise_for_order_status(403, "Daily loss limit", {"message": "Daily loss limit reached"})

    def test_raise_for_403_drawdown(self):
        """403 with drawdown message raises KalshiDrawdownHaltError."""
        with pytest.raises(KalshiDrawdownHaltError):
            raise_for_order_status(403, "Drawdown", {"message": "Max drawdown exceeded"})

    def test_raise_for_403_live_not_enabled(self):
        """403 with live not enabled message raises KalshiLiveNotEnabledError."""
        with pytest.raises(KalshiLiveNotEnabledError):
            raise_for_order_status(403, "Live not enabled", {"message": "Live trading not enabled"})

    def test_raise_for_403_forbidden(self):
        """403 without specific pattern raises KalshiAuthError with FORBIDDEN code."""
        with pytest.raises(KalshiAuthError) as exc_info:
            raise_for_order_status(403, "Forbidden", {"message": "Access denied"})
        assert exc_info.value.error_code == KalshiOrderErrorCode.FORBIDDEN

    def test_raise_for_404_order_group_not_found(self):
        """404 with order group message raises KalshiOrderGroupLimitError."""
        with pytest.raises(KalshiOrderGroupLimitError) as exc_info:
            raise_for_order_status(404, "Order group not found", {"message": "Order group not found"})
        assert exc_info.value.error_code == KalshiOrderErrorCode.ORDER_GROUP_NOT_FOUND

    def test_raise_for_404_market_not_found(self):
        """404 with market message raises KalshiValidationError with MARKET_NOT_FOUND code."""
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(404, "Market not found", {"message": "Market not found"})
        assert exc_info.value.error_code == KalshiOrderErrorCode.MARKET_NOT_FOUND

    def test_raise_for_409_order_group_triggered(self):
        """409 with order group triggered message raises KalshiOrderGroupLimitError."""
        with pytest.raises(KalshiOrderGroupLimitError) as exc_info:
            raise_for_order_status(409, "Order group triggered", {"message": "Order group already triggered"})
        assert exc_info.value.error_code == KalshiOrderErrorCode.ORDER_GROUP_TRIGGERED

    def test_raise_for_422_insufficient_funds(self):
        """422 with insufficient message raises KalshiInsufficientFundsError."""
        with pytest.raises(KalshiInsufficientFundsError):
            raise_for_order_status(422, "Insufficient", {"message": "Insufficient funds"})

    def test_raise_for_422_position_limit(self):
        """422 with limit/cap message raises KalshiPositionLimitError."""
        with pytest.raises(KalshiPositionLimitError):
            raise_for_order_status(422, "Limit exceeded", {"message": "Position limit would be exceeded"})

    def test_raise_for_429_rate_limit(self):
        """429 raises KalshiRateLimitError with retry_after."""
        with pytest.raises(KalshiRateLimitError) as exc_info:
            raise_for_order_status(429, "Rate limited", {"message": "Too many requests", "retry_after": 60})
        assert exc_info.value.retry_after == 60
        assert exc_info.value.error_code == KalshiOrderErrorCode.RATE_LIMIT

    def test_raise_for_503_circuit_breaker(self):
        """503 with circuit message raises KalshiCircuitBreakerError."""
        with pytest.raises(KalshiCircuitBreakerError):
            raise_for_order_status(503, "Circuit breaker", {"message": "Circuit breaker is open"})

    def test_raise_for_5xx_exchange_error(self):
        """5xx raises KalshiExchangeError."""
        with pytest.raises(KalshiExchangeError) as exc_info:
            raise_for_order_status(500, "Internal error", {"message": "Internal server error"})
        assert exc_info.value.error_code == KalshiOrderErrorCode.EXCHANGE_ERROR

    def test_raise_for_502_exchange_error(self):
        """502 raises KalshiExchangeError."""
        with pytest.raises(KalshiExchangeError):
            raise_for_order_status(502, "Bad gateway", {"message": "Bad gateway"})

    def test_raise_with_error_context(self):
        """error_context is included in error details."""
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(
                400, "Bad request",
                {"message": "Bad request"},
                error_context={"ticker": "BTC-USD", "side": "yes"}
            )
        assert exc_info.value.details.get("context") == {"ticker": "BTC-USD", "side": "yes"}

    def test_raise_with_error_code_from_response(self):
        """error_code from response JSON is parsed and used."""
        with pytest.raises(KalshiValidationError) as exc_info:
            raise_for_order_status(
                400, "Invalid",
                {"message": "Invalid", "error_code": "invalid_price"}
            )
        assert exc_info.value.error_code == KalshiOrderErrorCode.INVALID_PRICE


class TestErrorTaxonomyCompleteness:
    """Ensure the error taxonomy covers all expected scenarios."""

    def test_all_error_codes_have_unique_values(self):
        """All enum values are unique."""
        values = [code.value for code in KalshiOrderErrorCode]
        assert len(values) == len(set(values)), "All error code values should be unique"

    def test_all_error_codes_have_metadata(self):
        """All error codes return valid metadata."""
        for code in KalshiOrderErrorCode:
            assert code.severity in ("critical", "warning", "info")
            assert code.category in ("risk", "validation", "market", "system", "funds", "auth", "order_group", "other")
            assert isinstance(code.description, str)
            assert isinstance(code.is_retryable, bool)

    def test_legacy_error_type_compatibility(self):
        """error_type property is populated for backward compatibility."""
        err = KalshiOrderError("Test", error_code=KalshiOrderErrorCode.KILL_SWITCH)
        assert err.error_type == "risk"
        assert err.error_type == err.category  # Should match category
