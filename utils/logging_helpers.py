"""Logging utilities and helpers for structured logging.

Provides convenience functions and context managers for consistent
structured logging across the MERID codebase.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from utils.logger import get_logger, set_task_context

logger = get_logger(__name__)


@contextmanager
def log_execution(
    operation_name: str,
    logger_instance: Any = None,
    log_level: str = "INFO",
    **extra_fields: Any,
):
    """Context manager to log execution duration and result.
    
    Args:
        operation_name: Name of the operation being logged
        logger_instance: Logger instance (uses module logger if None)
        log_level: Log level to use (INFO, DEBUG, etc.)
        **extra_fields: Extra fields to include in log entry
    
    Example:
        with log_execution("order_submission", logger, market_id="KXBTUPDOWN-15M"):
            submit_order(...)
    """
    if logger_instance is None:
        logger_instance = logger
    
    start_time = time.time()
    extra_fields["operation"] = operation_name
    
    logger_instance.log(
        log_level,
        f"{operation_name} started",
        extra={**extra_fields, "status": "started"}
    )
    
    try:
        yield
        duration_ms = (time.time() - start_time) * 1000
        logger_instance.log(
            log_level,
            f"{operation_name} completed",
            extra={**extra_fields, "status": "completed", "duration_ms": duration_ms}
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger_instance.error(
            f"{operation_name} failed",
            extra={
                **extra_fields,
                "status": "failed",
                "duration_ms": duration_ms,
                "error_type": type(e).__name__,
                "error_message": str(e)
            },
            exc_info=True
        )
        raise


@contextmanager
def log_trading_context(
    venue: str,
    agent_id: str,
    mode: str,
    env: str,
    tick: Optional[int] = None,
):
    """Context manager to set trading task context.
    
    Args:
        venue: Trading venue (kalshi, alpaca, etc.)
        agent_id: Agent identifier
        mode: Trading mode (paper, live)
        env: Environment (demo, production)
        tick: Loop tick number
    
    Example:
        with log_trading_context("kalshi", "btc_15m_regime", "paper", "demo", tick=12345):
            # All logs in this block will have trading context
            logger.info("Processing market data")
    """
    set_task_context(
        venue=venue,
        agent_id=agent_id,
        mode=mode,
        env=env,
        tick=tick
    )
    yield


def log_trading_operation(
    operation: str,
    logger_instance: Any,
    market_id: Optional[str] = None,
    side: Optional[str] = None,
    contracts: Optional[int] = None,
    price_cents: Optional[int] = None,
    notional_usd: Optional[float] = None,
    **extra_fields: Any,
) -> None:
    """Log a trading operation with standard fields.
    
    Args:
        operation: Operation name (e.g., "order_submitted", "fill_received")
        logger_instance: Logger instance
        market_id: Market identifier
        side: Order side (YES, NO, BUY, SELL)
        contracts: Number of contracts
        price_cents: Price in cents
        notional_usd: Notional value in USD
        **extra_fields: Additional fields to log
    """
    extra = {
        "operation": operation,
        "domain": "trading",
    }
    
    if market_id:
        extra["market_id"] = market_id
    if side:
        extra["side"] = side
    if contracts is not None:
        extra["contracts"] = contracts
    if price_cents is not None:
        extra["price_cents"] = price_cents
    if notional_usd is not None:
        extra["notional_usd"] = notional_usd
    
    extra.update(extra_fields)
    
    logger_instance.info(f"{operation}", extra=extra)


def log_risk_check(
    check_name: str,
    logger_instance: Any,
    current_value: Optional[float] = None,
    limit_value: Optional[float] = None,
    action: Optional[str] = None,
    **extra_fields: Any,
) -> None:
    """Log a risk check with standard fields.
    
    Args:
        check_name: Name of the risk check (e.g., "position_limit", "drawdown")
        logger_instance: Logger instance
        current_value: Current value being checked
        limit_value: Limit threshold
        action: Action taken (allow, reject, warn)
        **extra_fields: Additional fields to log
    """
    extra = {
        "risk_check": check_name,
        "domain": "risk",
    }
    
    if current_value is not None:
        extra["current_value"] = current_value
    if limit_value is not None:
        extra["limit_value"] = limit_value
    if action:
        extra["action"] = action
    
    extra.update(extra_fields)
    
    import logging
    log_level = logging.WARNING if action == "reject" else logging.INFO
    logger_instance.log(log_level, f"Risk check: {check_name}", extra=extra)


def log_guardrail_check(
    guardrail_name: str,
    logger_instance: Any,
    value: Optional[float] = None,
    threshold: Optional[float] = None,
    passed: bool = True,
    **extra_fields: Any,
) -> None:
    """Log a guardrail check with standard fields.
    
    Args:
        guardrail_name: Name of the guardrail (e.g., "max_spread", "min_depth")
        logger_instance: Logger instance
        value: Value being checked
        threshold: Threshold value
        passed: Whether the check passed
        **extra_fields: Additional fields to log
    """
    extra = {
        "guardrail": guardrail_name,
        "domain": "execution",
        "passed": passed,
    }
    
    if value is not None:
        extra["value"] = value
    if threshold is not None:
        extra["threshold"] = threshold
    
    extra.update(extra_fields)
    
    log_level = "WARNING" if not passed else "DEBUG"
    logger_instance.log(log_level, f"Guardrail: {guardrail_name}", extra=extra)


def log_api_request(
    logger_instance: Any,
    endpoint: str,
    method: str = "GET",
    client_ip: Optional[str] = None,
    **extra_fields: Any,
) -> None:
    """Log an API request with standard fields.
    
    Args:
        logger_instance: Logger instance
        endpoint: API endpoint path
        method: HTTP method
        client_ip: Client IP address
        **extra_fields: Additional fields to log
    """
    extra = {
        "endpoint": endpoint,
        "method": method,
        "domain": "api",
    }
    
    if client_ip:
        extra["client_ip"] = client_ip
    
    extra.update(extra_fields)
    
    logger_instance.info(f"API request: {method} {endpoint}", extra=extra)


def log_api_response(
    logger_instance: Any,
    endpoint: str,
    status_code: int,
    duration_ms: float,
    **extra_fields: Any,
) -> None:
    """Log an API response with standard fields.
    
    Args:
        logger_instance: Logger instance
        endpoint: API endpoint path
        status_code: HTTP status code
        duration_ms: Request duration in milliseconds
        **extra_fields: Additional fields to log
    """
    extra = {
        "endpoint": endpoint,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "domain": "api",
    }
    
    extra.update(extra_fields)
    
    log_level = "ERROR" if status_code >= 400 else "INFO"
    logger_instance.log(log_level, f"API response: {endpoint}", extra=extra)


def log_error(
    logger_instance: Any,
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    **extra_fields: Any,
) -> None:
    """Log an error with exception details and context.
    
    Args:
        logger_instance: Logger instance
        error: Exception object
        context: Additional context dictionary
        **extra_fields: Additional fields to log
    """
    extra = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    
    if context:
        extra.update(context)
    
    extra.update(extra_fields)
    
    logger_instance.error(
        f"Error: {type(error).__name__}: {str(error)}",
        extra=extra,
        exc_info=True
    )
