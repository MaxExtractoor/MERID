"""Tests for the MERID resilience layer: CircuitBreaker, Bulkhead, OperationResult, retry.

Covers:
- CircuitBreaker: state transitions (closed→open→half-open→closed), failure counting,
  recovery timeout, reset, stats, registry
- Bulkhead: concurrency limiting, queue overflow, stats, registry
- OperationResult: ok/fail/empty constructors, unwrap variants, map, bool, metadata
- retry_with_backoff: retries on retryable errors, no-retry on non-retryable,
  backoff timing, on_retry callback
- RetryContext: manual retry loop, should_retry, handle_error
- timed_result: decorator wrapping
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from merid.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_all_breakers,
    get_circuit_breaker,
    reset_all_breakers,
)
from merid.resilience.bulkhead import (
    Bulkhead,
    BulkheadFullError,
    BulkheadStats,
    get_bulkhead,
    get_all_bulkheads,
    reset_all_bulkheads,
)
from merid.resilience.result import OperationResult, timed_result
from merid.resilience.retry import (
    RetryConfig,
    RetryContext,
    retry_with_backoff,
    _calculate_backoff,
)


# ── CircuitBreaker Tests ──────────────────────────────────────────────

class TestCircuitBreakerStateTransitions:
    """Verify circuit breaker state machine: closed → open → half-open → closed."""

    @pytest.fixture
    def breaker(self):
        return CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=0.1)

    @pytest.mark.asyncio
    async def test_starts_closed(self, breaker):
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, breaker):
        for _ in range(3):
            await breaker.record_failure(RuntimeError("fail"))
        assert breaker.state == CircuitState.OPEN
        assert breaker.is_open

    @pytest.mark.asyncio
    async def test_blocks_calls_when_open(self, breaker):
        for _ in range(3):
            await breaker.record_failure(RuntimeError("fail"))
        with pytest.raises(CircuitOpenError):
            async with breaker:
                pass

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_recovery(self, breaker):
        for _ in range(3):
            await breaker.record_failure(RuntimeError("fail"))
        assert breaker.is_open
        # Wait for recovery timeout
        await asyncio.sleep(0.15)
        # Next call should be allowed (half-open)
        async with breaker:
            pass  # Success in half-open closes circuit
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_reopens_on_half_open_failure(self, breaker):
        for _ in range(3):
            await breaker.record_failure(RuntimeError("fail"))
        await asyncio.sleep(0.15)
        # Trigger half-open check, then fail
        try:
            async with breaker:
                raise RuntimeError("half-open fail")
        except RuntimeError:
            pass
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, breaker):
        await breaker.record_failure(RuntimeError("fail"))
        await breaker.record_failure(RuntimeError("fail"))
        assert breaker.failure_count == 2
        await breaker.record_success()
        assert breaker.failure_count == 0

    @pytest.mark.asyncio
    async def test_stays_closed_below_threshold(self, breaker):
        await breaker.record_failure(RuntimeError("fail"))
        await breaker.record_failure(RuntimeError("fail"))
        assert breaker.state == CircuitState.CLOSED


class TestCircuitBreakerReset:
    """Verify manual reset behavior."""

    @pytest.mark.asyncio
    async def test_reset_closes_open_circuit(self):
        breaker = CircuitBreaker(name="reset-test", failure_threshold=2, recovery_timeout=60.0)
        await breaker.record_failure(RuntimeError("fail"))
        await breaker.record_failure(RuntimeError("fail"))
        assert breaker.is_open
        breaker.reset()
        assert breaker.is_closed
        assert breaker.failure_count == 0


class TestCircuitBreakerStats:
    """Verify stats reporting."""

    @pytest.mark.asyncio
    async def test_stats_structure(self):
        breaker = CircuitBreaker(name="stats-test", failure_threshold=5, recovery_timeout=30.0)
        stats = breaker.get_stats()
        assert stats["name"] == "stats-test"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 5
        assert stats["recovery_timeout"] == 30.0
        assert stats["time_until_retry"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_reflect_failures(self):
        breaker = CircuitBreaker(name="stats-fail", failure_threshold=5)
        await breaker.record_failure(RuntimeError("fail"))
        await breaker.record_failure(RuntimeError("fail"))
        stats = breaker.get_stats()
        assert stats["failure_count"] == 2
        assert stats["state"] == "closed"


class TestCircuitBreakerRegistry:
    """Verify global registry behavior."""

    def test_get_circuit_breaker_creates_new(self):
        breaker = get_circuit_breaker("registry-test-unique-1234")
        assert breaker.name == "registry-test-unique-1234"

    def test_get_circuit_breaker_returns_cached(self):
        b1 = get_circuit_breaker("registry-cached-5678")
        b2 = get_circuit_breaker("registry-cached-5678")
        assert b1 is b2

    def test_get_all_breakers_returns_dict(self):
        result = get_all_breakers()
        assert isinstance(result, dict)


class TestCircuitOpenError:
    """Verify CircuitOpenError attributes."""

    def test_error_attributes(self):
        err = CircuitOpenError("test-venue", 15.5)
        assert err.name == "test-venue"
        assert err.time_until_retry == 15.5
        assert "test-venue" in str(err)
        assert "15.5" in str(err)


# ── Bulkhead Tests ────────────────────────────────────────────────────

class TestBulkheadConcurrency:
    """Verify bulkhead limits concurrent operations."""

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        bh = Bulkhead(name="bh-test", max_concurrent=3, max_queued=10)
        async with bh:
            assert bh.active_count == 1
        assert bh.active_count == 0

    @pytest.mark.asyncio
    async def test_tracks_active_count(self):
        bh = Bulkhead(name="bh-active", max_concurrent=5, max_queued=10)
        wait = await bh.acquire()
        assert bh.active_count == 1
        await bh.release()
        assert bh.active_count == 0

    @pytest.mark.asyncio
    async def test_rejects_when_queue_full(self):
        bh = Bulkhead(name="bh-full", max_concurrent=1, max_queued=1)
        # Fill the single concurrent slot
        await bh.acquire()
        # Fill the single queue slot (this will queue, waiting for semaphore)
        # Launch a queued acquire in background
        async def queued_acquire():
            await bh.acquire()
        task = asyncio.create_task(queued_acquire())
        await asyncio.sleep(0.05)  # Let it enter the queue
        # Now queue is full — next should be rejected
        with pytest.raises(BulkheadFullError):
            await bh.acquire()
        # Cleanup
        await bh.release()
        await asyncio.sleep(0.05)
        await bh.release()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestBulkheadStats:
    """Verify bulkhead statistics."""

    @pytest.mark.asyncio
    async def test_stats_structure(self):
        bh = Bulkhead(name="bh-stats", max_concurrent=5, max_queued=20)
        stats = bh.get_stats()
        assert isinstance(stats, BulkheadStats)
        assert stats.name == "bh-stats"
        assert stats.max_concurrent == 5
        assert stats.max_queued == 20
        assert stats.active_count == 0

    @pytest.mark.asyncio
    async def test_stats_track_operations(self):
        bh = Bulkhead(name="bh-ops", max_concurrent=5, max_queued=20)
        async with bh:
            pass
        stats = bh.get_stats()
        assert stats.total_accepted == 1
        assert stats.total_completed == 1
        assert stats.total_failed == 0

    @pytest.mark.asyncio
    async def test_stats_track_failures(self):
        bh = Bulkhead(name="bh-fail-ops", max_concurrent=5, max_queued=20)
        try:
            async with bh:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        stats = bh.get_stats()
        assert stats.total_failed == 1
        assert stats.total_completed == 0

    @pytest.mark.asyncio
    async def test_reset_stats(self):
        bh = Bulkhead(name="bh-reset", max_concurrent=5, max_queued=20)
        async with bh:
            pass
        bh.reset_stats()
        stats = bh.get_stats()
        assert stats.total_accepted == 0
        assert stats.total_completed == 0


class TestBulkheadRegistry:
    """Verify global bulkhead registry."""

    def test_get_bulkhead_creates_new(self):
        bh = get_bulkhead("bh-registry-unique-9999")
        assert bh.name == "bh-registry-unique-9999"

    def test_get_bulkhead_returns_cached(self):
        b1 = get_bulkhead("bh-registry-cached-8888")
        b2 = get_bulkhead("bh-registry-cached-8888")
        assert b1 is b2

    def test_get_all_bulkheads_returns_dict(self):
        result = get_all_bulkheads()
        assert isinstance(result, dict)


class TestBulkheadFullError:
    """Verify BulkheadFullError attributes."""

    def test_error_attributes(self):
        err = BulkheadFullError("test-bh", 10, 10)
        assert err.name == "test-bh"
        assert err.queued == 10
        assert err.max_queued == 10
        assert "test-bh" in str(err)


# ── OperationResult Tests ─────────────────────────────────────────────

class TestOperationResultConstructors:
    """Verify ok/fail/empty constructors."""

    def test_ok_result(self):
        r = OperationResult.ok({"data": 42}, latency_ms=10.5, retries=0)
        assert r.success is True
        assert r.data == {"data": 42}
        assert r.latency_ms == 10.5
        assert r.error is None

    def test_fail_result(self):
        err = ValueError("bad input")
        r = OperationResult.fail(err, latency_ms=5.0, retries=2)
        assert r.success is False
        assert r.error is err
        assert r.error_message == "bad input"
        assert r.retries == 2

    def test_empty_result(self):
        r = OperationResult.empty("No positions found")
        assert r.success is True
        assert r.data is None
        assert r.metadata["reason"] == "No positions found"

    def test_ok_with_metadata(self):
        r = OperationResult.ok("data", operation="list_markets", status_code=200)
        assert r.metadata["operation"] == "list_markets"
        assert r.metadata["status_code"] == 200


class TestOperationResultUnwrap:
    """Verify unwrap variants."""

    def test_unwrap_success(self):
        r = OperationResult.ok(42)
        assert r.unwrap() == 42

    def test_unwrap_failure_raises(self):
        err = RuntimeError("fail")
        r = OperationResult.fail(err)
        with pytest.raises(RuntimeError, match="fail"):
            r.unwrap()

    def test_unwrap_or_success(self):
        r = OperationResult.ok(42)
        assert r.unwrap_or(0) == 42

    def test_unwrap_or_failure(self):
        r = OperationResult.fail(RuntimeError("fail"))
        assert r.unwrap_or(0) == 0

    def test_unwrap_or_none_data(self):
        r = OperationResult.empty()
        assert r.unwrap_or([]) == []

    def test_unwrap_or_else_success(self):
        r = OperationResult.ok(42)
        assert r.unwrap_or_else(lambda: 0) == 42

    def test_unwrap_or_else_failure(self):
        r = OperationResult.fail(RuntimeError("fail"))
        assert r.unwrap_or_else(lambda: 99) == 99


class TestOperationResultMap:
    """Verify map transformation."""

    def test_map_success(self):
        r = OperationResult.ok(10)
        mapped = r.map(lambda x: x * 2)
        assert mapped.success is True
        assert mapped.data == 20

    def test_map_failure_passes_through(self):
        r = OperationResult.fail(RuntimeError("fail"))
        mapped = r.map(lambda x: x * 2)
        assert mapped.success is False

    def test_map_exception_becomes_failure(self):
        r = OperationResult.ok(10)
        mapped = r.map(lambda x: 1 / 0)
        assert mapped.success is False


class TestOperationResultBool:
    """Verify bool behavior."""

    def test_success_is_truthy(self):
        assert bool(OperationResult.ok(42)) is True

    def test_failure_is_falsy(self):
        assert bool(OperationResult.fail(RuntimeError("fail"))) is False

    def test_if_pattern(self):
        r = OperationResult.ok("data")
        if r:
            passed = True
        else:
            passed = False
        assert passed is True


class TestTimedResult:
    """Verify timed_result decorator."""

    @pytest.mark.asyncio
    async def test_wraps_success(self):
        @timed_result
        async def good_op():
            return 42

        result = await good_op()
        assert result.success is True
        assert result.data == 42
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_wraps_failure(self):
        @timed_result
        async def bad_op():
            raise ValueError("boom")

        result = await bad_op()
        assert result.success is False
        assert "boom" in result.error_message


# ── Retry Tests ───────────────────────────────────────────────────────

class TestRetryConfig:
    """Verify retry configuration defaults."""

    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.max_retries == 3
        assert cfg.backoff_base == 2.0
        assert cfg.backoff_max == 60.0
        assert 429 in cfg.retry_statuses
        assert 503 in cfg.retry_statuses


class TestBackoffCalculation:
    """Verify exponential backoff math."""

    def test_backoff_increases(self):
        cfg = RetryConfig(backoff_base=2.0, backoff_jitter=0.0)
        b0 = _calculate_backoff(0, cfg)
        b1 = _calculate_backoff(1, cfg)
        b2 = _calculate_backoff(2, cfg)
        # With jitter=0, backoff is exactly 2^attempt
        assert b0 == pytest.approx(1.0, abs=0.01)
        assert b1 == pytest.approx(2.0, abs=0.01)
        assert b2 == pytest.approx(4.0, abs=0.01)

    def test_backoff_capped_at_max(self):
        cfg = RetryConfig(backoff_base=2.0, backoff_max=5.0, backoff_jitter=0.0)
        b10 = _calculate_backoff(10, cfg)
        assert b10 == 5.0


class TestRetryWithBackoff:
    """Verify retry decorator behavior."""

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, backoff_base=0.01)
        async def succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeeds()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_error(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=2,
            backoff_base=0.01,
            retry_on=(ConnectionError,),
        )
        async def fails_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("down")
            return "ok"

        result = await fails_then_succeeds()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        @retry_with_backoff(
            max_retries=2,
            backoff_base=0.01,
            retry_on=(ConnectionError,),
        )
        async def always_fails():
            raise ConnectionError("permanent")

        with pytest.raises(ConnectionError, match="permanent"):
            await always_fails()

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=3,
            backoff_base=0.01,
            retry_on=(ConnectionError,),
            no_retry_on=(ValueError,),
        )
        async def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad")

        with pytest.raises(ValueError):
            await raises_value_error()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        retries_seen = []

        def on_retry(attempt, exc):
            retries_seen.append(attempt)

        @retry_with_backoff(
            max_retries=2,
            backoff_base=0.01,
            retry_on=(ConnectionError,),
            on_retry=on_retry,
        )
        async def fails_twice():
            if len(retries_seen) < 2:
                raise ConnectionError("down")
            return "ok"

        result = await fails_twice()
        assert result == "ok"
        assert retries_seen == [1, 2]

    @pytest.mark.asyncio
    async def test_unexpected_error_not_retried(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=3,
            backoff_base=0.01,
            retry_on=(ConnectionError,),
        )
        async def raises_unexpected():
            nonlocal call_count
            call_count += 1
            raise TypeError("unexpected")

        with pytest.raises(TypeError):
            await raises_unexpected()
        assert call_count == 1


class TestRetryContext:
    """Verify manual retry context manager."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        async with RetryContext(max_retries=3) as ctx:
            while ctx.should_retry():
                ctx.success()
                break
        assert ctx.attempt == 0
        assert ctx.retries_remaining == 3

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        attempt_count = 0
        async with RetryContext(max_retries=3, backoff_base=0.01) as ctx:
            while ctx.should_retry():
                try:
                    attempt_count += 1
                    if attempt_count < 3:
                        raise ConnectionError("down")
                    ctx.success()
                    break
                except ConnectionError as e:
                    await ctx.handle_error(e)
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_exhaustion(self):
        with pytest.raises(ConnectionError, match="permanent"):
            async with RetryContext(max_retries=1, backoff_base=0.01) as ctx:
                while ctx.should_retry():
                    try:
                        raise ConnectionError("permanent")
                    except ConnectionError as e:
                        await ctx.handle_error(e)
