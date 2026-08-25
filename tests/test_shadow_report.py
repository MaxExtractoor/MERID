"""Tests for scripts/shadow_report.py.

These tests generate synthetic shadow telemetry and verify that the report
produces correct metrics, exit codes, and safety-violation detection.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import pytest

# Use the venv python interpreter so the script runs in the same environment.
PYTHON = Path(sys.executable)
SHADOW_REPORT = Path(__file__).resolve().parents[1] / "scripts" / "shadow_report.py"


def _normal_cdf(z: float) -> float:
    return NormalDist().cdf(z)


def _compute_p_yes(spot: float, strike: float, seconds: float, vol: float = 0.6) -> float:
    t = seconds / (365.0 * 24.0 * 60.0 * 60.0)
    return _normal_cdf(math.log(spot / strike) / (vol * math.sqrt(t)))


def _make_candidate(
    *,
    run_id: str = "run_001",
    decision_id: str = "dec_001",
    ticker: str = "KXBTC15M-26AUG100000-00",
    asset: str = "BTC",
    spot: float = 66000.0,
    strike: float = 65000.0,
    seconds_to_expiry: float = 600.0,
    yes_bid_cents: float = 40.0,
    yes_ask_cents: float = 45.0,
    no_bid_cents: float = 55.0,
    no_ask_cents: float = 60.0,
    fee_cents: float = 2.0,
    selected_outcome: str = "yes",
    rejection_reason: str | None = None,
    settlement_reference: str = "cfb_rti_live",
    confidence_valid: bool = True,
    confidence_source: str = "uncertainty_engine",
    with_order: bool = True,
    final_minute: bool = False,
) -> dict:
    p_yes = _compute_p_yes(spot, strike, seconds_to_expiry)
    p_no = 1.0 - p_yes
    p_selected = p_yes if selected_outcome == "yes" else p_no

    if final_minute:
        seconds_to_expiry = 30.0

    executable = yes_ask_cents / 100.0 if selected_outcome == "yes" else no_ask_cents / 100.0
    fee = fee_cents / 100.0
    exit_reserve = fee
    model_risk_reserve = 0.05
    gross_edge = p_selected - executable
    net_edge = gross_edge - fee - exit_reserve - model_risk_reserve

    if selected_outcome == "yes":
        selected_price = yes_ask_cents
    else:
        # NO ask = 100 - YES bid, but for the record we use no_ask if provided.
        selected_price = no_ask_cents

    public_spot = spot + 10.0
    cf_rti_basis = public_spot - spot

    record = {
        "schema_version": 1,
        "record_type": "candidate",
        "run_id": run_id,
        "decision_id": decision_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ticker": ticker,
        "asset": asset,
        "target_price": strike,
        "spot_price": spot,
        "public_spot": public_spot,
        "cf_rti_basis": cf_rti_basis,
        "expiry_ts_ms": int(datetime.now(timezone.utc).timestamp() * 1000) + int(seconds_to_expiry * 1000),
        "seconds_to_expiry": seconds_to_expiry,
        "settlement_reference": settlement_reference,
        "cfb_symbol": "BRTI",
        "cfb_value": spot,
        "cfb_source_ts_ms": 1_700_000_000_000,
        "cfb_received_ts_ms": 1_700_000_000_050,
        "cfb_age_ms": 50,
        "cfb_sequence": 1,
        "cfb_60s_average": spot,
        "price_source_health": "healthy",
        "p_yes": p_yes,
        "p_no": p_no,
        "p_selected": p_selected,
        "p_opposite": p_no if selected_outcome == "yes" else p_yes,
        "gross_edge": gross_edge,
        "net_edge": net_edge,
        "confidence": 0.82,
        "confidence_valid": confidence_valid,
        "confidence_source": confidence_source,
        "confidence_reasons": [],
        "selected_outcome": selected_outcome,
        "selected_action": "buy",
        "selected_outcome_price": selected_price,
        "yes_bid_cents": yes_bid_cents,
        "yes_ask_cents": yes_ask_cents,
        "no_bid_cents": no_bid_cents,
        "no_ask_cents": no_ask_cents,
        "yes_depth_cc": 5000,
        "no_depth_cc": 5000,
        "fee_per_contract_cents": fee_cents,
        "annualized_vol": 0.6,
        "min_required_edge": 0.03,
        "model_risk_reserve": model_risk_reserve,
        "rejection_reason": rejection_reason,
        "edge_breakdown": {
            "p_yes": p_yes,
            "p_no": p_no,
            "selected_side": selected_outcome,
            "p_selected": p_selected,
            "p_opposite": p_no if selected_outcome == "yes" else p_yes,
            "executable_entry_price": executable,
            "entry_fee": fee,
            "exit_cost_reserve": exit_reserve,
            "model_risk_reserve": model_risk_reserve,
            "gross_edge": gross_edge,
            "net_edge": net_edge,
        },
    }

    if with_order:
        record["linked_order"] = True  # handled by a separate order record in the file
    return record


def _make_order(
    *,
    run_id: str = "run_001",
    decision_id: str = "dec_001",
    ticker: str = "KXBTC15M-26AUG100000-00",
    asset: str = "BTC",
    selected_outcome: str = "yes",
    price_cents: float = 45.0,
    status: str = "filled_paper",
    has_execution: bool = True,
) -> dict:
    kalshi_side = "BUY_YES" if selected_outcome == "yes" else "BUY_NO"
    return {
        "schema_version": 1,
        "record_type": "order",
        "run_id": run_id,
        "decision_id": decision_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ticker": ticker,
        "asset": asset,
        "kalshi_side": kalshi_side,
        "v2_book_side": "bid" if kalshi_side in ("BUY_YES", "SELL_NO") else "ask",
        "side": selected_outcome,
        "action": "buy",
        "price_cents": price_cents,
        "count": 1,
        "order_status": status,
        "order_mode": "paper",
        "has_execution": has_execution,
        "fill_price_cents": price_cents if has_execution else None,
        "client_order_id": f"15m_{ticker}_test",
    }


def _write_jsonl(path: Path, records: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


def _run_report(input_path: Path, extra_args: list | None = None) -> tuple:
    cmd = [str(PYTHON), str(SHADOW_REPORT), "--input", str(input_path), "--format", "both"]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def test_healthy_report_exits_zero():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        records = [
            _make_candidate(decision_id="dec_001"),
            _make_order(decision_id="dec_001"),
            _make_candidate(
                decision_id="dec_002",
                spot=64978.65,
                selected_outcome="no",
                no_ask_cents=45.0,
            ),
            _make_order(decision_id="dec_002", selected_outcome="no", price_cents=45.0),
        ]
        _write_jsonl(tmp_path / "shadow.jsonl", records)

        rc, stdout, stderr = _run_report(tmp_path)
        assert rc == 0, f"Expected exit 0, got {rc}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        assert "Wrote JSON" in stdout
        assert "exit_code: 0" in stdout


def test_invalid_settlement_provenance_exit_code():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        records = [
            _make_candidate(decision_id="dec_001", settlement_reference="public_spot_fallback:cf_rti_unavailable"),
        ]
        _write_jsonl(tmp_path / "shadow.jsonl", records)

        rc, stdout, stderr = _run_report(tmp_path)
        assert rc == 0, f"Expected no paper-eligible candidate; exit 0, got {rc}\n{stderr}"


def test_invalid_confidence_provenance_exit_code():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        records = [
            _make_candidate(decision_id="dec_001", confidence_valid=False, confidence_source="expired"),
            _make_order(decision_id="dec_001"),
        ]
        _write_jsonl(tmp_path / "shadow.jsonl", records)

        rc, stdout, stderr = _run_report(tmp_path)
        assert rc == 3, f"Expected exit 3, got {rc}\n{stderr}"


def test_p_selected_le_half_exit_code():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Construct a consistent candidate with p_yes=0.45 and executable 31c so
        # net_edge is positive but p_selected is still below the 0.5 threshold.
        candidate = _make_candidate(
            decision_id="dec_001",
            spot=64978.65,
            strike=65000.0,
            yes_ask_cents=31.0,
        )
        order = _make_order(decision_id="dec_001", price_cents=31.0)
        _write_jsonl(tmp_path / "shadow.jsonl", [candidate, order])

        rc, stdout, stderr = _run_report(tmp_path)
        assert rc == 4, f"Expected exit 4, got {rc}\n{stderr}"


def test_side_v2_mismatch_exit_code():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        records = [
            _make_candidate(decision_id="dec_001", selected_outcome="yes"),
            _make_order(decision_id="dec_001", selected_outcome="no"),  # wrong side
        ]
        _write_jsonl(tmp_path / "shadow.jsonl", records)

        rc, stdout, stderr = _run_report(tmp_path)
        assert rc == 5, f"Expected exit 5, got {rc}\n{stderr}"


def test_final_minute_admission_exit_code():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        records = [
            _make_candidate(decision_id="dec_001", final_minute=True),
            _make_order(decision_id="dec_001"),
        ]
        _write_jsonl(tmp_path / "shadow.jsonl", records)

        rc, stdout, stderr = _run_report(tmp_path)
        assert rc == 6, f"Expected exit 6, got {rc}\n{stderr}"


def test_strict_mode_fails_malformed_record():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with open(tmp_path / "bad.jsonl", "w", encoding="utf-8") as f:
            f.write("not json\n")

        rc, stdout, stderr = _run_report(tmp_path, ["--strict"])
        assert rc == 1, f"Expected exit 1, got {rc}\n{stderr}"


def test_run_id_filter_and_output_files():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        records = [
            _make_candidate(run_id="run_001", decision_id="dec_001", rejection_reason="insufficient_edge"),
            _make_candidate(run_id="run_002", decision_id="dec_002", rejection_reason="insufficient_edge"),
        ]
        _write_jsonl(tmp_path / "shadow.jsonl", records)

        with tempfile.TemporaryDirectory() as out_tmp:
            out_path = Path(out_tmp)
            rc, stdout, stderr = _run_report(tmp_path, ["--run-id", "run_001", "--output", str(out_path), "--format", "json"])
            assert rc == 0, f"Expected exit 0, got {rc}\n{stderr}"
            json_files = list(out_path.glob("*.json"))
            assert len(json_files) == 1
            report = json.loads(json_files[0].read_text(encoding="utf-8"))
            assert report["run_ids"] == ["run_001"]


def test_empty_directory_produces_report():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with tempfile.TemporaryDirectory() as out_tmp:
            out_path = Path(out_tmp)
            rc, stdout, stderr = _run_report(tmp_path, ["--output", str(out_path), "--format", "json"])
            assert rc == 0, f"Expected exit 0, got {rc}\n{stderr}"
            json_files = list(out_path.glob("*.json"))
            assert len(json_files) == 1
            report = json.loads(json_files[0].read_text(encoding="utf-8"))
            assert report["total_records"] == 0
