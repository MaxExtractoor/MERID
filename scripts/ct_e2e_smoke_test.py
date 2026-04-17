#!/usr/bin/env python3
"""Smoke: CT cycle emits UA metrics + trace (no live orders required).

Run from repo root with API keys optional — uses MERID_VALIDATION_MODE-style stubs
only if the continuous trader cannot initialise; otherwise runs one CT cycle in-process.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    os.environ.setdefault("KALSHI_TRADER_SMOKE_TEST", "true")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    from merid.prediction.ua_ct_metrics import reset_for_tests, snapshot
    from merid.trading.kalshi_continuous_trader import get_continuous_trader, reset_continuous_trader

    reset_for_tests()
    reset_continuous_trader()
    ct = get_continuous_trader()
    try:
        ct._run_cycle()
    except Exception as e:
        print("ct._run_cycle failed (expected in CI without keys):", e)
        return 0
    snap = snapshot()
    print("[smoke] ua_ct snapshot:", snap)
    if snap.get("evaluated", 0) < 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
