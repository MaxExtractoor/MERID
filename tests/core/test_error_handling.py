"""
Tests for core/error_handling.py - Error handling and circuit breaker system.

Tests circuit breakers, retry logic, error recovery, health checks, and decorators.
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from core.error_handling import (
    ErrorSeverity, RecoveryStrategy, ErrorContext, CircuitBreakerState,
    CircuitBreaker, CircuitBreakerOpenError, RetryStrategy,
    retry_async, retry_sync, ErrorHandler, get_error_handler,
    with_error_handling, HealthCheck, HealthMonitor, get_health_monitor
)


class TestErrorSeverity:
    """Test ErrorSeverity enum."""

    def test_error_severity_values(self):
        """Test error severity enum values."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"


class TestRecoveryStrategy:
    """Test RecoveryStrategy enum."""

    def test_recovery_strategy_values(self):
        """Test recovery strategy enum values."""
        assert RecoveryStrategy.RETRY.value == "retry"
        assert RecoveryStrategy.FALLBACK.value == "fallback"
        assert RecoveryStrategy.CIRCUIT_BREAK.value == "circuit_break"
        assert RecoveryStrategy.ESCALATE.value == "escalate"
        assert RecoveryStrategy.IGNORE.value == "ignore"


class TestErrorContext:
    """Test ErrorContext dataclass."""

    def test_error_context_creation(self):
        """Test error context creation."""
        context = ErrorContext(
            error_id="test_123",
            timestamp=1234567890.0,
            component="test_component",
            operation="test_operation",
            error_type="ValueError",
            error_message="Test error",
            severity=ErrorSeverity.HIGH,
            stack_trace="traceback here",
            metadata={"key": "value"}
        )

        assert context.error_id == "test_123"
        assert context.component == "test_component"
        assert context.severity == ErrorSeverity.HIGH
        assert context.recovery_attempted is False
        assert context.recovery_successful is False

    def test_error_context_defaults(self):
        """Test error context defaults."""
        context = ErrorContext(
            error_id="test",
            timestamp=1234567890.0,
            component="comp",
            operation="op",
            error_type="Error",
            error_message="msg",
            severity=ErrorSeverity.LOW,
            stack_trace="trace"
        )

        assert context.metadata == {}
        assert context.recovery_strategy is None


class TestCircuitBreakerState:
    """Test CircuitBreakerState dataclass."""

    def test_circuit_breaker_state_defaults(self):
        """Test circuit breaker state defaults."""
        state = CircuitBreakerState()
        assert state.failure_count == 0
        assert state.success_count == 0
        assert state.last_failure_time is None
        assert state.state == "closed"
        assert state.open_until is None


class TestCircuitBreaker:
    """Test CircuitBreaker functionality."""

    @pytest.fixture
    def breaker(self):
        """Create circuit breaker for testing."""
        return CircuitBreaker(name="test_breaker", failure_threshold=2, timeout=1.0)

    @pytest.mark.asyncio
    async def test_successful_call(self, breaker):
        """Test successful function call."""
        async def success_func():
            return "success"

        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state.state == "closed"
        assert breaker.state.success_count == 1

    @pytest.mark.asyncio
    async def test_failed_call_opens_circuit(self, breaker):
        """Test failed calls open the circuit."""
        async def fail_func():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            await breaker.call(fail_func)

        with pytest.raises(ValueError):
            await breaker.call(fail_func)

        # Circuit should now be open
        assert breaker.state.state == "open"
        assert breaker.state.failure_count == 2

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_calls(self, breaker):
        """Test that open circuit blocks further calls."""
        breaker.state.state = "open"
        breaker.state.open_until = time.time() + 10

        async def func():
            return "should not execute"

        with pytest.raises(CircuitBreakerOpenError):
            await breaker.call(func)

    @pytest.mark.asyncio
    async def test_half_open_transition(self, breaker):
        """Test transition to half-open state."""
        breaker.state.state = "open"
        breaker.state.open_until = time.time() - 1  # Expired

        async def success_func():
            return "success"

        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker.state.state == "half_open"

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self, breaker):
        """Test that failure in half-open reopens circuit."""
        breaker.state.state = "half_open"

        async def fail_func():
            raise ValueError("half-open failure")

        with pytest.raises(ValueError):
            await breaker.call(fail_func)

        assert breaker.state.state == "open"

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self, breaker):
        """Test that success in half-open closes circuit."""
        breaker.state.state = "half_open"
        breaker.success_threshold = 2

        async def success_func():
            return "success"

        await breaker.call(success_func)
        assert breaker.state.state == "half_open"  # Need 2 successes

        await breaker.call(success_func)
        assert breaker.state.state == "closed"

    def test_get_state(self, breaker):
        """Test getting circuit breaker state."""
        state = breaker.get_state()
        assert state["name"] == "test_breaker"
        assert state["state"] == "closed"
        assert state["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_sync_function_call(self, breaker):
        """Test calling synchronous function."""
        def sync_func():
            return "sync result"

        result = await breaker.call(sync_func)
        assert result == "sync result"


class TestCircuitBreakerOpenError:
    """Test CircuitBreakerOpenError exception."""

    def test_exception_creation(self):
        """Test circuit breaker open error."""
        error = CircuitBreakerOpenError("Circuit is open")
        assert str(error) == "Circuit is open"


class TestRetryStrategy:
    """Test RetryStrategy functionality."""

    def test_retry_strategy_defaults(self):
        """Test retry strategy defaults."""
        strategy = RetryStrategy()
        assert strategy.max_attempts == 3
        assert strategy.initial_delay == 1.0
        assert strategy.max_delay == 60.0
        assert strategy.exponential_base == 2.0
        assert strategy.jitter is True

    def test_get_delay_no_jitter(self):
        """Test delay calculation without jitter."""
        strategy = RetryStrategy(jitter=False)
        assert strategy.get_delay(0) == 1.0  # 1 * 2^0 = 1
        assert strategy.get_delay(1) == 2.0  # 1 * 2^1 = 2
        assert strategy.get_delay(2) == 4.0  # 1 * 2^2 = 4

    def test_get_delay_with_max(self):
        """Test delay respects max_delay."""
        strategy = RetryStrategy(initial_delay=10.0, max_delay=15.0, jitter=False)
        assert strategy.get_delay(10) == 15.0  # Capped at max_delay

    @patch('random.random')
    def test_get_delay_with_jitter(self, mock_random):
        """Test delay with jitter."""
        mock_random.return_value = 0.5  # Will multiply by 1.0 (0.5 + 0.5)
        strategy = RetryStrategy(initial_delay=2.0, jitter=True, exponential_base=1.0)
        delay = strategy.get_delay(0)
        assert 1.0 <= delay <= 2.0


class TestRetryAsync:
    """Test retry_async function."""

    @pytest.mark.asyncio
    async def test_successful_retry(self):
        """Test successful function call."""
        async def success_func():
            return "success"

        strategy = RetryStrategy(max_attempts=3)
        result = await retry_async(success_func, strategy)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test retry on failure."""
        call_count = 0

        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Attempt {call_count}")
            return "success"

        strategy = RetryStrategy(max_attempts=3)
        result = await retry_async(failing_func, strategy)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """Test retry exhaustion."""
        async def always_fail():
            raise ValueError("Always fails")

        strategy = RetryStrategy(max_attempts=2)
        with pytest.raises(ValueError, match="Always fails"):
            await retry_async(always_fail, strategy)


class TestRetrySync:
    """Test retry_sync function."""

    def test_successful_sync_retry(self):
        """Test successful sync function call."""
        def success_func():
            return "sync success"

        strategy = RetryStrategy(max_attempts=2)
        result = retry_sync(success_func, strategy)
        assert result == "sync success"

    @patch('time.sleep')
    def test_sync_retry_on_failure(self, mock_sleep):
        """Test sync retry on failure."""
        call_count = 0

        def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError(f"Sync attempt {call_count}")
            return "sync success"

        strategy = RetryStrategy(max_attempts=2)
        result = retry_sync(failing_func, strategy)
        assert result == "sync success"
        assert call_count == 2
        assert mock_sleep.call_count == 1


class TestErrorHandler:
    """Test ErrorHandler functionality."""

    @pytest.fixture
    def handler(self):
        """Create error handler for testing."""
        return ErrorHandler()

    @pytest.mark.asyncio
    async def test_handle_error(self, handler):
        """Test error handling."""
        error = ValueError("Test error")

        context = await handler.handle_error(
            error=error,
            component="test_component",
            operation="test_operation",
            severity=ErrorSeverity.HIGH,
            metadata={"key": "value"}
        )

        assert context.component == "test_component"
        assert context.operation == "test_operation"
        assert context.error_type == "ValueError"
        assert context.severity == ErrorSeverity.HIGH
        assert context.metadata["key"] == "value"
        assert context.error_id.startswith("test_component_test_operation_")

    @pytest.mark.asyncio
    async def test_register_circuit_breaker(self, handler):
        """Test circuit breaker registration."""
        breaker = handler.register_circuit_breaker("test_breaker", failure_threshold=3)
        assert breaker.name == "test_breaker"
        assert breaker.failure_threshold == 3
        assert handler.circuit_breakers["test_breaker"] is breaker

    def test_get_circuit_breaker(self, handler):
        """Test getting circuit breaker."""
        breaker = handler.register_circuit_breaker("test")
        assert handler.get_circuit_breaker("test") is breaker
        assert handler.get_circuit_breaker("nonexistent") is None

    @pytest.mark.asyncio
    async def test_register_recovery_handler(self, handler):
        """Test recovery handler registration."""
        recovery_called = False

        async def recovery_func(error, context):
            nonlocal recovery_called
            recovery_called = True

        handler.register_recovery_handler(ValueError, recovery_func)

        error = ValueError("Test")
        context = await handler.handle_error(error, "comp", "op")

        assert recovery_called is True
        assert context.recovery_successful is True
        assert context.recovery_strategy == RecoveryStrategy.FALLBACK

    def test_get_error_stats(self, handler):
        """Test getting error statistics."""
        stats = handler.get_error_stats()
        assert stats["total_errors"] == 0
        assert stats["circuit_breakers"] == {}

    def test_clear_old_errors(self, handler):
        """Test clearing old errors."""
        # Add some mock errors
        old_error = ErrorContext(
            error_id="old", timestamp=time.time() - 7200,  # 2 hours ago
            component="comp", operation="op", error_type="Error",
            error_message="msg", severity=ErrorSeverity.LOW, stack_trace=""
        )
        new_error = ErrorContext(
            error_id="new", timestamp=time.time() - 1800,  # 30 min ago
            component="comp", operation="op", error_type="Error",
            error_message="msg", severity=ErrorSeverity.LOW, stack_trace=""
        )

        handler.error_log = [old_error, new_error]
        handler.clear_old_errors(max_age_seconds=3600)  # 1 hour

        assert len(handler.error_log) == 1
        assert handler.error_log[0].error_id == "new"


class TestErrorHandlerSingleton:
    """Test error handler singleton."""

    def test_get_error_handler_singleton(self):
        """Test singleton behavior."""
        handler1 = get_error_handler()
        handler2 = get_error_handler()
        assert handler1 is handler2
        assert isinstance(handler1, ErrorHandler)


class TestWithErrorHandling:
    """Test with_error_handling decorator."""

    @pytest.fixture
    def handler(self):
        """Create fresh error handler for testing."""
        global _error_handler
        _error_handler = None  # Reset singleton
        return get_error_handler()

    @pytest.mark.asyncio
    async def test_async_decorator_success(self, handler):
        """Test decorator with successful async function."""
        @with_error_handling("test_comp", "test_op")
        async def success_func():
            return "success"

        result = await success_func()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_async_decorator_error_handling(self, handler):
        """Test decorator error handling for async functions."""
        @with_error_handling("test_comp", "test_op", severity=ErrorSeverity.CRITICAL)
        async def failing_func():
            raise ValueError("Test failure")

        with pytest.raises(ValueError):
            await failing_func()

        # Check error was logged
        assert len(handler.error_log) == 1
        assert handler.error_log[0].severity == ErrorSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_async_decorator_with_retry(self, handler):
        """Test decorator with retry strategy."""
        call_count = 0

        @with_error_handling(
            "test_comp", "test_op",
            retry_strategy=RetryStrategy(max_attempts=2)
        )
        async def retry_func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First attempt fails")
            return "success"

        result = await retry_func()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_decorator_with_circuit_breaker(self, handler):
        """Test decorator with circuit breaker."""
        call_count = 0

        @with_error_handling(
            "test_comp", "test_op",
            circuit_breaker="test_breaker"
        )
        async def breaker_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Circuit breaker test")

        # First call
        with pytest.raises(ValueError):
            await breaker_func()

        assert call_count == 1
        assert "test_breaker" in handler.circuit_breakers

    def test_sync_decorator_error_handling(self, handler):
        """Test decorator error handling for sync functions."""
        @with_error_handling("test_comp", "sync_op")
        def failing_sync_func():
            raise RuntimeError("Sync test failure")

        with pytest.raises(RuntimeError):
            failing_sync_func()

        # Check error was logged
        assert len(handler.error_log) == 1
        assert handler.error_log[0].component == "test_comp"


class TestHealthCheck:
    """Test HealthCheck functionality."""

    @pytest.fixture
    def health_check(self):
        """Create health check for testing."""
        return HealthCheck("test_component")

    @pytest.mark.asyncio
    async def test_successful_health_check(self, health_check):
        """Test successful health check."""
        def check_func():
            return True

        result = await health_check.check(check_func)
        assert result is True
        assert health_check.is_healthy is True
        assert health_check.consecutive_failures == 0
        assert len(health_check.health_history) == 1

    @pytest.mark.asyncio
    async def test_failed_health_check(self, health_check):
        """Test failed health check."""
        def check_func():
            return False

        result = await health_check.check(check_func)
        assert result is False
        assert health_check.is_healthy is False
        assert health_check.failure_count == 1
        assert health_check.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_health_check_exception(self, health_check):
        """Test health check with exception."""
        def failing_check():
            raise ValueError("Check failed")

        result = await health_check.check(failing_check)
        assert result is False
        assert health_check.is_healthy is False
        assert health_check.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_async_health_check(self, health_check):
        """Test async health check function."""
        async def async_check():
            await asyncio.sleep(0.01)
            return True

        result = await health_check.check(async_check)
        assert result is True
        assert health_check.is_healthy is True

    def test_get_status(self, health_check):
        """Test getting health status."""
        status = health_check.get_status()
        assert status["name"] == "test_component"
        assert status["is_healthy"] is True
        assert status["failure_count"] == 0

    def test_calculate_uptime_empty_history(self, health_check):
        """Test uptime calculation with empty history."""
        uptime = health_check._calculate_uptime()
        assert uptime == 100.0

    def test_calculate_uptime_with_history(self, health_check):
        """Test uptime calculation with history."""
        health_check.health_history = [
            {"healthy": True}, {"healthy": False}, {"healthy": True}
        ]
        uptime = health_check._calculate_uptime()
        assert uptime == 66.66666666666666  # 2/3


class TestHealthMonitor:
    """Test HealthMonitor functionality."""

    @pytest.fixture
    def health_monitor(self):
        """Create health monitor for testing."""
        return HealthMonitor()

    def test_register_health_check(self, health_monitor):
        """Test registering health check."""
        check = health_monitor.register_health_check("test_check")
        assert check.name == "test_check"
        assert health_monitor.health_checks["test_check"] is check

    def test_get_system_health_all_healthy(self, health_monitor):
        """Test system health when all components healthy."""
        health_monitor.register_health_check("comp1")
        health_monitor.register_health_check("comp2")

        health = health_monitor.get_system_health()
        assert health["overall_healthy"] is True
        assert len(health["components"]) == 2
        assert health["unhealthy_components"] == []

    def test_get_system_health_with_failures(self, health_monitor):
        """Test system health with failed components."""
        check1 = health_monitor.register_health_check("comp1")
        check2 = health_monitor.register_health_check("comp2")

        # Manually fail one check
        check2.is_healthy = False

        health = health_monitor.get_system_health()
        assert health["overall_healthy"] is False
        assert health["unhealthy_components"] == ["comp2"]

    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, health_monitor):
        """Test starting and stopping monitoring."""
        await health_monitor.start_monitoring(interval=0.1)
        assert health_monitor._monitoring is True
        assert health_monitor._monitor_task is not None

        await health_monitor.stop_monitoring()
        assert health_monitor._monitoring is False


class TestHealthMonitorSingleton:
    """Test health monitor singleton."""

    def test_get_health_monitor_singleton(self):
        """Test singleton behavior."""
        monitor1 = get_health_monitor()
        monitor2 = get_health_monitor()
        assert monitor1 is monitor2
        assert isinstance(monitor1, HealthMonitor)
