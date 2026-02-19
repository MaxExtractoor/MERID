"""
MERID Core Error Handling Framework
Comprehensive error handling, circuit breakers, retry logic, and self-healing mechanisms
"""

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type
from functools import wraps
import json

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoveryStrategy(Enum):
    """Recovery strategies for different error types"""
    RETRY = "retry"
    FALLBACK = "fallback"
    CIRCUIT_BREAK = "circuit_break"
    ESCALATE = "escalate"
    IGNORE = "ignore"


@dataclass
class ErrorContext:
    """Context information for an error"""
    error_id: str
    timestamp: float
    component: str
    operation: str
    error_type: str
    error_message: str
    severity: ErrorSeverity
    stack_trace: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    recovery_attempted: bool = False
    recovery_successful: bool = False
    recovery_strategy: Optional[RecoveryStrategy] = None


@dataclass
class CircuitBreakerState:
    """Circuit breaker state tracking"""
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    state: str = "closed"  # closed, open, half_open
    open_until: Optional[float] = None


class CircuitBreaker:
    """Circuit breaker pattern implementation"""
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0,
        half_open_timeout: float = 30.0
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_timeout = half_open_timeout
        self.state = CircuitBreakerState()
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        async with self._lock:
            current_time = time.time()
            
            # Check if circuit is open
            if self.state.state == "open":
                if self.state.open_until and current_time < self.state.open_until:
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker {self.name} is OPEN. "
                        f"Retry after {self.state.open_until - current_time:.1f}s"
                    )
                else:
                    # Transition to half-open
                    self.state.state = "half_open"
                    logger.info(f"Circuit breaker {self.name} transitioning to HALF_OPEN")
        
        # Execute function
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            await self._on_success()
            return result
            
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self):
        """Handle successful execution"""
        async with self._lock:
            self.state.success_count += 1
            self.state.last_success_time = time.time()
            
            if self.state.state == "half_open":
                if self.state.success_count >= self.success_threshold:
                    self.state.state = "closed"
                    self.state.failure_count = 0
                    self.state.success_count = 0
                    logger.info(f"Circuit breaker {self.name} CLOSED after recovery")
    
    async def _on_failure(self):
        """Handle failed execution"""
        async with self._lock:
            self.state.failure_count += 1
            self.state.last_failure_time = time.time()
            
            if self.state.state == "half_open":
                # Failure in half-open state reopens circuit
                self.state.state = "open"
                self.state.open_until = time.time() + self.timeout
                self.state.success_count = 0
                logger.warning(f"Circuit breaker {self.name} reopened after failure in HALF_OPEN")
            
            elif self.state.failure_count >= self.failure_threshold:
                # Too many failures, open circuit
                self.state.state = "open"
                self.state.open_until = time.time() + self.timeout
                logger.error(
                    f"Circuit breaker {self.name} OPENED after {self.state.failure_count} failures. "
                    f"Will retry in {self.timeout}s"
                )
    
    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state"""
        return {
            "name": self.name,
            "state": self.state.state,
            "failure_count": self.state.failure_count,
            "success_count": self.state.success_count,
            "last_failure_time": self.state.last_failure_time,
            "last_success_time": self.state.last_success_time,
            "open_until": self.state.open_until
        }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open"""
    pass


class RetryStrategy:
    """Configurable retry strategy with exponential backoff"""
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number"""
        delay = min(
            self.initial_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        
        if self.jitter:
            import random
            delay *= (0.5 + random.random())
        
        return delay


async def retry_async(
    func: Callable,
    strategy: RetryStrategy,
    *args,
    **kwargs
) -> Any:
    """Retry async function with exponential backoff"""
    last_exception = None
    
    for attempt in range(strategy.max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if attempt < strategy.max_attempts - 1:
                delay = strategy.get_delay(attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{strategy.max_attempts} failed: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {strategy.max_attempts} attempts failed. Last error: {e}"
                )
    
    raise last_exception


def retry_sync(
    func: Callable,
    strategy: RetryStrategy,
    *args,
    **kwargs
) -> Any:
    """Retry sync function with exponential backoff"""
    last_exception = None
    
    for attempt in range(strategy.max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if attempt < strategy.max_attempts - 1:
                delay = strategy.get_delay(attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{strategy.max_attempts} failed: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"All {strategy.max_attempts} attempts failed. Last error: {e}"
                )
    
    raise last_exception


class ErrorHandler:
    """Centralized error handling and recovery"""
    
    def __init__(self):
        self.error_log: List[ErrorContext] = []
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.error_counts: Dict[str, int] = {}
        self.recovery_handlers: Dict[Type[Exception], Callable] = {}
        self._lock = asyncio.Lock()
    
    def register_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout: float = 60.0
    ) -> CircuitBreaker:
        """Register a new circuit breaker"""
        breaker = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            timeout=timeout
        )
        self.circuit_breakers[name] = breaker
        return breaker
    
    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name"""
        return self.circuit_breakers.get(name)
    
    def register_recovery_handler(
        self,
        exception_type: Type[Exception],
        handler: Callable
    ):
        """Register custom recovery handler for exception type"""
        self.recovery_handlers[exception_type] = handler
    
    async def handle_error(
        self,
        error: Exception,
        component: str,
        operation: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ErrorContext:
        """Handle error with logging and recovery"""
        error_context = ErrorContext(
            error_id=f"{component}_{operation}_{int(time.time() * 1000)}",
            timestamp=time.time(),
            component=component,
            operation=operation,
            error_type=type(error).__name__,
            error_message=str(error),
            severity=severity,
            stack_trace=traceback.format_exc(),
            metadata=metadata or {}
        )
        
        async with self._lock:
            self.error_log.append(error_context)
            error_key = f"{component}:{type(error).__name__}"
            self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        
        # Log based on severity
        log_message = (
            f"Error in {component}.{operation}: {error_context.error_type} - "
            f"{error_context.error_message}"
        )
        
        if severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message)
        elif severity == ErrorSeverity.HIGH:
            logger.error(log_message)
        elif severity == ErrorSeverity.MEDIUM:
            logger.warning(log_message)
        else:
            logger.info(log_message)
        
        # Attempt recovery
        await self._attempt_recovery(error, error_context)
        
        return error_context
    
    async def _attempt_recovery(
        self,
        error: Exception,
        context: ErrorContext
    ):
        """Attempt to recover from error"""
        context.recovery_attempted = True
        
        # Check for registered recovery handler
        for exc_type, handler in self.recovery_handlers.items():
            if isinstance(error, exc_type):
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(error, context)
                    else:
                        handler(error, context)
                    context.recovery_successful = True
                    context.recovery_strategy = RecoveryStrategy.FALLBACK
                    logger.info(f"Recovery successful for {context.error_id}")
                except Exception as recovery_error:
                    logger.error(f"Recovery failed: {recovery_error}")
    
    def get_error_stats(self) -> Dict[str, Any]:
        """Get error statistics"""
        return {
            "total_errors": len(self.error_log),
            "errors_by_type": dict(self.error_counts),
            "recent_errors": [
                {
                    "component": e.component,
                    "operation": e.operation,
                    "error_type": e.error_type,
                    "severity": e.severity.value,
                    "timestamp": e.timestamp
                }
                for e in self.error_log[-10:]
            ],
            "circuit_breakers": {
                name: breaker.get_state()
                for name, breaker in self.circuit_breakers.items()
            }
        }
    
    def clear_old_errors(self, max_age_seconds: float = 3600):
        """Clear errors older than specified age"""
        cutoff = time.time() - max_age_seconds
        self.error_log = [e for e in self.error_log if e.timestamp > cutoff]


# Global error handler instance
_error_handler: Optional[ErrorHandler] = None


def get_error_handler() -> ErrorHandler:
    """Get global error handler instance"""
    global _error_handler
    if _error_handler is None:
        _error_handler = ErrorHandler()
    return _error_handler


def with_error_handling(
    component: str,
    operation: str,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    retry_strategy: Optional[RetryStrategy] = None,
    circuit_breaker: Optional[str] = None
):
    """Decorator for automatic error handling"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            handler = get_error_handler()
            
            # Get circuit breaker if specified
            breaker = None
            if circuit_breaker:
                breaker = handler.get_circuit_breaker(circuit_breaker)
                if not breaker:
                    breaker = handler.register_circuit_breaker(circuit_breaker)
            
            async def execute():
                try:
                    if retry_strategy:
                        return await retry_async(func, retry_strategy, *args, **kwargs)
                    else:
                        return await func(*args, **kwargs)
                except Exception as e:
                    await handler.handle_error(
                        e, component, operation, severity
                    )
                    raise
            
            if breaker:
                return await breaker.call(execute)
            else:
                return await execute()
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            handler = get_error_handler()
            
            try:
                if retry_strategy:
                    return retry_sync(func, retry_strategy, *args, **kwargs)
                else:
                    return func(*args, **kwargs)
            except Exception as e:
                import asyncio
                loop = asyncio.get_event_loop()
                loop.run_until_complete(
                    handler.handle_error(e, component, operation, severity)
                )
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class HealthCheck:
    """Component health checking"""
    
    def __init__(self, name: str):
        self.name = name
        self.last_check: Optional[float] = None
        self.is_healthy: bool = True
        self.failure_count: int = 0
        self.consecutive_failures: int = 0
        self.health_history: List[Dict[str, Any]] = []
    
    async def check(self, check_func: Callable) -> bool:
        """Execute health check"""
        try:
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func()
            else:
                result = check_func()
            
            self.is_healthy = bool(result)
            self.last_check = time.time()
            
            if self.is_healthy:
                self.consecutive_failures = 0
            else:
                self.failure_count += 1
                self.consecutive_failures += 1
            
            self.health_history.append({
                "timestamp": self.last_check,
                "healthy": self.is_healthy,
                "consecutive_failures": self.consecutive_failures
            })
            
            # Keep only last 100 checks
            if len(self.health_history) > 100:
                self.health_history = self.health_history[-100:]
            
            return self.is_healthy
            
        except Exception as e:
            logger.error(f"Health check failed for {self.name}: {e}")
            self.is_healthy = False
            self.failure_count += 1
            self.consecutive_failures += 1
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get health status"""
        return {
            "name": self.name,
            "is_healthy": self.is_healthy,
            "last_check": self.last_check,
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "uptime_percentage": self._calculate_uptime()
        }
    
    def _calculate_uptime(self) -> float:
        """Calculate uptime percentage from history"""
        if not self.health_history:
            return 100.0
        
        healthy_count = sum(1 for h in self.health_history if h["healthy"])
        return (healthy_count / len(self.health_history)) * 100.0


class HealthMonitor:
    """System-wide health monitoring"""
    
    def __init__(self):
        self.health_checks: Dict[str, HealthCheck] = {}
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    def register_health_check(self, name: str) -> HealthCheck:
        """Register a new health check"""
        check = HealthCheck(name)
        self.health_checks[name] = check
        return check
    
    async def start_monitoring(self, interval: float = 30.0):
        """Start continuous health monitoring"""
        self._monitoring = True
        
        async def monitor_loop():
            while self._monitoring:
                await asyncio.sleep(interval)
                # Health checks are executed on-demand by components
        
        self._monitor_task = asyncio.create_task(monitor_loop())
    
    async def stop_monitoring(self):
        """Stop health monitoring"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health"""
        all_healthy = all(
            check.is_healthy for check in self.health_checks.values()
        )
        
        return {
            "overall_healthy": all_healthy,
            "components": {
                name: check.get_status()
                for name, check in self.health_checks.items()
            },
            "unhealthy_components": [
                name for name, check in self.health_checks.items()
                if not check.is_healthy
            ]
        }


# Global health monitor
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get global health monitor instance"""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


def get_agent_failure_counts() -> Dict[str, int]:
    """Return {agent_name: consecutive_failure_count} for all registered health checks.

    Used by the AgentConsecutiveFailureAlert observability rule.
    """
    monitor = get_health_monitor()
    return {
        name: check.consecutive_failures
        for name, check in monitor.health_checks.items()
        if check.consecutive_failures > 0
    }
