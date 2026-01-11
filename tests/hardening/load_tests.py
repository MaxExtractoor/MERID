"""
MERID Production Hardening - Load Tests

Tests system performance under load:
- API endpoint stress testing
- Concurrent request handling
- Memory pressure
- Event bus throughput
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import httpx

from utils.logger import get_logger

logger = get_logger("tests.hardening.load")


@dataclass
class LoadTestResult:
    """Result of a load test."""
    test_name: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    requests_per_second: float
    duration_seconds: float
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": self.successful_requests / max(1, self.total_requests) * 100,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "requests_per_second": self.requests_per_second,
            "duration_seconds": self.duration_seconds,
            "error_count": len(self.errors),
        }


class APILoadTester:
    """
    Load tests API endpoints.
    """
    
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        return self
    
    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()
    
    async def _make_request(self, endpoint: str) -> Tuple[bool, float, Optional[str]]:
        """Make a single request and return (success, latency_ms, error)."""
        start = time.time()
        try:
            response = await self._client.get(f"{self.base_url}{endpoint}")
            latency = (time.time() - start) * 1000
            if response.status_code == 200:
                return True, latency, None
            else:
                return False, latency, f"HTTP {response.status_code}"
        except Exception as e:
            latency = (time.time() - start) * 1000
            return False, latency, str(e)
    
    async def load_test_endpoint(
        self,
        endpoint: str,
        num_requests: int = 100,
        concurrency: int = 10,
    ) -> LoadTestResult:
        """Load test a single endpoint."""
        start_time = time.time()
        latencies = []
        errors = []
        successful = 0
        failed = 0
        
        semaphore = asyncio.Semaphore(concurrency)
        
        async def bounded_request():
            nonlocal successful, failed
            async with semaphore:
                success, latency, error = await self._make_request(endpoint)
                latencies.append(latency)
                if success:
                    successful += 1
                else:
                    failed += 1
                    if error:
                        errors.append(error)
        
        # Run all requests
        tasks = [bounded_request() for _ in range(num_requests)]
        await asyncio.gather(*tasks)
        
        duration = time.time() - start_time
        
        # Calculate percentiles
        sorted_latencies = sorted(latencies)
        p50_idx = int(len(sorted_latencies) * 0.50)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)
        
        return LoadTestResult(
            test_name=f"load_test_{endpoint.replace('/', '_')}",
            total_requests=num_requests,
            successful_requests=successful,
            failed_requests=failed,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0,
            p50_latency_ms=sorted_latencies[p50_idx] if sorted_latencies else 0,
            p95_latency_ms=sorted_latencies[p95_idx] if sorted_latencies else 0,
            p99_latency_ms=sorted_latencies[p99_idx] if sorted_latencies else 0,
            requests_per_second=num_requests / duration if duration > 0 else 0,
            duration_seconds=duration,
            errors=errors[:10],  # Keep first 10 errors
        )
    
    async def run_standard_load_tests(self) -> List[LoadTestResult]:
        """Run load tests on standard endpoints."""
        endpoints = [
            "/api/v1/health",
            "/api/v1/treasury/status",
            "/api/v1/recovery/status",
            "/api/v1/sniping/status",
            "/api/v1/monitoring/dashboard",
            "/api/v1/institutional/intelligence/signals",
        ]
        
        results = []
        for endpoint in endpoints:
            logger.info("Load testing %s...", endpoint)
            result = await self.load_test_endpoint(
                endpoint,
                num_requests=50,
                concurrency=5,
            )
            results.append(result)
            logger.info(
                "  %d/%d successful, avg %.1fms, %.1f req/s",
                result.successful_requests,
                result.total_requests,
                result.avg_latency_ms,
                result.requests_per_second,
            )
        
        return results


class EventBusThroughputTester:
    """
    Tests event bus throughput.
    """
    
    async def test_event_throughput(
        self,
        num_events: int = 1000,
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """Test event bus throughput."""
        try:
            from core.streaming_bus import get_streaming_bus, StreamEvent
            
            bus = get_streaming_bus()
            start = time.time()
            
            events_published = 0
            for batch in range(num_events // batch_size):
                for i in range(batch_size):
                    event = StreamEvent(
                        channel="test",
                        event_type="throughput_test",
                        data={"batch": batch, "index": i},
                        source="load_test",
                    )
                    await bus.publish(event)
                    events_published += 1
            
            duration = time.time() - start
            
            return {
                "test_name": "event_bus_throughput",
                "events_published": events_published,
                "duration_seconds": duration,
                "events_per_second": events_published / duration if duration > 0 else 0,
                "passed": True,
            }
        except Exception as e:
            return {
                "test_name": "event_bus_throughput",
                "passed": False,
                "error": str(e),
            }


class MemoryPressureTester:
    """
    Tests system behavior under memory pressure.
    """
    
    async def test_large_payload_handling(self) -> Dict[str, Any]:
        """Test handling of large payloads."""
        try:
            # Create increasingly large payloads
            sizes = [1_000, 10_000, 100_000, 1_000_000]
            results = []
            
            for size in sizes:
                payload = "x" * size
                start = time.time()
                
                # Simulate processing
                processed = len(payload)
                del payload
                
                duration = (time.time() - start) * 1000
                results.append({
                    "size_bytes": size,
                    "processing_ms": duration,
                })
            
            return {
                "test_name": "large_payload_handling",
                "results": results,
                "passed": True,
            }
        except MemoryError:
            return {
                "test_name": "large_payload_handling",
                "passed": False,
                "error": "MemoryError",
            }
    
    async def test_concurrent_allocations(self) -> Dict[str, Any]:
        """Test concurrent memory allocations."""
        try:
            async def allocate_and_free():
                data = [i for i in range(10000)]
                await asyncio.sleep(0.01)
                return len(data)
            
            start = time.time()
            tasks = [allocate_and_free() for _ in range(100)]
            results = await asyncio.gather(*tasks)
            duration = time.time() - start
            
            return {
                "test_name": "concurrent_allocations",
                "allocations": len(results),
                "duration_seconds": duration,
                "passed": True,
            }
        except Exception as e:
            return {
                "test_name": "concurrent_allocations",
                "passed": False,
                "error": str(e),
            }


class LoadTestRunner:
    """
    Runs all load tests.
    """
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all load tests."""
        start = time.time()
        results = {
            "api_load_tests": [],
            "event_bus_tests": [],
            "memory_tests": [],
        }
        
        # API Load Tests
        logger.info("Running API load tests...")
        async with APILoadTester() as tester:
            api_results = await tester.run_standard_load_tests()
            results["api_load_tests"] = [r.to_dict() for r in api_results]
        
        # Event Bus Tests
        logger.info("Running event bus throughput tests...")
        event_tester = EventBusThroughputTester()
        results["event_bus_tests"].append(
            await event_tester.test_event_throughput(num_events=500)
        )
        
        # Memory Tests
        logger.info("Running memory pressure tests...")
        memory_tester = MemoryPressureTester()
        results["memory_tests"].append(
            await memory_tester.test_large_payload_handling()
        )
        results["memory_tests"].append(
            await memory_tester.test_concurrent_allocations()
        )
        
        # Summary
        api_passed = sum(1 for r in results["api_load_tests"] if r["success_rate"] > 95)
        api_total = len(results["api_load_tests"])
        
        results["summary"] = {
            "duration_seconds": time.time() - start,
            "api_tests_passed": f"{api_passed}/{api_total}",
            "event_bus_passed": all(r.get("passed", False) for r in results["event_bus_tests"]),
            "memory_tests_passed": all(r.get("passed", False) for r in results["memory_tests"]),
        }
        
        logger.info("Load tests complete in %.1fs", results["summary"]["duration_seconds"])
        
        return results


async def run_load_tests() -> Dict[str, Any]:
    """Entry point for running load tests."""
    runner = LoadTestRunner()
    return await runner.run_all_tests()


# Need this import for type hint
from typing import Tuple


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(run_load_tests())
    print(f"\nLoad Test Summary:")
    print(f"  API Tests: {result['summary']['api_tests_passed']}")
    print(f"  Event Bus: {'PASS' if result['summary']['event_bus_passed'] else 'FAIL'}")
    print(f"  Memory: {'PASS' if result['summary']['memory_tests_passed'] else 'FAIL'}")
