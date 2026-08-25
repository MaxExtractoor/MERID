"""Structured Error Classification System (2026 Best Practice).

Provides consistent error classification across the MERID system to enable:
- Distinction between expected vs unexpected errors
- Appropriate alerting thresholds (INFO vs WARNING vs ERROR)
- Degradation telemetry and monitoring
- Fail-open vs fail-closed decision support

Based on 2026 research: fail-open patterns require structured error classification
to avoid masking unexpected bugs while allowing graceful degradation for known issues.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass
import traceback


class ErrorCategory(Enum):
    """High-level error categories for classification."""
    
    # Expected operational issues (graceful degradation appropriate)
    NETWORK_TIMEOUT = "network_timeout"  # Transient network issues
    API_RATE_LIMIT = "api_rate_limit"  # Expected rate limiting
    DATA_STALE = "data_stale"  # Stale but usable data
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"  # Optional service down
    
    # Unexpected errors (should alert, fail-closed appropriate)
    DATA_CORRUPTION = "data_corruption"  # Invalid/inconsistent data
    LOGIC_ERROR = "logic_error"  # Code bugs, assertion failures
    STATE_CORRUPTION = "state_corruption"  # Invalid system state
    SECURITY_VIOLATION = "security_violation"  # Auth/permission issues
    
    # Unknown/unclassified
    UNKNOWN = "unknown"


class ErrorSeverity(Enum):
    """Error severity levels for alerting and response."""
    
    INFO = "info"  # Normal operational event, no action needed
    WARNING = "warning"  # Degraded but operational, monitor closely
    ERROR = "error"  # Requires attention, may impact functionality
    CRITICAL = "critical"  # Immediate action required, system at risk


class ErrorRecoveryStrategy(Enum):
    """Recovery strategy for classified errors."""
    
    # Graceful degradation (fail-open)
    RETRY_WITH_BACKOFF = "retry_with_backoff"  # Retry with exponential backoff
    USE_FALLBACK = "use_fallback"  # Use alternative data source
    DEGRADE_SERVICE = "degrade_service"  # Reduce functionality
    CONTINUE_WITH_WARNING = "continue_with_warning"  # Continue but log warning
    
    # Fail-closed (safety first)
    FAIL_CLOSED = "fail_closed"  # Block operation
    EMERGENCY_SHUTDOWN = "emergency_shutdown"  # Stop system
    RESTART_COMPONENT = "restart_component"  # Restart affected component
    ALERT_OPERATOR = "alert_operator"  # Require human intervention


@dataclass
class ClassifiedError:
    """Structured error classification with recovery guidance."""
    
    category: ErrorCategory
    severity: ErrorSeverity
    recovery_strategy: ErrorRecoveryStrategy
    message: str
    context: Dict[str, Any]
    traceback_str: Optional[str] = None
    timestamp: Optional[float] = None
    
    def should_alert(self) -> bool:
        """Determine if this error should trigger an alert."""
        return self.severity in [ErrorSeverity.ERROR, ErrorSeverity.CRITICAL]
    
    def is_expected(self) -> bool:
        """Determine if this is an expected operational issue."""
        return self.category in [
            ErrorCategory.NETWORK_TIMEOUT,
            ErrorCategory.API_RATE_LIMIT,
            ErrorCategory.DATA_STALE,
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
        ]
    
    def is_fail_open(self) -> bool:
        """Determine if this should use fail-open behavior."""
        return self.recovery_strategy in [
            ErrorRecoveryStrategy.RETRY_WITH_BACKOFF,
            ErrorRecoveryStrategy.USE_FALLBACK,
            ErrorRecoveryStrategy.DEGRADE_SERVICE,
            ErrorRecoveryStrategy.CONTINUE_WITH_WARNING,
        ]


class ErrorClassifier:
    """Classifies errors based on exception type and context."""
    
    # Known exception patterns
    NETWORK_EXCEPTIONS = [
        "ConnectionError",
        "TimeoutError",
        "requests.exceptions.Timeout",
        "requests.exceptions.ConnectionError",
        "asyncio.TimeoutError",
    ]
    
    RATE_LIMIT_EXCEPTIONS = [
        "RateLimitError",
        "TooManyRequests",
        "429",
    ]
    
    DATA_QUALITY_EXCEPTIONS = [
        "ValueError",
        "KeyError",
        "AttributeError",
        "TypeError",
    ]
    
    @classmethod
    def classify(
        cls,
        exception: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> ClassifiedError:
        """Classify an exception with appropriate category and recovery strategy.
        
        Args:
            exception: The exception to classify
            context: Additional context about the error
            
        Returns:
            ClassifiedError with category, severity, and recovery strategy
        """
        import time
        
        context = context or {}
        exception_type = type(exception).__name__
        exception_message = str(exception)
        
        # Check for network/timeout issues
        if any(pattern in exception_type or pattern in exception_message 
               for pattern in cls.NETWORK_EXCEPTIONS):
            return ClassifiedError(
                category=ErrorCategory.NETWORK_TIMEOUT,
                severity=ErrorSeverity.WARNING,
                recovery_strategy=ErrorRecoveryStrategy.RETRY_WITH_BACKOFF,
                message=f"Network timeout: {exception_message}",
                context=context,
                traceback_str=traceback.format_exc(),
                timestamp=time.time(),
            )
        
        # Check for rate limiting
        if any(pattern in exception_type or pattern in exception_message 
               for pattern in cls.RATE_LIMIT_EXCEPTIONS):
            return ClassifiedError(
                category=ErrorCategory.API_RATE_LIMIT,
                severity=ErrorSeverity.WARNING,
                recovery_strategy=ErrorRecoveryStrategy.RETRY_WITH_BACKOFF,
                message=f"Rate limit exceeded: {exception_message}",
                context=context,
                traceback_str=traceback.format_exc(),
                timestamp=time.time(),
            )
        
        # Check for data quality issues
        if any(pattern in exception_type or pattern in exception_message 
               for pattern in cls.DATA_QUALITY_EXCEPTIONS):
            # Check if this is expected (e.g., missing optional field)
            if context.get("expected_field_missing"):
                return ClassifiedError(
                    category=ErrorCategory.DATA_STALE,
                    severity=ErrorSeverity.INFO,
                    recovery_strategy=ErrorRecoveryStrategy.USE_FALLBACK,
                    message=f"Expected field missing: {exception_message}",
                    context=context,
                    traceback_str=traceback.format_exc(),
                    timestamp=time.time(),
                )
            else:
                return ClassifiedError(
                    category=ErrorCategory.DATA_CORRUPTION,
                    severity=ErrorSeverity.ERROR,
                    recovery_strategy=ErrorRecoveryStrategy.FAIL_CLOSED,
                    message=f"Data corruption: {exception_message}",
                    context=context,
                    traceback_str=traceback.format_exc(),
                    timestamp=time.time(),
                )
        
        # Default to unknown/logic error
        return ClassifiedError(
            category=ErrorCategory.LOGIC_ERROR,
            severity=ErrorSeverity.ERROR,
            recovery_strategy=ErrorRecoveryStrategy.ALERT_OPERATOR,
            message=f"Unexpected error: {exception_type}: {exception_message}",
            context=context,
            traceback_str=traceback.format_exc(),
            timestamp=time.time(),
        )


def classify_and_log(
    exception: Exception,
    logger,
    context: Optional[Dict[str, Any]] = None,
    component: str = "unknown"
) -> ClassifiedError:
    """Classify an exception and log it with appropriate level.
    
    Args:
        exception: The exception to classify and log
        logger: Logger instance
        context: Additional context about the error
        component: Component name for log prefix
        
    Returns:
        ClassifiedError for further processing
    """
    classified = ErrorClassifier.classify(exception, context)
    
    # Log with appropriate level
    if classified.severity == ErrorSeverity.INFO:
        logger.info(f"[{component}] {classified.message} | category={classified.category.value}")
    elif classified.severity == ErrorSeverity.WARNING:
        logger.warning(f"[{component}] {classified.message} | category={classified.category.value} | strategy={classified.recovery_strategy.value}")
    elif classified.severity == ErrorSeverity.ERROR:
        logger.error(f"[{component}] {classified.message} | category={classified.category.value} | strategy={classified.recovery_strategy.value}")
    elif classified.severity == ErrorSeverity.CRITICAL:
        logger.critical(f"[{component}] {classified.message} | category={classified.category.value} | strategy={classified.recovery_strategy.value}")
    
    return classified
