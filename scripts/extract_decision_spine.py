"""Extract the decision spine (side_ev + decisions + outcomes) from
decision_audit.db in time slices -> data/decision_spine.parquet

The DB is HDD-bound; never scan unbounded. 6h slices over the full
decision_ts span.

    python scripts/extract_decision_spine.py
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

DB = "data/decision_audit.db"
OUT = "data/decision_spine.pkl"
SLICE_S = 6 * 3600

SIDE_EV_COLS = [
    "decision_id", "side", "model_evaluated", "executable", "selected",
    "passed_net_ev", "executable_entry_price_cents",
    "executable_entry_depth_fp", "expected_entry_fill_cents",
    "expected_entry_slippage_cents", "raw_probability",
    "calibrated_probability", "gross_edge_cents", "entry_fee_cents",
    "exit_or_settlement_fee_cents", "expected_net_ev_cents",
    "lower_confidence_bound_ev_cents", "required_edge_cents",
    "passed_edge_gate", "gate_ev_cents", "decision_lane",
    "admission_owner", "evidence_state",
    "top_of_book_executable_contracts",
    "counterfactual_assumed_filled_contracts",
    "counterfactual_fill_ratio", "counterfactual_full_fill_possible",
    "counterfactual_execution_status", "counterfactual_entry_source",
    "adverse_selection_haircut_cents", "model_uncertainty_haircut_cents",
    "edge_bias_correction_c", "exclusion_reason",
]
DEC_COLS = ["ticker", "decision_ts", "selected_side", "decision",
            "admission_lane"]
OUT_COLS = ["settled_yes", "settlement_value_cents",
            "counterfactual_yes_pnl_cents", "counterfactual_no_pnl_cents",
            "actual_fill_price_cents", "actual_entry_fee_cents",
            "realized_net_pnl_cents", "capital_realized_pnl_cents",
            "outcome_status", "order_intent_id", "fill_id",
            "exit_attribution"]


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True,
                           timeout=300)
    mn, mx = conn.execute(
        "SELECT min(decision_ts), max(decision_ts) FROM strategy_decisions"
    ).fetchone()
    print(f"span {mn} -> {mx} ({(mx-mn)/86400:.1f} days)", flush=True)

    se = ",".join(f"e.{c}" for c in SIDE_EV_COLS)
    dc = ",".join(f"d.{c}" for c in DEC_COLS)
    oc = ",".join(f"o.{c}" for c in OUT_COLS)
    sql = f"""
    SELECT {se}, {dc}, {oc}
    FROM strategy_decision_side_ev e
    JOIN strategy_decisions d ON e.decision_id = d.decision_id
    LEFT JOIN strategy_decision_outcomes o ON e.decision_id = o.decision_id
    WHERE d.decision_ts BETWEEN ? AND ?
    """

    frames = []
    t0 = time.time()
    lo = mn
    while lo < mx:
        hi = min(lo + SLICE_S, mx)
        try:
            df = pd.read_sql_query(sql, conn, params=(lo, hi))
        except Exception as exc:
            print(f"slice {lo}-{hi} FAILED: {exc}", flush=True)
            lo = hi
            continue
        frames.append(df)
        print(f"slice {lo:.0f}-{hi:.0f}: {len(df)} rows "
              f"({time.time()-t0:.0f}s)", flush=True)
        lo = hi
    conn.close()

    if not frames:
        print("no rows")
        return 1
    all_df = pd.concat(frames, ignore_index=True)
    all_df.to_pickle(OUT)
    print(f"wrote {OUT}: {len(all_df)} rows, "
          f"{all_df['ticker'].nunique()} tickers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
