"""Produce the audit matrices from alignment_ledger.db (read-only)."""
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "audit_output_alignment_20261101"
LED = OUT / "alignment_ledger.db"

con = sqlite3.connect(f"file:{LED.as_posix()}?mode=ro", uri=True)
con.execute("PRAGMA query_only=1")
con.execute("PRAGMA temp_store=MEMORY")

rep = {}

# ---------------- runs ----------------
runs = {}
for r in con.execute(
    "SELECT run_id, build_sha, config_version, COUNT(*), MIN(decision_ts), MAX(decision_ts), "
    "SUM(decision='ENTER') FROM decisions GROUP BY run_id, build_sha, config_version"
):
    runs[r[0]] = {
        "build_sha": r[1], "config_version": r[2], "decisions": r[3],
        "first_ts": r[4], "last_ts": r[5], "enter": r[6],
    }
rep["runs"] = runs

# ---------------- lane x asset x side matrix ----------------
mat = defaultdict(lambda: Counter())
for r in con.execute(
    """SELECT COALESCE(decision_lane,'formula'), asset, side,
              COUNT(*), SUM(policy_eligible), SUM(executable), SUM(passed_net_ev),
              SUM(selected), SUM(formula_gate_passed), SUM(effective_edge_gate_passed),
              AVG(expected_net_ev_cents), SUM(counterfactual_assumed_filled_contracts)
       FROM side_ev e JOIN decisions d USING(decision_id)
       GROUP BY 1,2,3"""
):
    lane, asset, side = r[0], r[1], r[2]
    mat[f"{lane}|{asset}|{side}"] = {
        "evals": r[3], "policy_eligible": r[4], "executable": r[5],
        "passed_net_ev": r[6], "selected": r[7], "formula_gate": r[8],
        "effective_gate": r[9], "avg_net_ev_c": round(r[10] or 0, 3),
        "cf_contracts": r[11],
    }
rep["lane_asset_side"] = dict(mat)

# ---------------- decision outcomes by lane ----------------
lane_out = defaultdict(lambda: Counter())
for r in con.execute(
    """SELECT COALESCE(d.admission_lane, COALESCE(e.decision_lane,'formula')) AS lane,
              d.decision, d.primary_reason_code, COUNT(*),
              SUM(CASE WHEN o.fill_id IS NOT NULL THEN 1 ELSE 0 END),
              SUM(o.realized_net_pnl_cents)
       FROM decisions d
       LEFT JOIN side_ev e ON e.decision_id=d.decision_id AND e.side=d.selected_side
       LEFT JOIN outcomes o ON o.decision_id=d.decision_id
       GROUP BY 1,2,3"""
):
    lane_out[f"{r[0]}|{r[1]}|{r[2]}"] = {"n": r[3], "with_fill": r[4], "pnl_c": r[5]}
rep["lane_decision_outcomes"] = dict(lane_out)

# ---------------- gate matrix ----------------
gate_pass = defaultdict(Counter)
gate_fail_first = Counter()
n_gates_parsed = 0
for (gid, gjson, afg, asset) in con.execute(
    "SELECT decision_id, gate_results_json, all_failed_gates_json, asset FROM decisions"
):
    n_gates_parsed += 1
    try:
        g = json.loads(gjson or "{}")
    except Exception:
        continue
    for name, gv in g.items():
        passed = gv.get("passed")
        gate_pass[name][ "pass" if passed else "fail"] += 1
        if not passed:
            gate_fail_first[(name, gv.get("gate_code"))] += 0  # counted below
    try:
        for fg in json.loads(afg or "[]"):
            gate_fail_first[(fg, asset)] += 1
    except Exception:
        pass
rep["gate_matrix"] = {k: dict(v) for k, v in sorted(gate_pass.items())}
rep["failed_gates_by_asset"] = {
    f"{k[0]}|{k[1]}": v for k, v in gate_fail_first.most_common(60)
}
rep["n_gates_parsed"] = n_gates_parsed

# ---------------- evidence ----------------
ev = {}
for r in con.execute(
    """SELECT COALESCE(evidence_state,'none'), COALESCE(evidence_action,'none'), COUNT(*),
              AVG(evidence_age_s), MAX(evidence_age_s)
       FROM side_ev GROUP BY 1,2"""
):
    ev[f"{r[0]}|{r[1]}"] = {"n": r[2], "avg_age_s": round(r[3] or 0, 1), "max_age_s": r[4]}
rep["evidence_state_action"] = ev
bind = Counter()
for r in con.execute(
    "SELECT evidence_binding_gate, COUNT(*) FROM side_ev WHERE evidence_binding_gate IS NOT NULL GROUP BY 1"
):
    bind[r[0]] = r[1]
rep["evidence_binding_gates"] = dict(bind)

# ---------------- calibration ----------------
cal = defaultdict(lambda: {"n": 0, "win": 0, "sum_p": 0.0, "brier": 0.0, "sum_px": 0.0})
for r in con.execute(
    """SELECT o.asset, e.side,
              CAST(ROUND(e.calibrated_probability*10)*10 AS INT) AS bin10,
              COUNT(*), SUM(o.settled_yes), AVG(e.calibrated_probability),
              AVG((e.calibrated_probability - o.settled_yes)*(e.calibrated_probability - o.settled_yes)),
              AVG(e.executable_entry_price_cents)
       FROM opportunity o
       JOIN side_ev e ON e.decision_id=o.decision_id AND e.side=o.side
       WHERE o.settled_yes IS NOT NULL AND e.calibrated_probability IS NOT NULL
       GROUP BY 1,2,3"""
):
    key = f"{r[0]}|{r[1]}|p{r[2]:02d}"
    cal[key] = {"n": r[3], "settled_yes": r[4], "mean_p": round(r[5], 4),
                "brier": round(r[6], 5), "mean_px_c": round(r[7] or 0, 1)}
rep["calibration_bins"] = cal

# ---------------- opportunity attribution ----------------
attr = defaultdict(lambda: {"n": 0, "cf_pnl_c": 0.0, "cf_pos": 0, "cf_sum_c": 0.0})
for r in con.execute(
    """SELECT o.asset, o.side, o.primary_reason_code,
              COUNT(*),
              SUM(CASE WHEN o.side='yes' THEN o.counterfactual_yes_pnl_cents
                       ELSE o.counterfactual_no_pnl_cents END),
              SUM(CASE WHEN (o.side='yes' AND o.counterfactual_yes_pnl_cents>0)
                        OR (o.side='no' AND o.counterfactual_no_pnl_cents>0) THEN 1 ELSE 0 END)
       FROM opportunity o
       WHERE o.decision='NO_TRADE' AND o.outcome_status='SETTLED'
       GROUP BY 1,2,3"""
):
    key = f"{r[0]}|{r[1]}|{r[2]}"
    attr[key] = {"n": r[3], "cf_pnl_sum_c": round(r[4] or 0, 1), "cf_positive_n": r[5]}
rep["missed_opportunity_cf"] = dict(sorted(attr.items(), key=lambda kv: -(kv[1]["cf_pnl_sum_c"] or 0)))

# ---------------- execution ledger ----------------
execrows = []
for r in con.execute(
    """SELECT d.decision_id, d.ticker, d.selected_side, d.admission_lane,
              o.order_intent_id, o.exchange_order_id, o.fill_id,
              o.actual_fill_price_cents, o.realized_net_pnl_cents, o.outcome_status
       FROM decisions d JOIN outcomes o ON o.decision_id=d.decision_id
       WHERE d.decision='ENTER'"""
):
    execrows.append({
        "decision_id": r[0], "ticker": r[1], "side": r[2], "lane": r[3],
        "intent": r[4], "order": r[5], "fill": r[6],
        "px_c": r[7], "pnl_c": r[8], "status": r[9],
    })
(OUT / "execution_ledger_rows.json").write_text(json.dumps(execrows, indent=1))
rep["enter_rows"] = len(execrows)
miss = Counter()
for e in execrows:
    if not e["intent"]:
        miss["no_intent"] += 1
    if e["intent"] and not e["order"]:
        miss["intent_no_order"] += 1
    if e["order"] and not e["fill"]:
        miss["order_no_fill"] += 1
rep["exec_chain_missing_links"] = dict(miss)

(OUT / "analysis_report.json").write_text(json.dumps(rep, indent=1, default=str))
print("decisions:", rep["n_gates_parsed"], "opportunity rows done")
print("runs:", len(runs))
print("lanes:", sorted({k.split('|')[0] for k in mat}))
print("gate names:", len(rep["gate_matrix"]))
print("exec missing:", rep["exec_chain_missing_links"])
con.close()
