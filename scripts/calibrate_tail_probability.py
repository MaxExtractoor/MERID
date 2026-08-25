#!/usr/bin/env python3
"""Fit a tail probability calibrator from the corrected 7-day trade data.

The output is a JSON file consumed by `merid.risk.probability.tail_calibrator`
and used to cap model probability for held-side market prices in the cheap tail.

Usage:
    python scripts/calibrate_tail_probability.py \
        --input trade_analysis_raw_7d.json \
        --output data/probability_tail_calibration.json \
        --buffer 0.05
"""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.risk.probability.tail_calibrator import TailProbabilityCalibrator


def load_trades(input_path: str) -> List[Dict[str, Any]]:
    with open(input_path, "r") as f:
        data = json.load(f)
    if isinstance(data, dict) and "trades" in data:
        return data["trades"]
    if isinstance(data, list):
        return data
    raise ValueError("Input must be a trade list or a dict with key 'trades'")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit tail probability calibrator")
    parser.add_argument("--input", type=str, default="trade_analysis_raw_7d.json", help="Trade analysis JSON")
    parser.add_argument("--output", type=str, default="data/probability_tail_calibration.json", help="Output JSON")
    parser.add_argument("--buffer", type=float, default=0.05, help="Model-probability cap buffer above actual win rate")
    args = parser.parse_args()

    trades = load_trades(args.input)
    if len(trades) < 10:
        print(f"ERROR: need at least 10 trades, got {len(trades)}")
        return 1

    calibrator = TailProbabilityCalibrator.from_trade_analysis(trades, buffer=args.buffer)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(calibrator.to_dict(), f, indent=2, default=str)

    print("=" * 70)
    print("TAIL PROBABILITY CALIBRATION")
    print("=" * 70)
    print(f"Trades used: {calibrator.n_trades}")
    print(f"Buffer:      {calibrator.buffer}")
    print(f"Knots:       {len(calibrator.held_prices)}")
    print(f"Output:      {out_path}")
    print()
    print("Calibration table (held YES price -> actual P(YES wins)):")
    for x, y in zip(calibrator.held_prices, calibrator.actual_probs):
        print(f"  ${x:.2f} -> {y:.3f}")
    print()
    print("Sample caps (with buffer):")
    for p in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.50, 0.80]:
        prob = calibrator.p_yes(p)
        print(f"  held YES ${p:.2f}: actual={prob:.3f}, cap={prob + calibrator.buffer:.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
