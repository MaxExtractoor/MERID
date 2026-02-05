"""Tests for OperationResult type."""

import pytest

from merid.resilience.result import OperationResult, timed_result


class TestOperationResult:
    """Tests for OperationResult class."""

    def test_ok_result(self):
        """ok() creates successful result."""
        result = OperationResult.ok("data", latency_ms=50.0)
        
        assert result.success is True
        assert result.data == "data"
        assert result.error is None
        assert result.latency_ms == 50.0

    def test_fail_result(self):
        """fail() creates failed result."""
        error = ValueError("bad input")
        result = OperationResult.fail(error, latency_ms=10.0)
        
        assert result.success is False
        assert result.data is None
        assert result.error is error
        assert result.error_message == "bad input"
        assert result.latency_ms == 10.0

    def test_empty_result(self):
        """empty() creates empty but successful result."""
        result = OperationResult.empty("No positions found")
        
        assert result.success is True
        assert result.data is None
        assert result.metadata["reason"] == "No positions found"

    def test_bool_success(self):
        """Success result is truthy."""
        result = OperationResult.ok("data")
        assert bool(result) is True
        assert result  # if result: pattern

    def test_bool_failure(self):
        """Failed result is falsy."""
        result = OperationResult.fail(ValueError())
        assert bool(result) is False

    def test_unwrap_success(self):
        """unwrap() returns data on success."""
        result = OperationResult.ok("data")
        assert result.unwrap() == "data"

    def test_unwrap_failure_raises(self):
        """unwrap() raises error on failure."""
        error = ValueError("bad")
        result = OperationResult.fail(error)
        
        with pytest.raises(ValueError):
            result.unwrap()

    def test_unwrap_or_success(self):
        """unwrap_or() returns data on success."""
        result = OperationResult.ok("data")
        assert result.unwrap_or("default") == "data"

    def test_unwrap_or_failure(self):
        """unwrap_or() returns default on failure."""
        result = OperationResult.fail(ValueError())
        assert result.unwrap_or("default") == "default"

    def test_unwrap_or_else_success(self):
        """unwrap_or_else() returns data on success."""
        result = OperationResult.ok("data")
        assert result.unwrap_or_else(lambda: "computed") == "data"

    def test_unwrap_or_else_failure(self):
        """unwrap_or_else() calls function on failure."""
        result = OperationResult.fail(ValueError())
        assert result.unwrap_or_else(lambda: "computed") == "computed"

    def test_map_success(self):
        """map() transforms successful data."""
        result = OperationResult.ok(5)
        mapped = result.map(lambda x: x * 2)
        
        assert mapped.success is True
        assert mapped.data == 10

    def test_map_failure_passes_through(self):
        """map() passes through failures."""
        result = OperationResult.fail(ValueError("bad"))
        mapped = result.map(lambda x: x * 2)
        
        assert mapped.success is False
        assert mapped.error_message == "bad"

    def test_map_error_in_transform(self):
        """map() catches errors in transform function."""
        result = OperationResult.ok("not a number")
        mapped = result.map(lambda x: int(x))
        
        assert mapped.success is False

    def test_metadata_in_ok(self):
        """ok() stores metadata."""
        result = OperationResult.ok("data", venue="kalshi", market_id="ABC")
        
        assert result.metadata["venue"] == "kalshi"
        assert result.metadata["market_id"] == "ABC"

    def test_retries_tracked(self):
        """Retries count is tracked."""
        result = OperationResult.ok("data", retries=2)
        assert result.retries == 2


class TestTimedResult:
    """Tests for timed_result decorator."""

    @pytest.mark.asyncio
    async def test_success_with_timing(self):
        """Successful call returns result with timing."""
        @timed_result
        async def fast_op():
            return "done"
        
        result = await fast_op()
        
        assert result.success is True
        assert result.data == "done"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_failure_with_timing(self):
        """Failed call returns result with timing."""
        @timed_result
        async def failing_op():
            raise ValueError("oops")
        
        result = await failing_op()
        
        assert result.success is False
        assert result.error_message == "oops"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_timing_accuracy(self):
        """Timing reflects actual operation duration."""
        import asyncio
        
        @timed_result
        async def slow_op():
            await asyncio.sleep(0.05)
            return "done"
        
        result = await slow_op()
        
        assert result.latency_ms >= 40  # At least 40ms
        assert result.latency_ms < 200  # Not too slow
