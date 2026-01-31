#!/usr/bin/env python3
"""Run the E2E simulation harness and print a summary."""
from __future__ import annotations

import argparse
import json
import sys

import os
import sys
# Ensure repo root is importable when running this script directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulations.e2e import E2ESimulation


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run E2E MERID simulation")
    p.add_argument("--steps", type=int, default=20)
    p.add_argument("--threshold", type=float, default=50.0)
    p.add_argument("--actor", type=str, default="sim")
    p.add_argument("--min-orders", type=int, default=0, help="Minimum number of orders expected; return non-zero if not met")
    p.add_argument("--require-audit", action="store_true", help="Require at least one audit entry; return non-zero if none present")

    args = p.parse_args(argv)
    sim = E2ESimulation(steps=args.steps, threshold=args.threshold, actor=args.actor)
    res = sim.run()
    print(json.dumps(res, indent=2))

    # Basic assertions that cause non-zero exit on failure
    if args.min_orders and len(res.get("orders", [])) < args.min_orders:
        print(f"E2E assertion failed: expected at least {args.min_orders} orders, got {len(res.get('orders', []))}", file=sys.stderr)
        return 2
    if args.require_audit and res.get("audit_count", 0) < 1:
        print("E2E assertion failed: expected at least one audit entry", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
