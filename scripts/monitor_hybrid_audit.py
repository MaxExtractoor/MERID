"""30-minute live monitor for the hybrid audit pipeline.

Checks every 60 seconds:
- Server health
- hybrid_model_decomposition / shadow_side_telemetry ticker format
- rejected_candidates ticker format
- settlement_outcomes arrivals
- Runs generate_hybrid_signal_audit.py and reports progress

Usage:
    .\.venv\Scripts\python.exe scripts\monitor_hybrid_audit.py --duration 1800
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT_SCRIPT = os.path.join(REPO, "scripts", "generate_hybrid_signal_audit.py")
PROGRESS = os.path.join(REPO, "reports", "hybrid_audit_progress.json")
DECOMP = os.path.join(REPO, "data", "logs", "hybrid_model_decomposition.jsonl")
SHADOW = os.path.join(REPO, "data", "logs", "shadow_side_telemetry.jsonl")
REJECTED = os.path.join(REPO, "logs", "rejected_candidates.jsonl")
SETTLEMENTS = os.path.join(REPO, "logs", "settlement_outcomes.jsonl")
HEALTH = "http://127.0.0.1:8011/api/v1/health"


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] {msg}", flush=True)


def _tail_jsonl(path: str, n: int = 5) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            out.append({"__parse_error": str(exc), "__raw": line[:200]})
    return out


def _check_ticker_format(records: List[Dict[str, Any]], key: str) -> List[str]:
    issues: List[str] = []
    for rec in records:
        if "__parse_error" in rec:
            issues.append(f"parse error in {key}: {rec['__parse_error']}")
            continue
        ticker = rec.get("ticker")
        if not ticker:
            issues.append(f"missing ticker in {key}")
        elif re.fullmatch(r"[A-Z]{2,5}", str(ticker)):
            issues.append(f"asset-code ticker still present in {key}: {ticker}")
    return issues


def _health() -> str:
    try:
        with urllib.request.urlopen(HEALTH, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="ignore").strip()
    except Exception as exc:
        return f"ERROR: {exc}"


def _run_audit() -> Dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, AUDIT_SCRIPT],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _count_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def monitor(duration_seconds: int, interval_seconds: int) -> int:
    end = time.time() + duration_seconds
    iteration = 0
    issues_total: List[str] = []
    while time.time() < end:
        iteration += 1
        log(f"--- monitor tick {iteration} ---")

        # Health
        health = _health()
        log(f"health: {health}")
        if "alive" not in health and "ERROR" in health:
            issues_total.append(f"health check failed: {health}")

        # Audit run
        audit = _run_audit()
        if "error" in audit:
            issues_total.append(f"audit runner error: {audit['error']}")
        elif audit.get("returncode", 0) == 0:
            log("audit: PASSING artifact written")
        else:
            log("audit: not ready (expected while data accumulates)")

        if audit.get("stderr"):
            for line in audit["stderr"].splitlines():
                if line.strip():
                    issues_total.append(f"audit stderr: {line.strip()}")

        # Progress report
        n_total = 0
        if os.path.exists(PROGRESS):
            try:
                with open(PROGRESS, "r", encoding="utf-8") as f:
                    progress = json.load(f)
                n_total = progress.get("n_total_settled_evaluations", 0)
                log(
                    f"progress: total={n_total} hold_out={progress.get('hold_out_set_size')} "
                    f"passes={progress.get('passes')} failures={progress.get('failures')}"
                )
            except Exception as exc:
                issues_total.append(f"progress parse error: {exc}")

        # Ticker format checks
        dec = _tail_jsonl(DECOMP, 10)
        issues = _check_ticker_format(dec, "decomp")
        if issues:
            for issue in issues:
                issues_total.append(issue)
            log(f"decomp issues: {len(issues)}")
        else:
            last = dec[-1] if dec else {}
            log(f"decomp last ticker: {last.get('ticker')}")

        shadow = _tail_jsonl(SHADOW, 5)
        issues = _check_ticker_format(shadow, "shadow")
        if issues:
            for issue in issues:
                issues_total.append(issue)
            log(f"shadow issues: {len(issues)}")
        else:
            last = shadow[-1] if shadow else {}
            log(f"shadow last ticker: {last.get('ticker')}")

        rej = _tail_jsonl(REJECTED, 5)
        issues = _check_ticker_format(rej, "rejected")
        if issues:
            for issue in issues:
                issues_total.append(issue)
            log(f"rejected issues: {len(issues)}")
        else:
            last = rej[-1] if rej else {}
            log(f"rejected last ticker: {last.get('ticker')}")

        # Settlement arrivals
        n_settlements = _count_lines(SETTLEMENTS)
        last_settlements = _tail_jsonl(SETTLEMENTS, 3)
        log(f"settlements: total_lines={n_settlements} last={last_settlements[-1].get('ticker') if last_settlements else 'N/A'}")

        log(f"issues so far: {len(issues_total)}")

        # Print found issues
        for issue in issues_total[-5:]:  # only new-ish from this tick
            log(f"  ISSUE: {issue}")

        # Sleep until next interval, but stop if duration elapsed
        remaining = end - time.time()
        if remaining <= 0:
            break
        time.sleep(min(interval_seconds, remaining))

    log("--- monitor complete ---")
    if issues_total:
        log(f"TOTAL ISSUES FOUND: {len(issues_total)}")
        for issue in issues_total:
            log(f"  - {issue}")
    else:
        log("NO ISSUES FOUND")
    return 0 if not issues_total else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=1800, help="Seconds to monitor")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks")
    args = parser.parse_args()
    return monitor(args.duration, args.interval)


if __name__ == "__main__":
    sys.exit(main())
