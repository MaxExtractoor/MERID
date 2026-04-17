#!/usr/bin/env python3
"""Simple smoke test: fire many risk warnings quickly to exercise
PredictionAlertManager suppression and the Telegram buffered sink.

Run from repo root:
    py -3 scripts\smoke_test_alerts.py
"""
import time
from datetime import datetime

from merid.prediction.alerts import get_alert_manager


def main() -> None:
    mgr = get_alert_manager()
    print(f"Sinks registered: {len(mgr._sinks)}")

    market_id = "KXBTC-26MAR2117"
    print(f"Firing 20 rapid warnings for market {market_id}...")

    for i in range(20):
        msg = f"Simulated rapid warning #{i} (strike {i})"
        mgr.fire_risk_warning(market_id, msg, data={"strike": i})
        time.sleep(0.15)

    print("Fired messages. Recent alert summary:")
    summary = mgr.summary()
    print(f"  total_alerts: {summary['total_alerts']}")
    print(f"  sinks_registered: {summary['sinks_registered']}")
    print("  recent titles:")
    for a in summary["recent"]:
        ts = a.get("timestamp")
        print(f"    - [{a['severity']}] {a['title']} @ {ts}")

    print("Waiting 12s to allow any buffered Telegram flushes/backoff to run...")
    time.sleep(12)

    print("Done.")


if __name__ == '__main__':
    main()
