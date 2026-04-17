#!/usr/bin/env python3
"""Kalshi go-live preflight (env + readiness) before restarting uvicorn or CT.

Recommended sequence
    1. Load the correct merged environment (demo: e.g. ``.env`` + ``.env.kalshi-sim``;
       live: ``.env`` + ``.env.kalshi-live-prod`` — set ``KALSHI_API_KEY_ID``,
       ``KALSHI_PRIVATE_KEY_PATH``, ``KALSHI_TRADER_BANKROLL``, and live URL guards).
    2. Run this script from repo root (add ``--reset-kill-switch`` only if
       ``data/risk_kill_switch.json`` still has ``active: true`` from a prior halt).
    3. Restart the server.
    4. Wait for reconciliation + catalog warmup; first-boot WARNs are normal.

``--strict`` forwards to ``MERID_KALSHI_EXECUTION_READINESS_CHECK.py`` and fails on any
WARN — use for a strict go-live, not every routine restart.

Usage (from repo root)::

    py scripts/kalshi_go_live_preflight.py
    py scripts/kalshi_go_live_preflight.py --reset-kill-switch
    py scripts/kalshi_go_live_preflight.py --strict

Environment:
    Load your .env before running (or set vars in the shell) so ENV checks pass.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Kalshi go-live preflight: optional kill-switch clear + full readiness check.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Steps: (1) merge the right .env profile for demo vs live, "
            "(2) run this command, (3) restart server, "
            "(4) allow warmup. "
            "See MERID_KALSHI_EXECUTION_READINESS_CHECK.py --help for stage details."
        ),
    )
    parser.add_argument(
        "--reset-kill-switch",
        action="store_true",
        help=(
            "Persist disarmed kill switch to disk via risk_controller.reset('go_live_preflight') "
            "(same effect as dashboard reset); use if KILL_SWITCH/FILE would otherwise FAIL"
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat readiness WARN as failure (strict go-live); forwards to MERID_KALSHI_EXECUTION_READINESS_CHECK.py",
    )
    args = parser.parse_args()

    root = _project_root()
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    if args.reset_kill_switch:
        from merid.risk.kill_switches import risk_controller

        risk_controller.reset("go_live_preflight")
        print("[preflight] Kill switch reset written to disk (if it was active).")

    check = root / "MERID_KALSHI_EXECUTION_READINESS_CHECK.py"
    cmd = [sys.executable, str(check)]
    if args.strict:
        cmd.append("--strict")
    proc = subprocess.run(cmd, cwd=str(root))
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
