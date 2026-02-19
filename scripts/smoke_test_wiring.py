#!/usr/bin/env python3
"""Smoke-test all key API endpoints to verify wiring.

Usage:
    python scripts/smoke_test_wiring.py [--base http://localhost:8000]

Exits 0 if all endpoints respond (any status), exit 1 if any connection fails.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from typing import List

import httpx

# ── Endpoint registry ────────────────────────────────────────────────

ENDPOINTS = [
    # Core
    ("GET", "/api/system/health", "System Health"),
    ("GET", "/api/v1/system/health", "System Health v1"),
    ("GET", "/api/v1/api/status", "API Status"),

    # Trading & Positions
    ("GET", "/api/v1/portfolio/summary", "Portfolio Summary"),
    ("GET", "/api/v1/positions", "Positions"),
    ("GET", "/api/v1/orders", "Orders"),

    # Prediction Markets
    ("GET", "/api/v1/us-compliant/prediction-markets", "Prediction Markets"),
    ("GET", "/api/v1/prediction-markets/summary", "PM Summary"),
    ("GET", "/api/v1/prediction-markets/risk", "PM Risk"),
    ("GET", "/api/v1/prediction-markets/alerts", "PM Alerts"),
    ("GET", "/api/v1/prediction-markets/venue-gate", "PM Venue Gate"),

    # Prediction Consensus
    ("GET", "/api/v1/prediction/consensus/summary", "Prediction Consensus"),
    ("GET", "/api/v1/prediction/metrics", "Prediction Metrics"),

    # Betting
    ("GET", "/api/v1/betting/overview", "Betting Overview"),
    ("GET", "/api/v1/betting/consensus/summary", "Betting Consensus"),
    ("GET", "/api/v1/betting/consensus/events", "Betting Events"),
    ("GET", "/api/v1/betting/consensus/metrics", "Betting Metrics"),

    # Cognitive
    ("GET", "/api/v1/cognitive/snapshot", "Cognitive Snapshot"),

    # Paper Trading
    ("GET", "/api/v1/paper-trading/portfolio", "Paper Portfolio"),
    ("GET", "/api/v1/paper-trading/positions", "Paper Positions"),
    ("GET", "/api/v1/paper-trading/orders", "Paper Orders"),

    # Observability
    ("GET", "/api/v1/system/observability", "Observability"),

    # Rewards
    ("GET", "/api/v1/rewards/summary", "Rewards Summary"),

    # Flow & Signal
    ("GET", "/api/v1/flow/radar", "Flow Radar"),
    ("GET", "/api/v1/signal-layer/features", "Signal Features"),
    ("GET", "/api/v1/signal-layer/snapshot", "Signal Snapshot"),

    # Loop
    ("GET", "/api/v1/loop/status", "Loop Status"),

    # Risk
    ("GET", "/api/v1/risk/metrics", "Risk Metrics"),
    ("GET", "/api/risk/pnl-summary", "Risk PnL Summary"),

    # Agents
    ("GET", "/api/v1/agents", "Agents"),
    ("GET", "/api/agents/summary", "Agents Summary"),

    # Consensus
    ("GET", "/api/v1/consensus/summary", "Consensus Summary"),
]


@dataclass
class Result:
    method: str
    path: str
    label: str
    status: int
    latency_ms: float
    ok: bool
    error: str = ""


def run_smoke(base: str, timeout: float = 10.0) -> List[Result]:
    results: List[Result] = []
    client = httpx.Client(base_url=base, timeout=timeout, follow_redirects=True)

    for method, path, label in ENDPOINTS:
        t0 = time.perf_counter()
        try:
            resp = client.request(method, path)
            latency = (time.perf_counter() - t0) * 1000
            results.append(Result(
                method=method, path=path, label=label,
                status=resp.status_code, latency_ms=round(latency, 1),
                ok=True,
            ))
        except Exception as exc:
            latency = (time.perf_counter() - t0) * 1000
            results.append(Result(
                method=method, path=path, label=label,
                status=0, latency_ms=round(latency, 1),
                ok=False, error=str(exc)[:80],
            ))

    client.close()
    return results


def print_report(results: List[Result]) -> int:
    print("\n" + "=" * 78)
    print("  MERID Wiring Smoke Test Report")
    print("=" * 78)

    passed = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)
    total = len(results)

    # Group by status
    ok_2xx = [r for r in results if r.ok and 200 <= r.status < 300]
    ok_4xx = [r for r in results if r.ok and 400 <= r.status < 500]
    ok_5xx = [r for r in results if r.ok and r.status >= 500]
    conn_fail = [r for r in results if not r.ok]

    for r in results:
        if r.ok:
            icon = "✅" if r.status < 400 else "⚠️" if r.status < 500 else "❌"
        else:
            icon = "💥"
        status_str = str(r.status) if r.ok else "ERR"
        print(f"  {icon} [{status_str:>3}] {r.latency_ms:>7.1f}ms  {r.method:4} {r.path}")
        if r.error:
            print(f"       └─ {r.error}")

    print("\n" + "-" * 78)
    print(f"  Total: {total}  |  Connected: {passed}  |  2xx: {len(ok_2xx)}  |  4xx: {len(ok_4xx)}  |  5xx: {len(ok_5xx)}  |  Conn Fail: {len(conn_fail)}")

    if conn_fail:
        print(f"\n  ⚠️  {len(conn_fail)} endpoint(s) failed to connect.")
        return 1

    print("\n  ✅ All endpoints reachable.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="MERID wiring smoke test")
    parser.add_argument("--base", default="http://localhost:8000", help="Base URL")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout (s)")
    args = parser.parse_args()

    print(f"Smoke-testing {len(ENDPOINTS)} endpoints against {args.base} ...")
    results = run_smoke(args.base, args.timeout)
    code = print_report(results)
    sys.exit(code)


if __name__ == "__main__":
    main()
