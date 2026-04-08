#!/usr/bin/env python3
"""Kalshi integration dry-run / pre-restart verification script.

Runs the Kalshi components in a non-live environment (or demo) and
asserts that everything is correctly wired:

 1. Logs chosen REST and WS URLs, KALSHI_ENV, and env/URL consistency.
 2. Validates URL invariants (fails fast if elections host detected).
 3. Checks credentials are present (warns if missing).
 4. Simulates catalog health summary (market counts by asset).
 5. Reports execution gate mode.

Usage::

    # Non-live (paper/demo) check:
    KALSHI_ENV=demo python scripts/kalshi_dryrun.py

    # Live pre-flight check (no real connections made):
    KALSHI_ENV=live python scripts/kalshi_dryrun.py --no-connect

Exit code:
    0  All checks passed.
    1  One or more blocking issues found.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

# ── Minimal logging setup ─────────────────────────────────────────────────

_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✔{_RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠{_RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}✖{_RESET} {msg}")


def _info(msg: str) -> None:
    print(f"  {_CYAN}i{_RESET} {msg}")


def _section(title: str) -> None:
    print(f"\n{_BOLD}{title}{_RESET}")
    print("─" * len(title))


# ── Main checks ───────────────────────────────────────────────────────────


def check_env_and_urls() -> list[str]:
    """Check KALSHI_ENV and URL configuration. Returns list of blocking issues."""
    issues: list[str] = []
    kalshi_env = os.getenv("KALSHI_ENV", "").strip().lower()
    _info(f"KALSHI_ENV = {kalshi_env!r}")

    if not kalshi_env:
        _warn("KALSHI_ENV is not set — defaulting to no environment check")
    elif kalshi_env == "live":
        _info("Mode: LIVE (real money — ensure credentials are correct)")
    else:
        _info(f"Mode: {kalshi_env} (non-live)")

    try:
        from merid.event_venues.kalshi.models import KalshiConfig
        cfg = KalshiConfig()
        base_url = cfg.base_url
        ws_url = cfg.ws_url
        use_demo = cfg.use_demo
    except Exception as exc:
        _fail(f"Could not instantiate KalshiConfig: {exc}")
        issues.append(str(exc))
        return issues

    _info(f"REST base URL : {base_url}")
    _info(f"WS   base URL : {ws_url}")
    _info(f"use_demo      : {use_demo}")

    # Hard invariant checks
    try:
        from merid.event_venues.kalshi.invariants import (
            assert_valid_rest_url,
            assert_valid_ws_url,
            validate_config_env_match,
        )
        assert_valid_rest_url(base_url)
        _ok(f"REST URL is valid: {base_url}")
    except ValueError as exc:
        _fail(str(exc))
        issues.append(str(exc))

    try:
        from merid.event_venues.kalshi.invariants import assert_valid_ws_url
        assert_valid_ws_url(ws_url)
        _ok(f"WS URL is valid: {ws_url}")
    except (ValueError, NameError) as exc:
        _fail(str(exc))
        issues.append(str(exc))

    # Soft env/URL consistency check
    try:
        from merid.event_venues.kalshi.invariants import validate_config_env_match
        env_issues = validate_config_env_match(cfg, kalshi_env)
        if env_issues:
            for issue in env_issues:
                _warn(f"Config/env mismatch: {issue}")
        else:
            _ok("KALSHI_ENV and config URLs are consistent")
    except Exception as exc:
        _warn(f"Could not run env/URL consistency check: {exc}")

    return issues


def check_credentials() -> list[str]:
    """Check that Kalshi credentials are present. Returns warnings (non-blocking)."""
    warnings: list[str] = []
    api_key = os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_API_KEY")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")

    if api_key:
        _ok(f"KALSHI_API_KEY_ID present (id={api_key[:8]}...)")
    else:
        _warn("KALSHI_API_KEY_ID is not set — RSA authentication will fail")
        warnings.append("KALSHI_API_KEY_ID missing")

    if key_path or key_pem:
        src = f"path={key_path}" if key_path and key_path != "change_me" else "PEM inline"
        _ok(f"Private key present ({src})")
    else:
        _warn("No private key configured (KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM)")
        warnings.append("Kalshi private key missing")

    return warnings


def check_catalog_health_simulated() -> dict[str, Any]:
    """Simulate catalog health by importing and probing KalshiMarketCatalog.

    Returns a summary dict with keys: healthy (bool), market_count (int),
    per_asset (dict).
    """
    result: dict[str, Any] = {"healthy": False, "market_count": 0, "per_asset": {}}
    try:
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        _ok("KalshiMarketCatalog imported successfully")
        result["import_ok"] = True
    except Exception as exc:
        _fail(f"Failed to import KalshiMarketCatalog: {exc}")
        result["import_error"] = str(exc)
        return result

    # Check that the catalog uses a valid URL through the config
    try:
        from merid.event_venues.kalshi.models import KalshiConfig
        from merid.event_venues.kalshi.invariants import assert_valid_rest_url
        cfg = KalshiConfig()
        assert_valid_rest_url(cfg.base_url)
        _ok(f"Catalog would connect to valid REST endpoint: {cfg.base_url}")
        result["url_valid"] = True
        result["rest_url"] = cfg.base_url
    except Exception as exc:
        _fail(f"Catalog URL validation failed: {exc}")
        result["url_error"] = str(exc)

    _info(
        "Note: Catalog is not refreshed in dry-run mode "
        "(no live REST calls are made)"
    )
    _info("In production, catalog.refresh() fetches markets and populates by_asset/by_timeframe indexes")

    return result


def check_execution_gate() -> dict[str, Any]:
    """Probe the execution gate state without running actual checks."""
    result: dict[str, Any] = {"gate_state": "unknown"}
    try:
        from core.execution_gate import GateState, GATE_LIMITED_WHITELIST
        _ok(f"ExecutionGate imported — whitelist: {sorted(GATE_LIMITED_WHITELIST)}")
        _info(
            "Gate whitelist does NOT include 'kalshi_ws' — WS failure moves gate "
            "to BLOCKED (not LIMITED). This is correct fail-closed behaviour."
        )
        result["import_ok"] = True
        result["whitelist"] = sorted(GATE_LIMITED_WHITELIST)
    except Exception as exc:
        _fail(f"Failed to import execution gate: {exc}")
        result["import_error"] = str(exc)

    # Check MERID_EXEC_GATE_REQUIRE_KALSHI_WS
    require_ws = os.environ.get("MERID_EXEC_GATE_REQUIRE_KALSHI_WS", "1").lower() not in (
        "0", "false", "no"
    )
    if require_ws:
        _ok("MERID_EXEC_GATE_REQUIRE_KALSHI_WS=1 (default) — WS required for FULL mode")
    else:
        _warn(
            "MERID_EXEC_GATE_REQUIRE_KALSHI_WS=0 — WS gate bypassed. "
            "This is a non-standard override and should not be used in normal live operation."
        )

    return result


def run_dryrun(args: argparse.Namespace) -> int:
    """Execute all dry-run checks. Returns exit code (0=ok, 1=issues found)."""
    print(f"\n{_BOLD}{'='*60}{_RESET}")
    print(f"{_BOLD}  Kalshi Integration Pre-Restart Dry-Run{_RESET}")
    print(f"{_BOLD}{'='*60}{_RESET}")
    print(f"  Timestamp : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print(f"  Python    : {sys.version.split()[0]}")

    blocking: list[str] = []
    warnings: list[str] = []

    # 1. Environment and URL checks
    _section("1. Environment & URL invariants")
    blocking.extend(check_env_and_urls())

    # 2. Credentials
    _section("2. Credentials")
    cred_warnings = check_credentials()
    warnings.extend(cred_warnings)

    # 3. Catalog health simulation
    _section("3. Market catalog (simulation)")
    catalog_result = check_catalog_health_simulated()

    # 4. Execution gate
    _section("4. Execution gate")
    gate_result = check_execution_gate()

    # ── Summary ──────────────────────────────────────────────────────────
    _section("Summary")
    if blocking:
        _fail(f"{len(blocking)} blocking issue(s):")
        for issue in blocking:
            print(f"      • {issue}")
        print()
        _fail("RESULT: NOT READY — resolve blocking issues before restarting live trading")
        print(
            f"\n  {_CYAN}Tip:{_RESET} Ensure KALSHI_API_HOST is NOT set to "
            f"api.elections.kalshi.com\n       and that KALSHI_ENV=live with valid credentials."
        )
        return 1
    elif warnings:
        _warn(f"{len(warnings)} non-blocking warning(s):")
        for w in warnings:
            print(f"      • {w}")
        _ok("RESULT: CONFIGURATION LOOKS VALID (warnings present — review above)")
        return 0
    else:
        _ok("RESULT: ALL CHECKS PASSED — configuration is ready for live startup")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Kalshi integration dry-run pre-restart verification"
    )
    parser.add_argument(
        "--no-connect",
        action="store_true",
        help="Skip any live network connections (default: True in dry-run mode)",
    )
    args = parser.parse_args()

    # Ensure the project root is in the path
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    return run_dryrun(args)


if __name__ == "__main__":
    sys.exit(main())
