"""Build the alignment-ledger extract for the MERID 15m audit.

Reads every durable source with mode=ro ATTACH; writes a NEW sqlite DB at
audit_output_alignment_20261101/alignment_ledger.db. No live store is
modified; WAL sources are opened read-only so the live writer is untouched.

Row unit = market-side opportunity (decision x side), per the audit spec:
contract required / market offered / model believed / evidence+artifacts /
lanes considered / accept-reject reason / execution available.
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "audit_output_alignment_20261101"
LEDGER = OUT / "alignment_ledger.db"

SRC = {
    "dec": "data/decision_audit.db",
    "att": "data/kalshi_order_attempts.db",
    "fil": "data/kalshi_fills.db",
    "fac": "data/trade_attribution_fact.db",
    "rti": "data/cf_rti_ticks.db",
}


def attach_ro(con: sqlite3.Connection, alias: str, rel: str) -> None:
    p = (ROOT / rel).resolve().as_posix()
    con.execute(f"ATTACH 'file:{p}?mode=ro' AS {alias}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-hours", type=float, default=36.0)
    args = ap.parse_args()
    cutoff = time.time() - args.since_hours * 3600
    OUT.mkdir(exist_ok=True)
    if LEDGER.exists():
        LEDGER.unlink()
    con = sqlite3.connect(f"file:{LEDGER.as_posix()}?mode=rwc", uri=True)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    for alias, rel in SRC.items():
        attach_ro(con, alias, rel)
    con.execute("PRAGMA query_only=OFF")

    # ---------- decisions (window) ----------
    con.execute(
        """CREATE TABLE decisions AS
           SELECT decision_id, parent_decision_id, decision_ts, decision_ts_iso,
                  run_id, candidate_id, build_sha, policy_epoch, config_version,
                  model_version, calibration_version, strategy_name, strategy_version,
                  ticker, asset, market_open_ts, close_ts, close_ts_iso,
                  seconds_to_close, strike, settlement_reference,
                  settlement_rule_version, selected_side, decision,
                  primary_reason_code, reason_codes, exclusion_reason,
                  admission_lane, admission_owner, provisional_cell_id,
                  dir_regime, shadow_cohort_json,
                  gate_results_json, all_failed_gates_json,
                  gate_evaluation_schema_version, is_eligible_for_research
             FROM dec.strategy_decisions
            WHERE decision_ts > ?""",
        (cutoff,),
    )
    con.execute("CREATE INDEX idx_d_id ON decisions(decision_id)")
    con.execute("CREATE INDEX idx_d_ticker ON decisions(ticker, decision_ts)")
    con.execute("CREATE INDEX idx_d_run ON decisions(run_id)")
    n_dec = con.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]

    # ---------- snapshots ----------
    con.execute(
        """CREATE TABLE snapshots AS
           SELECT s.* FROM dec.strategy_decision_snapshots s
            WHERE s.decision_id IN (SELECT decision_id FROM decisions)"""
    )
    con.execute("CREATE INDEX idx_s_id ON snapshots(decision_id)")
    n_snap = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]

    # ---------- side_ev ----------
    con.execute(
        """CREATE TABLE side_ev AS
           SELECT e.* FROM dec.strategy_decision_side_ev e
            WHERE e.decision_id IN (SELECT decision_id FROM decisions)"""
    )
    con.execute("CREATE INDEX idx_e_id ON side_ev(decision_id)")
    n_ev = con.execute("SELECT COUNT(*) FROM side_ev").fetchone()[0]

    # ---------- outcomes ----------
    con.execute(
        """CREATE TABLE outcomes AS
           SELECT o.* FROM dec.strategy_decision_outcomes o
            WHERE o.decision_id IN (SELECT decision_id FROM decisions)"""
    )
    con.execute("CREATE INDEX idx_o_id ON outcomes(decision_id)")
    con.execute("CREATE INDEX idx_o_fill ON outcomes(fill_id)")
    con.execute("CREATE INDEX idx_o_order ON outcomes(exchange_order_id)")
    n_out = con.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]

    # ---------- decision events ----------
    con.execute(
        """CREATE TABLE decision_events AS
           SELECT e.* FROM dec.strategy_decision_events e
            WHERE e.decision_id IN (SELECT decision_id FROM decisions)
               OR e.run_id IN (SELECT DISTINCT run_id FROM decisions)"""
    )
    con.execute("CREATE INDEX idx_de_id ON decision_events(decision_id)")
    n_dv = con.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0]

    # ---------- heartbeats + gaps ----------
    con.execute(
        "CREATE TABLE heartbeats AS SELECT * FROM dec.decision_audit_heartbeats WHERE created_at > ?",
        (cutoff,),
    )
    con.execute(
        "CREATE TABLE gaps AS SELECT * FROM dec.decision_audit_gaps WHERE end_ts > ?",
        (cutoff,),
    )

    # ---------- order attempts (whole store is small) ----------
    con.execute("CREATE TABLE order_attempts AS SELECT * FROM att.order_attempts")
    con.execute("CREATE INDEX idx_oa_coid ON order_attempts(client_order_id)")
    con.execute("CREATE INDEX idx_oa_intent ON order_attempts(intent_id)")
    con.execute("CREATE INDEX idx_oa_dec ON order_attempts(decision_id)")
    con.execute("CREATE TABLE exit_order_attempts AS SELECT * FROM att.exit_order_attempts")
    con.execute("CREATE TABLE exit_order_attempt_events AS SELECT * FROM att.exit_order_attempt_events")

    # ---------- fills ----------
    con.execute("CREATE TABLE fills AS SELECT * FROM fil.kalshi_fills")
    con.execute("CREATE INDEX idx_f_oid ON fills(order_id)")
    con.execute("CREATE INDEX idx_f_coid ON fills(client_order_id)")
    con.execute("CREATE INDEX idx_f_intent ON fills(intent_id)")

    # ---------- attribution ----------
    con.execute("CREATE TABLE attribution AS SELECT * FROM fac.trade_attribution_fact")
    con.execute("CREATE INDEX idx_at_fill ON attribution(fill_id)")
    con.execute("CREATE INDEX idx_at_order ON attribution(order_id)")
    con.execute("CREATE INDEX idx_at_intent ON attribution(intent_id)")

    # ---------- rti ticks (window) ----------
    con.execute(
        "CREATE TABLE rti_ticks AS SELECT * FROM rti.rti_ticks WHERE local_ts_ms > ?",
        (int(cutoff * 1000),),
    )

    # ---------- opportunity ledger (decision x side) ----------
    con.execute(
        """CREATE TABLE opportunity AS
           SELECT d.decision_id, d.candidate_id, d.run_id, d.build_sha,
                  d.policy_epoch, d.config_version, d.model_version,
                  d.calibration_version,
                  e.side AS side,
                  d.asset, d.ticker, d.decision_ts, d.decision_ts_iso,
                  d.market_open_ts, d.close_ts, d.seconds_to_close, d.strike,
                  d.settlement_reference, d.settlement_rule_version,
                  d.selected_side, d.decision, d.primary_reason_code,
                  d.reason_codes, d.exclusion_reason,
                  d.admission_lane, d.admission_owner, d.provisional_cell_id,
                  d.dir_regime, d.shadow_cohort_json, d.gate_results_json,
                  d.all_failed_gates_json, d.gate_evaluation_schema_version,
                  s.spot_price, s.spot_source, s.spot_age_ms,
                  s.settlement_reference_price, s.settlement_reference_source,
                  s.settlement_reference_ts, s.settlement_reference_age_ms,
                  s.yes_bid_cents, s.yes_ask_cents, s.no_bid_cents, s.no_ask_cents,
                  s.book_age_ms, s.book_sequence, s.book_is_crossed,
                  s.book_is_executable, s.yes_depth, s.no_depth,
                  s.quote_owner, s.degraded_mode, s.ws_last_seq,
                  s.ws_last_event_age_ms, s.ws_last_queue_wait_ms,
                  s.ws_parity_healthy, s.rest_age_ms,
                  s.vol_forecast, s.vol_source, s.vol_age_ms,
                  s.zscore, s.distance_to_strike, s.log_moneyness,
                  s.velocity, s.velocity_source, s.velocity_age_ms,
                  s.confidence, s.confidence_reasons,
                  e.eligible_for_model, e.eligible_for_policy,
                  e.exclusion_reason AS side_exclusion_reason,
                  e.model_evaluated, e.policy_eligible, e.executable,
                  e.passed_net_ev, e.selected,
                  e.executable_entry_price_cents, e.executable_entry_depth_fp,
                  e.expected_entry_fill_cents, e.expected_entry_slippage_cents,
                  e.raw_probability, e.calibrated_probability,
                  e.gross_edge_cents, e.entry_fee_cents,
                  e.exit_or_settlement_fee_cents,
                  e.adverse_selection_haircut_cents,
                  e.model_uncertainty_haircut_cents,
                  e.policy_giveback_reserve_c,
                  e.implementation_shortfall_reserve_c,
                  e.edge_bias_correction_c,
                  e.expected_net_ev_cents, e.lower_confidence_bound_ev_cents,
                  e.required_edge_cents, e.gate_ev_cents,
                  e.formula_required_c, e.effective_required_c,
                  e.effective_required_source,
                  e.formula_gate_passed, e.effective_edge_gate_passed,
                  e.passed_edge_gate,
                  e.decision_lane, e.threshold_source, e.legacy_risk_label,
                  e.evidence_state, e.evidence_age_s, e.evidence_action,
                  e.evidence_binding_gate, e.evidence_artifact_mtime,
                  e.evidence_last_refresh_success_at,
                  e.requested_contracts, e.top_of_book_executable_contracts,
                  e.counterfactual_assumed_filled_contracts,
                  e.counterfactual_fill_ratio,
                  e.counterfactual_full_fill_possible,
                  e.counterfactual_execution_status,
                  e.counterfactual_entry_source,
                  e.reserve_snapshot_id, e.reserve_artifact_hash,
                  e.reserve_artifact_asof, e.reserve_cohort_key,
                  e.reserve_cohort_sample_count, e.reserve_estimator_version,
                  o.settled_at, o.settled_yes, o.settlement_value_cents,
                  o.counterfactual_yes_pnl_cents, o.counterfactual_no_pnl_cents,
                  o.order_intent_id, o.exchange_order_id, o.fill_id,
                  o.actual_fill_price_cents, o.actual_entry_fee_cents,
                  o.actual_exit_price_cents, o.actual_exit_fee_cents,
                  o.realized_net_pnl_cents, o.outcome_status,
                  o.unresolved_reason, o.exit_attribution
             FROM decisions d
             JOIN side_ev e ON e.decision_id = d.decision_id
             LEFT JOIN snapshots s ON s.decision_id = d.decision_id
             LEFT JOIN outcomes o ON o.decision_id = d.decision_id"""
    )
    con.execute("CREATE INDEX idx_opp_ticker ON opportunity(ticker, decision_ts)")
    con.execute("CREATE INDEX idx_opp_asset ON opportunity(asset, side, decision_ts)")
    con.execute("CREATE INDEX idx_opp_lane ON opportunity(decision_lane)")
    n_opp = con.execute("SELECT COUNT(*) FROM opportunity").fetchone()[0]

    con.commit()
    summary = {
        "cutoff_ts": cutoff,
        "since_hours": args.since_hours,
        "decisions": n_dec,
        "snapshots": n_snap,
        "side_ev": n_ev,
        "outcomes": n_out,
        "decision_events": n_dv,
        "opportunity_rows": n_opp,
    }
    (OUT / "extract_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    con.close()


if __name__ == "__main__":
    sys.exit(main())
