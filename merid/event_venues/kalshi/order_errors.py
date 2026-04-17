"""Structured error handling for Kalshi order operations.

Provides exception hierarchy for order-related errors with proper categorization
for retry logic and user-facing error messages.
"""

from collections import defaultdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


# ── Error code taxonomy ──────────────────────────────────────────────────────


class KalshiOrderErrorCode(Enum):
    """Rich error code enum with embedded metadata (severity, category, etc.).

    Each member carries (value, severity, category, description, is_retryable).
    """

    # ── Risk / safety ────────────────────────────────────────────────────────
    KILL_SWITCH = ("kill_switch", "critical", "risk", "Kill switch active - trading halted", False)
    CIRCUIT_BREAKER = ("circuit_breaker", "critical", "risk", "Circuit breaker tripped", False)
    DAILY_LOSS_LIMIT = ("daily_loss_limit", "critical", "risk", "Daily loss limit reached", False)
    DRAWDOWN_HALT = ("drawdown_halt", "critical", "risk", "Max drawdown exceeded", False)
    CATEGORY_CAP_EXCEEDED = ("category_cap_exceeded", "critical", "risk", "Category position cap exceeded", False)
    POSITION_LIMIT = ("position_limit", "warning", "risk", "Position limit would be exceeded", False)
    CORRELATED_STACK_CAP = ("correlated_stack_cap", "warning", "risk", "Correlated stack cap exceeded", False)
    RISK_CHECK_FAILED = ("risk_check_failed", "warning", "risk", "Risk check failed", False)
    SANITY_CHECK_FAILED = ("sanity_check_failed", "warning", "risk", "Sanity check failed", False)

    # ── Validation ───────────────────────────────────────────────────────────
    INVALID_ORDER = ("invalid_order", "info", "validation", "Order parameters are invalid", False)
    NON_POSITIVE_SIZE = ("non_positive_size", "info", "validation", "Order size must be positive", False)
    INVALID_PRICE = ("invalid_price", "warning", "validation", "Invalid price submitted", False)
    INVALID_TICKER = ("invalid_ticker", "warning", "validation", "Unknown or invalid ticker", False)
    INVALID_SIDE = ("invalid_side", "warning", "validation", "Side must be yes or no", False)
    INVALID_ACTION = ("invalid_action", "warning", "validation", "Invalid order action", False)
    UNSUPPORTED_MODE = ("unsupported_mode", "warning", "validation", "Mode not supported for this route", False)
    SYNC_ROUTE_UNSUPPORTED = ("sync_route_unsupported", "warning", "validation", "Sync route not supported", False)

    # ── Market conditions ────────────────────────────────────────────────────
    MARKET_CLOSED = ("market_closed", "warning", "market", "Market is closed or halted", False)
    MARKET_NOT_FOUND = ("market_not_found", "warning", "market", "Market not found", False)
    MARKET_NOT_TRADEABLE = ("market_not_tradeable", "warning", "market", "Market is not tradeable", False)
    SPREAD_TOO_WIDE = ("spread_too_wide", "warning", "market", "Spread is too wide to trade", False)
    PRICE_OUTSIDE_RANGE = ("price_outside_range", "warning", "market", "Price is outside valid market range", False)
    VOLUME_TOO_LOW = ("volume_too_low", "warning", "market", "Volume too low to trade", False)
    MARKET_CONDITION_UNFAVORABLE = ("market_condition_unfavorable", "warning", "market", "Market conditions unfavorable", False)

    # ── System ───────────────────────────────────────────────────────────────
    EXCHANGE_ERROR = ("exchange_error", "critical", "system", "Exchange error occurred", True)
    RATE_LIMIT = ("rate_limit", "warning", "system", "Rate limit hit - throttling", True)
    WEBSOCKET_UNAVAILABLE = ("websocket_unavailable", "warning", "system", "WebSocket connection unavailable", True)
    LIVE_EXECUTION_ERROR = ("live_execution_error", "warning", "system", "Live execution error", False)
    RISK_CONTROLLER_UNAVAILABLE = ("risk_controller_unavailable", "critical", "system", "Risk controller unavailable", True)
    RISK_MANAGER_UNAVAILABLE = ("risk_manager_unavailable", "critical", "system", "Risk manager unavailable", True)
    ROUTING_EXCEPTION = ("routing_exception", "warning", "system", "Order routing exception", True)
    PM_AGENT_EXECUTION = (
        "pm_agent_execution",
        "warning",
        "system",
        "PM agent execution failed before/during order routing",
        False,
    )
    UNKNOWN = ("unknown", "info", "system", "Unknown error occurred", True)

    # ── Funds / balance ──────────────────────────────────────────────────────
    INSUFFICIENT_FUNDS = ("insufficient_funds", "warning", "funds", "Insufficient funds for order", False)
    MAX_COST_EXCEEDED = ("max_cost_exceeded", "warning", "funds", "Max cost per order exceeded", False)
    LIVE_NOT_ENABLED = ("live_not_enabled", "warning", "funds", "Live trading is not enabled", False)

    # ── Auth ─────────────────────────────────────────────────────────────────
    AUTH_FAILED = ("auth_failed", "info", "auth", "Authentication failed", False)
    API_KEY_INVALID = ("api_key_invalid", "warning", "auth", "API key is invalid or expired", False)
    FORBIDDEN = ("forbidden", "warning", "auth", "Access forbidden", False)

    # ── Order groups ─────────────────────────────────────────────────────────
    ORDER_GROUP_NOT_FOUND = ("order_group_not_found", "warning", "order_group", "Order group not found", False)
    ORDER_GROUP_INVALID_LIMIT = ("order_group_invalid_limit", "warning", "order_group", "Invalid order group limit", False)
    ORDER_GROUP_TRIGGERED = ("order_group_triggered", "warning", "order_group", "Order group already triggered", False)

    def __new__(
        cls,
        value: str,
        severity: str,
        category: str,
        description: str,
        is_retryable: bool,
    ) -> "KalshiOrderErrorCode":
        obj = object.__new__(cls)
        obj._value_ = value
        obj.severity = severity
        obj.category = category
        obj.description = description
        obj.is_retryable = is_retryable
        return obj

    @classmethod
    def from_string(cls, value: Optional[str]) -> "KalshiOrderErrorCode":
        """Safely convert a string to an error code, defaulting to UNKNOWN."""
        if not value:
            return cls.UNKNOWN
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


# ── Exception hierarchy ──────────────────────────────────────────────────────


class KalshiOrderError(Exception):
    """Base exception for Kalshi order operations."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[KalshiOrderErrorCode] = None,
        details: Optional[Dict[str, Any]] = None,
        # Legacy compat — error_type was used before error_code
        error_type: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self._error_code = error_code or KalshiOrderErrorCode.UNKNOWN
        self.details = details or {}

    @property
    def error_code(self) -> KalshiOrderErrorCode:
        return self._error_code

    @property
    def severity(self) -> str:
        return self._error_code.severity

    @property
    def category(self) -> str:
        return self._error_code.category

    @property
    def is_retryable(self) -> bool:
        return self._error_code.is_retryable

    @property
    def error_type(self) -> str:
        """Backward-compatible alias for category."""
        return self._error_code.category

    def __str__(self) -> str:
        code_val = self._error_code.value
        if self.status_code:
            return f"[{code_val}] {self.status_code}: {self.message}"
        return f"[{code_val}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self._error_code.value,
            "message": self.message,
            "status_code": self.status_code,
            "severity": self.severity,
            "category": self.category,
            "error_type": self.error_type,
            "is_retryable": self.is_retryable,
            "description": self._error_code.description,
            "details": self.details,
        }


class KalshiValidationError(KalshiOrderError):
    """Order validation failed (400 Bad Request)."""

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        error_code: Optional[KalshiOrderErrorCode] = None,
    ):
        super().__init__(
            message=message,
            status_code=400,
            error_code=error_code or KalshiOrderErrorCode.INVALID_ORDER,
            details=details,
        )


class KalshiAuthError(KalshiOrderError):
    """Authentication / authorization failed."""

    def __init__(
        self,
        message: str,
        status_code: int = 401,
        details: Optional[Dict[str, Any]] = None,
        error_code: Optional[KalshiOrderErrorCode] = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code,
            error_code=error_code or KalshiOrderErrorCode.AUTH_FAILED,
            details=details,
        )


class KalshiRateLimitError(KalshiOrderError):
    """Rate limit exceeded (429)."""

    def __init__(
        self,
        message: str = "Rate-limited while placing orders",
        retry_after: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=429,
            error_code=KalshiOrderErrorCode.RATE_LIMIT,
            details=details,
        )
        self.retry_after = retry_after


class KalshiExchangeError(KalshiOrderError):
    """Kalshi exchange error (5xx)."""

    def __init__(
        self,
        message: str = "Exchange error, try again later",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code,
            error_code=KalshiOrderErrorCode.EXCHANGE_ERROR,
            details=details,
        )


class KalshiInsufficientFundsError(KalshiOrderError):
    """Insufficient funds (422 / 400)."""

    def __init__(
        self,
        message: str = "Insufficient funds for order",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=422,
            error_code=KalshiOrderErrorCode.INSUFFICIENT_FUNDS,
            details=details,
        )


class KalshiMarketClosedError(KalshiOrderError):
    """Market is closed or trading halted."""

    def __init__(
        self,
        message: str = "Market is closed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=400,
            error_code=KalshiOrderErrorCode.MARKET_CLOSED,
            details=details,
        )


class KalshiKillSwitchError(KalshiOrderError):
    """Kill switch is engaged — all execution blocked."""

    def __init__(
        self,
        message: str = "Kill switch is active",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code=KalshiOrderErrorCode.KILL_SWITCH,
            details=details,
        )


class KalshiRiskCheckError(KalshiOrderError):
    """Generic risk check failed."""

    def __init__(
        self,
        message: str = "Risk check failed",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code=KalshiOrderErrorCode.RISK_CHECK_FAILED,
            details=details,
        )


class KalshiDailyLossLimitError(KalshiOrderError):
    """Daily loss limit reached."""

    def __init__(
        self,
        message: str = "Daily loss limit reached",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code=KalshiOrderErrorCode.DAILY_LOSS_LIMIT,
            details=details,
        )


class KalshiDrawdownHaltError(KalshiOrderError):
    """Maximum drawdown exceeded."""

    def __init__(
        self,
        message: str = "Max drawdown exceeded",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code=KalshiOrderErrorCode.DRAWDOWN_HALT,
            details=details,
        )


class KalshiPositionLimitError(KalshiOrderError):
    """Position limit would be exceeded."""

    def __init__(
        self,
        message: str = "Position limit exceeded",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code=KalshiOrderErrorCode.POSITION_LIMIT,
            details=details,
        )


class KalshiCircuitBreakerError(KalshiOrderError):
    """Circuit breaker is open."""

    def __init__(
        self,
        message: str = "Circuit breaker is open",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=503,
            error_code=KalshiOrderErrorCode.CIRCUIT_BREAKER,
            details=details,
        )


class KalshiLiveNotEnabledError(KalshiOrderError):
    """Live trading is not enabled for this account."""

    def __init__(
        self,
        message: str = "Live trading is not enabled",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code=KalshiOrderErrorCode.LIVE_NOT_ENABLED,
            details=details,
        )


class KalshiLiveExecutionError(KalshiOrderError):
    """Error during live order execution."""

    def __init__(
        self,
        message: str = "Live execution error",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code,
            error_code=KalshiOrderErrorCode.LIVE_EXECUTION_ERROR,
            details=details,
        )


class KalshiOrderGroupDeleteError(KalshiOrderError):
    """Order group deletion failed."""

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
            error_code=KalshiOrderErrorCode.ORDER_GROUP_NOT_FOUND,
            details=details,
        )
        self.group_id = group_id


class KalshiOrderGroupLimitError(KalshiOrderError):
    """Order group limit update failed.

    Common cases:
    - 400 invalid_limit: contracts_limit out of range
    - 404 order_group_not_found: group doesn't exist
    - 409 group_triggered: group already triggered
    """

    def __init__(
        self,
        message: str,
        group_id: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        error_code: Optional[KalshiOrderErrorCode] = None,
    ):
        super().__init__(
            message=message,
            status_code=status_code or 400,
            error_code=error_code or KalshiOrderErrorCode.ORDER_GROUP_INVALID_LIMIT,
            details=details,
        )
        self.group_id = group_id


# ── Utility functions ────────────────────────────────────────────────────────


def raise_for_order_status(
    status_code: int,
    response_text: str,
    response_json: Optional[Dict] = None,
    error_context: Optional[Dict[str, Any]] = None,
) -> None:
    """Raise appropriate exception based on HTTP status code.

    Args:
        status_code: HTTP status code
        response_text: Raw response text
        response_json: Parsed response JSON if available
        error_context: Extra context to include in details["context"]

    Raises:
        KalshiOrderError: Appropriate subclass based on status code and message
    """
    message = ""
    if response_json:
        message = response_json.get("message", "")
    if not message:
        message = response_text[:200]

    details: Dict[str, Any] = dict(response_json or {})
    if error_context:
        details["context"] = error_context

    msg_lower = message.lower()

    # ── Try to parse error_code from response JSON ───────────────────────────
    json_error_code: Optional[KalshiOrderErrorCode] = None
    if response_json and "error_code" in response_json:
        raw_code = response_json["error_code"]
        if isinstance(raw_code, str):
            parsed = KalshiOrderErrorCode.from_string(raw_code)
            if parsed != KalshiOrderErrorCode.UNKNOWN:
                json_error_code = parsed

    # ── 400 Bad Request ──────────────────────────────────────────────────────
    if status_code == 400:
        if "kill switch" in msg_lower:
            raise KalshiKillSwitchError(message, details)
        if "position limit" in msg_lower or "position limit would" in msg_lower:
            raise KalshiPositionLimitError(message, details)
        if "insufficient" in msg_lower or "balance" in msg_lower:
            raise KalshiInsufficientFundsError(message, details)
        if "closed" in msg_lower or "halted" in msg_lower:
            raise KalshiMarketClosedError(message, details)
        raise KalshiValidationError(message, details, error_code=json_error_code)

    # ── 401 Unauthorized ─────────────────────────────────────────────────────
    if status_code == 401:
        raise KalshiAuthError(message, status_code=401, details=details,
                              error_code=KalshiOrderErrorCode.AUTH_FAILED)

    # ── 403 Forbidden ────────────────────────────────────────────────────────
    if status_code == 403:
        if "kill switch" in msg_lower:
            raise KalshiKillSwitchError(message, details)
        if "daily loss" in msg_lower:
            raise KalshiDailyLossLimitError(message, details)
        if "drawdown" in msg_lower or "max drawdown" in msg_lower:
            raise KalshiDrawdownHaltError(message, details)
        if "live not enabled" in msg_lower or "live trading not enabled" in msg_lower:
            raise KalshiLiveNotEnabledError(message, details)
        raise KalshiAuthError(message, status_code=403, details=details,
                              error_code=KalshiOrderErrorCode.FORBIDDEN)

    # ── 404 Not Found ────────────────────────────────────────────────────────
    if status_code == 404:
        if "order group" in msg_lower:
            raise KalshiOrderGroupLimitError(
                message, status_code=404, details=details,
                error_code=KalshiOrderErrorCode.ORDER_GROUP_NOT_FOUND,
            )
        if "market" in msg_lower:
            raise KalshiValidationError(
                message, details, error_code=KalshiOrderErrorCode.MARKET_NOT_FOUND,
            )
        raise KalshiValidationError(message, details)

    # ── 409 Conflict ─────────────────────────────────────────────────────────
    if status_code == 409:
        if "order group" in msg_lower:
            raise KalshiOrderGroupLimitError(
                message, status_code=409, details=details,
                error_code=KalshiOrderErrorCode.ORDER_GROUP_TRIGGERED,
            )
        raise KalshiOrderError(message=message, status_code=409, details=details)

    # ── 422 Unprocessable ────────────────────────────────────────────────────
    if status_code == 422:
        if "insufficient" in msg_lower:
            raise KalshiInsufficientFundsError(message, details)
        if "limit" in msg_lower or "cap" in msg_lower:
            raise KalshiPositionLimitError(message, details)
        raise KalshiValidationError(message, details)

    # ── 429 Too Many Requests ────────────────────────────────────────────────
    if status_code == 429:
        retry_after = response_json.get("retry_after") if response_json else None
        raise KalshiRateLimitError(message, retry_after, details)

    # ── 503 Service Unavailable ──────────────────────────────────────────────
    if status_code == 503:
        if "circuit" in msg_lower:
            raise KalshiCircuitBreakerError(message, details)
        raise KalshiExchangeError(message, status_code, details)

    # ── All other 5xx ────────────────────────────────────────────────────────
    if 500 <= status_code < 600:
        raise KalshiExchangeError(message, status_code, details)

    # ── Unknown ──────────────────────────────────────────────────────────────
    raise KalshiOrderError(
        message=message,
        status_code=status_code,
        error_code=KalshiOrderErrorCode.UNKNOWN,
        details=details,
    )


def is_retryable_error(error: KalshiOrderError) -> bool:
    """Check if an error is retryable."""
    return error.is_retryable


def get_user_message(error: KalshiOrderError) -> str:
    """Get user-friendly error message."""
    category = error.category
    if category == "validation":
        return f"Order validation failed: {error.message}"
    if category == "auth":
        return f"Authentication failed. Check your API keys and permissions."
    if category == "funds":
        return f"Insufficient funds: {error.message}"
    if category == "market":
        return f"Market unavailable: {error.message}"
    if category == "risk":
        return f"Risk check failed: {error.message}"
    if category == "order_group":
        return f"Order group error: {error.message}"
    if category == "system":
        return f"System error: {error.message}"
    return f"Order failed: {error.message}"


def get_error_breakdown(
    codes: List[Union[str, KalshiOrderErrorCode]],
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, List[str]]]:
    """Aggregate error codes into by_code, by_severity, and by_category counts.

    Args:
        codes: List of error code strings or KalshiOrderErrorCode enum values

    Returns:
        (by_code, by_severity, by_category) where:
        - by_code: {code_value: count}
        - by_severity: {severity: count}  (always has critical/warning/info keys)
        - by_category: {category: [code_values]}
    """
    by_code: Dict[str, int] = defaultdict(int)
    by_severity: Dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    by_category: Dict[str, List[str]] = defaultdict(list)

    for raw in codes:
        if isinstance(raw, KalshiOrderErrorCode):
            code = raw
        else:
            code = KalshiOrderErrorCode.from_string(raw)

        by_code[code.value] += 1
        sev = code.severity
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if code.value not in by_category[code.category]:
            by_category[code.category].append(code.value)

    return dict(by_code), by_severity, dict(by_category)
