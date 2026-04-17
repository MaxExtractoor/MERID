#!/usr/bin/env python3
"""Risk Health CLI — Quick operator visibility into trading risk state.

Usage:
    python scripts/risk_health.py              # Full health report
    python scripts/risk_health.py --summary    # One-line status
    python scripts/risk_health.py --watch      # Continuous monitoring

Exit codes:
    0 — Trading allowed (healthy)
    1 — Trading blocked (kill switch, cooldown, or other blockers)
    2 — API error or unreachable
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Dict, Any, Optional

import requests


DEFAULT_BASE_URL = "http://localhost:8000"
RISK_THRESHOLD_PCT = 90.0  # Warn if any cap exceeds this utilization


def fetch_snapshot(base_url: str) -> Optional[Dict[str, Any]]:
    """Fetch risk snapshot from API."""
    try:
        resp = requests.get(
            f"{base_url}/api/risk/snapshot",
            timeout=10,
            headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to {base_url}")
        return None
    except requests.exceptions.Timeout:
        print(f"ERROR: Request to {base_url} timed out")
        return None
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP {e.response.status_code} from API")
        return None


def format_currency(value: float) -> str:
    """Format USD value."""
    if value >= 1000:
        return f"${value/1000:.1f}k"
    return f"${value:.0f}"


def print_health_report(snapshot: Dict[str, Any]) -> int:
    """Print formatted health report. Returns exit code."""
    ts = snapshot.get("timestamp", "unknown")
    blocked = snapshot.get("trading_blocked", False)
    reason = snapshot.get("trading_blocked_reason", "")
    
    # Header
    print(f"\n{'='*60}")
    print(f"MERID Risk Health Report — {ts}")
    print(f"{'='*60}")
    
    # Overall status
    if blocked:
        print(f"\n🔴 TRADING BLOCKED")
        print(f"   Reason: {reason}")
    else:
        print(f"\n🟢 Trading Allowed")
    
    # Kill switches
    print(f"\n--- Kill Switches ---")
    guard = snapshot.get("kill_switch_guard", {})
    rc = snapshot.get("kill_switch_risk_controller", {})
    print(f"  Guard:     {'🔴 ACTIVE' if guard.get('active') else '🟢 OK'}")
    if guard.get('active') and guard.get('reason'):
        print(f"             Reason: {guard['reason']}")
    print(f"  Risk Ctrl: {'🔴 ACTIVE' if rc.get('active') else '🟢 OK'}")
    if rc.get('active') and rc.get('reason'):
        print(f"             Reason: {rc['reason']}")
    
    # Asset caps
    print(f"\n--- Asset Caps ---")
    assets = snapshot.get("assets", {})
    if not assets:
        print("  No asset caps configured")
    else:
        for asset, data in sorted(assets.items()):
            pct = data.get("utilization_pct", 0)
            used = data.get("used", 0)
            limit = data.get("limit", 0)
            remaining = data.get("remaining", 0)
            
            # Status indicator
            if pct >= 95:
                icon = "🔴"
            elif pct >= RISK_THRESHOLD_PCT:
                icon = "🟡"
            else:
                icon = "🟢"
            
            print(f"  {icon} {asset:5s} {pct:5.1f}% ({format_currency(used)}/{format_currency(limit)}, {format_currency(remaining)} rem)")
    
    # Domain/venue caps
    print(f"\n--- Domain Caps ---")
    domains = snapshot.get("domains", {})
    for name, data in sorted(domains.items()):
        pct = data.get("utilization_pct", 0)
        used = data.get("used", 0)
        limit = data.get("limit", 0)
        print(f"  {name}: {pct:.1f}% ({format_currency(used)}/{format_currency(limit)})")
    
    print(f"\n--- Venue Caps ---")
    venues = snapshot.get("venues", {})
    for name, data in sorted(venues.items()):
        pct = data.get("utilization_pct", 0)
        used = data.get("used", 0)
        limit = data.get("limit", 0)
        print(f"  {name}: {pct:.1f}% ({format_currency(used)}/{format_currency(limit)})")
    
    # CQI
    print(f"\n--- CQI / Throttle ---")
    cqi = snapshot.get("cqi", {})
    score = cqi.get("score", 0)
    throttle = cqi.get("throttle_pct", 100)
    block_below = cqi.get("block_below", 0.3)
    
    if score < block_below:
        icon = "🔴"
    elif score < 0.6:
        icon = "🟡"
    else:
        icon = "🟢"
    
    print(f"  {icon} Score: {score:.2f} (throttle: {throttle:.0f}%, block below: {block_below:.2f})")
    
    # Cooldown
    print(f"\n--- Cooldown ---")
    cooldown = snapshot.get("cooldown", {})
    if cooldown.get("active"):
        remaining = cooldown.get("seconds_remaining", 0)
        print(f"  🟡 ACTIVE ({remaining:.1f}s remaining)")
    else:
        print(f"  🟢 Inactive")
    
    # Recent events
    protect_events = snapshot.get("recent_protect_events", [])
    cap_events = snapshot.get("recent_cap_events", [])
    
    if protect_events or cap_events:
        print(f"\n--- Recent Events ---")
        for evt in protect_events[-5:]:
            print(f"  🚨 {evt}")
        for evt in cap_events[-5:]:
            print(f"  ⚠️  {evt}")
    
    print(f"\n{'='*60}\n")
    
    return 1 if blocked else 0


def print_summary(snapshot: Dict[str, Any]) -> int:
    """Print one-line summary. Returns exit code."""
    blocked = snapshot.get("trading_blocked", False)
    reason = snapshot.get("trading_blocked_reason", "")
    
    # Asset status
    assets = snapshot.get("assets", {})
    high_util = [
        f"{a}:{d['utilization_pct']:.0f}%"
        for a, d in assets.items()
        if d.get("utilization_pct", 0) >= RISK_THRESHOLD_PCT
    ]
    
    status = "BLOCKED" if blocked else "OK"
    asset_str = ", ".join(high_util) if high_util else "all normal"
    
    print(f"Risk: {status} | Blockers: {reason or 'none'} | High util: {asset_str}")
    return 1 if blocked else 0


def watch_mode(base_url: str, interval: int = 30) -> None:
    """Continuous monitoring mode."""
    print(f"Watching risk state every {interval}s (Ctrl+C to exit)...")
    print(f"Base URL: {base_url}\n")
    
    prev_blocked = None
    
    while True:
        snapshot = fetch_snapshot(base_url)
        if snapshot is None:
            print(f"\n🔴 API UNREACHABLE at {time.strftime('%H:%M:%S')}")
            time.sleep(interval)
            continue
        
        blocked = snapshot.get("trading_blocked", False)
        ts = snapshot.get("timestamp", "?")[11:19]  # HH:MM:SS only
        
        # One-line status
        guard = snapshot.get("kill_switch_guard", {}).get("active", False)
        rc = snapshot.get("kill_switch_risk_controller", {}).get("active", False)
        cooldown = snapshot.get("cooldown", {}).get("active", False)
        
        status_parts = []
        if blocked:
            status_parts.append("BLOCKED")
            if guard:
                status_parts.append("guard")
            if rc:
                status_parts.append("risk_ctrl")
            if cooldown:
                status_parts.append("cooldown")
        else:
            status_parts.append("OK")
        
        status = "/".join(status_parts)
        
        # High utilization warning
        assets = snapshot.get("assets", {})
        high = [a for a, d in assets.items() if d.get("utilization_pct", 0) >= RISK_THRESHOLD_PCT]
        high_str = f" ⚠️ {','.join(high)}>90%" if high else ""
        
        # State change detection
        change_icon = ""
        if prev_blocked is not None and blocked != prev_blocked:
            change_icon = " 🔥 STATE CHANGE"
        prev_blocked = blocked
        
        print(f"[{ts}] {status}{high_str}{change_icon}")
        
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description="MERID Risk Health CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Full health report
  %(prog)s --summary          # One-line status check
  %(prog)s --watch            # Continuous monitoring
  %(prog)s --url http://prod:8000 --summary
        """
    )
    parser.add_argument(
        "--url", 
        default=DEFAULT_BASE_URL,
        help=f"Base URL for API (default: {DEFAULT_BASE_URL})"
    )
    parser.add_argument(
        "--summary", 
        action="store_true",
        help="Print one-line summary instead of full report"
    )
    parser.add_argument(
        "--watch", 
        action="store_true",
        help="Continuous monitoring mode"
    )
    parser.add_argument(
        "--interval", 
        type=int, 
        default=30,
        help="Watch mode interval in seconds (default: 30)"
    )
    
    args = parser.parse_args()
    
    if args.watch:
        try:
            watch_mode(args.url, args.interval)
        except KeyboardInterrupt:
            print("\nExiting watch mode.")
            sys.exit(0)
    else:
        snapshot = fetch_snapshot(args.url)
        if snapshot is None:
            sys.exit(2)
        
        if args.summary:
            exit_code = print_summary(snapshot)
        else:
            exit_code = print_health_report(snapshot)
        
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
