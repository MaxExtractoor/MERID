"""Resilience contract for ``EnhancedKalshiExecutor``.

This file codifies the public behaviour of the retry + circuit-breaker
surface the session's production fixes touched:

1. ``EnhancedKalshiExecutor._retry_wrapper`` — previously called
   ``retry_async`` positionally, producing a ``TypeError: got multiple
   values for argument 'max_retries'`` at every retry-wrapped call site.
   The fix rebuilds the decorator once and applies it to ``func`` per
   call.  The contract tests here lock in:

     * the wrapper *is* a usable decorator factory (no binding error);
     * a retryable exception is retried exactly ``max_retries + 1`` times;
     * non-retryable exceptions short-circuit after a single call.

2. ``CircuitBreaker.last_failure_time`` — a new public property exposed
   so executor health probes can surface breaker state without reaching
   into private fields.  ``EnhancedKalshiExecutor.get_health_stats()``
   now advertises this field per operation-type breaker; the contract
   tests here freeze the returned shape and the state semantics
   (``closed`` → ``open`` → ``half_open`` → ``closed``).

Scope intentionally stays narrow and behavioural — the low-level
primitives (``retry_with_backoff``, ``CircuitBreaker``) already have
dedicated unit coverage under ``tests/merid/resilience/``.  This file
specifies the *composition* layer at the executor.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.client_enhanced import EnhancedKalshiClient
from merid.execution.executors.kalshi import KalshiExecutor
from merid.execution.executors.kalshi_enhanced import (
    EnhancedKalshiExecutor,
    ExecutorOperationResult,
)
from merid.resilience import OperationResult
from merid.resilience.circuit_breaker import (
    CircuitState,
    reset_all_breakers,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_global_breakers():
    """Reset the process-wide breaker registry around each test.

    ``get_circuit_breaker`` caches breakers by name, so a breaker opened
    in one test would leak its OPEN state into the next unless reset.
    """
    reset_all_breakers()
    try:
        yield
    finally:
        reset_all_breakers()


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=EnhancedKalshiClient)
    client.get_market_result = AsyncMock()
    client.get_orderbook_result = AsyncMock()
    client.place_order_result = AsyncMock()
    client.get_open_orders_result = AsyncMock()
    client.cancel_order_result = AsyncMock()
    client.get_balance_result = AsyncMock()
    return client


@pytest.fixture
def mock_base_executor() -> MagicMock:
    executor = MagicMock(spec=KalshiExecutor)
    executor._client = None
    return executor


@pytest.fixture
def executor(mock_client, mock_base_executor) -> EnhancedKalshiExecutor:
    with patch(
        "merid.execution.executors.kalshi_enhanced.KalshiExecutor",
        return_value=mock_base_executor,
    ):
        ex = EnhancedKalshiExecutor()
    ex._enhanced_client = mock_client
    ex.reset_all_circuit_breakers()
    return ex


# ═══════════════════════════════════════════════════════════════════════════
# A. Retry wrapper contract
# ═══════════════════════════════════════════════════════════════════════════


class TestRetryWrapperIsADecoratorFactory:
    """The regression the session's retry_async fix was written to prevent."""

    @pytest.mark.asyncio
    async def test_wrapper_binds_without_typeerror(self):
        """Building + applying the decorator must not raise TypeError.

        The pre-fix code invoked ``retry_async(func, max_retries=N, ...)``
        which bound ``func`` to the ``max_retries`` slot *and* then
        collided with the explicit kwarg.  This test exercises the exact
        bind site so a silent regression of the positional form is
        caught immediately.
        """
        decorator = EnhancedKalshiExecutor._retry_wrapper(max_retries=2)

        async def op() -> str:
            return "ok"

        wrapped = decorator(op)
        result = await wrapped()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_wrapper_retries_retryable_connection_error(self):
        """ConnectionError is on the ``retry_on`` tuple → retry N+1 times."""
        calls = 0
        decorator = EnhancedKalshiExecutor._retry_wrapper(max_retries=3)

        async def always_fail() -> None:
            nonlocal calls
            calls += 1
            raise ConnectionError("transient")

        wrapped = decorator(always_fail)

        # asyncio.sleep is what the retry decorator uses to back off; patch it
        # out so the test runs instantly and doesn't prove anything about
        # wall-clock sleep duration (that's specified in the retry unit tests).
        with patch(
            "merid.resilience.retry.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            with pytest.raises(ConnectionError):
                await wrapped()

        # 1 initial attempt + 3 retries == 4 total calls
        assert calls == 4
        # One sleep per retry (3), not between failing-and-giving-up
        assert mock_sleep.call_count == 3

    @pytest.mark.asyncio
    async def test_wrapper_retries_asyncio_timeout(self):
        """``asyncio.TimeoutError`` is also on the ``retry_on`` tuple."""
        calls = 0
        decorator = EnhancedKalshiExecutor._retry_wrapper(max_retries=2)

        async def flaky() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise asyncio.TimeoutError("slow")
            return "ok"

        wrapped = decorator(flaky)
        with patch(
            "merid.resilience.retry.asyncio.sleep", new_callable=AsyncMock
        ):
            assert await wrapped() == "ok"
        assert calls == 2  # fails once, succeeds on retry

    @pytest.mark.asyncio
    async def test_wrapper_does_not_retry_non_retryable(self):
        """Exceptions outside ``retry_on`` must propagate after one call."""
        calls = 0
        decorator = EnhancedKalshiExecutor._retry_wrapper(max_retries=3)

        async def bad_input() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("user error")

        wrapped = decorator(bad_input)
        with patch(
            "merid.resilience.retry.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            with pytest.raises(ValueError):
                await wrapped()

        assert calls == 1, (
            "Non-retryable exception must not trigger the backoff loop; "
            "production would otherwise waste the retry budget on a "
            "deterministic failure."
        )
        assert mock_sleep.call_count == 0

    @pytest.mark.asyncio
    async def test_wrapper_success_first_try(self):
        """Happy path: zero retries, zero sleeps, preserves return value."""
        decorator = EnhancedKalshiExecutor._retry_wrapper(max_retries=5)

        async def op(x: int, y: int) -> int:
            return x + y

        wrapped = decorator(op)
        with patch(
            "merid.resilience.retry.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            assert await wrapped(2, 3) == 5
        assert mock_sleep.call_count == 0


# ═══════════════════════════════════════════════════════════════════════════
# B. ``get_health_stats`` shape + last_failure_time contract
# ═══════════════════════════════════════════════════════════════════════════


_EXPECTED_OP_KEYS = {
    "get_quotes",
    "get_positions",
    "execute_trade",
    "cancel_order",
    "get_balance",
}

_EXPECTED_TOP_LEVEL_KEYS = {
    "stats",
    "success_rate",
    "circuit_breakers",
    "kill_switch_active",
    "kill_switch_reset_time",
    "last_health_check",
}


class TestHealthStatsShape:
    """Freeze the observable shape of ``get_health_stats()``."""

    def test_top_level_keys_present_on_fresh_executor(self, executor):
        stats = executor.get_health_stats()
        assert _EXPECTED_TOP_LEVEL_KEYS.issubset(stats.keys()), (
            f"Missing top-level keys: "
            f"{_EXPECTED_TOP_LEVEL_KEYS - set(stats.keys())}"
        )

    def test_circuit_breakers_entry_per_op_type(self, executor):
        stats = executor.get_health_stats()
        cb = stats["circuit_breakers"]
        assert set(cb.keys()) == _EXPECTED_OP_KEYS, (
            f"Unexpected circuit_breakers keys: expected {_EXPECTED_OP_KEYS}, "
            f"got {set(cb.keys())}"
        )

    def test_each_breaker_reports_required_fields(self, executor):
        """Every breaker entry must expose state + failure_count + last_failure_time.

        ``last_failure_time`` is the field the session's
        ``CircuitBreaker.last_failure_time`` property was added for.
        """
        stats = executor.get_health_stats()
        for op, cb in stats["circuit_breakers"].items():
            assert "state" in cb, f"{op}: missing 'state'"
            assert "failure_count" in cb, f"{op}: missing 'failure_count'"
            assert "last_failure_time" in cb, (
                f"{op}: missing 'last_failure_time' — regression on the "
                f"CircuitBreaker public property."
            )

    def test_fresh_executor_reports_closed_breakers(self, executor):
        stats = executor.get_health_stats()
        for op, cb in stats["circuit_breakers"].items():
            assert cb["state"] == "closed", f"{op}: expected 'closed', got {cb['state']}"
            assert cb["failure_count"] == 0, f"{op}: expected 0 failures"
            assert cb["last_failure_time"] == 0.0, (
                f"{op}: last_failure_time must start at 0.0 before any "
                f"failure, got {cb['last_failure_time']}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# C. Breaker state transitions reflected in get_health_stats
# ═══════════════════════════════════════════════════════════════════════════


def _get_breaker_entry(executor: EnhancedKalshiExecutor, op: str) -> dict:
    return executor.get_health_stats()["circuit_breakers"][op]


class TestBreakerStateTransitionsThroughHealthStats:
    """CLOSED → OPEN → HALF_OPEN → CLOSED must all be observable."""

    @pytest.mark.asyncio
    async def test_failure_updates_count_and_last_failure_time(self, executor):
        """One sub-threshold failure → count=1, last_failure_time > 0, state=closed."""
        breaker = executor._circuit_breakers["get_quotes"]

        try:
            async with breaker:
                raise ConnectionError("boom")
        except ConnectionError:
            pass

        entry = _get_breaker_entry(executor, "get_quotes")
        assert entry["state"] == "closed"  # still below threshold
        assert entry["failure_count"] == 1
        assert entry["last_failure_time"] > 0.0, (
            "last_failure_time must surface the wall-clock of the most "
            "recent failure, not remain 0.0"
        )

    @pytest.mark.asyncio
    async def test_reaching_threshold_flips_state_to_open(self, executor):
        """``failure_threshold`` consecutive failures → state='open'."""
        breaker = executor._circuit_breakers["get_quotes"]
        threshold = breaker.failure_threshold

        for _ in range(threshold):
            try:
                async with breaker:
                    raise ConnectionError("boom")
            except ConnectionError:
                pass

        entry = _get_breaker_entry(executor, "get_quotes")
        assert entry["state"] == "open"
        assert entry["failure_count"] == threshold
        assert entry["last_failure_time"] > 0.0

    @pytest.mark.asyncio
    async def test_open_breaker_transitions_to_half_open_after_recovery(self, executor):
        """Once ``recovery_timeout`` elapses, entering the breaker → HALF_OPEN."""
        breaker = executor._circuit_breakers["get_quotes"]
        # Short-circuit the timeout so the test is fast and deterministic.
        breaker.recovery_timeout = 0.05

        for _ in range(breaker.failure_threshold):
            try:
                async with breaker:
                    raise ConnectionError("boom")
            except ConnectionError:
                pass
        assert breaker.state == CircuitState.OPEN

        await asyncio.sleep(0.08)

        # Entering the breaker should transition it to HALF_OPEN.  We use
        # a failing body so the transition itself is observable before the
        # state flips again on the outcome of the probe call.
        try:
            async with breaker:
                # At this moment the breaker has transitioned CLOSED-of-open
                # → HALF_OPEN by _check_state; surface that via the public
                # property.
                assert breaker.state == CircuitState.HALF_OPEN
                raise ConnectionError("still broken")
        except ConnectionError:
            pass

        # After the HALF_OPEN probe failed, the breaker re-opens.
        entry = _get_breaker_entry(executor, "get_quotes")
        assert entry["state"] == "open", (
            "Failure during HALF_OPEN probe must re-open the circuit."
        )

    @pytest.mark.asyncio
    async def test_half_open_success_returns_to_closed(self, executor):
        """OPEN → HALF_OPEN → success → CLOSED, failure_count reset to 0."""
        breaker = executor._circuit_breakers["get_quotes"]
        breaker.recovery_timeout = 0.05

        for _ in range(breaker.failure_threshold):
            try:
                async with breaker:
                    raise ConnectionError("boom")
            except ConnectionError:
                pass
        assert breaker.state == CircuitState.OPEN
        failure_time_before_recovery = breaker.last_failure_time
        assert failure_time_before_recovery > 0.0

        await asyncio.sleep(0.08)

        async with breaker:
            pass  # successful probe in HALF_OPEN

        entry = _get_breaker_entry(executor, "get_quotes")
        assert entry["state"] == "closed"
        assert entry["failure_count"] == 0
        # ``last_failure_time`` is a historical marker — a clean recovery
        # does not wipe the record of the most recent failure.  This
        # preserves enough context for dashboards and post-mortems.
        assert entry["last_failure_time"] == failure_time_before_recovery

    @pytest.mark.asyncio
    async def test_manual_reset_clears_last_failure_time(self, executor):
        """``reset_circuit_breaker`` is an explicit wipe — clear everything.

        This contrasts with the natural recovery path above: a manual
        reset is an operator action signalling "forget this breaker's
        history", so ``last_failure_time`` *is* zeroed.
        """
        breaker = executor._circuit_breakers["get_quotes"]

        for _ in range(breaker.failure_threshold):
            try:
                async with breaker:
                    raise ConnectionError("boom")
            except ConnectionError:
                pass
        assert breaker.last_failure_time > 0.0

        reset_ok = executor.reset_circuit_breaker("get_quotes")
        assert reset_ok is True

        entry = _get_breaker_entry(executor, "get_quotes")
        assert entry["state"] == "closed"
        assert entry["failure_count"] == 0
        assert entry["last_failure_time"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# D. Composition spot-check: retry + breaker together
# ═══════════════════════════════════════════════════════════════════════════


class TestRetryAndBreakerComposition:
    """The executor wraps ops with retry *and* breaker — spot-check the combo."""

    @pytest.mark.asyncio
    async def test_non_retryable_error_inside_op_does_not_burn_retry_budget(
        self, executor, mock_client
    ):
        """Validation errors must short-circuit retry.

        ``execute_trade`` is wrapped with ``@_retry_wrapper(max_retries=3)``.
        A ``ValueError`` raised inside the op (e.g. validation) should
        propagate on the first attempt, not retried three extra times.
        """
        calls = 0

        async def boom(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise ValueError("bad payload")

        mock_client.place_order_result.side_effect = boom

        with patch(
            "merid.resilience.retry.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            result = await executor.execute_trade("TEST-TICKER", "buy", 10)

        # execute_trade catches the exception and returns a failed
        # ExecutorOperationResult; the key assertion is that the op was
        # attempted exactly once.
        assert isinstance(result, ExecutorOperationResult)
        assert result.success is False
        assert calls == 1, (
            f"Non-retryable error burned retry budget: {calls} attempts"
        )
        assert mock_sleep.call_count == 0
