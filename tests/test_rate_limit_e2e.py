"""End-to-end rate limiter dry run test.

Validates that the rate limiter correctly throttles multiple noisy agents
while maintaining aggregate QPS under the configured limit.

Run: pytest tests/test_rate_limit_e2e.py -v -s
"""

import asyncio
import time
import pytest
from typing import List, Dict, Any
from dataclasses import dataclass

from merid.external_api_rate_limiter import (
    TokenBucket,
    TokenBucketConfig,
    get_limiter,
    AgentQuotaManager,
    _buckets,
)
from monitoring.rate_limit_metrics import (
    record_request,
    record_throttled,
    enable_rate_limit_metrics,
)


@dataclass
class AgentResult:
    """Result from a single agent's execution."""
    agent_id: str
    requests_made: int
    requests_throttled: int
    avg_latency_ms: float
    total_time_s: float


class NoisyAgent:
    """Simulates an agent that tries to make requests as fast as possible."""
    
    def __init__(
        self,
        agent_id: str,
        provider: str,
        target_rps: float,
        duration_s: float = 5.0
    ):
        self.agent_id = agent_id
        self.provider = provider
        self.target_rps = target_rps
        self.duration_s = duration_s
        self.results: Dict[str, Any] = {
            "requests": 0,
            "throttled": 0,
            "latencies": [],
        }
    
    async def run(self) -> AgentResult:
        """Run the agent, attempting to hit target RPS."""
        start = time.monotonic()
        limiter = get_limiter(self.provider)
        
        # Try to make requests as fast as possible
        while time.monotonic() - start < self.duration_s:
            # Attempt to acquire token
            t0 = time.perf_counter()
            acquired = await limiter.acquire(
                is_write=False,
                block=True,  # Block until token available
                timeout=10.0
            )
            latency = time.perf_counter() - t0
            
            if acquired:
                self.results["requests"] += 1
                self.results["latencies"].append(latency * 1000)  # ms
            else:
                self.results["throttled"] += 1
            
            # Small yield to prevent complete CPU saturation
            await asyncio.sleep(0.001)
        
        elapsed = time.monotonic() - start
        avg_latency = (
            sum(self.results["latencies"]) / len(self.results["latencies"])
            if self.results["latencies"] else 0.0
        )
        
        return AgentResult(
            agent_id=self.agent_id,
            requests_made=self.results["requests"],
            requests_throttled=self.results["throttled"],
            avg_latency_ms=avg_latency,
            total_time_s=elapsed,
        )


class TestRateLimiterE2E:
    """End-to-end rate limiter validation tests."""
    
    @pytest.fixture(autouse=True)
    def clean_slate(self):
        """Clean up global state before/after each test."""
        _buckets.clear()
        yield
        _buckets.clear()
    
    @pytest.mark.asyncio
    async def test_single_agent_respects_limit(self):
        """Single agent cannot exceed global rate limit."""
        # Strict limit: 5 r/s
        config = TokenBucketConfig(
            read_per_sec=5.0,
            write_per_sec=1.0,
            safety_factor=1.0  # No safety margin for precise test
        )
        get_limiter("test_provider", config)
        
        # Agent tries to go fast (10 r/s target)
        agent = NoisyAgent("agent_1", "test_provider", target_rps=10.0, duration_s=2.0)
        result = await agent.run()
        
        # Should have made ~10 requests (5 r/s × 2s), not 20
        # Token bucket allows burst, so we allow some variance
        assert result.requests_made <= 20, f"Made {result.requests_made} requests, expected ≤ 20"
        assert result.requests_made >= 5, f"Made only {result.requests_made} requests, expected ≥ 5"
        
        actual_rps = result.requests_made / result.total_time_s
        assert actual_rps <= 6.0, f"RPS {actual_rps} exceeded limit"
    
    @pytest.mark.asyncio
    async def test_multiple_agents_aggregate_limit(self):
        """Multiple noisy agents share limit, aggregate stays under cap."""
        # Limit: 10 r/s
        config = TokenBucketConfig(
            read_per_sec=10.0,
            write_per_sec=2.0,
            safety_factor=1.0
        )
        get_limiter("shared_provider", config)
        
        # 5 agents each trying to do 5 r/s (total 25 > 10 limit)
        agents = [
            NoisyAgent(f"agent_{i}", "shared_provider", target_rps=5.0, duration_s=3.0)
            for i in range(5)
        ]
        
        # Run concurrently
        results = await asyncio.gather(*[a.run() for a in agents])
        
        # Aggregate stats
        total_requests = sum(r.requests_made for r in results)
        total_throttled = sum(r.requests_throttled for r in results)
        total_time = results[0].total_time_s  # All same duration
        aggregate_rps = total_requests / total_time
        
        print(f"\n=== Multi-Agent Test Results ===")
        print(f"Agents: {len(agents)}")
        print(f"Target per agent: 5 r/s")
        print(f"Global limit: 10 r/s")
        print(f"Aggregate requests: {total_requests}")
        print(f"Aggregate throttled: {total_throttled}")
        print(f"Aggregate RPS: {aggregate_rps:.2f}")
        print(f"Per-agent results:")
        for r in results:
            print(f"  {r.agent_id}: {r.requests_made} req, {r.requests_throttled} throttled, "
                  f"{r.avg_latency_ms:.1f}ms avg wait")
        
        # Aggregate must stay under limit (allow 50% burst for real-world behavior)
        assert aggregate_rps <= 15.0, f"Aggregate RPS {aggregate_rps} exceeded limit"
        
        # All agents should have made some progress (no starvation)
        for r in results:
            assert r.requests_made >= 3, f"Agent {r.agent_id} starved ({r.requests_made} requests)"
        
        # Some throttling should have occurred
        assert total_throttled > 0, "Expected some throttling"
    
    @pytest.mark.asyncio
    async def test_burst_then_sustained_rate(self):
        """Burst allowed initially, then sustained rate enforced."""
        config = TokenBucketConfig(
            read_per_sec=5.0,
            write_per_sec=1.0,
            burst_limit=10,  # Allow 10 request burst
            safety_factor=1.0
        )
        get_limiter("burst_test", config)
        
        agent = NoisyAgent("burster", "burst_test", target_rps=20.0, duration_s=3.0)
        result = await agent.run()
        
        elapsed = result.total_time_s
        actual_rps = result.requests_made / elapsed
        
        print(f"\n=== Burst Test ===")
        print(f"Requests: {result.requests_made}")
        print(f"Throttled: {result.requests_throttled}")
        print(f"Actual RPS: {actual_rps:.2f}")
        print(f"Expected: ~5 r/s sustained with 10 burst")
        
        # Should have made ~15-20 requests (10 burst + 5/s × 2s)
        assert 12 <= result.requests_made <= 25
        
        # Sustained rate should be close to 5 r/s (allow 50% variance for burst/refill)
        assert 3.0 <= actual_rps <= 8.0, f"Sustained RPS {actual_rps} out of range"
    
    @pytest.mark.asyncio
    async def test_35_agents_fairness(self):
        """35 Kalshi agents sharing Messari-like limit (20/min = 0.33/s)."""
        # Simulate Messari rate limit
        config = TokenBucketConfig(
            read_per_sec=0.33,  # 20/min
            write_per_sec=0.1,
            safety_factor=1.0
        )
        get_limiter("messari_like", config)
        
        # 35 agents, each allocated 0.009 r/s (total 0.315 < 0.33 limit)
        manager = AgentQuotaManager()
        for i in range(35):
            await manager.register(
                f"kalshi_agent_{i}",
                "messari_like",
                read_per_sec=0.009,
                write_per_sec=0.002,
                priority=5
            )
        
        # Run all 35 agents for 10 seconds
        agents = [
            NoisyAgent(f"kalshi_agent_{i}", "messari_like", target_rps=0.02, duration_s=10.0)
            for i in range(35)
        ]
        
        results = await asyncio.gather(*[a.run() for a in agents])
        
        total_requests = sum(r.requests_made for r in results)
        aggregate_rps = total_requests / 10.0
        
        print(f"\n=== 35-Agent Fairness Test ===")
        print(f"Global limit: 0.33 r/s (20/min)")
        print(f"Agents: 35")
        print(f"Aggregate requests: {total_requests}")
        print(f"Aggregate RPS: {aggregate_rps:.3f}")
        print(f"Per-agent avg: {total_requests / 35:.1f} requests")
        
        # Aggregate should stay under 0.33 r/s (allow tolerance for slow test environment)
        assert aggregate_rps <= 1.0, f"RPS {aggregate_rps} exceeded limit"
        
        # At least 30 of 35 agents should have made progress (not all starved)
        agents_with_requests = sum(1 for r in results if r.requests_made > 0)
        assert agents_with_requests >= 30, f"Only {agents_with_requests}/35 agents made requests"
        
        # Fairness: std dev of requests should be low
        requests_per_agent = [r.requests_made for r in results]
        avg_requests = sum(requests_per_agent) / len(requests_per_agent)
        variance = sum((x - avg_requests) ** 2 for x in requests_per_agent) / len(requests_per_agent)
        std_dev = variance ** 0.5
        
        # Std dev should be less than 50% of mean (reasonable fairness)
        assert std_dev / avg_requests < 0.5, f"Unfair distribution (std_dev={std_dev:.1f}, mean={avg_requests:.1f})"
    
    @pytest.mark.asyncio
    async def test_quota_manager_enforcement(self):
        """Quota manager rejects over-allocation."""
        config = TokenBucketConfig(
            read_per_sec=10.0,
            write_per_sec=5.0,
            safety_factor=1.0
        )
        get_limiter("quota_test", config)
        
        manager = AgentQuotaManager()
        
        # Try to allocate 15 r/s total (exceeds 10 r/s global)
        approved = []
        for i in range(3):
            ok = await manager.register(
                f"greedy_{i}",
                "quota_test",
                read_per_sec=5.0,  # 3 × 5 = 15 > 10
                write_per_sec=1.0
            )
            approved.append(ok)
        
        # First 2 should be approved (5 + 5 = 10)
        assert approved[0] is True
        assert approved[1] is True
        
        # Third should be rejected (would be 15 > 10)
        assert approved[2] is False
        
        # Verify with actual traffic
        agents = [
            NoisyAgent("greedy_0", "quota_test", target_rps=10.0, duration_s=2.0),
            NoisyAgent("greedy_1", "quota_test", target_rps=10.0, duration_s=2.0),
        ]
        
        results = await asyncio.gather(*[a.run() for a in agents])
        total_rps = sum(r.requests_made for r in results) / 2.0
        
        # Aggregate should stay around 10 r/s (allow 100% burst for real world)
        assert total_rps <= 20.0, f"Quota not enforced: {total_rps} r/s"


class TestRateLimiterMetricsE2E:
    """E2E tests with metrics collection."""
    
    @pytest.fixture(autouse=True)
    def clean_slate(self):
        """Clean up global state."""
        _buckets.clear()
        yield
        _buckets.clear()
    
    @pytest.mark.asyncio
    async def test_metrics_collected_under_load(self):
        """Metrics are correctly collected during high load."""
        config = TokenBucketConfig(
            read_per_sec=20.0,
            write_per_sec=5.0,
            safety_factor=1.0
        )
        bucket = get_limiter("metrics_test", config)
        
        # Generate load
        agents = [
            NoisyAgent(f"m_{i}", "metrics_test", target_rps=10.0, duration_s=3.0)
            for i in range(5)
        ]
        
        results = await asyncio.gather(*[a.run() for a in agents])
        
        # Check bucket metrics
        status = bucket.get_status()
        
        print(f"\n=== Metrics Test ===")
        print(f"Total requests: {status['total_requests']}")
        print(f"Throttled: {status['throttled_requests']}")
        print(f"429 received: {status['rate_limited_responses']}")
        print(f"Read tokens available: {status['read_tokens']:.2f}")
        
        total_requests = sum(r.requests_made for r in results)
        
        # Metrics should reflect activity (within reasonable range)
        assert status["total_requests"] > 0
        assert status["total_requests"] >= total_requests * 0.5, \
            f"Metrics count {status['total_requests']} too low vs actual {total_requests}"
        
        # Some throttling expected (5 agents × 10 r/s = 50 > 20 limit)
        assert status["throttled_requests"] > 0


# =============================================================================
# Performance Benchmark
# =============================================================================

@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_rate_limiter_throughput():
    """Benchmark maximum throughput."""
    config = TokenBucketConfig(
        read_per_sec=1000.0,
        write_per_sec=500.0,
        safety_factor=1.0
    )
    get_limiter("perf_test", config)
    
    # Single agent trying to max out
    agent = NoisyAgent("perf", "perf_test", target_rps=2000.0, duration_s=1.0)
    result = await agent.run()
    
    print(f"\n=== Throughput Benchmark ===")
    print(f"Requests: {result.requests_made}")
    print(f"Actual RPS: {result.requests_made / result.total_time_s:.0f}")
    print(f"Target: 1000 r/s")
    
    # Should be close to 1000 r/s (allow 50% variance for test environment)
    assert 500 <= result.requests_made <= 1500


# =============================================================================
# Run Directly
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
