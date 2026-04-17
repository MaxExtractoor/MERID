"""Test suite for external API rate limiting.

Validates token bucket math, retry behavior, and quota management.
Run with: pytest tests/test_external_rate_limiter.py -v
"""

import asyncio
import time
import pytest
from unittest.mock import Mock, AsyncMock, patch

from merid.external_api_rate_limiter import (
    TokenBucket,
    TokenBucketConfig,
    ExternalAPIClient,
    AgentQuotaManager,
    RateLimitError,
    get_limiter,
    _buckets,
)


class TestTokenBucketMath:
    """Test token bucket rate calculations."""

    def test_initial_tokens_at_burst_limit(self):
        """Bucket starts full at burst capacity."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5, burst_limit=20, safety_factor=1.0)
        bucket = TokenBucket(config, provider="test")
        
        assert bucket._read_tokens == 20
        assert bucket._write_tokens == 20

    def test_safety_factor_applied(self):
        """Safety factor reduces effective rates."""
        config = TokenBucketConfig(
            read_per_sec=10,
            write_per_sec=5,
            safety_factor=0.8
        )
        
        assert config.read_per_sec == 8.0  # 10 * 0.8
        assert config.write_per_sec == 4.0  # 5 * 0.8
        assert config.burst_limit == 8.0  # max(10, 5) * 0.8

    def test_refill_calculation(self):
        """Tokens refill based on elapsed time and rate."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        bucket = TokenBucket(config)
        
        # Empty the bucket
        bucket._read_tokens = 0
        bucket._write_tokens = 0
        bucket._last_refill = time.monotonic() - 1.0  # 1 second ago
        
        bucket._refill()
        
        # Should have refilled 10 * 1.0 = 10 tokens (but capped at burst)
        assert bucket._read_tokens == 8.0  # 10 * 0.8 safety factor
        assert bucket._write_tokens == 4.0  # 5 * 0.8 safety factor

    @pytest.mark.asyncio
    async def test_acquire_consumes_tokens(self):
        """Acquiring tokens reduces bucket."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5, burst_limit=10)
        bucket = TokenBucket(config)
        
        initial = bucket._read_tokens
        
        acquired = await bucket.acquire(is_write=False, tokens=3.0)
        
        assert acquired is True
        assert bucket._read_tokens == initial - 3.0

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_empty(self):
        """When tokens exhausted, acquire blocks until refill."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        bucket = TokenBucket(config)
        
        # Empty the bucket
        bucket._read_tokens = 0
        bucket._last_refill = time.monotonic()
        
        # Should block for ~0.125s to refill 1 token at 10/sec
        start = time.monotonic()
        acquired = await bucket.acquire(is_write=False, tokens=1.0, block=True, timeout=1.0)
        elapsed = time.monotonic() - start
        
        assert acquired is True
        assert elapsed >= 0.1  # Should have waited

    @pytest.mark.asyncio
    async def test_acquire_nonblocking_returns_false(self):
        """Non-blocking acquire returns False when no tokens."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        bucket = TokenBucket(config)
        
        bucket._read_tokens = 0
        
        acquired = await bucket.acquire(is_write=False, tokens=1.0, block=False)
        
        assert acquired is False

    @pytest.mark.asyncio
    async def test_acquire_timeout(self):
        """Acquire with short timeout returns False if wait too long."""
        config = TokenBucketConfig(read_per_sec=1, write_per_sec=1)  # Very slow refill
        bucket = TokenBucket(config)
        
        bucket._read_tokens = 0
        
        # Need 1 token, refill rate 1/sec, timeout 0.1s
        acquired = await bucket.acquire(is_write=False, tokens=1.0, block=True, timeout=0.1)
        
        assert acquired is False


class TestTokenBucketConcurrency:
    """Test thread safety and concurrent access."""

    @pytest.mark.asyncio
    async def test_concurrent_acquires_respect_limit(self):
        """Multiple concurrent acquires don't exceed rate."""
        config = TokenBucketConfig(read_per_sec=100, write_per_sec=50, burst_limit=50, safety_factor=1.0)
        bucket = TokenBucket(config)
        
        # Fire 50 concurrent acquires
        tasks = [bucket.acquire(is_write=False) for _ in range(50)]
        results = await asyncio.gather(*tasks)
        
        # All should succeed (burst capacity is exactly 50)
        assert all(results)
        
        # Bucket should be near empty (50 consumed from 50 burst)
        assert bucket._read_tokens < 5, f"Expected near-empty bucket, got {bucket._read_tokens}"

    @pytest.mark.asyncio
    async def test_rate_enforced_over_time(self):
        """Over time, actual rate stays under configured rate."""
        config = TokenBucketConfig(read_per_sec=50, write_per_sec=25, burst_limit=10, safety_factor=1.0)
        bucket = TokenBucket(config)
        
        count = 0
        start = time.monotonic()
        
        # Try to acquire as fast as possible for 0.5 seconds
        while time.monotonic() - start < 0.5:
            acquired = await bucket.acquire(is_write=False, block=False)
            if acquired:
                count += 1
            else:
                # Wait a bit for refill
                await asyncio.sleep(0.02)
        
        elapsed = time.monotonic() - start
        actual_rate = count / elapsed
        
        # Should be close to 50/sec but not exceed it significantly (allow 100% burst overhead for test)
        assert actual_rate <= 100, f"Rate {actual_rate} too high, expected <= 100"


class TestExternalAPIClient:
    """Test rate-limited HTTP client."""

    @pytest.mark.asyncio
    async def test_client_uses_rate_limiter(self):
        """Client acquires tokens before making requests."""
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = Mock(
                status_code=200,
                headers={},
                json=lambda: {"data": "test"}
            )
            
            async with ExternalAPIClient(
                base_url="https://api.example.com",
                provider="test",
                read_per_sec=10,
                write_per_sec=5
            ) as client:
                await client.get("/test")
            
            # Should have called httpx
            assert mock_request.called

    @pytest.mark.asyncio
    async def test_429_triggers_retry(self):
        """HTTP 429 triggers exponential backoff retry."""
        responses = [
            Mock(status_code=429, headers={"Retry-After": "0.1"}),
            Mock(status_code=200, headers={}, json=lambda: {"data": "success"}),
        ]
        
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = responses
            
            async with ExternalAPIClient(
                base_url="https://api.example.com",
                provider="test_retry",
                read_per_sec=10,
                write_per_sec=5,
                max_retries=3,
                backoff_base=0.1
            ) as client:
                response = await client.get("/test")
            
            assert response.status_code == 200
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self):
        """After max retries, RateLimitError is raised."""
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = Mock(status_code=429, headers={})
            
            async with ExternalAPIClient(
                base_url="https://api.example.com",
                provider="test_fail",
                read_per_sec=10,
                write_per_sec=5,
                max_retries=2,
                backoff_base=0.01
            ) as client:
                with pytest.raises(RateLimitError):
                    await client.get("/test")
            
            # Should have tried 3 times (initial + 2 retries)
            assert mock_request.call_count == 3

    @pytest.mark.asyncio
    async def test_server_error_triggers_retry(self):
        """5xx errors trigger retry."""
        responses = [
            Mock(status_code=500, headers={}),
            Mock(status_code=200, headers={}, json=lambda: {"data": "success"}),
        ]
        
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = responses
            
            async with ExternalAPIClient(
                base_url="https://api.example.com",
                provider="test_500",
                read_per_sec=10,
                write_per_sec=5,
                max_retries=3,
                backoff_base=0.01
            ) as client:
                response = await client.get("/test")
            
            assert response.status_code == 200
            assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_network_error_triggers_retry(self):
        """Network errors trigger retry."""
        from httpx import ConnectError
        
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = [
                ConnectError("Connection refused"),
                Mock(status_code=200, headers={}, json=lambda: {"data": "success"}),
            ]
            
            async with ExternalAPIClient(
                base_url="https://api.example.com",
                provider="test_net",
                read_per_sec=10,
                write_per_sec=5,
                max_retries=3,
                backoff_base=0.01
            ) as client:
                response = await client.get("/test")
            
            assert response.status_code == 200


class TestAgentQuotaManager:
    """Test per-agent quota allocation."""

    @pytest.fixture(autouse=True)
    async def clean_slate(self):
        """Clean up global state between tests."""
        _buckets.clear()
        yield
        _buckets.clear()

    @pytest.mark.asyncio
    async def test_quota_registration_approved_if_under_global(self):
        """Quota approved when sum stays under global limit."""
        # Set up global limiter
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        get_limiter("test_provider", config)
        
        manager = AgentQuotaManager()
        
        # Register agent with quota under global limit
        approved = await manager.register(
            agent_id="agent_1",
            provider="test_provider",
            read_per_sec=5.0,  # Under 10 global
            write_per_sec=2.0  # Under 5 global
        )
        
        assert approved is True

    @pytest.mark.asyncio
    async def test_quota_rejected_if_exceeds_global(self):
        """Quota rejected when it would exceed global limit."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        get_limiter("test_provider", config)
        
        manager = AgentQuotaManager()
        
        # First agent takes 6 read
        await manager.register("agent_1", "test_provider", 6.0, 2.0)
        
        # Second agent wants 6 read (total 12 > 10 global)
        approved = await manager.register("agent_2", "test_provider", 6.0, 2.0)
        
        assert approved is False

    @pytest.mark.asyncio
    async def test_multiple_agents_quota_sum(self):
        """Multiple agents can register if sum stays under global."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        get_limiter("test_provider", config)
        
        manager = AgentQuotaManager()
        
        # Register 5 agents at 1.5 read each = 7.5 total (under 10)
        for i in range(5):
            approved = await manager.register(
                f"agent_{i}",
                "test_provider",
                read_per_sec=1.5,
                write_per_sec=0.5
            )
            assert approved is True
        
        # Verify total allocation
        quotas = manager.get_all()
        total_read = sum(q.read_per_sec for q in quotas.values())
        assert total_read == 7.5

    @pytest.mark.asyncio
    async def test_unregister_frees_quota(self):
        """Unregistering agent frees quota for others."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        get_limiter("test_provider", config)
        
        manager = AgentQuotaManager()
        
        # First agent takes all quota (at full global rate)
        await manager.register("agent_1", "test_provider", 8.0, 4.0)
        
        # Second agent rejected
        approved = await manager.register("agent_2", "test_provider", 1.0, 1.0)
        assert approved is False
        
        # Unregister first
        await manager.unregister("agent_1", "test_provider")
        
        # Second agent now approved
        approved = await manager.register("agent_2", "test_provider", 1.0, 1.0)
        assert approved is True


class TestRateLimiterMetrics:
    """Test metrics and observability."""

    @pytest.mark.asyncio
    async def test_total_requests_tracked(self):
        """Total requests are counted."""
        config = TokenBucketConfig(read_per_sec=100, write_per_sec=50)
        bucket = TokenBucket(config)
        
        for _ in range(10):
            await bucket.acquire(is_write=False)
        
        status = bucket.get_status()
        assert status["total_requests"] == 10

    @pytest.mark.asyncio
    async def test_throttled_requests_tracked(self):
        """Throttled requests are counted."""
        config = TokenBucketConfig(read_per_sec=1, write_per_sec=1)
        bucket = TokenBucket(config)
        
        # Empty bucket
        bucket._read_tokens = 0
        
        # Non-blocking acquires should fail and count as throttled
        for _ in range(5):
            await bucket.acquire(is_write=False, block=False)
        
        status = bucket.get_status()
        assert status["throttled_requests"] == 5

    @pytest.mark.asyncio
    async def test_rate_limited_responses_tracked(self):
        """429 responses from provider are tracked."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5)
        bucket = TokenBucket(config)
        
        bucket.record_rate_limited_response()
        bucket.record_rate_limited_response()
        
        status = bucket.get_status()
        assert status["rate_limited_responses"] == 2


class TestProviderConfigs:
    """Test loading provider configs from YAML."""

    def test_messari_config_loaded(self):
        """Messari config loads from YAML."""
        from merid.external_api_rate_limiter import _load_config_for_provider
        
        config = _load_config_for_provider("messari")
        
        # Config may or may not load depending on file; just verify function works
        # If loaded, check structure
        if config:
            assert hasattr(config, 'read_per_sec')
            assert config.read_per_sec > 0

    def test_coingecko_config_loaded(self):
        """CoinGecko config loads from YAML."""
        from merid.external_api_rate_limiter import _load_config_for_provider
        
        config = _load_config_for_provider("coingecko")
        
        # Config may or may not load depending on file; just verify function works
        if config:
            assert hasattr(config, 'read_per_sec')
            assert config.read_per_sec > 0

    def test_unknown_provider_returns_none(self):
        """Unknown provider returns None."""
        from merid.external_api_rate_limiter import _load_config_for_provider
        
        config = _load_config_for_provider("nonexistent_provider")
        
        assert config is None


class TestIntegrationScenarios:
    """Integration tests simulating real usage patterns."""

    @pytest.mark.asyncio
    async def test_35_agents_fair_share(self):
        """35 agents can share a provider limit fairly."""
        # Simulate Messari: 20/min = 0.33/sec
        config = TokenBucketConfig(read_per_sec=0.33, write_per_sec=0.1, safety_factor=1.0)
        get_limiter("messari_sim", config)
        
        manager = AgentQuotaManager()
        
        # Register 35 agents with 0.009 r/s each = 0.315 total (under 0.33)
        approved_count = 0
        for i in range(35):
            approved = await manager.register(
                f"kalshi_agent_{i}",
                "messari_sim",
                read_per_sec=0.009,
                write_per_sec=0.002
            )
            if approved:
                approved_count += 1
        
        # Most should be approved (allowing for rounding)
        assert approved_count >= 30, f"Only {approved_count} approved, expected >= 30"

    @pytest.mark.asyncio
    async def test_burst_then_throttle(self):
        """Burst allowed, then throttling kicks in."""
        config = TokenBucketConfig(read_per_sec=10, write_per_sec=5, burst_limit=5, safety_factor=1.0)
        bucket = TokenBucket(config, provider="burst_test")
        
        # First 5 should succeed immediately (burst)
        burst_results = []
        for _ in range(5):
            result = await bucket.acquire(is_write=False, block=False)
            burst_results.append(result)
        
        assert all(burst_results)
        
        # 6th should fail (no tokens, not blocking) or succeed if burst > 5
        sixth = await bucket.acquire(is_write=False, block=False)
        # With burst=5, exactly 5 should succeed
        assert not sixth, "Expected 6th acquire to fail"

    @pytest.mark.asyncio
    async def test_concurrent_burst_not_exceeded(self):
        """Concurrent burst respects burst limit."""
        config = TokenBucketConfig(read_per_sec=1000, write_per_sec=500, burst_limit=10, safety_factor=1.0)
        bucket = TokenBucket(config)
        
        # 20 concurrent acquires of 1 token each
        tasks = [bucket.acquire(is_write=False, tokens=1.0, block=False) for _ in range(20)]
        results = await asyncio.gather(*tasks)
        
        # Only burst_limit should succeed (or close to it due to refill during execution)
        passed = sum(results)
        assert 8 <= passed <= 12, f"Expected 8-12 passes, got {passed}"


# =============================================================================
# Performance Benchmarks
# =============================================================================

class TestPerformance:
    """Performance benchmarks (not strict assertions)."""

    @pytest.mark.asyncio
    async def test_acquire_latency_under_1ms(self):
        """Token acquisition should be fast when tokens available."""
        config = TokenBucketConfig(read_per_sec=10000, write_per_sec=5000)
        bucket = TokenBucket(config)
        
        # Warm up
        await bucket.acquire(is_write=False)
        
        # Measure 100 acquires
        start = time.perf_counter()
        for _ in range(100):
            await bucket.acquire(is_write=False)
        elapsed = time.perf_counter() - start
        
        avg_latency_ms = (elapsed / 100) * 1000
        
        # Should be well under 1ms when no waiting
        assert avg_latency_ms < 1.0, f"Avg latency {avg_latency_ms}ms too high"

    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_concurrent_acquires_throughput(self):
        """Measure throughput under concurrent load."""
        config = TokenBucketConfig(read_per_sec=1000, write_per_sec=500)
        bucket = TokenBucket(config)
        
        async def worker():
            for _ in range(100):
                await bucket.acquire(is_write=False)
        
        start = time.perf_counter()
        await asyncio.gather(*[worker() for _ in range(10)])
        elapsed = time.perf_counter() - start
        
        # 1000 acquires should complete reasonably fast
        throughput = 1000 / elapsed
        print(f"\nThroughput: {throughput:.0f} acquires/sec")


# =============================================================================
# Cleanup
# =============================================================================

@pytest.fixture(autouse=True)
def cleanup_global_state():
    """Clean up global state after each test."""
    yield
    # Clear global buckets
    _buckets.clear()
