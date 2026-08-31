"""Tests for the offline calibration & expectancy audit report."""

import json
import sqlite3
from pathlib import Path

import pytest

from merid.analysis import calibration_report as cr


# ---------------------------------------------------------------------------
# Pure metric helpers
# ---------------------------------------------------------------------------

def test_brier_known_values():
    # Perfect predictions
    assert cr.brier([(1.0, 1), (0.0, 0)]) == pytest.approx(0.0)
    # Always wrong
    assert cr.brier([(1.0, 0), (0.0, 1)]) == pytest.approx(1.0)
    # Coin-flip forecaster on balanced outcomes
    assert cr.brier([(0.5, 1), (0.5, 0)]) == pytest.approx(0.25)
    assert cr.brier([]) is None


def test_calibration_bias_sign():
    # Overconfident: predicts 0.8, outcomes 0.5 rate -> positive bias
    assert cr.calibration_bias([(0.8, 1), (0.8, 0)]) == pytest.approx(0.3)
    # Underconfident
    assert cr.calibration_bias([(0.2, 1), (0.2, 0)]) == pytest.approx(-0.3)
    # Calibrated
    assert cr.calibration_bias([(0.63, 1), (0.37, 0)]) == pytest.approx(0.0)
    assert cr.calibration_bias([]) is None


def test_expectancy():
    assert cr.expectancy([0.10, -0.20, 0.05]) == pytest.approx(-0.05 / 3)
    assert cr.expectancy([]) is None


def test_bucketing():
    assert cr._bucket(48.0, cr.PRICE_BUCKETS) == "40-49c"
    assert cr._bucket(75.0, cr.PRICE_BUCKETS) == "66-75c"
    assert cr._bucket(5.0, cr.PRICE_BUCKETS) == "out-of-range"
    assert cr._bucket(None, cr.PRICE_BUCKETS) is None
    assert cr._bucket(float("nan"), cr.PRICE_BUCKETS) is None
    assert cr._bucket(2.0, cr.SPREAD_BUCKETS) == "2-3c"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _telemetry_row(asset="BTC", ticker="KXBTC15M-T1", side="yes", model=0.63,
                   market=0.48, raw_edge=15.0, robust=8.0, candidate=True,
                   selected=True, tte=7.5, yes_ask=48, yes_bid=46):
    return {
        "type": "decision_record",
        "schema_version": 1,
        "run_id": "abc123",
        "event_ts_utc": "2026-08-17T12:00:00Z",
        "cycle_id": 1,
        "asset": asset,
        "ticker": ticker,
        "selected_side": side,
        "minutes_to_expiry": tte,
        "model_prob_selected": model,
        "market_p_selected": market,
        "raw_edge_cents": raw_edge,
        "robust_ev_cents": robust,
        "candidate_generated": candidate,
        "allocator_selected": selected,
        "rejection_reason": None if candidate else "ev_gate_non_positive",
        "yes_ask_cents": yes_ask,
        "yes_bid_cents": yes_bid,
        "no_ask_cents": None,
        "no_bid_cents": None,
        "yes_depth": 120,
        "no_depth": None,
    }


def test_load_decision_records_skips_malformed(tmp_path):
    p = tmp_path / "tel.jsonl"
    p.write_text(
        json.dumps(_telemetry_row()) + "\n"
        + "not json\n"
        + json.dumps({"type": "decision_scorecard", "cycle_id": 1}) + "\n"
        + json.dumps(_telemetry_row(asset="DOGE", ticker="KXDOGE15M-T2", candidate=False, selected=False)) + "\n",
        encoding="utf-8",
    )
    records = cr.load_decision_records(p)
    assert len(records) == 2  # scorecard and malformed line excluded
    assert cr.load_decision_records(tmp_path / "missing.jsonl") == []


def test_outcome_normalization(tmp_path):
    p = tmp_path / "out.jsonl"
    p.write_text("\n".join([
        json.dumps({"ticker": "A", "outcome": "yes"}),
        json.dumps({"ticker": "B", "outcome": 0}),
        json.dumps({"ticker": "C", "outcome": 100}),
        json.dumps({"ticker": "D", "outcome": 50}),       # ambiguous -> dropped
        json.dumps({"ticker": "E", "outcome": None}),      # unknown -> dropped
        json.dumps({"market_ticker": "F", "settlement": "no"}),
    ]), encoding="utf-8")
    outcomes = cr.load_outcomes(p)
    assert outcomes == {"A": 1, "B": 0, "C": 1, "F": 0}


def test_load_fill_pnls_readonly(tmp_path):
    db = tmp_path / "fills.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE kalshi_fills (fill_id TEXT PRIMARY KEY, market_ticker TEXT, "
        "proceeds_dollars REAL, fee_cost REAL)"
    )
    conn.execute("INSERT INTO kalshi_fills VALUES ('f1', 'KXBTC15M-T1', 0.40, 0.02)")
    conn.execute("INSERT INTO kalshi_fills VALUES ('f2', 'KXBTC15M-T1', -0.50, 0.02)")
    conn.execute("INSERT INTO kalshi_fills VALUES ('f3', 'KXDOGE15M-T2', 0.10, 0.01)")
    conn.commit()
    conn.close()
    pnls = cr.load_fill_pnls(db)
    assert pnls["KXBTC15M-T1"]["realized_pnl_dollars"] == pytest.approx(-0.10)
    assert pnls["KXBTC15M-T1"]["fills"] == 2
    assert pnls["KXDOGE15M-T2"]["realized_pnl_dollars"] == pytest.approx(0.10)
    assert cr.load_fill_pnls(tmp_path / "missing.db") == {}


# ---------------------------------------------------------------------------
# Join + report
# ---------------------------------------------------------------------------

def test_join_excludes_unresolved_from_calibration_never_treats_as_zero():
    records = [
        _telemetry_row(ticker="T-RES"),            # will resolve YES
        _telemetry_row(ticker="T-UNRES"),          # no outcome available
    ]
    outcomes = {"T-RES": 1}
    rows = cr.join_rows(records, outcomes, {})
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["T-RES"]["y"] == 1
    assert by_ticker["T-UNRES"]["y"] is None
    assert by_ticker["T-UNRES"]["resolved"] is False

    report = cr.build_report(records, outcomes, {})
    overall = report["slices"]["overall"]
    assert overall["evaluated"] == 2
    assert overall["resolved"] == 1
    # Brier computed only from the resolved row: (0.63-1)^2
    assert overall["brier_derived_model"] == pytest.approx((0.63 - 1) ** 2)


def test_no_side_spread_is_none_not_zero():
    rec = _telemetry_row()
    rec["yes_bid_cents"] = None  # missing bid
    rows = cr.join_rows([rec], {}, {})
    assert rows[0]["spread_cents"] is None
    report = cr.build_report([rec], {}, {})
    # Unbucketable spread is excluded from spread buckets, not counted as 0-1c
    assert report["slices"]["by_spread_bucket"] == {}


def test_report_slices_and_labeling():
    records = [
        _telemetry_row(asset="BTC", ticker="B1", model=0.63, market=0.48),
        _telemetry_row(asset="BTC", ticker="B2", model=0.60, market=0.50),
        _telemetry_row(asset="DOGE", ticker="D1", model=0.57, market=0.56,
                       raw_edge=1.0, robust=-6.0, candidate=False, selected=False),
    ]
    outcomes = {"B1": 1, "B2": 0, "D1": 1}
    pnls = {"B1": {"realized_pnl_dollars": 0.50, "fees_dollars": 0.02, "fills": 2},
            "B2": {"realized_pnl_dollars": -0.50, "fees_dollars": 0.02, "fills": 1}}
    report = cr.build_report(records, outcomes, pnls)

    # Terminology labeling required by the audit finding
    assert "derived_model_probability" in report["terminology"]
    assert "settlement_calibration" in report["terminology"]

    btc = report["slices"]["by_asset"]["BTC"]
    assert btc["evaluated"] == 2
    assert btc["resolved"] == 2
    assert btc["selected"] == 2
    assert btc["fee_inclusive_expectancy_dollars"] == pytest.approx(0.0)
    assert btc["total_realized_pnl_dollars"] == pytest.approx(0.0)
    assert btc["brier_market_reference"] is not None
    # predicted edge 0.15/0.10 vs realized (1-0.48)=0.52 and (0-0.50)=-0.50
    # gaps: 0.15-0.52=-0.37, 0.10-(-0.50)=0.60 -> mean 0.115
    assert btc["mean_predicted_minus_realized_edge"] == pytest.approx((-0.37 + 0.60) / 2)

    doge = report["slices"]["by_asset"]["DOGE"]
    assert doge["candidates"] == 0
    assert doge["top_rejection_reasons"] == {"ev_gate_non_positive": 1}

    by_side = report["slices"]["by_side"]
    assert "yes" in by_side
    by_price = report["slices"]["by_price_bucket"]
    assert "40-49c" in by_price and "50-65c" in by_price

    text = cr.render_text(report)
    assert "CALIBRATION AUDIT REPORT" in text
    assert "by_asset" in text


def test_dedupe_latest_per_market_prevents_repeat_selection_bias():
    # Same ticker selected on 17 cycles (typical within one 15m window) must
    # collapse to one market decision for calibration.
    repeated = [
        _telemetry_row(ticker="KXBTC15M-T1", model=0.63, market=0.48)
        for _ in range(17)
    ]
    other = _telemetry_row(ticker="KXETH15M-T2", asset="ETH", model=0.51, market=0.54,
                           candidate=False, selected=False)
    rows = cr.join_rows(repeated + [other], {"KXBTC15M-T1": 1, "KXETH15M-T2": 0}, {})
    deduped = cr.dedupe_latest_per_market(rows)
    assert len(deduped) == 2

    report = cr.build_report(repeated + [other],
                             {"KXBTC15M-T1": 1, "KXETH15M-T2": 0}, {})
    assert report["decision_funnel"]["evaluated_cycles"] == 18
    assert report["decision_funnel"]["calibration_eligible_records"] == 2
    assert report["counts"]["unique_decision_markets"] == 2
    # Brier uses 2 rows, not 18: ((0.63-1)^2 + (0.51-0)^2) / 2
    expected = ((0.63 - 1) ** 2 + 0.51 ** 2) / 2
    assert report["slices"]["overall"]["brier_derived_model"] == pytest.approx(expected)


def test_null_identity_rows_excluded_from_calibration():
    """Rows without ticker or selected_side must not enter the calibration
    cohort, Brier, side, or price buckets."""
    pre = [
        {"type": "decision_record", "asset": "BTC", "ticker": None, "selected_side": None,
         "model_prob_selected": 0.63, "market_p_selected": 0.48},
        {"type": "decision_record", "asset": "BTC", "ticker": "KXBTC15M-T1", "selected_side": None,
         "model_prob_selected": 0.63, "market_p_selected": 0.48},
    ]
    report = cr.build_report(pre, {}, {})
    assert report["decision_funnel"]["pre_side_rejections"] == 2
    assert report["decision_funnel"]["calibration_eligible_records"] == 0
    assert report["slices"]["overall"]["evaluated"] == 0


def test_resolution_reconciliation_pending_and_unresolvable(tmp_path):
    """Unresolved eligible rows within/outside the grace period map to correct
    states and the reconciliation table includes them."""
    import time as _time
    now = _time.time()
    # Row from 45 minutes ago, 15 minutes to expiry -> settled 30 minutes ago (past grace)
    old = _telemetry_row(ticker="KXBTC15M-OLD", model=0.60, market=0.50)
    old["event_ts_utc"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(now - 2700))
    old["minutes_to_expiry"] = 15.0
    # Row from 1 minute ago, 5 minutes to expiry -> still pending
    new = _telemetry_row(ticker="KXBTC15M-NEW", model=0.60, market=0.50)
    new["event_ts_utc"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(now - 60))
    new["minutes_to_expiry"] = 5.0
    report = cr.build_report([old, new], {}, {}, now_ts=now)
    recon = report["resolution_reconciliation"]
    assert len(recon["unresolvable"]) == 1
    assert recon["unresolvable"][0]["ticker"] == "KXBTC15M-OLD"
    assert recon["unresolvable"][0]["reason"] == "no_outcome_record_past_grace"
    assert len(recon["pending"]) == 1
    assert recon["pending"][0]["ticker"] == "KXBTC15M-NEW"
    assert report["decision_funnel"]["calibration_eligible_records"] == 2
    assert report["decision_funnel"]["resolved_records"] == 0


def test_cli_end_to_end(tmp_path, capsys):
    tel = tmp_path / "tel.jsonl"
    tel.write_text(json.dumps(_telemetry_row(ticker="T1")) + "\n", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps({"ticker": "T1", "outcome": "yes"}) + "\n", encoding="utf-8")
    json_out = tmp_path / "report" / "r.json"
    rc = cr.main([
        "--telemetry", str(tel),
        "--outcomes", str(out),
        "--fills-db", str(tmp_path / "absent.db"),
        "--json-out", str(json_out),
    ])
    assert rc == 0
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert report["counts"]["evaluated_records"] == 1
    assert report["decision_funnel"]["resolved_records"] == 1
    assert report["decision_funnel"]["calibration_eligible_records"] == 1
    captured = capsys.readouterr()
    assert "DERIVED" in captured.out


def test_calibration_report_uses_calibration_diagnostics_and_edge_slices():
    """The canonical brier/ece/reliability metrics come from calibration_diagnostics,
    and the edge-sign/magnitude slices are present for edge calibration."""
    records = [
        _telemetry_row(asset="BTC", ticker="B1", side="yes", model=0.42, market=0.40),
        _telemetry_row(asset="BTC", ticker="B2", side="yes", model=0.60, market=0.62),
    ]
    outcomes = {"B1": 1, "B2": 0}
    report = cr.build_report(records, outcomes, {})

    overall = report["slices"]["overall"]
    assert "brier_skill_score" in overall
    assert "expected_calibration_error" in overall
    assert "reliability_curve" in overall
    assert "mean_predicted_edge" in overall
    assert "mean_realized_edge" in overall

    by_edge = report["slices"]["by_edge_sign"]
    assert "underpriced" in by_edge
    assert "overpriced" in by_edge
    assert by_edge["underpriced"]["mean_predicted_edge"] == pytest.approx(0.02)
    assert by_edge["overpriced"]["mean_predicted_edge"] == pytest.approx(-0.02)

    by_mag = report["slices"]["by_edge_magnitude"]
    assert "0-2c" in by_mag or "2-5c" in by_mag
