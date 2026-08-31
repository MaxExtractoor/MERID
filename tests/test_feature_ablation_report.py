"""Tests for the feature ablation report."""

import json

import pytest

from merid.analysis import feature_ablation_report as far


def _row(ticker, side, market, model, outcome, **features):
    return {
        "type": "decision_record",
        "schema_version": 1,
        "run_id": "test",
        "event_ts_utc": "2026-08-17T12:00:00Z",
        "cycle_id": 1,
        "asset": ticker.split("-")[0].replace("KX", "").replace("15M", ""),
        "ticker": ticker,
        "selected_side": side,
        "minutes_to_expiry": 7.5,
        "model_prob_selected": model,
        "market_p_selected": market,
        "raw_edge_cents": (model - market) * 100.0,
        "robust_ev_cents": (model - market) * 100.0 - 2.0,
        "candidate_generated": True,
        "allocator_selected": False,
        "rejection_reason": None,
        **features,
    }


def test_incremental_vs_market_improves_with_real_signal():
    # 20 yes-side records.  Market price = 0.40.  True yes rate = 0.75.
    # The derived model is the market (no edge), so it is uncalibrated.
    # The rti_return_10s feature is positive for all "yes" outcomes and
    # negative for "no" outcomes; market + rti_return should be more
    # discriminating.
    records = []
    for i in range(20):
        outcome = 1 if i < 15 else 0
        rti = 0.20 if outcome == 1 else -0.20
        records.append(
            _row(
                f"KXBTC15M-T{i}",
                "yes",
                0.40,
                0.40,
                outcome,
                rti_return_10s=rti,
                microstructure_delta_pp=0.0,
                feature_valid=True,
            )
        )

    outcomes = {f"KXBTC15M-T{i}": (1 if i < 15 else 0) for i in range(20)}
    fill_pnls = {}

    report = far.build_feature_ablation_report(records, outcomes, fill_pnls)
    incremental = report["incremental_vs_market"]

    assert "baseline_market" in incremental
    assert "rti_return_10s" in incremental
    # AUC should improve because the feature is perfectly correlated with outcome.
    assert incremental["rti_return_10s"]["auc_roc"] > incremental["baseline_market"]["auc_roc"]


def test_feature_slices_groups_by_feature_value():
    records = [
        _row("KXBTC15M-T0", "yes", 0.40, 0.55, 1, microstructure_yes_book_imbalance=0.8),
        _row("KXBTC15M-T1", "yes", 0.40, 0.55, 1, microstructure_yes_book_imbalance=0.7),
        _row("KXBTC15M-T2", "yes", 0.40, 0.55, 0, microstructure_yes_book_imbalance=-0.5),
        _row("KXBTC15M-T3", "yes", 0.40, 0.55, 0, microstructure_yes_book_imbalance=-0.6),
    ]
    outcomes = {r["ticker"]: r["market_p_selected"] for r in records}
    # Replace outcomes with actuals above.
    outcomes = {
        "KXBTC15M-T0": 1,
        "KXBTC15M-T1": 1,
        "KXBTC15M-T2": 0,
        "KXBTC15M-T3": 0,
    }
    report = far.build_feature_ablation_report(records, outcomes, {})

    slices = report["feature_slices"]
    assert "book_imbalance_yes" in slices
    # Two positive, two negative rows.
    assert "positive" in slices["book_imbalance_yes"]["buckets"]
    assert "negative" in slices["book_imbalance_yes"]["buckets"]


def test_cli_end_to_end(tmp_path, capsys):
    tel = tmp_path / "tel.jsonl"
    out = tmp_path / "out.jsonl"
    jout = tmp_path / "report.json"

    records = [
        _row("KXBTC15M-T0", "yes", 0.40, 0.55, 1, rti_return_10s=0.15),
        _row("KXBTC15M-T1", "yes", 0.40, 0.55, 0, rti_return_10s=-0.15),
    ]
    with tel.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    outcomes = {"KXBTC15M-T0": 1, "KXBTC15M-T1": 0}
    with out.open("w") as f:
        for t, y in outcomes.items():
            f.write(json.dumps({"ticker": t, "outcome": y}) + "\n")

    far.main(["--telemetry", str(tel), "--outcomes", str(out), "--json-out", str(jout)])
    captured = capsys.readouterr()
    assert "Wrote feature ablation report" in captured.out
    report = json.loads(jout.read_text())
    assert report["report_schema_version"] == far.REPORT_SCHEMA_VERSION
