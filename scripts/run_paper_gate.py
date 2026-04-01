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

Early Stopping (NEW):
  By default, the gate will stop early if it detects repeated failures, saving
  time on runs that are clearly failing. Early stop triggers when:
  - At least 5 samples collected (2.5 minutes), AND
  - Either 5 consecutive failures OR 80% failure rate

  When early stopped, the gate automatically fetches profiling data from
  /health/event_loop/profiles/summary and /profiles to help identify the
  lag sources causing the failures.

Usage:
    # Default: 30-minute gate with early stopping enabled
    python scripts/run_paper_gate.py

    # Short 5-minute gate for quick validation after fixes
    python scripts/run_paper_gate.py --duration 5

    # Disable early stopping (run full duration even if failing)
    python scripts/run_paper_gate.py --no-early-stop

    # Custom early stop thresholds
    python scripts/run_paper_gate.py --early-stop-min-samples 3 --early-stop-consecutive 3

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

# ── Early stopping constants ──────────────────────────────────────────────────

EARLY_STOP_MIN_SAMPLES: int = 5  # Minimum samples before early stop (2.5 min @ 30s interval)
EARLY_STOP_CONSECUTIVE_FAILURES: int = 5  # Consecutive failures trigger early stop
EARLY_STOP_FAILURE_RATE: float = 0.8  # 80% failure rate after min samples triggers early stop

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
    # Early stopping
    early_stopped: bool = False
    early_stop_reason: Optional[str] = None
    profiling_summary: Optional[dict] = None
    top_offending_profiles: Optional[List[dict]] = None
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


def _fetch_profiling_data(base_url: str, timeout: float = 5.0) -> tuple[Optional[dict], Optional[list]]:
    """
    Fetch profiling data from /health/event_loop/profiles/summary and /profiles.

    Returns (summary_dict, profiles_list) or (None, None) on error.
    """
    try:
        # Fetch summary
        summary_url = f"{base_url.rstrip('/')}/health/event_loop/profiles/summary"
        req = urllib.request.Request(summary_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                summary = json.loads(resp.read().decode("utf-8"))
            else:
                summary = None

        # Fetch top profiles
        profiles_url = f"{base_url.rstrip('/')}/health/event_loop/profiles?limit=5"
        req = urllib.request.Request(profiles_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                profiles_data = json.loads(resp.read().decode("utf-8"))
                profiles = profiles_data.get("profiles", [])
            else:
                profiles = None

        return summary, profiles
    except Exception:
        return None, None


def _check_early_stop(
    samples: List[dict],
    min_samples: int,
    consecutive_threshold: int,
    failure_rate_threshold: float,
) -> tuple[bool, Optional[str]]:
    """
    Determine if early stopping should be triggered.

    Returns (should_stop, reason_string) tuple.

    Early stop triggers when:
    1. We have at least min_samples successful samples, AND
    2. Either:
       a) Last consecutive_threshold samples all failed, OR
       b) Overall failure rate >= failure_rate_threshold

    A sample is considered "failed" if:
    - P95 >= 500ms, OR
    - degraded=true, OR
    - samples_above_crit > 0
    """
    if len(samples) < min_samples:
        return False, None

    # Count failures
    failures = []
    for s in samples:
        if s["status"] != "ok":
            failures.append(True)
            continue

        # Check gate criteria
        is_failed = False
        if s.get("p95_ms") is not None and s["p95_ms"] >= P95_LIMIT_MS:
            is_failed = True
        if s.get("degraded") is True:
            is_failed = True
        if s.get("samples_above_crit") and s["samples_above_crit"] > 0:
            is_failed = True

        failures.append(is_failed)

    # Check consecutive failures
    if len(failures) >= consecutive_threshold:
        recent_failures = failures[-consecutive_threshold:]
        if all(recent_failures):
            return True, f"{consecutive_threshold} consecutive failures (P95≥500ms or degraded=true)"

    # Check failure rate
    total_successful_samples = sum(1 for s in samples if s["status"] == "ok")
    if total_successful_samples >= min_samples:
        failure_count = sum(failures)
        failure_rate = failure_count / len(failures)
        if failure_rate >= failure_rate_threshold:
            return True, f"High failure rate: {failure_rate:.1%} ({failure_count}/{len(failures)} samples)"

    return False, None


# ── Core gate logic ───────────────────────────────────────────────────────────


def run_gate(
    base_url: str = "http://localhost:8000",
    duration_s: float = 1800.0,
    poll_interval_s: float = 30.0,
    gate_id: Optional[str] = None,
    verbose: bool = True,
    enable_early_stop: bool = True,
    early_stop_min_samples: int = EARLY_STOP_MIN_SAMPLES,
    early_stop_consecutive_failures: int = EARLY_STOP_CONSECUTIVE_FAILURES,
    early_stop_failure_rate: float = EARLY_STOP_FAILURE_RATE,
) -> GateResult:
    """
    Run the paper gate for ``duration_s`` seconds, polling every
    ``poll_interval_s`` seconds.

    Returns a :class:`GateResult` with verdict and all samples.

    Early stopping
    --------------
    If ``enable_early_stop`` is True (default), the gate will stop early if it
    detects repeated failures, saving time on runs that are clearly failing.

    Early stop triggers when:
    - At least ``early_stop_min_samples`` samples collected, AND
    - Either ``early_stop_consecutive_failures`` consecutive failures OR
      failure rate >= ``early_stop_failure_rate``
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

        # ── Early stopping check ──────────────────────────────────────────────
        if enable_early_stop:
            should_stop, stop_reason = _check_early_stop(
                result.samples,
                early_stop_min_samples,
                early_stop_consecutive_failures,
                early_stop_failure_rate,
            )
            if should_stop:
                result.early_stopped = True
                result.early_stop_reason = stop_reason
                if verbose:
                    print(f"\n{'─'*72}")
                    print(f"  🛑 EARLY STOP TRIGGERED")
                    print(f"  Reason: {stop_reason}")
                    print(f"  Fetching profiling data...")
                    print(f"{'─'*72}\n")

                # Fetch profiling data
                summary, profiles = _fetch_profiling_data(base_url)
                result.profiling_summary = summary
                result.top_offending_profiles = profiles

                break  # Exit the polling loop

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

        if result.early_stopped:
            actual_duration = (datetime.fromisoformat(result.ended_at) -
                             datetime.fromisoformat(result.started_at)).total_seconds()
            print(f"  🛑 EARLY STOPPED after {actual_duration:.0f}s (planned: {result.duration_s:.0f}s)")
            print(f"  Reason: {result.early_stop_reason}")
        else:
            print(f"  Duration: {result.duration_s:.0f}s  |  Polls: {result.total_polls}")

        print(f"  Polls: {result.total_polls} ({result.successful_polls} successful)")
        print(f"  P50 (mean/max): {result.p50_mean_ms}ms / {result.p50_max_ms}ms")
        print(f"  P95 (mean/max): {result.p95_mean_ms}ms / {result.p95_max_ms}ms")
        print(f"  P99 (mean/max): {result.p99_mean_ms}ms / {result.p99_max_ms}ms")
        print(f"  Max observed lag: {result.max_observed_lag_ms}ms")
        print(f"  Degraded samples: {result.degraded_samples}")
        print(f"  Critical-lag samples: {result.total_crit_samples}")

        # Show profiling summary if available
        if result.profiling_summary:
            summary = result.profiling_summary
            print(f"\n  📊 PROFILING SUMMARY")
            print(f"  Total profiles captured: {summary.get('total_profiles', 0)}")
            if summary.get('total_profiles', 0) > 0:
                print(f"  Max lag: {summary.get('max_lag_ms', 0):.1f}ms")
                print(f"  Avg lag: {summary.get('avg_lag_ms', 0):.1f}ms")

                # Show top offending coroutines
                offenders_coro = summary.get('offenders_by_coroutine', {})
                if offenders_coro:
                    print(f"\n  Top offending coroutines:")
                    sorted_coro = sorted(offenders_coro.items(), key=lambda x: x[1], reverse=True)[:5]
                    for coro_name, count in sorted_coro:
                        print(f"    • {coro_name}: {count} occurrences")

                # Show top offending modules
                offenders_mod = summary.get('offenders_by_module', {})
                if offenders_mod:
                    print(f"\n  Top offending modules:")
                    sorted_mod = sorted(offenders_mod.items(), key=lambda x: x[1], reverse=True)[:5]
                    for mod_name, count in sorted_mod:
                        print(f"    • {mod_name}: {count} occurrences")

        if result.passed:
            print(f"\n  ✅  GATE PASS — all criteria satisfied")
        else:
            print(f"\n  ❌  GATE FAIL — {len(violations)} violation(s):")
            for v in violations:
                print(f"       • {v}")

            if result.early_stopped:
                print(f"\n  💡 NEXT STEPS:")
                print(f"     1. Review profiling data above to identify lag sources")
                print(f"     2. Add yields / offload blocking work in offending code")
                print(f"     3. Re-run a short gate (5-10 min) after fixes")
                print(f"     4. Only run full 30-min gate when short gates pass")

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
    p.add_argument(
        "--no-early-stop",
        action="store_true",
        help="Disable early stopping (run full duration even if clearly failing)",
    )
    p.add_argument(
        "--early-stop-min-samples",
        type=int,
        default=EARLY_STOP_MIN_SAMPLES,
        metavar="N",
        help=f"Minimum samples before early stop (default: {EARLY_STOP_MIN_SAMPLES})",
    )
    p.add_argument(
        "--early-stop-consecutive",
        type=int,
        default=EARLY_STOP_CONSECUTIVE_FAILURES,
        metavar="N",
        help=f"Consecutive failures to trigger early stop (default: {EARLY_STOP_CONSECUTIVE_FAILURES})",
    )
    p.add_argument(
        "--early-stop-rate",
        type=float,
        default=EARLY_STOP_FAILURE_RATE,
        metavar="RATE",
        help=f"Failure rate threshold for early stop (default: {EARLY_STOP_FAILURE_RATE})",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.dry_run:
        print("Dry-run: all imports resolved, configuration valid.")
        print(f"  Base URL       : {args.base_url}")
        print(f"  Duration       : {args.duration} minutes")
        print(f"  Poll interval  : {args.poll_interval} seconds")
        print(f"  Early stop     : {'disabled' if args.no_early_stop else 'enabled'}")
        if not args.no_early_stop:
            print(f"    - Min samples: {args.early_stop_min_samples}")
            print(f"    - Consecutive : {args.early_stop_consecutive}")
            print(f"    - Failure rate: {args.early_stop_rate:.0%}")
        return 0

    try:
        result = run_gate(
            base_url=args.base_url,
            duration_s=args.duration * 60.0,
            poll_interval_s=args.poll_interval,
            gate_id=args.gate_id,
            verbose=not args.quiet,
            enable_early_stop=not args.no_early_stop,
            early_stop_min_samples=args.early_stop_min_samples,
            early_stop_consecutive_failures=args.early_stop_consecutive,
            early_stop_failure_rate=args.early_stop_rate,
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
