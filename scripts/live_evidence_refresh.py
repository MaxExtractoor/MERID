#!/usr/bin/env python3
"""External refresh of data/live_entry_evidence.json.

Runs the decision-audit-ledger evidence query in a separate process on a
query_only WAL connection - never takes the ledger writer lock and cannot
starve the audit pipeline.  Use this instead of MERID_LIVE_EVIDENCE_EXPORT=1
on hosts where the 48h join takes tens of minutes against the multi-GB
audit DB.

Schedule it out-of-process (Windows Task Scheduler, cron, etc.) at a
cadence well inside the evidence FRESH tier, e.g. every 12h:

    schtasks /create /tn "MERID live evidence refresh" /sc hourly /mo 12 ^
        /tr "C:\\Dev\\MERID\\.venv\\Scripts\\python.exe C:\\Dev\\MERID\\scripts\\refresh_live_evidence.py"

Usage:
    python scripts/refresh_live_evidence.py [--hours 48] [--db data/decision_audit.db]
"""

import argparse
import json
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=48.0,
                    help="trailing window of settled outcomes to aggregate")
    ap.add_argument("--db", default="data/decision_audit.db")
    ap.add_argument("--path", default="data/live_entry_evidence.json")
    args = ap.parse_args()

    os.environ["MERID_LIVE_EVIDENCE_PATH"] = args.path

    from merid.execution.decision_audit_ledger import DecisionAuditLedger

    t0 = time.time()
    fake = SimpleNamespace(db_path=args.db)
    DecisionAuditLedger._refresh_live_entry_evidence(fake, t0, args.hours)
    elapsed = time.time() - t0
    print(f"refresh completed in {elapsed:.1f}s")

    if os.path.exists(args.path):
        with open(args.path) as f:
            art = json.load(f)
        n = sum(
            rec["n"] for sides in art.get("assets", {}).values()
            for rec in sides.values())
        print(f"artifact: generated_at={art.get('generated_at'):.0f} "
              f"window_hours={art.get('window_hours')} rows_aggregated={n}")
        # _refresh_live_entry_evidence stamps generated_at with the start
        # time; restamp at completion so freshness tiers measure correctly.
        art["generated_at"] = time.time()
        tmp = args.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(art, f)
        os.replace(tmp, args.path)
        print("restamped generated_at -> now")
        return 0
    print("ERROR: artifact not written")
    return 1


if __name__ == "__main__":
    sys.exit(main())
