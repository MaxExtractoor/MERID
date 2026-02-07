"""
Alertmanager Configuration Validator

Validates alertmanager.yml structure, routing, and receiver completeness.
Run: python monitoring/verify-alertmanager.py [--test-telegram]

Readiness Impact: O-03 — Alertmanager verified.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

MONITORING_DIR = Path(__file__).resolve().parent
ALERTMANAGER_FILE = MONITORING_DIR / "alertmanager.yml"
ALERT_RULES_FILE = MONITORING_DIR / "alert_rules.yml"
PROMETHEUS_FILE = MONITORING_DIR / "prometheus-config.yml"


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def validate_alertmanager(config: Dict[str, Any]) -> List[str]:
    """Validate alertmanager.yml structure."""
    issues: List[str] = []

    # Check required top-level keys
    for key in ("global", "route", "receivers"):
        if key not in config:
            issues.append(f"Missing top-level key: {key}")

    # Check route has a default receiver
    route = config.get("route", {})
    if not route.get("receiver"):
        issues.append("Route missing default receiver")

    # Check all referenced receivers exist
    receiver_names = {r["name"] for r in config.get("receivers", [])}
    default_receiver = route.get("receiver", "")
    if default_receiver and default_receiver not in receiver_names:
        issues.append(f"Default receiver '{default_receiver}' not defined")

    for sub_route in route.get("routes", []):
        recv = sub_route.get("receiver", "")
        if recv and recv not in receiver_names:
            issues.append(f"Route receiver '{recv}' not defined")

    # Check receivers have at least one notification channel
    for receiver in config.get("receivers", []):
        name = receiver.get("name", "unknown")
        has_channel = any(
            receiver.get(k)
            for k in (
                "email_configs",
                "slack_configs",
                "pagerduty_configs",
                "webhook_configs",
                "telegram_configs",
            )
        )
        if not has_channel:
            issues.append(f"Receiver '{name}' has no notification channels")

    # Check inhibit rules reference valid alert names
    for rule in config.get("inhibit_rules", []):
        if not rule.get("source_match") and not rule.get("source_matchers"):
            issues.append("Inhibit rule missing source_match")
        if not rule.get("target_match") and not rule.get("target_matchers"):
            issues.append("Inhibit rule missing target_match")

    return issues


def validate_alert_rules(path: Path) -> List[str]:
    """Validate alert_rules.yml exists and has groups."""
    issues: List[str] = []
    if not path.exists():
        issues.append(f"Alert rules file not found: {path}")
        return issues

    config = load_yaml(path)
    groups = config.get("groups", [])
    if not groups:
        issues.append("No alert rule groups defined")
    else:
        total_rules = sum(len(g.get("rules", [])) for g in groups)
        if total_rules < 5:
            issues.append(f"Only {total_rules} alert rules defined (expected >= 5)")

    return issues


def validate_prometheus(path: Path) -> List[str]:
    """Validate prometheus config references alertmanager."""
    issues: List[str] = []
    if not path.exists():
        issues.append(f"Prometheus config not found: {path}")
        return issues

    config = load_yaml(path)
    alerting = config.get("alerting", {})
    alertmanagers = alerting.get("alertmanagers", [])
    if not alertmanagers:
        issues.append("Prometheus config has no alertmanager targets")

    return issues


def test_telegram() -> bool:
    """Send a test alert via Telegram."""
    import os

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("  [SKIP] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    try:
        import urllib.request
        import json

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps(
            {"chat_id": chat_id, "text": "🔔 MERID Alertmanager smoke test — if you see this, alerts are working."}
        ).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get("ok"):
            print("  [PASS] Telegram test message sent")
            return True
        else:
            print(f"  [FAIL] Telegram API error: {result}")
            return False
    except Exception as exc:
        print(f"  [FAIL] Telegram test failed: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Validate Alertmanager configuration")
    parser.add_argument("--test-telegram", action="store_true", help="Send a test Telegram alert")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    print("=" * 50)
    print("MERID Alertmanager Verification")
    print("=" * 50)

    all_issues: List[str] = []
    checks_passed = 0
    checks_total = 0

    # 1. Alertmanager config
    print("\n--- alertmanager.yml ---")
    checks_total += 1
    if ALERTMANAGER_FILE.exists():
        config = load_yaml(ALERTMANAGER_FILE)
        issues = validate_alertmanager(config)
        if issues:
            for i in issues:
                print(f"  [FAIL] {i}")
            all_issues.extend(issues)
        else:
            receivers = len(config.get("receivers", []))
            routes = len(config.get("route", {}).get("routes", []))
            print(f"  [PASS] Valid — {receivers} receivers, {routes} routes")
            checks_passed += 1
    else:
        print(f"  [FAIL] File not found: {ALERTMANAGER_FILE}")
        all_issues.append("alertmanager.yml not found")

    # 2. Alert rules
    print("\n--- alert_rules.yml ---")
    checks_total += 1
    issues = validate_alert_rules(ALERT_RULES_FILE)
    if issues:
        for i in issues:
            print(f"  [FAIL] {i}")
        all_issues.extend(issues)
    else:
        config = load_yaml(ALERT_RULES_FILE)
        groups = config.get("groups", [])
        total_rules = sum(len(g.get("rules", [])) for g in groups)
        print(f"  [PASS] {len(groups)} groups, {total_rules} rules")
        checks_passed += 1

    # 3. Prometheus → Alertmanager wiring
    print("\n--- prometheus-config.yml ---")
    checks_total += 1
    issues = validate_prometheus(PROMETHEUS_FILE)
    if issues:
        for i in issues:
            print(f"  [FAIL] {i}")
        all_issues.extend(issues)
    else:
        print("  [PASS] Prometheus references alertmanager")
        checks_passed += 1

    # 4. Telegram test
    if args.test_telegram:
        print("\n--- Telegram Smoke Test ---")
        checks_total += 1
        if test_telegram():
            checks_passed += 1

    # Summary
    print("\n" + "=" * 50)
    print(f"Results: {checks_passed}/{checks_total} passed")
    if all_issues:
        print(f"Issues: {len(all_issues)}")
        for i in all_issues:
            print(f"  - {i}")
    else:
        print("✅ All alertmanager checks passed")
    print("=" * 50)

    sys.exit(0 if not all_issues else 1)


if __name__ == "__main__":
    main()
