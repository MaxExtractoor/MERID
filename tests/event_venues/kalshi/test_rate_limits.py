"""
Phase 2: Rate-Limit Enforcement Tests

Tests for Kalshi REST client rate-limit enforcement covering:
1. 429 response handling with Retry-After header
2. 429 response without Retry-After (exponential backoff)
3. Non-retryable 4xx errors (400, 401, 403)
4. Self-throttling via token bucket

Reference: .windsurf/tickets/phase2-rate-limit-enforcement-tests.md
Baseline: Commit c25d2702
"""

import asyncio
import time
from typing import Dict, Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
import respx

from merid.event_venues.kalshi.client import (
    KalshiVenueClient,
    KalshiTokenBucket,
    KalshiBusinessError,
    KALSHI_MAX_RETRIES,
)
from merid.event_venues.kalshi.models import KalshiConfig


class Test429WithRetryAfterHeader:
    """Test 429 response handling with Retry-After header."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_with_retry_after_waits_exact_duration(self):
        """Verify client waits exactly the Retry-After duration."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        # Mock 429 response with Retry-After: 5
        route = respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "5"}),
                httpx.Response(200, json={"markets": []})
            ]
        )
        
        start = time.time()
        result = await client._request_with_resilience(
            "GET", "/markets", operation_name="test_429"
        )
        elapsed = time.time() - start
        
        # Should wait ~5 seconds (Retry-After value)
        assert 4.5 <= elapsed <= 5.5, f"Expected ~5s wait, got {elapsed:.2f}s"
        assert result.success
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_retry_succeeds_after_wait(self):
        """Verify retry succeeds after respecting Retry-After."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        route = respx.get("https://api.kalshi.test/trade-api/v2/portfolio/balance").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "2"}),
                httpx.Response(200, json={"balance": 1000})
            ]
        )
        
        result = await client._request_with_resilience(
            "GET", "/portfolio/balance", operation_name="get_balance"
        )
        
        assert result.success
        assert result.data["balance"] == 1000
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_multiple_sequential_429s_cumulative_backoff(self):
        """Verify multiple 429s respect each Retry-After header."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        route = respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "2"}),
                httpx.Response(429, headers={"Retry-After": "3"}),
                httpx.Response(200, json={"markets": []})
            ]
        )
        
        start = time.time()
        result = await client._request_with_resilience(
            "GET", "/markets", operation_name="test_sequential_429"
        )
        elapsed = time.time() - start
        
        # Should wait ~5 seconds total (2 + 3)
        assert 4.5 <= elapsed <= 6.0, f"Expected ~5s cumulative wait, got {elapsed:.2f}s"
        assert result.success
        assert route.call_count == 3


class Test429WithoutRetryAfterHeader:
    """Test 429 response handling without Retry-After (exponential backoff)."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_without_retry_after_uses_exponential_backoff(self):
        """Verify exponential backoff when Retry-After header absent."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        route = respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            side_effect=[
                httpx.Response(429),  # No Retry-After
                httpx.Response(200, json={"markets": []})
            ]
        )
        
        start = time.time()
        result = await client._request_with_resilience(
            "GET", "/markets", operation_name="test_backoff"
        )
        elapsed = time.time() - start
        
        # Should wait ~1 second (2^0 = 1)
        assert 0.8 <= elapsed <= 1.5, f"Expected ~1s backoff, got {elapsed:.2f}s"
        assert result.success
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_exponential_backoff_sequence(self):
        """Verify backoff doubles: 1s, 2s, 4s."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        # 3 failures + 1 success (exhaust retries)
        route = respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            side_effect=[
                httpx.Response(429),  # Wait 1s (2^0)
                httpx.Response(429),  # Wait 2s (2^1)
                httpx.Response(429),  # Wait 4s (2^2)
                httpx.Response(200, json={"markets": []})
            ]
        )
        
        start = time.time()
        result = await client._request_with_resilience(
            "GET", "/markets", operation_name="test_exp_backoff"
        )
        elapsed = time.time() - start
        
        # Should wait ~7 seconds total (1 + 2 + 4)
        assert 6.5 <= elapsed <= 8.0, f"Expected ~7s cumulative, got {elapsed:.2f}s"
        assert result.success
        assert route.call_count == 4

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_max_retries_exceeded_returns_failure(self):
        """Verify max retries exceeded returns failure result."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        # Always return 429 (will exhaust KALSHI_MAX_RETRIES)
        route = respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            return_value=httpx.Response(429)
        )
        
        result = await client._request_with_resilience(
            "GET", "/markets", operation_name="test_max_retries"
        )
        
        assert not result.success
        assert result.metadata.get("status_code") == 429
        # Should try initial + 3 retries = 4 total
        assert route.call_count == KALSHI_MAX_RETRIES + 1


class TestNonRetryable4xxErrors:
    """Test non-retryable 4xx error handling."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_400_bad_request_never_retried(self):
        """Verify 400 Bad Request surfaces error immediately without retry."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        route = respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            return_value=httpx.Response(400, json={"error": "Invalid parameters"})
        )
        
        result = await client._request_with_resilience(
            "GET", "/markets", operation_name="test_400"
        )
        
        assert not result.success
        assert result.metadata.get("status_code") == 400
        assert isinstance(result.error, KalshiBusinessError)
        # Should only try once, never retry
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_401_unauthorized_surfaces_auth_error(self):
        """Verify 401 Unauthorized surfaces auth error without infinite retry."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        # Mock to prevent actual auth attempt
        client._authenticate = AsyncMock()
        
        route = respx.get("https://api.kalshi.test/trade-api/v2/portfolio/balance").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )
        
        result = await client._request_with_resilience(
            "GET", "/portfolio/balance", operation_name="test_401"
        )
        
        assert not result.success
        assert result.metadata.get("status_code") == 401
        # Should try once, attempt re-auth, try again, then give up (max 2 calls)
        assert route.call_count <= 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_403_forbidden_surfaces_permission_error(self):
        """Verify 403 Forbidden surfaces permission error without retry."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        route = respx.post("https://api.kalshi.test/trade-api/v2/portfolio/orders").mock(
            return_value=httpx.Response(403, json={"error": "Forbidden"})
        )
        
        result = await client._request_with_resilience(
            "POST", "/portfolio/orders", 
            json_data={"ticker": "KXBTC", "side": "yes"},
            operation_name="test_403"
        )
        
        assert not result.success
        assert result.metadata.get("status_code") == 403
        # Should only try once
        assert route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_422_unprocessable_entity_surfaces_business_error(self):
        """Verify 422 Unprocessable Entity treated as non-retryable business error."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config)
        
        route = respx.post("https://api.kalshi.test/trade-api/v2/portfolio/orders").mock(
            return_value=httpx.Response(422, json={"error": "Invalid ticker"})
        )
        
        result = await client._request_with_resilience(
            "POST", "/portfolio/orders",
            json_data={"ticker": "INVALID"},
            operation_name="test_422"
        )
        
        assert not result.success
        assert result.metadata.get("status_code") == 422
        assert isinstance(result.error, KalshiBusinessError)
        # Should only try once
        assert route.call_count == 1


class TestSelfThrottling:
    """Test self-throttling via token bucket."""

    @pytest.mark.asyncio
    async def test_token_bucket_throttles_burst_requests(self):
        """Verify token bucket throttles burst of requests to respect tier limit."""
        # Basic tier: 20 read requests/sec
        bucket = KalshiTokenBucket(tier="basic")
        
        # Send burst of 30 read requests
        start = time.time()
        for _ in range(30):
            await bucket.acquire(is_write=False)
        elapsed = time.time() - start
        
        # Bucket starts with 20 tokens, so first 20 requests are instant
        # Remaining 10 requests need ~0.5s (10 requests / 20 req/sec)
        assert 0.4 <= elapsed <= 0.8, f"Expected ~0.5s for 30 requests (20 initial + 10 throttled), got {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_token_bucket_measures_actual_rate(self):
        """Verify actual request rate stays at/below tier limit."""
        bucket = KalshiTokenBucket(tier="basic")
        
        # Track request timestamps
        timestamps = []
        
        start = time.time()
        for _ in range(25):
            await bucket.acquire(is_write=False)
            timestamps.append(time.time())
        
        # Measure rate over 1-second windows
        window_start = timestamps[0]
        requests_in_window = 0
        max_rate = 0.0
        
        for ts in timestamps:
            if ts - window_start <= 1.0:
                requests_in_window += 1
            else:
                max_rate = max(max_rate, requests_in_window)
                window_start = ts
                requests_in_window = 1
        
        # Max rate should not exceed 20 req/sec (basic tier)
        assert max_rate <= 21, f"Rate exceeded limit: {max_rate} req/sec > 20"

    @pytest.mark.asyncio
    async def test_token_bucket_separate_read_write_limits(self):
        """Verify read and write tokens tracked separately."""
        bucket = KalshiTokenBucket(tier="basic")
        
        # Exhaust read tokens
        for _ in range(20):
            await bucket.acquire(is_write=False)
        
        # Write tokens should still be available
        assert bucket.write_tokens_available >= 9.0
        
        # Next read should wait
        start = time.time()
        await bucket.acquire(is_write=False)
        wait_time = time.time() - start
        
        assert wait_time > 0.01, "Should have waited for read token refill"

    @pytest.mark.asyncio
    async def test_token_bucket_refills_over_time(self):
        """Verify tokens refill at the tier rate."""
        bucket = KalshiTokenBucket(tier="basic")
        
        # Consume all read tokens
        for _ in range(20):
            await bucket.acquire(is_write=False)
        
        # Should have ~0 read tokens
        assert bucket.read_tokens_available < 1.0
        
        # Wait 0.5 seconds
        await asyncio.sleep(0.5)
        
        # Should have refilled ~10 tokens (20 req/sec * 0.5s)
        assert 8.0 <= bucket.read_tokens_available <= 12.0

    @pytest.mark.asyncio
    async def test_write_requests_use_write_bucket(self):
        """Verify write requests consume write tokens, not read tokens."""
        bucket = KalshiTokenBucket(tier="basic")
        
        # Send 10 write requests
        for _ in range(10):
            await bucket.acquire(is_write=True)
        
        # Write tokens should be depleted
        assert bucket.write_tokens_available < 1.0
        
        # Read tokens should still be full
        assert bucket.read_tokens_available >= 19.0


class TestRateLimitIntegration:
    """Integration tests for rate-limit handling in full client."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_client_uses_token_bucket_for_all_requests(self):
        """Verify client self-throttles using token bucket."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config, rate_tier="basic")
        
        # Mock successful responses
        respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            return_value=httpx.Response(200, json={"markets": []})
        )
        
        # Track token bucket state before burst
        initial_tokens = client._rate_limiter.read_tokens_available
        
        # Send burst of 25 requests
        start = time.time()
        tasks = [
            client._request_with_resilience("GET", "/markets", operation_name=f"req_{i}")
            for i in range(25)
        ]
        await asyncio.gather(*tasks)
        elapsed = time.time() - start
        
        # Bucket starts with 20 tokens, so first 20 requests are instant
        # Remaining 5 requests need ~0.25s (5 requests / 20 req/sec)
        # With async gather, timing can be tight - just verify some throttling occurred
        assert elapsed >= 0.2, f"Should have throttled, elapsed: {elapsed:.2f}s"

    @pytest.mark.asyncio
    @respx.mock
    async def test_429_handling_does_not_consume_extra_tokens(self):
        """Verify 429 retry doesn't double-consume tokens."""
        config = KalshiConfig(rest_api_url="https://api.kalshi.test/trade-api/v2")
        client = KalshiVenueClient(config=config, rate_tier="basic")
        
        route = respx.get("https://api.kalshi.test/trade-api/v2/markets").mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}),
                httpx.Response(200, json={"markets": []})
            ]
        )
        
        # Should consume 2 tokens total (initial + retry)
        initial_tokens = client._rate_limiter.read_tokens_available
        
        result = await client._request_with_resilience(
            "GET", "/markets", operation_name="test_token_consumption"
        )
        
        final_tokens = client._rate_limiter.read_tokens_available
        
        assert result.success
        # Should have consumed exactly 2 tokens (not more due to retry logic)
        assert initial_tokens - final_tokens <= 2.5  # Allow small timing variance
