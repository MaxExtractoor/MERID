"""Escape-cohort emission die-off diagnostic (decision_audit.db).

The claim>=+2c split audit found 81% of the cohort carries
``admission_owner='evidence_escape'`` with ``decision_lane`` mostly NaN
and ZERO actual fills in ~4.7d.  This script rebuilds the funnel for
that cohort directly from the audit DB:

  side_ev (admission_owner=evidence_escape, expected_net_ev>=2)
    -> strategy_decisions (selected_side / admission_lane /
       primary_reason_code / reason_codes)
    -> strategy_decision_events (event_type x stage x reason_code)

plus a control cohort (same claim threshold, other admission owners)
so die-off rates are comparable.  HDD-bound DB: all reads are
decision_ts-sliced (6h) and event lookups go through the
decision_id index — never bare count(*) scans.

    python scripts/audit_escape_emission_dieoff.py [--days N]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

DB = "data/decision_audit.db"
OUT_JSON = "reports/escape_emission_dieoff.json"
SLICE_S = 6 * 3600
CLAIM_THR = 2.0
OWNER = "evidence_escape"

COHORT_SQL = """
SELECT e.decision_id, e.side, e.expected_net_ev_cents, e.decision_lane,
       e.admission_owner, e.exclusion_reason, e.selected, e.executable,
       e.passed_net_ev, e.counterfactual_execution_status,
       e.gate_ev_cents, e.required_edge_cents,
       d.decision_ts, d.ticker, d.selected_side, d.admission_lane AS d_lane,
       d.primary_reason_code, d.reason_codes, d.decision
FROM strategy_decision_side_ev e
JOIN strategy_decisions d ON e.decision_id = d.decision_id
WHERE e.expected_net_ev_cents >= ?
  AND (e.admission_owner = ? OR e.admission_owner IS NULL
       OR e.admission_owner = '' OR e.admission_owner != ?)
  AND d.decision_ts BETWEEN ? AND ?
"""

# Two passes: escape-owned rows and everything else (control).
ESCAPE_SQL = COHORT_SQL.replace(
    "(e.admission_owner = ? OR e.admission_owner IS NULL\n"
    "       OR e.admission_owner = '' OR e.admission_owner != ?)",
    "e.admission_owner = ?",
)
CONTROL_SQL = COHORT_SQL.replace(
    "(e.admission_owner = ? OR e.admission_owner IS NULL\n"
    "       OR e.admission_owner = '' OR e.admission_owner != ?)",
    "(e.admission_owner IS NULL OR e.admission_owner = '' "
    "OR e.admission_owner != ?)",
)

EVENTS_SQL = """
SELECT decision_id, event_type, stage, reason_code
FROM strategy_decision_events
WHERE decision_id IN ({placeholders})
"""


def _slices(lo: float, hi: float):
    t = lo
    while t < hi:
        yield t, min(t + SLICE_S, hi)
        t += SLICE_S


def fetch_cohort(conn, sql, lo, hi, owner):
    rows = []
    for a, b in _slices(lo, hi):
        try:
            rows.extend(conn.execute(sql, (CLAIM_THR, owner, a, b)).fetchall())
        except Exception as exc:
            print(f"slice {a}-{b} FAILED: {exc}", flush=True)
    return rows


def counter_dict(rows, idx):
    c = Counter()
    for r in rows:
        c[str(r[idx])] += 1
    return dict(c.most_common(40))


def funnel(decision_ids, conn, batch=400):
    """event_type/stage/reason_code counts + per-decision terminal mix."""
    ev_counts = Counter()
    term = Counter()
    ids = sorted(set(decision_ids))
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        ph = ",".join("?" for _ in chunk)
        try:
            for did, et, st, rc in conn.execute(
                    EVENTS_SQL.format(placeholders=ph), chunk):
                ev_counts[(str(et), str(st), str(rc))] += 1
        except Exception as exc:
            print(f"events batch {i} FAILED: {exc}", flush=True)
    return ev_counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=0,
                    help="limit to last N days (0 = full span)")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=300)
    mn, mx = conn.execute(
        "SELECT min(decision_ts), max(decision_ts) FROM strategy_decisions"
    ).fetchone()
    hi = mx
    lo = mn if args.days <= 0 else max(mn, mx - args.days * 86400)
    print(f"span {lo:.0f} -> {hi:.0f} "
          f"({(hi - lo) / 86400:.1f} days)", flush=True)

    rep = {"span": [lo, hi], "claim_threshold": CLAIM_THR,
           "owner": OWNER}

    # ---- cohort extraction (two passes) ----
    esc = fetch_cohort(conn, ESCAPE_SQL, lo, hi, OWNER)
    ctl = fetch_cohort(conn, CONTROL_SQL, lo, hi, OWNER)
    print(f"escape rows={len(esc)} control rows={len(ctl)}", flush=True)

    def summarize(rows, tag):
        dids = {r[0] for r in rows}
        s = {
            "n_side_evals": len(rows),
            "n_decisions": len(dids),
            "selected_side_nonnull": sum(1 for r in rows
                                         if r[14] not in (None, "")),
            "side_selected": sum(1 for r in rows if r[6] == 1),
            "side_executable": sum(1 for r in rows if r[7] == 1),
            "side_passed_net_ev": sum(1 for r in rows if r[8] == 1),
            "exec_status": counter_dict(rows, 9),
            "side_exclusion_reason": counter_dict(rows, 5),
            "decision_lane": counter_dict(rows, 3),
            "d_admission_lane": counter_dict(rows, 15),
            "primary_reason_code": counter_dict(rows, 16),
            "reason_codes": counter_dict(rows, 17),
            "decision_field": counter_dict(rows, 18),
        }
        rep[tag] = s
        return dids

    esc_dids = summarize(esc, "escape_cohort")
    ctl_dids = summarize(ctl, "control_cohort")

    # ---- event funnel ----
    print("escape events ...", flush=True)
    esc_ev = funnel(esc_dids, conn)
    rep["escape_events"] = {
        f"{et}|{st}|{rc}": c for (et, st, rc), c in esc_ev.most_common(80)}
    # per-decision terminal-state mix: last event per decision
    print("control events ...", flush=True)
    ctl_ev = funnel(ctl_dids, conn)
    rep["control_events"] = {
        f"{et}|{st}|{rc}": c for (et, st, rc), c in ctl_ev.most_common(80)}

    # ---- sanity notes (static) ----
    rep["sanity"] = {
        "evidence_escape_lane_env": "MERID_EVIDENCE_ESCAPE_LANE "
        "(default True; no .env override observed)",
        "hard_block_mode_env": "MERID_EVIDENCE_HARD_BLOCK_MODE=challenge "
        "(.env line 748)",
        "post_only_lane_sets": [
            "maker_taker_integration.py fallback: decision_lane in "
            "(threshold_cell, evidence_cell_escape, "
            "current_build_provisional) AND post_only",
            "order_router._intent_requires_post_only: same set + "
            "execution_policy.required_post_only",
            "resolve_bounded_lane_execution_policy: does NOT include "
            "evidence_cell_escape (threshold_cell, "
            "current_build_provisional, empirical_marginal_maker, "
            "pinned_fav only)",
        ],
        "provenance_check": "order_router._validate_decision_provenance "
        "requires decision_id/run_id/confidence/confidence_valid/"
        "confidence_source/settlement_reference/data_state/regime_label "
        "— decision_lane is NOT in the checklist",
    }

    Path(OUT_JSON).parent.mkdir(exist_ok=True)
    Path(OUT_JSON).write_text(json.dumps(rep, indent=2, default=str))
    print(json.dumps({k: v for k, v in rep.items()
                      if k != "escape_events" and k != "control_events"},
                     indent=2, default=str)[:6000])
    print("\n-- escape_events top --")
    for k, v in list(rep["escape_events"].items())[:40]:
        print(f"{v:6d}  {k}")
    print("\n-- control_events top --")
    for k, v in list(rep["control_events"].items())[:40]:
        print(f"{v:6d}  {k}")
    print(f"\nwrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
