"""Canary readiness check before one-contract live trading."""

import os


def _get(name):
    return os.environ.get(name)


def _ok(value):
    return value and value.lower() in ("1", "true", "yes")


def main():
    issues = []
    notes = []

    # Credentials
    key_id = _get("KALSHI_API_KEY_ID") or _get("KALSHI_LIVE_API_KEY_ID")
    key_path = _get("KALSHI_PRIVATE_KEY_PATH") or _get("KALSHI_LIVE_PRIVATE_KEY_PATH")
    if not key_id:
        issues.append("KALSHI_API_KEY_ID (or KALSHI_LIVE_API_KEY_ID) is not set")
    if not key_path:
        issues.append("KALSHI_PRIVATE_KEY_PATH (or KALSHI_LIVE_PRIVATE_KEY_PATH) is not set")

    # Live mode
    if not _ok(_get("MERID_ALLOW_LIVE_TRADES")):
        issues.append("MERID_ALLOW_LIVE_TRADES is not true")
    if (_get("MERID_PM_TRADING_MODE") or "").lower() != "live":
        issues.append("MERID_PM_TRADING_MODE is not 'live'")

    # One-contract sizing
    max_pos = _get("KALSHI_TRADER_MAX_POSITION")
    if max_pos != "1":
        issues.append("KALSHI_TRADER_MAX_POSITION must be 1 for the canary")

    # EV gate and ledger (fall back to module defaults if env not set)
    ev_authoritative = _get("MERID_EV_GATE_AUTHORITATIVE")
    ledger_enabled = _get("MERID_ORDER_DECISION_LEDGER_ENABLED")
    if ev_authoritative is None:
        from merid.prediction.trade_decision import MERID_EV_GATE_AUTHORITATIVE
        ev_authoritative = str(MERID_EV_GATE_AUTHORITATIVE)
    if ledger_enabled is None:
        from merid.prediction.trade_decision import MERID_ORDER_DECISION_LEDGER_ENABLED
        ledger_enabled = str(MERID_ORDER_DECISION_LEDGER_ENABLED)
    if not _ok(ev_authoritative):
        issues.append("EV gate is not authoritative")
    if not _ok(ledger_enabled):
        issues.append("Order decision ledger is not enabled")

    # Stop candidate submission remains off
    try:
        from merid.config.live_config import get_resolved_live_config

        resolved = get_resolved_live_config(allow_unresolved=True)
        if resolved and resolved.resolved and resolved.stop_candidate_submission_enabled:
            issues.append("stop_candidate_submission_enabled is True in resolved live config")
        else:
            notes.append("stop_candidate_submission_enabled is False in resolved live config")
    except Exception as exc:
        issues.append(f"Could not resolve live config: {exc}")

    if issues:
        print("CANARY BLOCKED — fix before live:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("CANARY READY for one-contract live start.")
        for note in notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
