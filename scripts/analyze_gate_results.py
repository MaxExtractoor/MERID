#!/usr/bin/env python3
"""
Analyze and summarize gate results with detailed per-sample P95 breakdowns.

This script reads gate result JSON files (from run_paper_gate.py) and provides:
- Overall P95/P99/Max statistics
- Per-sample P95 analysis
- T+5min window identification and analysis
- Go/No-Go verdict for live trading

Usage:
    python scripts/analyze_gate_results.py reports/gate_10min.json
    python scripts/analyze_gate_results.py reports/gate_30min.json --highlight-5min
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class SampleAnalysis:
    """Analysis of a single gate sample."""
    sample_index: int
    elapsed_s: float
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    p99_ms: Optional[float]
    max_ms: Optional[float]
    degraded: bool
    crit_samples: int

    def is_5min_window(self) -> bool:
        """Check if this sample falls within a T+5min window (±30s)."""
        # 5-minute marks: 300, 600, 900, 1200, 1500, 1800 seconds
        for mark in [300, 600, 900, 1200, 1500, 1800]:
            if abs(self.elapsed_s - mark) <= 30:
                return True
        return False

    def status_icon(self) -> str:
        """Visual status indicator."""
        if self.degraded or (self.p95_ms and self.p95_ms >= 500):
            return "⚠️ "
        return "✅"


def load_gate_result(file_path: Path) -> dict:
    """Load gate result JSON."""
    with file_path.open("r") as f:
        return json.load(f)


def analyze_samples(samples: List[dict]) -> List[SampleAnalysis]:
    """Convert raw samples to SampleAnalysis objects."""
    results = []
    for s in samples:
        if s["status"] != "ok":
            continue  # Skip failed polls

        analysis = SampleAnalysis(
            sample_index=s["poll_index"],
            elapsed_s=s["elapsed_s"],
            p50_ms=s.get("p50_ms"),
            p95_ms=s.get("p95_ms"),
            p99_ms=s.get("p99_ms"),
            max_ms=s.get("max_ms"),
            degraded=s.get("degraded", False),
            crit_samples=s.get("samples_above_crit", 0),
        )
        results.append(analysis)

    return results


def print_summary(gate_data: dict, samples: List[SampleAnalysis], highlight_5min: bool = False):
    """Print comprehensive gate analysis summary."""
    print("\n" + "=" * 80)
    print(f"  MERID Gate Analysis: {gate_data['gate_id']}")
    print("=" * 80)

    # Overall stats
    print(f"\nDuration: {gate_data['duration_s']:.0f}s ({gate_data['duration_s']/60:.1f} min)")
    print(f"Total polls: {gate_data['total_polls']} (successful: {gate_data['successful_polls']}, failed: {gate_data['failed_polls']})")

    print(f"\n📊 Overall Statistics:")
    print(f"  P50: min={gate_data.get('p50_min_ms', 'N/A')}ms  max={gate_data.get('p50_max_ms', 'N/A')}ms  mean={gate_data.get('p50_mean_ms', 'N/A')}ms")
    print(f"  P95: min={gate_data.get('p95_min_ms', 'N/A')}ms  max={gate_data.get('p95_max_ms', 'N/A')}ms  mean={gate_data.get('p95_mean_ms', 'N/A')}ms")
    print(f"  P99: min={gate_data.get('p99_min_ms', 'N/A')}ms  max={gate_data.get('p99_max_ms', 'N/A')}ms  mean={gate_data.get('p99_mean_ms', 'N/A')}ms")
    print(f"  Max observed lag: {gate_data.get('max_observed_lag_ms', 'N/A')}ms")
    print(f"  Degraded samples: {gate_data['degraded_samples']}")
    print(f"  Critical-lag samples: {gate_data['total_crit_samples']}")

    # Per-sample breakdown
    print(f"\n📋 Per-Sample P95 Breakdown:")
    print(f"  {'Sample':<8} {'Elapsed':<10} {'P50':<10} {'P95':<10} {'P99':<10} {'Max':<10} {'Status':<10}")
    print("  " + "-" * 70)

    for s in samples:
        p50_str = f"{s.p50_ms:.1f}ms" if s.p50_ms is not None else "N/A"
        p95_str = f"{s.p95_ms:.1f}ms" if s.p95_ms is not None else "N/A"
        p99_str = f"{s.p99_ms:.1f}ms" if s.p99_ms is not None else "N/A"
        max_str = f"{s.max_ms:.1f}ms" if s.max_ms is not None else "N/A"
        elapsed_str = f"{s.elapsed_s:.0f}s"

        # Highlight 5-minute windows if requested
        marker = ""
        if highlight_5min and s.is_5min_window():
            marker = " 🔴 T+5min"

        print(f"  {s.status_icon()} [{s.sample_index:3d}] {elapsed_str:<10} {p50_str:<10} {p95_str:<10} {p99_str:<10} {max_str:<10} {s.degraded!s:<10}{marker}")

    # 5-minute window analysis
    if highlight_5min:
        fivemin_samples = [s for s in samples if s.is_5min_window()]
        if fivemin_samples:
            print(f"\n🔍 T+5min Window Analysis ({len(fivemin_samples)} samples):")
            p95_values = [s.p95_ms for s in fivemin_samples if s.p95_ms is not None]
            if p95_values:
                print(f"  P95: min={min(p95_values):.1f}ms  max={max(p95_values):.1f}ms  mean={sum(p95_values)/len(p95_values):.1f}ms")
            degraded_count = sum(1 for s in fivemin_samples if s.degraded)
            if degraded_count > 0:
                print(f"  ⚠️  {degraded_count} degraded samples in 5-min windows")

    # Go/No-Go verdict
    print(f"\n🎯 Go/No-Go Verdict:")

    criteria = {
        "P95 < 500ms": gate_data.get('p95_max_ms', 0) < 500,
        "P99 < 800ms": gate_data.get('p99_max_ms', 0) < 800,
        "Max < 1000ms": gate_data.get('max_observed_lag_ms', 0) < 1000,
        "degraded_samples == 0": gate_data['degraded_samples'] == 0,
        "No connection failures": gate_data['failed_polls'] == 0,
    }

    all_pass = all(criteria.values())

    for criterion, passed in criteria.items():
        status = "✅" if passed else "❌"
        print(f"  {status} {criterion}")

    if all_pass:
        print(f"\n  ✅✅✅ GO FOR LIVE TRADING — All criteria satisfied")
    else:
        print(f"\n  ❌ NO-GO — Fix issues before live trading")
        if gate_data.get('violations'):
            print(f"\n  Violations:")
            for v in gate_data['violations']:
                print(f"    • {v}")

    print("=" * 80 + "\n")


def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description="Analyze gate results and provide go/no-go verdict for live trading"
    )
    parser.add_argument("result_file", type=Path, help="Gate result JSON file")
    parser.add_argument(
        "--highlight-5min",
        action="store_true",
        help="Highlight and analyze T+5min window samples",
    )

    args = parser.parse_args(argv)

    if not args.result_file.exists():
        print(f"Error: File not found: {args.result_file}")
        return 1

    gate_data = load_gate_result(args.result_file)
    samples = analyze_samples(gate_data.get("samples", []))

    print_summary(gate_data, samples, highlight_5min=args.highlight_5min)

    return 0 if gate_data.get("passed", False) else 1


if __name__ == "__main__":
    sys.exit(main())
