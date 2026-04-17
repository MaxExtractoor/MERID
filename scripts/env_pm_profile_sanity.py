#!/usr/bin/env python3
"""Assert process env matches one of the canonical PM profiles (no network).

Usage::

    py scripts/env_pm_profile_sanity.py
    py scripts/env_pm_profile_sanity.py --expect prod-live
    py scripts/env_pm_profile_sanity.py --expect stage-paper

Exit 0 if the active profile matches; exit 2 if ambiguous or mismatch.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def _is_prod_live() -> bool:
    return (
        os.getenv("MERID_PM_PROFILE", "").strip().lower() == "production"
        and os.getenv("MERID_PM_TRADING_MODE", "").strip().lower() == "live"
        and _truthy("MERID_PM_LIVE_ENABLED")
        and _truthy("MERID_ALLOW_LIVE_TRADES")
        and os.getenv("MERID_KALSHI_WS_CLIENT", "").strip().lower() == "ws"
        and not _truthy("MERID_ENABLE_KALSHI_CT")
        and os.getenv("MERID_VALIDATION_MODE", "").strip() != "1"
        and not _truthy("KALSHI_TRADER_SMOKE_TEST")
        and _truthy("KALSHI_CONFIRM_LIVE")
        and os.getenv("KALSHI_ENV", "").strip().lower() == "live"
    )


def _is_stage_paper() -> bool:
    return (
        os.getenv("MERID_PM_TRADING_MODE", "").strip().lower() == "paper"
        and not _truthy("MERID_PM_LIVE_ENABLED")
        and os.getenv("MERID_KALSHI_WS_CLIENT", "").strip().lower() == "ws"
        and not _truthy("MERID_ENABLE_KALSHI_CT")
        and os.getenv("MERID_VALIDATION_MODE", "").strip() != "1"
    )


def _is_validation_only() -> bool:
    return os.getenv("MERID_VALIDATION_MODE", "").strip() == "1"


def detect() -> str:
    pl = _is_prod_live()
    sp = _is_stage_paper()
    vo = _is_validation_only()
    n = int(pl) + int(sp) + int(vo)
    if n > 1:
        return "ambiguous"
    if pl:
        return "prod-live"
    if sp:
        return "stage-paper"
    if vo:
        return "validation-only"
    return "custom"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--expect",
        choices=("prod-live", "stage-paper", "validation-only", "any"),
        default="any",
        help="Require this profile (default: any, just print detected label)",
    )
    args = p.parse_args()
    label = detect()
    print(f"detected_pm_env_profile={label}")
    if args.expect == "any":
        return 0 if label != "ambiguous" else 2
    if label == "ambiguous":
        print("error: env matches more than one canonical profile", file=sys.stderr)
        return 2
    if label != args.expect:
        print(f"error: expected {args.expect!r} but got {label!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
