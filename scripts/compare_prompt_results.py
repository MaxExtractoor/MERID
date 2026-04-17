#!/usr/bin/env python3
"""Prompt regression detector — compares current eval results against baseline.

Usage:
    python compare_prompt_results.py \
        --baseline baseline/prompt_benchmark.json \
        --current prompt_benchmark.json \
        --threshold 0.05
"""

import argparse
import json
import sys
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(description="Compare prompt evaluation results")
    p.add_argument("--baseline", required=True, help="Path to baseline JSON")
    p.add_argument("--current", required=True, help="Path to current JSON")
    p.add_argument("--threshold", type=float, default=0.05,
                   help="Max allowed score drop (0.05 = 5%)")
    return p.parse_args()


def load_results(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"WARNING: {path} not found — skipping comparison", file=sys.stderr)
        return {}
    return json.loads(p.read_text())


def compare(baseline: dict, current: dict, threshold: float) -> int:
    if not baseline or not current:
        print("No comparison performed (one or both files missing).")
        return 0

    regressions = []
    b_scores = baseline.get("scores", {})
    c_scores = current.get("scores", {})

    for key, b_val in b_scores.items():
        c_val = c_scores.get(key)
        if c_val is None:
            print(f"  WARNING: metric '{key}' missing from current results")
            continue
        drop = b_val - c_val
        if drop > threshold:
            regressions.append((key, b_val, c_val, drop))
            print(f"  REGRESSION: {key}: {b_val:.3f} → {c_val:.3f} (drop={drop:.3f})")
        else:
            print(f"  OK: {key}: {b_val:.3f} → {c_val:.3f}")

    if regressions:
        print(f"\n{len(regressions)} regression(s) exceed threshold {threshold}")
        return 1

    print("\nAll metrics within acceptable threshold.")
    return 0


def main():
    args = parse_args()
    baseline = load_results(args.baseline)
    current = load_results(args.current)
    return compare(baseline, current, args.threshold)


if __name__ == "__main__":
    sys.exit(main())
