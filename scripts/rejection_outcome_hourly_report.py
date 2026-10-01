"""Canonical rejection/outcome report over the decision audit ledger.

Single source of truth: ``data/decision_audit.db`` (SQLite, WAL).  Reads only
the audit projection — ``strategy_decisions`` + ``strategy_decision_events`` +
``strategy_decision_outcomes`` + ``strategy_decision_side_ev`` — never the
JSONL telemetry streams, which remain operational/debug artifacts.

For a fixed ``run_id`` and decision-time window the report answers, per
*actual blocking stage* (not just the model's first failure):

  - how many candidates each stage rejected and for which reasons;
  - whether the rejections were correct, measured by the rejected contract's
    OFFICIAL settlement outcome priced at the recorded decision-time
    executable entry, net of the versioned fee/slippage model and scaled to
    the fill quantity the book could actually absorb;
  - how many candidates were fully / partially / not executable, and how many
    remain unresolved or were excluded for data quality.

A rejected trade is never labelled a winner because spot later moved the
"right" way — the counterfactual applies only when a specific side's recorded
executable quote could have filled, and is reported separately by
executability class.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\rejection_outcome_hourly_report.py --run-id RUN_2026_10_05T12_00
    .\\.venv\\Scripts\\python.exe scripts\\rejection_outcome_hourly_report.py --run-id RUN --start-utc 2026-10-05T12:00:00Z --end-utc 2026-10-05T13:00:00Z
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_FLAT_EPS_CENTS = 1.0
_WINDOW_S = 900.0

# Stage used when a candidate died before compute_trade_decision.
_PRE_DECISION = "PRE_DECISION"


def _parse_ts(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _price_bucket(cents: Optional[float]) -> str:
    if cents is None:
        return "unknown"
    lo = int(float(cents) // 10) * 10
    return f"{lo:02d}-{lo + 9:02d}c"


def _tte_bucket(secs: Optional[float]) -> str:
    if secs is None:
        return "unknown"
    if secs < 180:
        return "<3m"
    if secs < 420:
        return "3-7m"
    if secs < 720:
        return "7-12m"
    return "12-15m"


def _shortfall_band(shortfall: Optional[float]) -> str:
    if shortfall is None:
        return "n/a"
    if shortfall <= 1.0:
        return "0-1c (marginal)"
    if shortfall <= 2.0:
        return "1-2c"
    if shortfall <= 5.0:
        return "2-5c"
    return "5c+"


def _window_label(close_ts: Optional[float], run_start: float) -> str:
    if close_ts is None:
        return "unknown"
    idx = int((float(close_ts) - run_start) // _WINDOW_S)
    idx = max(0, min(idx, 3))
    return f"W{idx + 1}"


def _terminal_stage(events: List[Dict[str, Any]], model_reason: str) -> Tuple[str, Optional[str]]:
    """Actual blocking stage: latest rejection/veto event wins; the model row
    is the fallback when no post-model event exists."""
    priority = {
        "ALLOCATION_REJECTED": ("ALLOCATION", None),
        "RISK_REJECTED": ("RISK", None),
        "COOLDOWN_REJECTED": ("RISK", None),
        "ROUTER_REJECTED": ("ROUTER", None),
        "PRE_DECISION_REJECTED": (_PRE_DECISION, None),
    }
    # Latest event by ts already ordered desc.
    for ev in events:
        et = ev.get("event_type")
        if et in priority:
            return priority[et][0], ev.get("reason_code")
        if et == "ORDER_SUBMITTED":
            return "SUBMITTED", None
        if et == "ORDER_FILLED":
            return "FILLED", None
    return ("MODEL", model_reason) if model_reason else ("MODEL", None)


def _interpretation(stage: str) -> str:
    return {
        "PRE_DECISION": "data-health incident, not an alpha miss",
        "MODEL": "threshold calibration candidate",
        "ALLOCATION": "portfolio selection question",
        "RISK": "risk-policy question",
        "ROUTER": "routing/latency question",
        "SUBMITTED": "executed (pending settlement)",
        "FILLED": "executed",
    }.get(stage, "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Rejection/outcome hourly report (audit DB)")
    ap.add_argument(
        "--db",
        default=os.environ.get("MERID_DECISION_AUDIT_DB_PATH", os.path.join("data", "decision_audit.db")),
    )
    ap.add_argument("--run-id", default=None, help="Restrict to this run_id (recommended)")
    ap.add_argument("--start-utc", default=None, help="Window start (ISO-8601 or epoch s)")
    ap.add_argument("--end-utc", default=None, help="Window end (ISO-8601 or epoch s)")
    ap.add_argument("--out-dir", default="reports")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"audit db not found: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Resolve window: explicit bounds win; otherwise span the run_id's data.
    start_ts = _parse_ts(args.start_utc)
    end_ts = _parse_ts(args.end_utc)
    if args.run_id and (start_ts is None or end_ts is None):
        row = conn.execute(
            "SELECT MIN(decision_ts) AS lo, MAX(decision_ts) AS hi "
            "FROM strategy_decisions WHERE run_id = ?",
            (args.run_id,),
        ).fetchone()
        if row and row["lo"] is not None:
            start_ts = start_ts if start_ts is not None else float(row["lo"])
            end_ts = end_ts if end_ts is not None else float(row["hi"]) + 1.0
    if start_ts is None or end_ts is None:
        # Fallback: last 60 minutes of recorded decisions.
        row = conn.execute("SELECT MAX(decision_ts) AS hi FROM strategy_decisions").fetchone()
        if not row or row["hi"] is None:
            print("no decisions in audit db")
            return 1
        end_ts = float(row["hi"]) + 1.0
        start_ts = end_ts - 3600.0
    run_start = start_ts

    where = "d.decision_ts >= ? AND d.decision_ts < ?"
    params: List[Any] = [start_ts, end_ts]
    if args.run_id:
        where += " AND d.run_id = ?"
        params.append(args.run_id)

    decisions = conn.execute(
        f"""
        SELECT d.decision_id, d.candidate_id, d.run_id, d.decision_ts, d.ticker,
               d.asset, d.selected_side, d.decision, d.primary_reason_code,
               d.all_failed_gates_json, d.gate_results_json,
               d.is_eligible_for_research, d.exclusion_reason,
               d.seconds_to_close, d.close_ts, d.record_source,
               o.outcome_status, o.settled_yes, o.settlement_value_cents,
               o.counterfactual_yes_pnl_cents, o.counterfactual_no_pnl_cents,
               o.unresolved_reason
        FROM strategy_decisions d
        LEFT JOIN strategy_decision_outcomes o ON o.decision_id = d.decision_id
        WHERE {where}
        """,
        params,
    ).fetchall()

    decision_ids = [r["decision_id"] for r in decisions]
    events_by_decision: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    if decision_ids:
        marks = ",".join("?" for _ in decision_ids)
        for ev in conn.execute(
            f"""
            SELECT decision_id, event_type, stage, reason_code, event_ts
            FROM strategy_decision_events
            WHERE decision_id IN ({marks})
            ORDER BY event_ts DESC
            """,
            decision_ids,
        ).fetchall():
            events_by_decision[ev["decision_id"]].append(dict(ev))

    side_ev_by_decision: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    if decision_ids:
        for row in conn.execute(
            f"""
            SELECT decision_id, side, selected, executable_entry_price_cents,
                   counterfactual_execution_status, counterfactual_fill_ratio,
                   counterfactual_assumed_filled_contracts, requested_contracts,
                   expected_net_ev_cents, required_edge_cents, passed_edge_gate
            FROM strategy_decision_side_ev
            WHERE decision_id IN ({marks})
            """,
            decision_ids,
        ).fetchall():
            side_ev_by_decision[row["decision_id"]].append(dict(row))

    gap_count = conn.execute(
        "SELECT COUNT(*) FROM decision_audit_gaps WHERE start_ts < ? AND end_ts > ?",
        (end_ts, start_ts),
    ).fetchone()[0]

    # ── Aggregation ──────────────────────────────────────────────────────
    stage_reason: Dict[Tuple[str, str], Dict[str, Any]] = collections.defaultdict(
        lambda: {"candidates": 0, "resolved": 0, "full_exec": 0,
                 "wins": 0, "losses": 0, "flat": 0, "net_cents": 0.0,
                 "unresolved": 0, "excluded": 0}
    )
    by_window: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_asset: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    gate_fail_counter: collections.Counter = collections.Counter()
    cofail_counter: collections.Counter = collections.Counter()
    band_pnl: Dict[str, float] = collections.defaultdict(float)
    band_n: Dict[str, int] = collections.defaultdict(int)
    unresolved_rows: List[Dict[str, Any]] = []
    coverage = collections.Counter()
    csv_rows: List[Dict[str, Any]] = []

    for d in decisions:
        coverage["total"] += 1
        if not d["ticker"]:
            coverage["missing_ticker"] += 1
        if not d["decision_id"]:
            coverage["missing_decision_id"] += 1
        if d["gate_results_json"] in (None, "{}", ""):
            coverage["missing_gate_vector"] += 1

        events = events_by_decision.get(d["decision_id"], [])
        stage, stage_reason_code = _terminal_stage(events, d["primary_reason_code"])
        reason = stage_reason_code or d["primary_reason_code"] or "unknown"

        # Chosen counterfactual side: the selected side, else the side that
        # came closest to qualifying (max expected net EV).
        side_rows = side_ev_by_decision.get(d["decision_id"], [])
        chosen = None
        if side_rows:
            sel = (d["selected_side"] or "").lower()
            chosen = next((r for r in side_rows if r["side"] == sel and sel), None)
            if chosen is None:
                chosen = max(
                    side_rows,
                    key=lambda r: (r.get("expected_net_ev_cents") or -1e9),
                )

        exec_status = (chosen or {}).get("counterfactual_execution_status") or "NOT_APPLICABLE"
        entry_cents = (chosen or {}).get("executable_entry_price_cents")
        outcome = (d["outcome_status"] or "PENDING").upper()
        cf_pnl = None
        label = "unresolved"
        if outcome in ("SETTLED", "RESOLVED"):
            if chosen and chosen.get("side") == "yes":
                cf_pnl = d["counterfactual_yes_pnl_cents"]
            elif chosen and chosen.get("side") == "no":
                cf_pnl = d["counterfactual_no_pnl_cents"]
            if cf_pnl is not None and exec_status.startswith("NOT_EXECUTABLE"):
                label = "not_executable"
            elif cf_pnl is not None:
                label = (
                    "win" if cf_pnl > _FLAT_EPS_CENTS
                    else "loss" if cf_pnl < -_FLAT_EPS_CENTS
                    else "flat"
                )
            else:
                label = "no_counterfactual"
        elif outcome == "UNRESOLVED":
            label = "unresolved"

        excluded = not d["is_eligible_for_research"]
        key = (stage, str(reason).split(":")[0])
        agg = stage_reason[key]
        agg["candidates"] += 1
        if excluded:
            agg["excluded"] += 1
        if outcome in ("SETTLED", "RESOLVED"):
            agg["resolved"] += 1
            if exec_status == "FULLY_EXECUTABLE":
                agg["full_exec"] += 1
            if label == "win":
                agg["wins"] += 1
            elif label == "loss":
                agg["losses"] += 1
            elif label == "flat":
                agg["flat"] += 1
            if cf_pnl is not None:
                agg["net_cents"] += cf_pnl
        else:
            agg["unresolved"] += 1
            unresolved_rows.append({
                "decision_id": d["decision_id"],
                "ticker": d["ticker"],
                "asset": d["asset"],
                "stage": stage,
                "reason": reason,
                "outcome_status": outcome,
                "unresolved_reason": d["unresolved_reason"],
                "close_ts": d["close_ts"],
            })

        wlabel = _window_label(d["close_ts"], run_start)
        by_window[wlabel]["candidates"] += 1
        by_window[wlabel][f"{stage}"] += 1
        by_asset[d["asset"] or "unknown"]["candidates"] += 1
        by_asset[d["asset"] or "unknown"][stage] += 1

        try:
            failed = json.loads(d["all_failed_gates_json"] or "[]")
        except Exception:
            failed = []
        for g in failed:
            gate_fail_counter[g] += 1
        if len(failed) > 1:
            cofail_counter[tuple(sorted(failed))] += 1

        # Marginal band: shortfall of the chosen side's net EV vs required edge.
        if chosen and stage == "MODEL":
            net_ev = chosen.get("expected_net_ev_cents")
            req = chosen.get("required_edge_cents")
            if net_ev is not None and req is not None:
                shortfall = max(0.0, float(req) - float(net_ev))
                band = _shortfall_band(shortfall)
                if cf_pnl is not None and exec_status == "FULLY_EXECUTABLE":
                    band_pnl[band] += cf_pnl
                    band_n[band] += 1

        csv_rows.append({
            "decision_id": d["decision_id"],
            "candidate_id": d["candidate_id"],
            "run_id": d["run_id"],
            "decision_ts": d["decision_ts"],
            "ticker": d["ticker"],
            "asset": d["asset"],
            "selected_side": d["selected_side"],
            "decision": d["decision"],
            "model_reason": d["primary_reason_code"],
            "terminal_stage": stage,
            "terminal_reason": reason,
            "outcome_status": outcome,
            "settled_yes": d["settled_yes"],
            "exec_status": exec_status,
            "entry_cents": entry_cents,
            "fill_ratio": (chosen or {}).get("counterfactual_fill_ratio"),
            "counterfactual_pnl_cents": cf_pnl,
            "label": label,
            "is_eligible_for_research": d["is_eligible_for_research"],
            "exclusion_reason": d["exclusion_reason"],
            "all_failed_gates": d["all_failed_gates_json"],
            "window": wlabel,
        })

    # ── Outputs ──────────────────────────────────────────────────────────
    os.makedirs(args.out_dir, exist_ok=True)
    tag = args.run_id or f"{int(start_ts)}"
    json_path = os.path.join(args.out_dir, f"rejection_outcome_hourly_{tag}.json")
    csv_path = os.path.join(args.out_dir, f"rejection_outcome_hourly_{tag}.csv")
    md_path = os.path.join(args.out_dir, f"rejection_outcome_hourly_{tag}.md")

    stage_table = [
        {
            "stage": stage,
            "reason": reason,
            **vals,
            "interpretation": _interpretation(stage),
        }
        for (stage, reason), vals in sorted(stage_reason.items())
    ]
    payload = {
        "run_id": args.run_id,
        "window": {"start_utc": start_ts, "end_utc": end_ts},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": dict(coverage),
        "audit_gaps_in_window": gap_count,
        "by_stage_reason": stage_table,
        "by_window": {k: dict(v) for k, v in sorted(by_window.items())},
        "by_asset": {k: dict(v) for k, v in sorted(by_asset.items())},
        "gate_failure_counts": dict(gate_fail_counter.most_common()),
        "cofailures": {" + ".join(k): v for k, v in cofail_counter.most_common(20)},
        "marginal_band_full_exec_pnl": {
            k: {"n": band_n[k], "net_cents": band_pnl[k]} for k in band_pnl
        },
        "unresolved": unresolved_rows,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    if csv_rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)

    # ── Markdown summary ─────────────────────────────────────────────────
    lines = [
        f"# Rejection/Outcome Report — run `{tag}`",
        "",
        f"Window: {datetime.fromtimestamp(start_ts, timezone.utc).isoformat()} → "
        f"{datetime.fromtimestamp(end_ts, timezone.utc).isoformat()}",
        f"Candidates: {coverage['total']} | audit gaps in window: {gap_count} | "
        f"missing gate vector: {coverage['missing_gate_vector']}",
        "",
        "## Blocking stage × reason",
        "",
        "| stage | reason | cands | resolved | full-exec | wins | losses | flat | net¢ | unresolved | excluded | interpretation |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in stage_table:
        lines.append(
            f"| {row['stage']} | {row['reason']} | {row['candidates']} | {row['resolved']} | "
            f"{row['full_exec']} | {row['wins']} | {row['losses']} | {row['flat']} | "
            f"{row['net_cents']:+.1f} | {row['unresolved']} | {row['excluded']} | {row['interpretation']} |"
        )
    lines += [
        "",
        "## All-failed-gate counts (co-failures included)",
        "",
    ]
    for gate, n in gate_fail_counter.most_common(20):
        lines.append(f"- {gate}: {n}")
    lines += [
        "",
        "## Marginal-band counterfactual P&L (fully executable only)",
        "",
        "| band | n | net¢ |",
        "|---|---|---|",
    ]
    for band in ("0-1c (marginal)", "1-2c", "2-5c", "5c+"):
        if band in band_n:
            lines.append(f"| {band} | {band_n[band]} | {band_pnl[band]:+.1f} |")
    lines += [
        "",
        f"## Unresolved / pending outcomes: {len(unresolved_rows)}",
        "",
    ]
    for u in unresolved_rows[:50]:
        lines.append(
            f"- {u['ticker']} ({u['asset']}) stage={u['stage']} reason={u['reason']} "
            f"status={u['outcome_status']} {u['unresolved_reason'] or ''}"
        )
    lines += [
        "",
        "> Counterfactuals are priced at the recorded decision-time executable "
        "entry, net of the versioned fee model, scaled to top-of-book visible "
        "quantity. A rejected contract is never a 'winner' unless its exact "
        "side settled profitably at a fill that could actually have executed.",
    ]
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"wrote {json_path}")
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")
    print(
        f"\ncandidates={coverage['total']} resolved={sum(v['resolved'] for v in stage_reason.values())} "
        f"unresolved={len(unresolved_rows)} gaps={gap_count}"
    )
    for row in stage_table[:15]:
        print(
            f"  {row['stage']:<13} {row['reason']:<40} n={row['candidates']:<4} "
            f"wins={row['wins']:<3} losses={row['losses']:<3} net={row['net_cents']:+.1f}c"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
