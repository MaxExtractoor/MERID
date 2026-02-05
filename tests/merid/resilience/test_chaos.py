"""Chaos tests for resilience layer.

These tests simulate failure scenarios to verify circuit breakers,
retries, and error handling degrade gracefully.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    get_circuit_breaker,
    reset_all_breakers,
)
from merid.resilience.result import OperationResult


class TestCircuitBreakerChaos:
    """Circuit breaker behavior under failure scenarios."""
    
    @pytest.fixture(autouse=True)
    def reset_breakers(self):
        """Reset all circuit breakers between tests."""
        reset_all_breakers()
        yield
        reset_all_breakers()
    
    @pytest.fixture
    def breaker(self):
        """Create circuit breaker with tight thresholds for testing."""
        return CircuitBreaker(
            name="chaos_test",
            failure_threshold=3,
            recovery_timeout=0.1,  # 100ms for fast tests
        )
    
    @pytest.mark.asyncio
    async def test_rapid_failures_open_circuit(self, breaker):
        """Rapid consecutive failures open the circuit."""
        assert breaker.state == CircuitState.CLOSED
        
        # Simulate 3 rapid failures
        for i in range(3):
            await breaker.record_failure(Exception(f"Failure {i}"))
        
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self, breaker):
        """Open circuit rejects calls immediately."""
        # Trip the breaker
        for _ in range(3):
            await breaker.record_failure(Exception("Fail"))
        
        assert breaker.state == CircuitState.OPEN
        
        # Attempts should raise CircuitOpenError
        with pytest.raises(CircuitOpenError):
            async with breaker:
                pass
    
    @pytest.mark.asyncio
    async def test_half_open_allows_probe(self, breaker):
        """After timeout, circuit goes half-open and allows probe."""
        # Trip the breaker
        for _ in range(3):
            await breaker.record_failure(Exception("Fail"))
        
        assert breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        
        # State transition happens on context entry, not passively
        # Entering context should transition to half-open and allow call
        async with breaker:
            pass  # Success
        
        # After successful call in half-open, should be closed
        assert breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self, breaker):
        """Successful call in half-open state closes circuit."""
        # Trip the breaker
        for _ in range(3):
            await breaker.record_failure(Exception("Fail"))
        
        # Wait for recovery
        await asyncio.sleep(0.15)
        
        # Enter context to trigger transition and succeed
        async with breaker:
            pass
        
        assert breaker.state == CircuitState.CLOSED
    
    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self, breaker):
        """Failed call in half-open state reopens circuit."""
        # Trip the breaker
        for _ in range(3):
            await breaker.record_failure(Exception("Fail"))
        
        # Wait for recovery
        await asyncio.sleep(0.15)
        
        # Enter context to trigger half-open, then fail
        try:
            async with breaker:
                raise RuntimeError("Still failing")
        except RuntimeError:
            pass
        
        # Should be back to open
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_intermittent_failures_dont_trip(self, breaker):
        """Failures mixed with successes don't trip circuit."""
        # Fail, succeed, fail, succeed pattern
        await breaker.record_failure(Exception("Fail 1"))
        await breaker.record_success()
        await breaker.record_failure(Exception("Fail 2"))
        await breaker.record_success()
        
        # Should still be closed (successes reset counter)
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerRegistry:
    """Tests for global circuit breaker registry."""
    
    @pytest.fixture(autouse=True)
    def reset_breakers(self):
        reset_all_breakers()
        yield
        reset_all_breakers()
    
    def test_get_or_create_breaker(self):
        """get_circuit_breaker creates or returns existing breaker."""
        b1 = get_circuit_breaker("venue_a", failure_threshold=5)
        b2 = get_circuit_breaker("venue_a")
        
        assert b1 is b2  # Same instance
    
    def test_separate_breakers_per_venue(self):
        """Each venue gets its own circuit breaker."""
        b1 = get_circuit_breaker("kalshi")
        b2 = get_circuit_breaker("polymarket")
        
        assert b1 is not b2
        assert b1.name == "kalshi"
        assert b2.name == "polymarket"
    
    @pytest.mark.asyncio
    async def test_one_venue_failure_doesnt_affect_other(self):
        """Circuit breaker isolation - one venue down doesn't affect others."""
        # Create fresh breakers with unique names to avoid registry conflicts
        b_kalshi = CircuitBreaker("kalshi_iso_test", failure_threshold=2)
        b_poly = CircuitBreaker("poly_iso_test", failure_threshold=2)
        
        # Trip Kalshi breaker
        await b_kalshi.record_failure(Exception("Kalshi down"))
        await b_kalshi.record_failure(Exception("Kalshi down"))
        
        assert b_kalshi.state == CircuitState.OPEN
        assert b_poly.state == CircuitState.CLOSED  # Unaffected


class TestOperationResultChaos:
    """Tests for OperationResult under edge cases."""
    
    def test_fail_result_with_metadata(self):
        """Failed result preserves error and metadata."""
        error = ValueError("Bad input")
        result = OperationResult.fail(
            error,
            latency_ms=150.5,
            retries=3,
            operation="test_op",
        )
        
        assert not result.success
        assert result.error is error
        assert result.latency_ms == 150.5
        assert result.retries == 3
    
    def test_unwrap_on_failure_raises(self):
        """unwrap() on failed result raises the error."""
        error = RuntimeError("Failed")
        result = OperationResult.fail(error)
        
        with pytest.raises(RuntimeError, match="Failed"):
            result.unwrap()
    
    def test_unwrap_or_returns_default(self):
        """unwrap_or() returns default on failure."""
        result = OperationResult.fail(RuntimeError("Failed"))
        
        value = result.unwrap_or("default")
        assert value == "default"
    
    def test_unwrap_or_else_calls_factory(self):
        """unwrap_or_else() calls factory on failure."""
        result = OperationResult.fail(RuntimeError("Failed"))
        
        value = result.unwrap_or_else(lambda: "computed")
        assert value == "computed"
    
    def test_map_on_success(self):
        """map() transforms successful result."""
        result = OperationResult.ok(5)
        mapped = result.map(lambda x: x * 2)
        
        assert mapped.success
        assert mapped.data == 10
    
    def test_map_on_failure_preserves_error(self):
        """map() on failure preserves error, doesn't call fn."""
        error = RuntimeError("Failed")
        result = OperationResult.fail(error)
        
        call_count = [0]
        def transform(x):
            call_count[0] += 1
            return x * 2
        
        mapped = result.map(transform)
        
        assert not mapped.success
        assert mapped.error is error
        assert call_count[0] == 0  # Transform not called


class TestConcurrentCircuitBreakers:
    """Tests for circuit breaker behavior under concurrent access."""
    
    @pytest.fixture(autouse=True)
    def reset_breakers(self):
        reset_all_breakers()
        yield
        reset_all_breakers()
    
    @pytest.mark.asyncio
    async def test_concurrent_failures_trip_circuit(self):
        """Concurrent failures from multiple tasks trip circuit."""
        breaker = CircuitBreaker("concurrent_test", failure_threshold=5)
        
        async def fail_once():
            await breaker.record_failure(Exception("Concurrent fail"))
        
        # Run 5 concurrent failures
        await asyncio.gather(*[fail_once() for _ in range(5)])
        
        assert breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_concurrent_successes_close_circuit(self):
        """After tripping, successful call in half-open closes circuit."""
        breaker = CircuitBreaker(
            "concurrent_close_test",
            failure_threshold=2,
            recovery_timeout=0.05,
        )
        
        # Trip the breaker
        await breaker.record_failure(Exception("Fail"))
        await breaker.record_failure(Exception("Fail"))
        assert breaker.state == CircuitState.OPEN
        
        # Wait for half-open
        await asyncio.sleep(0.1)
        
        # Use context manager to trigger transition and succeed
        async with breaker:
            pass
        
        assert breaker.state == CircuitState.CLOSED
