"""Performance benchmarking for Kalshi API.

Benchmarks latency and throughput for all major endpoints.
Usage:
    python scripts/benchmark_kalshi_api.py --duration 60 --output results.json
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin

import aiohttp


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    endpoint: str
    method: str
    latency_ms: float
    status_code: int
    success: bool
    timestamp: float
    error: Optional[str] = None


@dataclass
class EndpointStats:
    """Aggregated statistics for an endpoint."""
    endpoint: str
    method: str
    count: int = 0
    successes: int = 0
    failures: int = 0
    latencies: List[float] = field(default_factory=list)
    errors: Dict[str, int] = field(default_factory=dict)

    def add_result(self, result: BenchmarkResult) -> None:
        """Add a benchmark result."""
        self.count += 1
        if result.success:
            self.successes += 1
            self.latencies.append(result.latency_ms)
        else:
            self.failures += 1
            error_type = result.error or "unknown"
            self.errors[error_type] = self.errors.get(error_type, 0) + 1

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        if not self.latencies:
            return {
                "endpoint": self.endpoint,
                "method": self.method,
                "count": self.count,
                "success_rate": 0.0,
                "latency_ms": {"min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0},
                "errors": self.errors,
            }

        sorted_latencies = sorted(self.latencies)
        n = len(sorted_latencies)

        return {
            "endpoint": self.endpoint,
            "method": self.method,
            "count": self.count,
            "success_rate": self.successes / self.count,
            "latency_ms": {
                "min": round(min(sorted_latencies), 2),
                "max": round(max(sorted_latencies), 2),
                "avg": round(statistics.mean(sorted_latencies), 2),
                "p50": round(sorted_latencies[int(n * 0.5)], 2),
                "p95": round(sorted_latencies[int(n * 0.95)], 2),
                "p99": round(sorted_latencies[int(n * 0.99)], 2) if n >= 100 else round(max(sorted_latencies), 2),
            },
            "errors": self.errors,
        }


class KalshiAPIBenchmark:
    """Benchmark runner for Kalshi API."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[BenchmarkResult] = []

    async def benchmark_endpoint(
        self,
        session: aiohttp.ClientSession,
        method: str,
        endpoint: str,
        iterations: int = 100,
        payload: Optional[Dict] = None,
    ) -> EndpointStats:
        """Benchmark a single endpoint."""
        stats = EndpointStats(endpoint=endpoint, method=method)
        url = urljoin(self.base_url, f"/api/v1/kalshi{endpoint}")

        for _ in range(iterations):
            start = time.perf_counter()
            error = None
            status_code = 0
            success = False

            try:
                if method == "GET":
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        status_code = resp.status
                        success = 200 <= status_code < 500  # 4xx is still success for benchmark
                        await resp.text()
                elif method == "POST":
                    async with session.post(
                        url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        status_code = resp.status
                        success = 200 <= status_code < 500
                        await resp.text()

            except asyncio.TimeoutError:
                error = "timeout"
            except aiohttp.ClientError as e:
                error = f"client_error: {type(e).__name__}"
            except Exception as e:
                error = f"error: {type(e).__name__}"

            latency_ms = (time.perf_counter() - start) * 1000

            result = BenchmarkResult(
                endpoint=endpoint,
                method=method,
                latency_ms=latency_ms,
                status_code=status_code,
                success=success and error is None,
                timestamp=time.time(),
                error=error,
            )
            stats.add_result(result)
            self.results.append(result)

            # Small delay between requests
            await asyncio.sleep(0.01)

        return stats

    async def run_benchmarks(self, duration_seconds: int = 60) -> Dict:
        """Run all benchmarks."""
        print(f"Starting Kalshi API Benchmark against {self.base_url}")
        print(f"Duration: {duration_seconds} seconds")
        print("-" * 80)

        timeout = aiohttp.ClientTimeout(total=30)
        conn = aiohttp.TCPConnector(limit=100, limit_per_host=20)

        async with aiohttp.ClientSession(timeout=timeout, connector=conn) as session:
            endpoints_to_test = [
                # (method, endpoint, iterations, payload)
                ("GET", "/health", 100, None),
                ("GET", "/markets?limit=20", 50, None),
                ("GET", "/catalog", 30, None),
                ("GET", "/positions", 50, None),
                ("GET", "/orders", 50, None),
                ("GET", "/balance", 50, None),
                ("GET", "/risk", 50, None),
                ("GET", "/edge?tickers=KXBTC-24DEC-ABOVE-60000", 30, None),
                ("GET", "/sizing-metrics", 30, None),
                ("GET", "/portfolio/summary", 30, None),
                ("GET", "/portfolio/risk", 20, None),
                ("GET", "/portfolio/var", 20, None),
                ("GET", "/fills?limit=50", 30, None),
                ("GET", "/volume-changes", 20, None),
                ("GET", "/consensus-signals", 20, None),
                ("GET", "/risk/events", 30, None),
            ]

            all_stats = []
            start_time = time.time()
            iterations = 0

            while time.time() - start_time < duration_seconds:
                for method, endpoint, iters, payload in endpoints_to_test:
                    # Check time budget
                    if time.time() - start_time >= duration_seconds:
                        break

                    stats = await self.benchmark_endpoint(
                        session, method, endpoint, iters, payload
                    )
                    all_stats.append(stats)
                    iterations += iters

                    print(
                        f"{method:6} {endpoint:<50} "
                        f"count={stats.count:3} "
                        f"avg={stats.to_dict()['latency_ms']['avg']:>6.1f}ms "
                        f"p95={stats.to_dict()['latency_ms']['p95']:>6.1f}ms "
                        f"ok={stats.successes:3}"
                    )

                print("-" * 80)

            # Calculate overall stats
            total_requests = sum(s.count for s in all_stats)
            total_successes = sum(s.successes for s in all_stats)

            all_latencies = []
            for s in all_stats:
                all_latencies.extend(s.latencies)

            summary = {
                "config": {
                    "base_url": self.base_url,
                    "duration_seconds": duration_seconds,
                },
                "summary": {
                    "total_requests": total_requests,
                    "total_successes": total_successes,
                    "success_rate": total_successes / total_requests if total_requests > 0 else 0,
                    "requests_per_second": total_requests / duration_seconds,
                    "overall_latency_ms": {
                        "avg": round(statistics.mean(all_latencies), 2) if all_latencies else 0,
                        "p50": round(sorted(all_latencies)[int(len(all_latencies) * 0.5)], 2) if all_latencies else 0,
                        "p95": round(sorted(all_latencies)[int(len(all_latencies) * 0.95)], 2) if all_latencies else 0,
                        "p99": round(sorted(all_latencies)[int(len(all_latencies) * 0.99)], 2) if len(all_latencies) >= 100 else (round(max(all_latencies), 2) if all_latencies else 0),
                    },
                },
                "endpoints": [s.to_dict() for s in all_stats],
            }

            return summary


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Benchmark Kalshi API")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--duration", type=int, default=60, help="Benchmark duration in seconds")
    parser.add_argument("--output", help="Output JSON file for results")
    args = parser.parse_args()

    benchmark = KalshiAPIBenchmark(base_url=args.base_url)
    results = asyncio.run(benchmark.run_benchmarks(duration_seconds=args.duration))

    # Print summary
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"Total requests: {results['summary']['total_requests']}")
    print(f"Success rate: {results['summary']['success_rate']:.1%}")
    print(f"Requests/sec: {results['summary']['requests_per_second']:.1f}")
    print()
    print("Overall latency:")
    for metric, value in results['summary']['overall_latency_ms'].items():
        print(f"  {metric}: {value}ms")

    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
