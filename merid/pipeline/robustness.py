"""
Pipeline Robustness Fixes

Critical fixes for identified robustness issues in pipeline and publishing components.
"""

import asyncio
import threading
import time
from typing import Any, Dict, List, Optional, Callable
from functools import wraps
from dataclasses import dataclass
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.pipeline.robustness")


# ── Robustness Decorators ─────────────────────────────────────────────────────

def retry_async(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """Async retry decorator with exponential backoff."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_attempts + 1}), "
                            f"retrying in {delay:.1f}s: {exc}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"{func.__name__} failed after {max_attempts + 1} attempts: {exc}")
            
            raise last_exception
        return wrapper
    return decorator


def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    expected_exception: type = Exception
):
    """Circuit breaker decorator for external service calls."""
    def decorator(func):
        # Store circuit state per function
        if not hasattr(func, '_circuit_state'):
            func._circuit_state = {
                'failure_count': 0,
                'last_failure_time': None,
                'state': 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
            }
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            state = func._circuit_state
            now = time.time()
            
            # Check if circuit should be half-open
            if (state['state'] == 'OPEN' and 
                now - state['last_failure_time'] > recovery_timeout):
                state['state'] = 'HALF_OPEN'
                logger.info(f"Circuit {func.__name__} entering HALF_OPEN state")
            
            # Reject calls if circuit is open
            if state['state'] == 'OPEN':
                raise Exception(f"Circuit breaker OPEN for {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                
                # Reset on success
                if state['state'] == 'HALF_OPEN':
                    state['state'] = 'CLOSED'
                    state['failure_count'] = 0
                    logger.info(f"Circuit {func.__name__} reset to CLOSED")
                
                return result
                
            except expected_exception as exc:
                state['failure_count'] += 1
                state['last_failure_time'] = now
                
                # Open circuit if threshold exceeded
                if state['failure_count'] >= failure_threshold:
                    state['state'] = 'OPEN'
                    logger.error(f"Circuit {func.__name__} OPENED after {state['failure_count']} failures")
                
                raise exc
        
        return wrapper
    return decorator


def validate_inputs(**validators):
    """Input validation decorator (preserves sync/async nature of wrapped function)."""
    import inspect

    def decorator(func):
        try:
            _param_names = list(inspect.signature(func).parameters.keys())
        except (ValueError, TypeError):
            _param_names = []

        def _run_validations(*args, **kwargs):
            # Resolve positional args to their parameter names
            bound: dict = {}
            for i, val in enumerate(args):
                if i < len(_param_names):
                    bound[_param_names[i]] = val
            bound.update(kwargs)

            for param, validator in validators.items():
                if param in bound:
                    value = bound[param]
                    if not validator(value):
                        raise ValueError(f"Invalid value for {param}: {value}")

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                _run_validations(*args, **kwargs)
                return await func(*args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                _run_validations(*args, **kwargs)
                return func(*args, **kwargs)
            return sync_wrapper
    return decorator


def rate_limit(calls_per_second: float):
    """Rate limiting decorator."""
    def decorator(func):
        if not hasattr(func, '_rate_limit_state'):
            func._rate_limit_state = {
                'last_call': 0.0,
                'min_interval': 1.0 / calls_per_second
            }
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            state = func._rate_limit_state
            now = time.time()
            
            # Enforce rate limit
            time_since_last = now - state['last_call']
            if time_since_last < state['min_interval']:
                await asyncio.sleep(state['min_interval'] - time_since_last)
            
            state['last_call'] = time.time()
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# ── Thread Safe State Management ─────────────────────────────────────────────

class ThreadSafeState:
    """Thread-safe state manager for shared data."""
    
    def __init__(self):
        self._lock = threading.RLock()
        self._state: Dict[str, Any] = {}
    
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._state[key] = value
    
    def update(self, updates: Dict[str, Any]) -> None:
        with self._lock:
            self._state.update(updates)
    
    def delete(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)
    
    def clear(self) -> None:
        with self._lock:
            self._state.clear()


# ── Resource Management ─────────────────────────────────────────────────────

class ResourceManager:
    """Context manager for async resources."""
    
    def __init__(self):
        self._resources: List[Any] = []
        self._cleanup_tasks: List[Callable] = []
    
    def register(self, resource: Any, cleanup_func: Optional[Callable] = None) -> None:
        """Register a resource for cleanup."""
        self._resources.append(resource)
        if cleanup_func:
            self._cleanup_tasks.append(cleanup_func)
    
    async def cleanup_all(self) -> None:
        """Clean up all registered resources."""
        for cleanup_func in self._cleanup_tasks:
            try:
                if asyncio.iscoroutinefunction(cleanup_func):
                    await cleanup_func()
                else:
                    cleanup_func()
            except Exception as exc:
                logger.error(f"Resource cleanup error: {exc}")
        
        self._resources.clear()
        self._cleanup_tasks.clear()


# ── Health Check System ─────────────────────────────────────────────────────

@dataclass
class HealthStatus:
    component: str
    healthy: bool
    message: str
    timestamp: datetime
    details: Dict[str, Any] = None


class HealthChecker:
    """Health check system for pipeline components."""
    
    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._last_results: Dict[str, HealthStatus] = {}
    
    def register_check(self, name: str, check_func: Callable) -> None:
        """Register a health check function."""
        self._checks[name] = check_func
    
    async def run_check(self, name: str) -> HealthStatus:
        """Run a specific health check."""
        if name not in self._checks:
            return HealthStatus(
                component=name,
                healthy=False,
                message="Health check not registered",
                timestamp=datetime.now(timezone.utc)
            )
        
        try:
            result = self._checks[name]()
            if asyncio.iscoroutine(result):
                result = await result
            
            return HealthStatus(
                component=name,
                healthy=True,
                message="OK",
                timestamp=datetime.now(timezone.utc),
                details=result if isinstance(result, dict) else {}
            )
        except Exception as exc:
            return HealthStatus(
                component=name,
                healthy=False,
                message=str(exc),
                timestamp=datetime.now(timezone.utc)
            )
    
    async def run_all_checks(self) -> Dict[str, HealthStatus]:
        """Run all registered health checks."""
        results = {}
        for name in self._checks:
            results[name] = await self.run_check(name)
            self._last_results[name] = results[name]
        
        return results
    
    def get_summary(self) -> Dict[str, Any]:
        """Get health check summary."""
        if not self._last_results:
            return {"status": "unknown", "checks": 0}
        
        total = len(self._last_results)
        healthy = sum(1 for status in self._last_results.values() if status.healthy)
        
        return {
            "status": "healthy" if healthy == total else "degraded" if healthy > 0 else "unhealthy",
            "checks": total,
            "healthy_checks": healthy,
            "unhealthy_checks": total - healthy,
            "last_check": max(status.timestamp for status in self._last_results.values()).isoformat()
        }


# ── Input Validators ───────────────────────────────────────────────────────

def validate_non_empty_string(value: Any) -> bool:
    """Validate non-empty string."""
    return isinstance(value, str) and len(value.strip()) > 0


def validate_positive_number(value: Any) -> bool:
    """Validate positive number."""
    try:
        num = float(value)
        return num > 0
    except (ValueError, TypeError):
        return False


def validate_probability(value: Any) -> bool:
    """Validate probability (0-1)."""
    try:
        prob = float(value)
        return 0.0 <= prob <= 1.0
    except (ValueError, TypeError):
        return False


def validate_timestamp(value: Any) -> bool:
    """Validate timestamp string."""
    if not isinstance(value, str):
        return False
    
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False


# ── Error Recovery Patterns ─────────────────────────────────────────────────

class ErrorRecovery:
    """Error recovery patterns for pipeline operations."""
    
    @staticmethod
    async def safe_execute(
        func: Callable,
        *args,
        fallback_value: Any = None,
        log_error: bool = True,
        **kwargs
    ) -> Any:
        """Safely execute a function with fallback."""
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as exc:
            if log_error:
                logger.error(f"Safe execute failed for {func.__name__}: {exc}")
            return fallback_value
    
    @staticmethod
    async def with_timeout(
        func: Callable,
        timeout: float,
        *args,
        fallback_value: Any = None,
        **kwargs
    ) -> Any:
        """Execute function with timeout."""
        try:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await asyncio.wait_for(result, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Function {func.__name__} timed out after {timeout}s")
            return fallback_value
        except Exception as exc:
            logger.error(f"Function {func.__name__} failed: {exc}")
            return fallback_value


# ── Monitoring and Metrics ─────────────────────────────────────────────────

class PipelineMetrics:
    """Metrics collection for pipeline operations."""
    
    def __init__(self):
        self._metrics = ThreadSafeState()
        self._start_time = time.time()
    
    def increment_counter(self, name: str, value: int = 1) -> None:
        """Increment a counter metric."""
        current = self._metrics.get(name, 0)
        self._metrics.set(name, current + value)
    
    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge metric."""
        self._metrics.set(name, value)
    
    def record_timing(self, name: str, duration: float) -> None:
        """Record a timing metric."""
        # Keep last 100 timings
        timings = self._metrics.get(f"{name}_timings", [])
        timings.append(duration)
        if len(timings) > 100:
            timings = timings[-100:]
        self._metrics.set(f"{name}_timings", timings)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary."""
        uptime = time.time() - self._start_time
        return {
            "uptime_seconds": uptime,
            "metrics": self._metrics._state.copy()
        }


# ── Graceful Shutdown ─────────────────────────────────────────────────────

class GracefulShutdown:
    """Graceful shutdown handler for pipeline components."""
    
    def __init__(self):
        self._shutdown_handlers: List[Callable] = []
        self._shutdown_event = asyncio.Event()
    
    def register_handler(self, handler: Callable) -> None:
        """Register a shutdown handler."""
        self._shutdown_handlers.append(handler)
    
    async def shutdown(self, reason: str = "Manual shutdown") -> None:
        """Execute graceful shutdown."""
        logger.info(f"Starting graceful shutdown: {reason}")
        self._shutdown_event.set()
        
        # Run all shutdown handlers
        for handler in self._shutdown_handlers:
            try:
                result = handler()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(f"Shutdown handler failed: {exc}")
        
        logger.info("Graceful shutdown completed")
    
    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress."""
        return self._shutdown_event.is_set()


# Global instances
_global_health_checker = HealthChecker()
_global_metrics = PipelineMetrics()
_global_shutdown = GracefulShutdown()

def get_health_checker() -> HealthChecker:
    """Get global health checker."""
    return _global_health_checker

def get_metrics() -> PipelineMetrics:
    """Get global metrics collector."""
    return _global_metrics

def get_shutdown_handler() -> GracefulShutdown:
    """Get global shutdown handler."""
    return _global_shutdown
