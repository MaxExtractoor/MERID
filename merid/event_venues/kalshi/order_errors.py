"""Structured error handling for Kalshi order operations.

Provides exception hierarchy for order-related errors with proper categorization
for retry logic and user-facing error messages.
"""

from enum import Enum
from typing import Any, Dict, Optional


class KalshiOrderErrorCode(str, Enum):
    """Structured error codes for Kalshi order operations.

    These codes are used in metrics, NoTrade tracking, and structured logging
    so operators can correlate failure types across the pipeline.
    """
    # Execution failures at the PM-agent layer (before any venue call)
    PM_AGENT_EXECUTION = "pm_agent_execution"
    # Venue / API-level errors
    VALIDATION_ERROR = "validation_error"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT = "rate_limit"
    EXCHANGE_ERROR = "exchange_error"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    MARKET_CLOSED = "market_closed"
    # Risk / gate errors
    RISK_BLOCKED = "risk_blocked"
    KILL_SWITCH = "kill_switch"
    STALE_SNAPSHOT = "stale_snapshot"
    # Misc
    UNKNOWN = "unknown"


class KalshiOrderError(Exception):
    """Base exception for Kalshi order operations.

    Attributes:
        message: Error message
        status_code: HTTP status code if applicable
        error_type: Category of error (validation, auth, rate_limit, exchange)
        details: Additional error details from API response
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_type: str = "unknown",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.details = details or {}

    def __str__(self) -> str:
        if self.status_code:
            return f"[{self.error_type}] {self.status_code}: {self.message}"
        return f"[{self.error_type}] {self.message}"


class KalshiValidationError(KalshiOrderError):
    """Order validation failed (400 Bad Request).

    This indicates the order parameters were invalid.
    Do not retry - fix the order parameters.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=400,
            error_type="validation",
            details=details,
        )


class KalshiAuthError(KalshiOrderError):
    """Authentication failed (401 Unauthorized / 403 Forbidden).

    This indicates API keys are invalid or permissions are insufficient.
    Do not retry without fixing credentials.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=401,
            error_type="auth",
            details=details,
        )


class KalshiRateLimitError(KalshiOrderError):
    """Rate limit exceeded (429 Too Many Requests).

    This indicates the API rate limit has been hit.
    Retry with exponential backoff.
    """

    def __init__(
        self,
        message: str = "Rate-limited while placing orders",
        retry_after: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=429,
            error_type="rate_limit",
            details=details,
        )
        self.retry_after = retry_after


class KalshiExchangeError(KalshiOrderError):
    """Kalshi exchange error (5xx).

    This indicates an internal error at Kalshi.
    Retry with exponential backoff.
    """

    def __init__(
        self,
        message: str = "Exchange error, try again later",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code,
            error_type="exchange",
            details=details,
        )


class KalshiInsufficientFundsError(KalshiOrderError):
    """Insufficient funds for order (422 or 400 with specific message).

    This indicates the account has insufficient balance.
    Do not retry without depositing funds or reducing order size.
    """

    def __init__(self, message: str = "Insufficient funds for order", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=422,
            error_type="insufficient_funds",
            details=details,
        )


class KalshiMarketClosedError(KalshiOrderError):
    """Market is closed or trading halted.

    This indicates the market is not accepting orders.
    Do not retry - check market status.
    """

    def __init__(self, message: str = "Market is closed", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            status_code=400,
            error_type="market_closed",
            details=details,
        )


class KalshiOrderGroupDeleteError(KalshiOrderError):
    """Order group deletion failed.

    This indicates an error while deleting an order group.
    404 is treated as "already deleted" and returns False.
    Other errors should be investigated.
    """

    def __init__(
        self,
        message: str,
        group_id: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code or 500,
            error_type="order_group_delete",
            details=details,
        )
        self.group_id = group_id


class KalshiOrderGroupLimitError(KalshiOrderError):
    """Order group limit update failed.

    This indicates an error while updating an order group limit.
    Common cases:
    - 400 invalid_limit: contracts_limit out of range or mismatch
    - 404 order_group_not_found: group doesn't exist
    - 409 group_triggered: group already triggered, reset required
    """

    def __init__(
        self,
        message: str,
        group_id: Optional[str] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code or 400,
            error_type="order_group_limit",
            details=details,
        )
        self.group_id = group_id
        self.error_code = error_code


def raise_for_order_status(status_code: int, response_text: str, response_json: Optional[Dict] = None) -> None:
    """Raise appropriate exception based on HTTP status code.

    Args:
        status_code: HTTP status code
        response_text: Raw response text
        response_json: Parsed response JSON if available

    Raises:
        KalshiOrderError: Appropriate subclass based on status code
    """
    message = ""
    if response_json:
        message = response_json.get("message", "")
    if not message:
        message = response_text[:200]  # First 200 chars

    details = response_json or {}

    if status_code == 400:
        # Check for specific error patterns
        msg_lower = message.lower()
        if "insufficient" in msg_lower or "balance" in msg_lower:
            raise KalshiInsufficientFundsError(message, details)
        if "closed" in msg_lower or "halted" in msg_lower:
            raise KalshiMarketClosedError(message, details)
        raise KalshiValidationError(message, details)

    if status_code in (401, 403):
        raise KalshiAuthError(message, details)

    if status_code == 429:
        retry_after = None
        if response_json:
            retry_after = response_json.get("retry_after")
        raise KalshiRateLimitError(message, retry_after, details)

    if status_code == 422:
        msg_lower = message.lower()
        if "insufficient" in msg_lower:
            raise KalshiInsufficientFundsError(message, details)
        raise KalshiValidationError(message, details)

    if 500 <= status_code < 600:
        raise KalshiExchangeError(message, status_code, details)

    # Unknown error - raise generic
    raise KalshiOrderError(
        message=message,
        status_code=status_code,
        error_type="unknown",
        details=details,
    )


def is_retryable_error(error: KalshiOrderError) -> bool:
    """Check if an error is retryable.

    Args:
        error: The error to check

    Returns:
        True if the error is retryable with backoff
    """
    return error.error_type in ("rate_limit", "exchange")


def get_user_message(error: KalshiOrderError) -> str:
    """Get user-friendly error message.

    Args:
        error: The error

    Returns:
        User-friendly message for display
    """
    messages = {
        "validation": f"Order validation failed: {error.message}",
        "auth": "Authentication failed. Check your API keys and permissions.",
        "rate_limit": "Too many requests. Please wait a moment and try again.",
        "exchange": "Kalshi is experiencing issues. Please try again later.",
        "insufficient_funds": f"Insufficient funds: {error.message}",
        "market_closed": f"Market unavailable: {error.message}",
        "unknown": f"Order failed: {error.message}",
    }
    return messages.get(error.error_type, error.message)
