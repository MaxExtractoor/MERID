"""Tests for retry decorator and utilities."""

import asyncio
import pytest

from merid.resilience.retry import retry_with_backoff, RetryConfig, RetryContext


class TestRetryDecorator:
    """Tests for retry_with_backoff decorator."""

    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """Successful call doesn't retry."""
        call_count = 0
        
        @retry_with_backoff(max_retries=3, backoff_base=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"
        
        result = await succeed()
        
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Retries on ConnectionError."""
        call_count = 0
        
        @retry_with_backoff(max_retries=3, backoff_base=0.01)
        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("network fail")
            return "ok"
        
        result = await fail_twice()
        
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Raises after max retries exceeded."""
        call_count = 0
        
        @retry_with_backoff(max_retries=2, backoff_base=0.01)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("always fails")
        
        with pytest.raises(ConnectionError):
            await always_fail()
        
        assert call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_no_retry_on_excluded(self):
        """Doesn't retry on excluded exception types."""
        call_count = 0
        
        @retry_with_backoff(
            max_retries=3,
            backoff_base=0.01,
            no_retry_on=(ValueError,)
        )
        async def fail_with_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad value")
        
        with pytest.raises(ValueError):
            await fail_with_value_error()
        
        assert call_count == 1  # No retries

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        """Calls on_retry callback on each retry."""
        retry_log = []
        
        def log_retry(attempt, error):
            retry_log.append((attempt, str(error)))
        
        @retry_with_backoff(
            max_retries=2,
            backoff_base=0.01,
            on_retry=log_retry
        )
        async def fail_twice():
            if len(retry_log) < 2:
                raise ConnectionError("fail")
            return "ok"
        
        result = await fail_twice()
        
        assert result == "ok"
        assert len(retry_log) == 2
        assert retry_log[0][0] == 1
        assert retry_log[1][0] == 2


class TestRetryContext:
    """Tests for RetryContext class."""

    @pytest.mark.asyncio
    async def test_success_first_try(self):
        """Success on first try exits loop."""
        async with RetryContext(max_retries=3) as ctx:
            while ctx.should_retry():
                ctx.success()
                break
        
        assert ctx.attempt == 0

    @pytest.mark.asyncio
    async def test_retry_after_failure(self):
        """Retries after handling error."""
        attempts = 0
        
        async with RetryContext(max_retries=3, backoff_base=0.01) as ctx:
            while ctx.should_retry():
                attempts += 1
                if attempts < 3:
                    await ctx.handle_error(ConnectionError("fail"))
                else:
                    ctx.success()
                    break
        
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_max_retries_raises(self):
        """Raises after max retries in context."""
        async with RetryContext(max_retries=2, backoff_base=0.01) as ctx:
            with pytest.raises(ConnectionError):
                while ctx.should_retry():
                    await ctx.handle_error(ConnectionError("always fail"))

    def test_retries_remaining(self):
        """retries_remaining counts down."""
        ctx = RetryContext(max_retries=3)
        assert ctx.retries_remaining == 3
        
        ctx._attempt = 1
        assert ctx.retries_remaining == 2
        
        ctx._attempt = 3
        assert ctx.retries_remaining == 0


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_default_values(self):
        """Default config has sensible values."""
        config = RetryConfig()
        
        assert config.max_retries == 3
        assert config.backoff_base == 2.0
        assert config.backoff_max == 60.0
        assert 429 in config.retry_statuses
        assert 500 in config.retry_statuses

    def test_custom_values(self):
        """Custom config overrides defaults."""
        config = RetryConfig(
            max_retries=5,
            backoff_base=1.5,
            retry_on=(ValueError,),
        )
        
        assert config.max_retries == 5
        assert config.backoff_base == 1.5
        assert config.retry_on == (ValueError,)
