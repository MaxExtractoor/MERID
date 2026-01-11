"""
MERID Stress Test Suite.

Comprehensive stress testing for all system components.

Usage:
    python -m tests.stress_test
    python -m tests.stress_test --component api
    python -m tests.stress_test --duration 300
"""

import asyncio
import time
import random
import statistics
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
import threading

try:
    import httpx
except ImportError:
    httpx = None

from utils.logger import get_logger

logger = get_logger("tests.stress")


@dataclass
class StressTestResult:
    """Result of a stress test."""
    test_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_duration_seconds: float = 0.0
    
    latencies_ms: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def requests_per_second(self) -> float:
        if self.total_duration_seconds == 0:
            return 0.0
        return self.total_requests / self.total_duration_seconds
    
    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return statistics.mean(self.latencies_ms)
    
    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_latencies = sorted(self.latencies_ms)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    @property
    def p99_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_latencies = sorted(self.latencies_ms)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate_pct": round(self.success_rate, 2),
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "requests_per_second": round(self.requests_per_second, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "error_count": len(self.errors),
            "sample_errors": self.errors[:5],
        }


class StressTestRunner:
    """Runs stress tests against MERID components."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: Dict[str, StressTestResult] = {}
    
    async def run_api_stress_test(
        self,
        endpoint: str,
        method: str = "GET",
        concurrent_users: int = 10,
        requests_per_user: int = 100,
        payload: Optional[Dict] = None,
    ) -> StressTestResult:
        """Stress test an API endpoint."""
        result = StressTestResult(test_name=f"API:{method}:{endpoint}")
        
        if httpx is None:
            result.errors.append("httpx not installed")
            return result
        
        async def make_request(client: httpx.AsyncClient) -> tuple:
            start = time.time()
            try:
                if method == "GET":
                    response = await client.get(f"{self.base_url}{endpoint}")
                elif method == "POST":
                    response = await client.post(f"{self.base_url}{endpoint}", json=payload or {})
                else:
                    response = await client.request(method, f"{self.base_url}{endpoint}")
                
                latency = (time.time() - start) * 1000
                return response.status_code < 500, latency, None
            except Exception as e:
                latency = (time.time() - start) * 1000
                return False, latency, str(e)
        
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []
            for _ in range(concurrent_users):
                for _ in range(requests_per_user):
                    tasks.append(make_request(client))
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        result.total_duration_seconds = time.time() - start_time
        
        for resp in responses:
            result.total_requests += 1
            if isinstance(resp, Exception):
                result.failed_requests += 1
                result.errors.append(str(resp))
            else:
                success, latency, error = resp
                result.latencies_ms.append(latency)
                if success:
                    result.successful_requests += 1
                else:
                    result.failed_requests += 1
                    if error:
                        result.errors.append(error)
        
        self.results[result.test_name] = result
        return result
    
    async def run_event_bus_stress_test(
        self,
        events_count: int = 10000,
        concurrent_publishers: int = 10,
    ) -> StressTestResult:
        """Stress test the event bus."""
        result = StressTestResult(test_name="EventBus:publish")
        
        try:
            from core.event_bus import get_event_bus
            bus = get_event_bus()
        except Exception as e:
            result.errors.append(f"Failed to get event bus: {e}")
            return result
        
        events_per_publisher = events_count // concurrent_publishers
        
        async def publish_events(publisher_id: int):
            latencies = []
            successes = 0
            failures = 0
            
            for i in range(events_per_publisher):
                start = time.time()
                try:
                    await bus.publish("stress_test", {
                        "publisher": publisher_id,
                        "sequence": i,
                        "timestamp": time.time(),
                    })
                    latencies.append((time.time() - start) * 1000)
                    successes += 1
                except Exception as e:
                    latencies.append((time.time() - start) * 1000)
                    failures += 1
            
            return successes, failures, latencies
        
        start_time = time.time()
        
        tasks = [publish_events(i) for i in range(concurrent_publishers)]
        results = await asyncio.gather(*tasks)
        
        result.total_duration_seconds = time.time() - start_time
        
        for successes, failures, latencies in results:
            result.successful_requests += successes
            result.failed_requests += failures
            result.latencies_ms.extend(latencies)
            result.total_requests += successes + failures
        
        self.results[result.test_name] = result
        return result
    
    async def run_consensus_stress_test(
        self,
        proposals_count: int = 100,
    ) -> StressTestResult:
        """Stress test the consensus engine."""
        result = StressTestResult(test_name="Consensus:propose")
        
        try:
            from consensus.consensus_engine import get_consensus_engine
            engine = get_consensus_engine()
        except Exception as e:
            result.errors.append(f"Failed to get consensus engine: {e}")
            return result
        
        start_time = time.time()
        
        for i in range(proposals_count):
            start = time.time()
            try:
                proposal_id = await engine.propose({
                    "type": "stress_test",
                    "sequence": i,
                    "data": {"test": True},
                })
                result.latencies_ms.append((time.time() - start) * 1000)
                result.successful_requests += 1
            except Exception as e:
                result.latencies_ms.append((time.time() - start) * 1000)
                result.failed_requests += 1
                result.errors.append(str(e))
            
            result.total_requests += 1
        
        result.total_duration_seconds = time.time() - start_time
        self.results[result.test_name] = result
        return result
    
    async def run_rate_limiter_stress_test(
        self,
        requests_count: int = 1000,
    ) -> StressTestResult:
        """Stress test the rate limiter."""
        result = StressTestResult(test_name="RateLimiter:check")
        
        try:
            from ratelimit import get_rate_limiter
            limiter = get_rate_limiter()
        except Exception as e:
            result.errors.append(f"Failed to get rate limiter: {e}")
            return result
        
        start_time = time.time()
        
        for i in range(requests_count):
            start = time.time()
            try:
                ip = f"192.168.1.{i % 256}"
                check_result = limiter.check(ip_address=ip, endpoint="/api/test")
                result.latencies_ms.append((time.time() - start) * 1000)
                if check_result.allowed:
                    result.successful_requests += 1
                else:
                    result.failed_requests += 1
            except Exception as e:
                result.latencies_ms.append((time.time() - start) * 1000)
                result.failed_requests += 1
                result.errors.append(str(e))
            
            result.total_requests += 1
        
        result.total_duration_seconds = time.time() - start_time
        self.results[result.test_name] = result
        return result
    
    async def run_metrics_stress_test(
        self,
        metrics_count: int = 10000,
    ) -> StressTestResult:
        """Stress test the metrics collector."""
        result = StressTestResult(test_name="Metrics:record")
        
        try:
            from monitoring import get_metrics_collector
            collector = get_metrics_collector()
        except Exception as e:
            result.errors.append(f"Failed to get metrics collector: {e}")
            return result
        
        start_time = time.time()
        
        for i in range(metrics_count):
            start = time.time()
            try:
                collector.record(f"stress_test_{i % 10}", random.random() * 100)
                result.latencies_ms.append((time.time() - start) * 1000)
                result.successful_requests += 1
            except Exception as e:
                result.latencies_ms.append((time.time() - start) * 1000)
                result.failed_requests += 1
                result.errors.append(str(e))
            
            result.total_requests += 1
        
        result.total_duration_seconds = time.time() - start_time
        self.results[result.test_name] = result
        return result
    
    async def run_snapshot_stress_test(
        self,
        snapshots_count: int = 10,
    ) -> StressTestResult:
        """Stress test the snapshot manager."""
        result = StressTestResult(test_name="Snapshot:create")
        
        try:
            from backup import get_snapshot_manager
            from backup.snapshot import SnapshotType
            manager = get_snapshot_manager()
        except Exception as e:
            result.errors.append(f"Failed to get snapshot manager: {e}")
            return result
        
        start_time = time.time()
        
        for i in range(snapshots_count):
            start = time.time()
            try:
                snapshot = manager.create_snapshot(
                    snapshot_type=SnapshotType.FULL,
                    description=f"Stress test {i}",
                )
                result.latencies_ms.append((time.time() - start) * 1000)
                result.successful_requests += 1
                
                manager.delete_snapshot(snapshot.snapshot_id)
            except Exception as e:
                result.latencies_ms.append((time.time() - start) * 1000)
                result.failed_requests += 1
                result.errors.append(str(e))
            
            result.total_requests += 1
        
        result.total_duration_seconds = time.time() - start_time
        self.results[result.test_name] = result
        return result
    
    async def run_full_stress_test(self) -> Dict[str, Any]:
        """Run all stress tests."""
        print("=" * 60)
        print("MERID STRESS TEST SUITE")
        print("=" * 60)
        
        tests = [
            ("API Health Check", self.run_api_stress_test("/health", "GET", 10, 50)),
            ("API Metrics", self.run_api_stress_test("/api/v1/monitoring/metrics", "GET", 5, 20)),
            ("Event Bus", self.run_event_bus_stress_test(5000, 5)),
            ("Rate Limiter", self.run_rate_limiter_stress_test(1000)),
            ("Metrics Collector", self.run_metrics_stress_test(5000)),
            ("Snapshot Manager", self.run_snapshot_stress_test(5)),
        ]
        
        for name, test_coro in tests:
            print(f"\nRunning: {name}...")
            try:
                result = await test_coro
                print(f"  Requests: {result.total_requests}")
                print(f"  Success Rate: {result.success_rate:.1f}%")
                print(f"  RPS: {result.requests_per_second:.1f}")
                print(f"  Avg Latency: {result.avg_latency_ms:.2f}ms")
                print(f"  P95 Latency: {result.p95_latency_ms:.2f}ms")
            except Exception as e:
                print(f"  FAILED: {e}")
        
        print("\n" + "=" * 60)
        print("STRESS TEST COMPLETE")
        print("=" * 60)
        
        return {name: r.to_dict() for name, r in self.results.items()}
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all test results."""
        total_requests = sum(r.total_requests for r in self.results.values())
        total_success = sum(r.successful_requests for r in self.results.values())
        
        return {
            "total_tests": len(self.results),
            "total_requests": total_requests,
            "total_successful": total_success,
            "overall_success_rate": (total_success / total_requests * 100) if total_requests > 0 else 0,
            "results": {name: r.to_dict() for name, r in self.results.items()},
        }


async def main():
    """Run stress tests."""
    import argparse
    
    parser = argparse.ArgumentParser(description="MERID Stress Test Suite")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL")
    parser.add_argument("--component", choices=["api", "eventbus", "consensus", "ratelimit", "metrics", "snapshot", "all"], default="all")
    args = parser.parse_args()
    
    runner = StressTestRunner(base_url=args.url)
    
    if args.component == "all":
        await runner.run_full_stress_test()
    elif args.component == "api":
        await runner.run_api_stress_test("/health", "GET", 20, 100)
    elif args.component == "eventbus":
        await runner.run_event_bus_stress_test(10000, 10)
    elif args.component == "ratelimit":
        await runner.run_rate_limiter_stress_test(5000)
    elif args.component == "metrics":
        await runner.run_metrics_stress_test(10000)
    elif args.component == "snapshot":
        await runner.run_snapshot_stress_test(10)
    
    print("\nSummary:")
    import json
    print(json.dumps(runner.get_summary(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
