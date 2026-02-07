"""Tests for CircuitBreaker resilience primitive."""

import asyncio
import pytest
import time

from merid.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    reset_all_breakers,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def setup_method(self):
        """Reset breakers before each test."""
        reset_all_breakers()

    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        """Circuit starts in CLOSED state."""
        breaker = CircuitBreaker("test", failure_threshold=3)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    @pytest.mark.asyncio
    async def test_success_keeps_closed(self):
        """Successful calls keep circuit closed."""
        breaker = CircuitBreaker("test", failure_threshold=3)
        
        async with breaker:
            pass  # Success
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_failures_below_threshold(self):
        """Failures below threshold keep circuit closed."""
        breaker = CircuitBreaker("test", failure_threshold=3)
        
        for _ in range(2):
            try:
                async with breaker:
                    raise ConnectionError("test error")
            except ConnectionError:
                pass
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 2

    @pytest.mark.asyncio
    async def test_threshold_opens_circuit(self):
        """Reaching failure threshold opens circuit."""
        breaker = CircuitBreaker("test", failure_threshold=3)
        
        for i in range(3):
            try:
                async with breaker:
                    raise ConnectionError(f"error {i}")
            except ConnectionError:
                pass
        
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_calls(self):
        """Open circuit blocks new calls."""
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60.0)
        
        # Trip the breaker
        try:
            async with breaker:
                raise ConnectionError("trip")
        except ConnectionError:
            pass
        
        assert breaker.is_open
        
        # Next call should be blocked
        with pytest.raises(CircuitOpenError) as exc_info:
            async with breaker:
                pass
        
        assert "test" in str(exc_info.value)
        assert exc_info.value.time_until_retry > 0

    @pytest.mark.asyncio
    async def test_recovery_timeout_to_half_open(self):
        """Circuit transitions to HALF_OPEN after recovery timeout."""
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        
        # Trip the breaker
        try:
            async with breaker:
                raise ConnectionError("trip")
        except ConnectionError:
            pass
        
        assert breaker.is_open
        
        # Wait for recovery
        await asyncio.sleep(0.15)
        
        # Next call should be allowed (half-open)
        async with breaker:
            pass
        
        # Should be closed now
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        """Failure in HALF_OPEN state reopens circuit."""
        breaker = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        
        # Trip the breaker
        try:
            async with breaker:
                raise ConnectionError("trip")
        except ConnectionError:
            pass
        
        # Wait for recovery
        await asyncio.sleep(0.15)
        
        # Fail in half-open
        try:
            async with breaker:
                raise ConnectionError("fail again")
        except ConnectionError:
            pass
        
        # Should be open again
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        """Success resets failure count."""
        breaker = CircuitBreaker("test", failure_threshold=3)
        
        # Two failures
        for _ in range(2):
            try:
                async with breaker:
                    raise ConnectionError()
            except ConnectionError:
                pass
        
        assert breaker.failure_count == 2
        
        # One success
        async with breaker:
            pass
        
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_reset_method(self):
        """Manual reset returns to CLOSED state."""
        breaker = CircuitBreaker("test", failure_threshold=1)
        
        # Trip the breaker
        try:
            async with breaker:
                raise ConnectionError()
        except ConnectionError:
            pass
        
        assert breaker.is_open
        
        # Reset
        breaker.reset()
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Stats contain expected fields."""
        breaker = CircuitBreaker("test", failure_threshold=3, recovery_timeout=30.0)
        
        stats = breaker.get_stats()
        
        assert stats["name"] == "test"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 3
        assert stats["recovery_timeout"] == 30.0


class TestCircuitBreakerRegistry:
    """Tests for global circuit breaker registry."""

    def setup_method(self):
        reset_all_breakers()

    def test_get_circuit_breaker_creates(self):
        """get_circuit_breaker creates new breaker."""
        breaker = get_circuit_breaker("venue_a")
        assert breaker.name == "venue_a"

    def test_get_circuit_breaker_caches(self):
        """get_circuit_breaker returns same instance."""
        breaker1 = get_circuit_breaker("venue_b")
        breaker2 = get_circuit_breaker("venue_b")
        assert breaker1 is breaker2

    def test_different_names_different_breakers(self):
        """Different names create different breakers."""
        breaker1 = get_circuit_breaker("venue_c")
        breaker2 = get_circuit_breaker("venue_d")
        assert breaker1 is not breaker2

    def test_reset_all_breakers(self):
        """reset_all_breakers resets all."""
        breaker = get_circuit_breaker("venue_e", failure_threshold=1)
        
        # Trip it
        breaker._state = CircuitState.OPEN
        breaker._failure_count = 5
        
        reset_all_breakers()
        
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
