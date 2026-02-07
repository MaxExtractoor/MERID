"""Tests for core/rate_limiter.py."""
import pytest
import asyncio
from unittest.mock import patch
from core.rate_limiter import RateLimiter, rate_limiter


class TestRateLimiterInitialization:
    """Test RateLimiter initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        limiter = RateLimiter()
        assert "alpaca" in limiter.default_limits
        assert "kalshi" in limiter.default_limits
        assert limiter.default_limits["alpaca"] == 10.0

    def test_default_intervals_set(self):
        """Test default intervals are calculated."""
        limiter = RateLimiter()
        assert limiter.min_interval["alpaca"] == 0.1  # 1/10
        assert limiter.min_interval["kraken"] == 3.0  # 1/0.33

    def test_default_quota_set(self):
        """Test default quota is set."""
        limiter = RateLimiter()
        assert limiter.quota["alpaca"]["remaining"] == 1000
        assert limiter.quota["alpaca"]["total"] == 1000


class TestRateLimiterSetLimit:
    """Test set_limit method."""

    def test_set_custom_limit(self):
        """Test setting custom rate limit."""
        limiter = RateLimiter()
        limiter.set_limit("custom_venue", 5.0)
        assert limiter.min_interval["custom_venue"] == 0.2  # 1/5


class TestRateLimiterUpdateQuota:
    """Test update_quota method."""

    def test_update_quota(self):
        """Test updating quota."""
        limiter = RateLimiter()
        limiter.update_quota("alpaca", remaining=500, total=1000, reset_in=30)
        assert limiter.quota["alpaca"]["remaining"] == 500
        assert limiter.quota["alpaca"]["total"] == 1000
        assert limiter.quota["alpaca"]["reset_in"] == 30

    def test_update_low_quota_warning(self):
        """Test warning logged on low quota."""
        limiter = RateLimiter()
        # Should not raise, just log
        limiter.update_quota("alpaca", remaining=50, total=1000, reset_in=60)
        assert limiter.quota["alpaca"]["remaining"] == 50


class TestRateLimiterWait:
    """Test wait method."""

    @pytest.mark.asyncio
    async def test_wait_first_call(self):
        """Test first call doesn't wait."""
        limiter = RateLimiter()
        result = await limiter.wait("alpaca")
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_respects_interval(self):
        """Test wait respects interval."""
        limiter = RateLimiter()
        limiter.min_interval["test"] = 0.1
        limiter.last_call["test"] = asyncio.get_event_loop().time()
        
        start = asyncio.get_event_loop().time()
        await limiter.wait("test")
        elapsed = asyncio.get_event_loop().time() - start
        
        assert elapsed >= 0.1

    @pytest.mark.asyncio
    async def test_wait_exhausted_quota(self):
        """Test wait returns False when quota exhausted."""
        limiter = RateLimiter()
        limiter.quota["test"] = {"remaining": 0, "total": 1000, "reset_in": 60}
        result = await limiter.wait("test")
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_decrements_quota(self):
        """Test wait decrements quota."""
        limiter = RateLimiter()
        limiter.quota["test"] = {"remaining": 100, "total": 1000, "reset_in": 60}
        await limiter.wait("test")
        assert limiter.quota["test"]["remaining"] == 99


class TestRateLimiterWaitWithBackoff:
    """Test wait_with_backoff method."""

    @pytest.mark.asyncio
    async def test_wait_with_backoff_no_attempt(self):
        """Test wait_with_backoff with no retry."""
        limiter = RateLimiter()
        result = await limiter.wait_with_backoff("alpaca", attempt=0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_with_backoff_with_attempt(self):
        """Test wait_with_backoff with retry attempts."""
        limiter = RateLimiter()
        limiter.min_interval["test"] = 0.0
        
        start = asyncio.get_event_loop().time()
        await limiter.wait_with_backoff("test", attempt=2)
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should wait 2^2 = 4 seconds, but capped at 60
        assert elapsed >= 4.0


class TestRateLimiterGetQuotaStatus:
    """Test get_quota_status method."""

    def test_get_existing_quota(self):
        """Test getting existing venue quota."""
        limiter = RateLimiter()
        limiter.quota["alpaca"] = {"remaining": 500, "total": 1000, "reset_in": 30}
        status = limiter.get_quota_status("alpaca")
        assert status["remaining"] == 500

    def test_get_default_for_unknown(self):
        """Test default quota for unknown venue."""
        limiter = RateLimiter()
        status = limiter.get_quota_status("unknown")
        assert status["remaining"] == 1000  # Default


class TestRateLimiterIsThrottled:
    """Test is_throttled method."""

    def test_is_throttled_true(self):
        """Test throttled when remaining < 50."""
        limiter = RateLimiter()
        limiter.quota["test"] = {"remaining": 30, "total": 1000, "reset_in": 60}
        assert limiter.is_throttled("test") is True

    def test_is_throttled_false(self):
        """Test not throttled when remaining >= 50."""
        limiter = RateLimiter()
        limiter.quota["test"] = {"remaining": 100, "total": 1000, "reset_in": 60}
        assert limiter.is_throttled("test") is False


class TestRateLimiterResetQuota:
    """Test reset_quota method."""

    def test_reset_quota(self):
        """Test resetting quota."""
        limiter = RateLimiter()
        limiter.quota["test"] = {"remaining": 0, "total": 1000, "reset_in": 0}
        limiter.reset_quota("test")
        assert limiter.quota["test"]["remaining"] == 1000


class TestRateLimiterSingleton:
    """Test rate_limiter singleton."""

    def test_singleton_exists(self):
        """Test rate_limiter singleton exists."""
        assert rate_limiter is not None
        assert isinstance(rate_limiter, RateLimiter)
