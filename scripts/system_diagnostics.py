#!/usr/bin/env python3
"""
MERID System Diagnostics - Deep Audit for Live Trading Readiness
=================================================================

Comprehensive system audit that checks all critical subsystems required for
live Kalshi trading. Use this before enabling KALSHI_ENV=live.

This script performs a deep system audit covering:
  1. Environment configuration validation
  2. Kalshi WebSocket health and connectivity
  3. Market catalog availability and freshness
  4. Execution gate status (all safety checks)
  5. Dependency health status
  6. Trading mode and safety interlock verification

Usage:
    python scripts/system_diagnostics.py
    python scripts/system_diagnostics.py --verbose   # detailed output
    python scripts/system_diagnostics.py --json      # machine-readable JSON output

Exit codes:
    0  System READY for live trading
    1  System NOT READY - issues found
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure repo root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def print_header(title: str, width: int = 80) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_status(label: str, status: str, detail: str = "", indent: int = 2) -> None:
    """Print a status line with color coding."""
    status_icon = {
        "PASS": "✅",
        "FAIL": "❌",
        "WARN": "⚠️",
        "INFO": "ℹ️",
        "UNKNOWN": "❓",
    }.get(status, "•")

    indent_str = " " * indent
    print(f"{indent_str}{status_icon} {label}")
    if detail:
        print(f"{indent_str}   {detail}")


async def audit_environment_config() -> Dict[str, Any]:
    """Audit environment configuration for live trading readiness."""
    print_header("1. ENVIRONMENT CONFIGURATION AUDIT")

    from merid.settings import settings

    results = {
        "status": "PASS",
        "issues": [],
        "warnings": [],
        "config": {}
    }

    # Check MERID_ENV
    print_status(f"MERID_ENV: {settings.MERID_ENV}", "INFO")
    results["config"]["MERID_ENV"] = settings.MERID_ENV

    # Check trading mode settings
    print_status(f"MERID_PM_TRADING_MODE: {settings.MERID_PM_TRADING_MODE}", "INFO")
    print_status(f"MERID_PM_LIVE_ENABLED: {settings.MERID_PM_LIVE_ENABLED}", "INFO")
    print_status(f"MERID_LIVE_TRADING_UNLOCKED: {settings.MERID_LIVE_TRADING_UNLOCKED}", "INFO")

    results["config"]["MERID_PM_TRADING_MODE"] = settings.MERID_PM_TRADING_MODE
    results["config"]["MERID_PM_LIVE_ENABLED"] = settings.MERID_PM_LIVE_ENABLED
    results["config"]["MERID_LIVE_TRADING_UNLOCKED"] = settings.MERID_LIVE_TRADING_UNLOCKED

    # Check Kalshi environment
    print_status(f"KALSHI_ENV: {settings.KALSHI_ENV}", "INFO")
    print_status(f"KALSHI_USE_DEMO: {settings.KALSHI_USE_DEMO}", "INFO")

    results["config"]["KALSHI_ENV"] = settings.KALSHI_ENV
    results["config"]["KALSHI_USE_DEMO"] = settings.KALSHI_USE_DEMO

    # Validate consistency
    validation = settings.validate_for_go_live(venues=["kalshi"])
    if not validation["ready"]:
        results["status"] = "FAIL"
        results["issues"].extend(validation["issues"])
        for issue in validation["issues"]:
            print_status(issue, "FAIL")
    else:
        print_status("All environment settings validated", "PASS")

    if validation["warnings"]:
        results["warnings"].extend(validation["warnings"])
        for warning in validation["warnings"]:
            print_status(warning, "WARN")

    return results


async def audit_websocket_health() -> Dict[str, Any]:
    """Audit Kalshi WebSocket connection health."""
    print_header("2. KALSHI WEBSOCKET HEALTH AUDIT")

    from merid.monitoring.dependency_health import check_kalshi_websocket_health

    health = check_kalshi_websocket_health()

    results = {
        "status": "PASS" if health.is_healthy else "FAIL",
        "health_status": health.status.value,
        "message": health.message,
        "details": health.details or {},
    }

    status_map = {
        "healthy": "PASS",
        "degraded": "WARN",
        "down": "FAIL",
        "unknown": "UNKNOWN",
        "disabled": "INFO",
    }

    print_status(f"WebSocket Status: {health.status.value}", status_map.get(health.status.value, "INFO"))
    print_status(health.message, "INFO", indent=4)

    if health.details:
        print_status("Connection Details:", "INFO", indent=4)
        for key, value in health.details.items():
            print_status(f"{key}: {value}", "INFO", indent=6)

    if not health.is_healthy:
        results["issues"] = [health.message]

    return results


async def audit_market_catalog() -> Dict[str, Any]:
    """Audit market catalog availability and freshness."""
    print_header("3. MARKET CATALOG AUDIT")

    from merid.monitoring.dependency_health import check_market_catalog_health

    health = check_market_catalog_health()

    results = {
        "status": "PASS" if health.is_healthy else "FAIL",
        "health_status": health.status.value,
        "message": health.message,
        "details": health.details or {},
    }

    status_map = {
        "healthy": "PASS",
        "degraded": "WARN",
        "down": "FAIL",
        "unknown": "UNKNOWN",
    }

    print_status(f"Catalog Status: {health.status.value}", status_map.get(health.status.value, "INFO"))
    print_status(health.message, "INFO", indent=4)

    if health.details:
        print_status("Catalog Details:", "INFO", indent=4)
        for key, value in health.details.items():
            print_status(f"{key}: {value}", "INFO", indent=6)

    if not health.is_healthy:
        results["issues"] = [health.message]

    return results


async def audit_execution_gate() -> Dict[str, Any]:
    """Audit execution gate status and all safety checks."""
    print_header("4. EXECUTION GATE SAFETY CHECKS")

    from core.execution_gate import check_execution_gate

    gate = check_execution_gate()

    results = {
        "status": "PASS" if not gate.blocked else "FAIL",
        "gate_state": gate.gate_state,
        "safe_to_trade": gate.safe_to_trade,
        "blocked": gate.blocked,
        "reasons": [
            {
                "source": r.source,
                "severity": r.severity,
                "message": r.message,
                "details": r.details,
                "hint": r.hint,
            }
            for r in gate.reasons
        ],
    }

    print_status(f"Gate State: {gate.gate_state.upper()}", "PASS" if not gate.blocked else "FAIL")
    print_status(f"Safe to Trade: {gate.safe_to_trade}", "PASS" if gate.safe_to_trade else "FAIL")

    if gate.reasons:
        print_status("Safety Check Results:", "INFO", indent=4)
        for reason in gate.reasons:
            severity_status = "FAIL" if reason.severity == "critical" else "WARN"
            print_status(f"[{reason.source}] {reason.message}", severity_status, indent=6)
            if reason.details:
                print_status(reason.details, "INFO", indent=8)
            if reason.hint:
                print_status(f"Fix: {reason.hint}", "INFO", indent=8)
    else:
        print_status("All safety checks passed", "PASS", indent=4)

    return results


async def audit_dependency_health() -> Dict[str, Any]:
    """Audit overall dependency health."""
    print_header("5. DEPENDENCY HEALTH AUDIT")

    from merid.monitoring.dependency_health import get_overall_dependency_health

    health = get_overall_dependency_health()

    results = {
        "status": "PASS" if health["overall_status"] == "healthy" else "FAIL",
        "overall_status": health["overall_status"],
        "dependencies": {
            "kalshi_websocket": health["kalshi_websocket"],
            "market_catalog": health["market_catalog"],
        },
        "critical_issues": health["critical_issues"],
    }

    status_map = {
        "healthy": "PASS",
        "degraded": "WARN",
        "down": "FAIL",
    }

    print_status(f"Overall Status: {health['overall_status']}", status_map.get(health["overall_status"], "INFO"))

    # WebSocket
    ws_status = health["kalshi_websocket"]["status"]
    print_status(f"Kalshi WebSocket: {ws_status}", status_map.get(ws_status, "INFO"), indent=4)
    print_status(health["kalshi_websocket"]["message"], "INFO", indent=6)

    # Market Catalog
    catalog_status = health["market_catalog"]["status"]
    print_status(f"Market Catalog: {catalog_status}", status_map.get(catalog_status, "INFO"), indent=4)
    print_status(health["market_catalog"]["message"], "INFO", indent=6)

    # Critical Issues
    if health["critical_issues"]:
        print_status("Critical Issues:", "FAIL", indent=4)
        for issue in health["critical_issues"]:
            print_status(issue, "FAIL", indent=6)

    return results


async def audit_trading_readiness() -> Dict[str, Any]:
    """Final readiness check - are we ready to trade live?"""
    print_header("6. FINAL TRADING READINESS ASSESSMENT")

    from merid.monitoring.dependency_health import is_trading_ready

    ready, issues = is_trading_ready()

    results = {
        "status": "PASS" if ready else "FAIL",
        "ready": ready,
        "issues": issues,
    }

    if ready:
        print_status("System READY for live trading", "PASS")
    else:
        print_status("System NOT READY for live trading", "FAIL")
        print_status("Blocking Issues:", "INFO", indent=4)
        for issue in issues:
            print_status(issue, "FAIL", indent=6)

    return results


async def run_full_audit(verbose: bool = False) -> Dict[str, Any]:
    """Run complete system audit."""
    start_time = time.time()

    print("\n" + "=" * 80)
    print("  MERID SYSTEM DIAGNOSTICS - LIVE TRADING READINESS AUDIT")
    print("=" * 80)
    print(f"  Audit Time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 80)

    audit_results = {
        "timestamp": time.time(),
        "audit_time_iso": time.strftime('%Y-%m-%d %H:%M:%S %Z'),
        "overall_status": "PASS",
        "sections": {},
    }

    # Run all audit sections
    sections = [
        ("environment", audit_environment_config()),
        ("websocket", audit_websocket_health()),
        ("market_catalog", audit_market_catalog()),
        ("execution_gate", audit_execution_gate()),
        ("dependency_health", audit_dependency_health()),
        ("trading_readiness", audit_trading_readiness()),
    ]

    for section_name, section_coro in sections:
        result = await section_coro
        audit_results["sections"][section_name] = result
        if result["status"] == "FAIL":
            audit_results["overall_status"] = "FAIL"

    elapsed = time.time() - start_time
    audit_results["audit_duration_seconds"] = round(elapsed, 2)

    # Final summary
    print_header("AUDIT SUMMARY")
    print_status(f"Overall Status: {audit_results['overall_status']}", audit_results["overall_status"])
    print_status(f"Audit Duration: {elapsed:.2f}s", "INFO")

    if audit_results["overall_status"] == "PASS":
        print("\n✅ SYSTEM READY FOR LIVE TRADING")
        print("\nNext steps:")
        print("  1. Set KALSHI_ENV=prod in .env")
        print("  2. Set MERID_PM_TRADING_MODE=live in .env")
        print("  3. Set MERID_PM_LIVE_ENABLED=true in .env")
        print("  4. Set MERID_LIVE_TRADING_UNLOCKED=true in .env")
        print("  5. Run scripts/go_live_preflight.py to verify all gates")
        print("  6. Monitor execution for first 30 minutes closely")
    else:
        print("\n❌ SYSTEM NOT READY - RESOLVE ISSUES BEFORE GOING LIVE")
        print("\nIssues found:")

        # Collect all issues
        all_issues = []
        for section_name, section_result in audit_results["sections"].items():
            if "issues" in section_result and section_result["issues"]:
                all_issues.extend([(section_name, issue) for issue in section_result["issues"]])
            # Check for nested reasons (execution gate)
            if "reasons" in section_result and section_result["reasons"]:
                critical_reasons = [r for r in section_result["reasons"] if r["severity"] == "critical"]
                all_issues.extend([(section_name, r["message"]) for r in critical_reasons])

        for i, (section, issue) in enumerate(all_issues, 1):
            print(f"  {i}. [{section}] {issue}")

    print()
    return audit_results


def main() -> None:
    parser = argparse.ArgumentParser(description="MERID system diagnostics for live trading")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    results = asyncio.run(run_full_audit(verbose=args.verbose))

    if args.json:
        print(json.dumps(results, indent=2))

    sys.exit(0 if results["overall_status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
