#!/usr/bin/env python3
"""Operator routine: verify PM + Kalshi gates before a live run.

Runs the same checks as scripts/go_live_preflight.py and prints stack flags.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

_RepoRoot = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RepoRoot))
sys.path.insert(0, str(_RepoRoot / "scripts"))

if sys.platform == "win32" and hasattr(sys.stdout, "buffer") and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _print_stack_flags() -> None:
    try:
        from merid.settings import settings
    except Exception as exc:
        print(f"\n  [WARN] Could not load settings: {exc}\n")
        return
    print("\n  --- Stack flags ---")
    print(f"  MERID_PM_PROFILE:          {settings.MERID_PM_PROFILE!r}")
    print(f"  MERID_PM_TRADING_MODE:     {settings.MERID_PM_TRADING_MODE!r}")
    print(f"  MERID_PM_LIVE_ENABLED:     {settings.MERID_PM_LIVE_ENABLED}")
    print(f"  MERID_ENABLE_KALSHI_CT:   {settings.MERID_ENABLE_KALSHI_CT}")
    print(f"  MERID_KALSHI_WS_CLIENT:    {settings.MERID_KALSHI_WS_CLIENT!r}")
    print(f"  MERID_VALIDATION_MODE:     {os.getenv('MERID_VALIDATION_MODE', '')!r}")
    print("\n  After server boot:")
    print("    GET /api/v1/operator/pm-live-readiness  (single binary + all checks)")
    print("    GET /api/v1/operator/agent-grid/startup-health")


async def _main() -> int:
    from go_live_preflight import run_all

    _print_stack_flags()
    return await run_all()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
