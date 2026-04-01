#!/usr/bin/env python3
"""
MERID 30-Minute Paper Gate Runner
===================================
Polls /health/event_loop every ~30 seconds for a configurable duration (default 30
minutes), records P50/P95/P99 lag and the ``degraded`` flag, then emits a gate
PASS/FAIL verdict against the criteria defined in VALIDATION_GUIDE.md:

  Gate pass criteria (all must hold for the full run):
  - P95 lag < 500 ms throughout
  - degraded=false on every sample
  - No high-lag profiles captured (samples_above_crit == 0)
  - No crashes / missed heartbeats (all HTTP polls succeed)

Usage:
    # Default: 30-minute gate against local server
    python scripts/run_paper_gate.py

    # Custom duration and server
    python scripts/run_paper_gate.py --duration 5 --base-url http://localhost:8000

    # Write results to a JSON file (for CI / fix_history appending)
    python scripts/run_paper_gate.py --output reports/paper_gate_1.json

    # Dry-run (validate imports and config only)
    python scripts/run_paper_gate.py --dry-run

Environment:
    MERID_TRADE_MODE=paper           must be set before starting the server
    MERID_ALLOW_LIVE_TRADES=false    must be set before starting the server

Exit codes:
    0  Gate PASS  — all criteria satisfied for the full run
    1  Gate FAIL  — one or more criteria violated; see output for details
    2  Connection error — server unreachable; check that MERID is running
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── Gate criteria constants ───────────────────────────────────────────────────

P95_LIMIT_MS: float = 500.0   # Fail if any sample exceeds this
DEGRADED_ALLOWED: bool = False  # Any degraded=true sample fails the gate
CRIT_SAMPLES_ALLOWED: int = 0   # samples_above_crit must stay 0

# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class PollSample:
    """A single /health/event_loop poll result."""
    poll_index: int
    elapsed_s: float
    timestamp: str
    status: str            # "ok" | "error"
    error: Optional[str]
    degraded: Optional[bool]
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    p99_ms: Optional[float]
    max_ms: Optional[float]
    samples_above_warn: Optional[int]
    samples_above_crit: Optional[int]


@dataclass
class GateResult:
    """Full gate run result."""
    gate_id: str
    started_at: str
    ended_at: str
    duration_s: float
    environment: str = "paper"
    trade_mode: str = "paper"
    allow_live_trades: bool = False
    total_polls: int = 0
    successful_polls: int = 0
    failed_polls: int = 0
    # Aggregate stats across all successful polls
    p50_min_ms: Optional[float] = None
    p50_max_ms: Optional[float] = None
    p95_min_ms: Optional[float] = None
    p95_max_ms: Optional[float] = None
    p99_min_ms: Optional[float] = None
    p99_max_ms: Optional[float] = None
    p50_mean_ms: Optional[float] = None
    p95_mean_ms: Optional[float] = None
    p99_mean_ms: Optional[float] = None
    max_observed_lag_ms: Optional[float] = None
    total_crit_samples: int = 0
    degraded_samples: int = 0
    # Verdict
    passed: bool = False
    violations: List[str] = field(default_factory=list)
    # Raw samples (for debugging / audit)
    samples: List[dict] = field(default_factory=list)


# ── HTTP helper ───────────────────────────────────────────────────────────────


def _poll_event_loop_health(base_url: str, timeout: float = 5.0) -> dict:
    """
    GET {base_url}/health/event_loop and return the parsed JSON body.

    Raises urllib.error.URLError on network failure.
    Raises ValueError on non-200 response or JSON parse error.
    """
    url = f"{base_url.rstrip('/')}/health/event_loop"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise ValueError(f"HTTP {resp.status} from {url}")
        body = resp.read().decode("utf-8")
        return json.loads(body)


def _extract_sample_values(body: dict) -> dict:
    """Extract the relevant scalar fields from a /health/event_loop response.

    The endpoint may return stats under ``stats_1m`` or directly at the top
    level (both formats are supported by the EventLoopMonitor health endpoint).
    """
    stats = body.get("stats_1m") or {}

    def _get(key: str):
        """Return the value from stats_1m if present, otherwise from body top level."""
        v = stats.get(key)
        if v is None:
            v = body.get(key)
        return v

    return {
        "degraded": body.get("degraded"),
        "p50_ms": _get("p50_ms"),
        "p95_ms": _get("p95_ms"),
        "p99_ms": _get("p99_ms"),
        "max_ms": _get("max_ms"),
        "samples_above_warn": _get("samples_above_warn"),
        "samples_above_crit": _get("samples_above_crit"),
    }


# ── Core gate logic ───────────────────────────────────────────────────────────


def run_gate(
    base_url: str = "http://localhost:8000",
    duration_s: float = 1800.0,
    poll_interval_s: float = 30.0,
    gate_id: Optional[str] = None,
    verbose: bool = True,
) -> GateResult:
    """
    Run the paper gate for ``duration_s`` seconds, polling every
    ``poll_interval_s`` seconds.

    Returns a :class:`GateResult` with verdict and all samples.
    """
    if gate_id is None:
        gate_id = f"paper-gate-{int(time.time())}"

    started_at = datetime.now(timezone.utc).isoformat()
    start_mono = time.monotonic()
    deadline = start_mono + duration_s

    result = GateResult(
        gate_id=gate_id,
        started_at=started_at,
        ended_at="",
        duration_s=duration_s,
    )

    p50_vals: List[float] = []
    p95_vals: List[float] = []
    p99_vals: List[float] = []
    max_vals: List[float] = []

    poll_index = 0

    if verbose:
        print(f"\n{'='*72}")
        print(f"  MERID 30-Minute Paper Gate: {gate_id}")
        print(f"  Started at: {started_at}")
        print(f"  Duration: {duration_s:.0f}s  |  Poll interval: {poll_interval_s:.0f}s")
        print(f"  Target: {base_url}/health/event_loop")
        print(f"{'='*72}\n")

    while time.monotonic() < deadline:
        elapsed = time.monotonic() - start_mono
        poll_ts = datetime.now(timezone.utc).isoformat()
        result.total_polls += 1

        sample = PollSample(
            poll_index=poll_index,
            elapsed_s=round(elapsed, 1),
            timestamp=poll_ts,
            status="ok",
            error=None,
            degraded=None,
            p50_ms=None,
            p95_ms=None,
            p99_ms=None,
            max_ms=None,
            samples_above_warn=None,
            samples_above_crit=None,
        )

        try:
            body = _poll_event_loop_health(base_url)
            vals = _extract_sample_values(body)

            sample.degraded = vals.get("degraded")
            sample.p50_ms = vals.get("p50_ms")
            sample.p95_ms = vals.get("p95_ms")
            sample.p99_ms = vals.get("p99_ms")
            sample.max_ms = vals.get("max_ms")
            sample.samples_above_warn = vals.get("samples_above_warn")
            sample.samples_above_crit = vals.get("samples_above_crit")

            result.successful_polls += 1

            # Accumulate
            if sample.p50_ms is not None:
                p50_vals.append(sample.p50_ms)
            if sample.p95_ms is not None:
                p95_vals.append(sample.p95_ms)
            if sample.p99_ms is not None:
                p99_vals.append(sample.p99_ms)
            if sample.max_ms is not None:
                max_vals.append(sample.max_ms)
            if sample.samples_above_crit:
                result.total_crit_samples += sample.samples_above_crit
            if sample.degraded:
                result.degraded_samples += 1

            if verbose:
                status_icon = "⚠️ " if sample.degraded else "✅"
                p95_str = f"{sample.p95_ms:.1f}ms" if sample.p95_ms is not None else "N/A"
                p99_str = f"{sample.p99_ms:.1f}ms" if sample.p99_ms is not None else "N/A"
                print(
                    f"  [{poll_index:3d}] {elapsed:6.0f}s  {status_icon} "
                    f"P95={p95_str}  P99={p99_str}  "
                    f"degraded={sample.degraded}  "
                    f"crit_samples={sample.samples_above_crit or 0}"
                )

        except (urllib.error.URLError, OSError) as exc:
            sample.status = "error"
            sample.error = str(exc)
            result.failed_polls += 1
            if verbose:
                print(f"  [{poll_index:3d}] {elapsed:6.0f}s  ❌ HTTP error: {exc}")

        result.samples.append(asdict(sample))
        poll_index += 1

        # Sleep until next poll (or gate deadline, whichever is sooner)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval_s, remaining))

    result.ended_at = datetime.now(timezone.utc).isoformat()

    # ── Compute aggregates ────────────────────────────────────────────────────
    if p50_vals:
        result.p50_min_ms = round(min(p50_vals), 3)
        result.p50_max_ms = round(max(p50_vals), 3)
        result.p50_mean_ms = round(sum(p50_vals) / len(p50_vals), 3)
    if p95_vals:
        result.p95_min_ms = round(min(p95_vals), 3)
        result.p95_max_ms = round(max(p95_vals), 3)
        result.p95_mean_ms = round(sum(p95_vals) / len(p95_vals), 3)
    if p99_vals:
        result.p99_min_ms = round(min(p99_vals), 3)
        result.p99_max_ms = round(max(p99_vals), 3)
        result.p99_mean_ms = round(sum(p99_vals) / len(p99_vals), 3)
    if max_vals:
        result.max_observed_lag_ms = round(max(max_vals), 3)

    # ── Evaluate gate criteria ────────────────────────────────────────────────
    violations: List[str] = []

    # 1. P95 lag < 500ms throughout
    if result.p95_max_ms is not None and result.p95_max_ms >= P95_LIMIT_MS:
        violations.append(
            f"P95 lag peaked at {result.p95_max_ms}ms >= {P95_LIMIT_MS}ms limit"
        )

    # 2. degraded=false on every sample
    if result.degraded_samples > 0:
        violations.append(
            f"degraded=true seen on {result.degraded_samples} sample(s)"
        )

    # 3. No high-lag profiles (samples_above_crit == 0)
    if result.total_crit_samples > CRIT_SAMPLES_ALLOWED:
        violations.append(
            f"{result.total_crit_samples} critical-lag samples captured (threshold: {P95_LIMIT_MS}ms)"
        )

    # 4. No connection errors (missed heartbeats)
    if result.failed_polls > 0:
        violations.append(
            f"{result.failed_polls} poll(s) failed (server unreachable / missed heartbeat)"
        )

    # 5. At least one successful poll required
    if result.successful_polls == 0:
        violations.append("No successful polls completed — server may not be running")

    result.violations = violations
    result.passed = len(violations) == 0

    # ── Final summary ─────────────────────────────────────────────────────────
    if verbose:
        print(f"\n{'='*72}")
        print(f"  Gate: {gate_id}")
        print(f"  Duration: {result.duration_s:.0f}s  |  Polls: {result.total_polls}")
        print(f"  P50 (mean/max): {result.p50_mean_ms}ms / {result.p50_max_ms}ms")
        print(f"  P95 (mean/max): {result.p95_mean_ms}ms / {result.p95_max_ms}ms")
        print(f"  P99 (mean/max): {result.p99_mean_ms}ms / {result.p99_max_ms}ms")
        print(f"  Max observed lag: {result.max_observed_lag_ms}ms")
        print(f"  Degraded samples: {result.degraded_samples}")
        print(f"  Critical-lag samples: {result.total_crit_samples}")
        if result.passed:
            print(f"\n  ✅  GATE PASS — all criteria satisfied")
        else:
            print(f"\n  ❌  GATE FAIL — {len(violations)} violation(s):")
            for v in violations:
                print(f"       • {v}")
        print(f"{'='*72}\n")

    return result


# ── CLI entry point ───────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run a timed MERID paper gate, polling /health/event_loop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the running MERID server (default: http://localhost:8000)",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=30.0,
        metavar="MINUTES",
        help="Gate duration in minutes (default: 30)",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="Seconds between polls (default: 30)",
    )
    p.add_argument(
        "--gate-id",
        default=None,
        help="Human-readable gate identifier (auto-generated if omitted)",
    )
    p.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Write gate result JSON to this file",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-poll output",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate imports and config, then exit 0 without connecting",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.dry_run:
        print("Dry-run: all imports resolved, configuration valid.")
        print(f"  Base URL    : {args.base_url}")
        print(f"  Duration    : {args.duration} minutes")
        print(f"  Poll interval: {args.poll_interval} seconds")
        return 0

    try:
        result = run_gate(
            base_url=args.base_url,
            duration_s=args.duration * 60.0,
            poll_interval_s=args.poll_interval,
            gate_id=args.gate_id,
            verbose=not args.quiet,
        )
    except KeyboardInterrupt:
        print("\nGate interrupted by user.")
        return 2
    except urllib.error.URLError as exc:
        print(f"Connection error — is the MERID server running at {args.base_url}?")
        print(f"  Details: {exc}")
        return 2

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(asdict(result), fh, indent=2)
        if not args.quiet:
            print(f"Gate result written to: {out_path}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
