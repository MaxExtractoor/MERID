#!/usr/bin/env python3
"""
MERID Go-Live Preflight Check
==============================
Verifies all 8 safety gates required before enabling live Kalshi trading.

Usage:
    python scripts/go_live_preflight.py
    python scripts/go_live_preflight.py --fix-hints   # show how to fix each failure

Exit codes:
    0  All gates PASS — safe to go live
    1  One or more gates FAIL — do NOT go live
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from pathlib import Path
from typing import List, Tuple

# Ensure repo root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force UTF-8 output on Windows to avoid cp1252 UnicodeEncodeError
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def _check(label: str, ok: bool, detail: str = "", fix: str = "") -> Tuple[bool, str]:
    status = PASS if ok else FAIL
    msg = f"  {status}  {label}"
    if detail:
        msg += f"\n         {detail}"
    if not ok and fix:
        msg += f"\n         \033[90mFix: {fix}\033[0m"
    return ok, msg


def gate_1_trading_mode() -> Tuple[bool, str]:
    from merid.settings import settings
    ok = settings.MERID_PM_TRADING_MODE == "live"
    return _check(
        "Gate 1: MERID_PM_TRADING_MODE = 'live'",
        ok,
        detail=f"Current: {settings.MERID_PM_TRADING_MODE!r}",
        fix="Set MERID_PM_TRADING_MODE=live in .env",
    )


def gate_2_live_enabled() -> Tuple[bool, str]:
    from merid.settings import settings
    ok = settings.MERID_PM_LIVE_ENABLED
    return _check(
        "Gate 2: MERID_PM_LIVE_ENABLED = True",
        ok,
        detail=f"Current: {settings.MERID_PM_LIVE_ENABLED}",
        fix="Set MERID_PM_LIVE_ENABLED=true in .env",
    )


def gate_3_live_unlocked() -> Tuple[bool, str]:
    from merid.settings import settings
    ok = settings.MERID_LIVE_TRADING_UNLOCKED
    return _check(
        "Gate 3: MERID_LIVE_TRADING_UNLOCKED = True",
        ok,
        detail=f"Current: {settings.MERID_LIVE_TRADING_UNLOCKED}",
        fix="Set MERID_LIVE_TRADING_UNLOCKED=true in .env",
    )


def gate_4_not_demo() -> Tuple[bool, str]:
    from merid.settings import settings
    ok = not settings.KALSHI_USE_DEMO
    return _check(
        "Gate 4: KALSHI_USE_DEMO = False (production API)",
        ok,
        detail=f"Current: {settings.KALSHI_USE_DEMO}",
        fix="Set KALSHI_USE_DEMO=false in .env",
    )


def gate_5_credentials() -> Tuple[bool, str]:
    from merid.settings import settings
    key_id = settings.KALSHI_API_KEY_ID
    key_path = settings.KALSHI_PRIVATE_KEY_PATH
    key_pem = settings.KALSHI_PRIVATE_KEY_PEM

    issues = []
    if not key_id or key_id in ("change_me", ""):
        issues.append("KALSHI_API_KEY_ID not set")

    # Accept either a key file path OR an inline PEM string
    has_key_path = key_path and key_path not in ("change_me", "")
    has_key_pem = bool(key_pem)
    if not has_key_path and not has_key_pem:
        issues.append("Neither KALSHI_PRIVATE_KEY_PATH nor KALSHI_PRIVATE_KEY_PEM is set")
    elif has_key_path and not Path(key_path).exists():
        issues.append(f"Private key file not found: {key_path}")

    ok = len(issues) == 0
    detail = "; ".join(issues) if issues else f"key_id={key_id[:8]}... key_path={key_path}"
    return _check(
        "Gate 5: Kalshi credentials configured",
        ok,
        detail=detail,
        fix="Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH in .env",
    )


def gate_6_kill_switch() -> Tuple[bool, str]:
    try:
        from merid.risk.kill_switches import risk_controller
        can_trade = risk_controller.can_trade()
        reason = risk_controller.get_kill_reason()
        detail = f"Kill switch active: {risk_controller._global_kill}"
        if reason:
            detail += f", reason: {reason}"
        return _check(
            "Gate 6: Kill switch not triggered",
            can_trade,
            detail=detail,
            fix="Call POST /api/v1/operator/reset-kill-switch or restart the process",
        )
    except Exception as exc:
        return _check(
            "Gate 6: Kill switch not triggered",
            False,
            detail=f"Could not load risk_controller: {exc}",
            fix="Ensure merid.risk.kill_switches is importable",
        )


async def gate_7_auth_check() -> Tuple[bool, str]:
    try:
        from merid.execution.executors.kalshi import KalshiExecutor
        executor = KalshiExecutor()
        ok = await executor.authenticate()
        return _check(
            "Gate 7: Kalshi API authentication succeeds",
            ok,
            detail="GET /exchange/status returned success" if ok else "Authentication failed — check credentials",
            fix="Verify KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH are correct",
        )
    except Exception as exc:
        return _check(
            "Gate 7: Kalshi API authentication succeeds",
            False,
            detail=f"Exception: {exc}",
            fix="Check credentials and network connectivity to api.kalshi.com",
        )


async def gate_8_balance_readable() -> Tuple[bool, str]:
    try:
        from merid.execution.executors.kalshi import KalshiExecutor
        executor = KalshiExecutor()
        balance = await executor.get_balance()
        available = balance.get("available_dollars", 0.0)
        ok = isinstance(available, (int, float))
        return _check(
            "Gate 8: Kalshi balance readable",
            ok,
            detail=f"Available: ${available:.2f}" if ok else "Balance fetch failed",
            fix="Verify API credentials have portfolio read permissions",
        )
    except Exception as exc:
        return _check(
            "Gate 8: Kalshi balance readable",
            False,
            detail=f"Exception: {exc}",
            fix="Check API key permissions on Kalshi dashboard",
        )


async def run_all() -> int:
    SEP = "=" * 51
    print(f"\n{SEP}")
    print("  MERID Go-Live Preflight Check")
    print(f"{SEP}\n")

    results: List[Tuple[bool, str]] = []

    # Synchronous gates
    for fn in [gate_1_trading_mode, gate_2_live_enabled, gate_3_live_unlocked,
               gate_4_not_demo, gate_5_credentials, gate_6_kill_switch]:
        ok, msg = fn()
        results.append((ok, msg))
        print(msg)

    # Async gates (require network)
    print("\n  [Network checks — may take a few seconds]")
    for coro in [gate_7_auth_check(), gate_8_balance_readable()]:
        ok, msg = await coro
        results.append((ok, msg))
        print(msg)

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    all_pass = passed == total

    print(f"\n{SEP}")
    if all_pass:
        print(f"  ALL {total}/{total} GATES PASSED -- SAFE TO GO LIVE")
    else:
        failed = total - passed
        print(f"  {failed}/{total} GATES FAILED -- DO NOT GO LIVE")
    print(f"{SEP}\n")

    return 0 if all_pass else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="MERID go-live preflight check")
    parser.parse_args()
    sys.exit(asyncio.run(run_all()))


if __name__ == "__main__":
    main()
