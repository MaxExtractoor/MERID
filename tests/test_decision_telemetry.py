"""Acceptance tests for per-cycle decision telemetry (schema v1).

Covers:
1. A five-asset cycle produces exactly five records, even with zero candidates.
2. A BTC-only selection reports why ETH/SOL/XRP/DOGE were rejected.
3. A cycle with two valid candidates records ranks and the allocator loser.
4. A missing/stale market generates a precise rejection code, not a blank record.
5. A telemetry write failure is non-fatal.
6. Serialization of Decimal, Enum, datetime, None, NaN/Infinity.
7. A replay fixture produces a stable scorecard.
"""

import enum
import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from merid.prediction import decision_telemetry as dt


@pytest.fixture(autouse=True)
def telemetry_tmp_path(tmp_path, monkeypatch):
    path = tmp_path / "decision_telemetry.jsonl"
    monkeypatch.setenv("MERID_DECISION_TELEMETRY_PATH", str(path))
    monkeypatch.delenv("MERID_DECISION_TELEMETRY", raising=False)
    dt._reset_writer_for_tests()
    yield path
    dt._reset_writer_for_tests()


def _read_records(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _waterfall(selected=False, final_reason="", stages=None):
    return {
        "asset": "BTC",
        "stages": stages or {
            "market_discovered": {"status": True, "reason": ""},
            "spot_price": {"status": True, "reason": ""},
            "market_open": {"status": True, "reason": ""},
            "signal_generated": {"status": True, "reason": ""},
            "candidate_generated": {"status": True, "reason": ""},
        },
        "selected": selected,
        "final_reason": final_reason,
    }


def _decision(**overrides):
    base = {
        "ticker": "KXBTC15M-26AUG17-T115999.99",
        "minutes_to_expiry": 7.5,
        "selected_side": "yes",
        "model_prob": 0.63,
        "market_prob": 0.48,
        "raw_edge_cents": 15.0,
        "entry_fee_cents": 2.0,
        "slippage_guard_cents": 5,
        "all_in_cost_cents": 50.0,
        "ev_net_cents": 13.0,
        "robust_ev_cents": 8.0,
        "velocity": 0.0004,
        "velocity_threshold": 0.00015,
        "macd_histogram": 0.0012,
        "rsi": 61.0,
        "fvg_direction": "up",
        "fvg_confidence": 0.7,
        "order_book_imbalance": 0.2,
        "yes_ask_cents": 48,
        "no_ask_cents": 53,
    }
    base.update(overrides)
    return base


def _make_five_asset_records(cycle_id=842):
    """One selected BTC candidate plus four EV-gate rejections."""
    records = []
    btc = dt.build_asset_record(
        cycle_id=cycle_id,
        asset="BTC",
        decision=_decision(),
        waterfall=_waterfall(selected=True),
        candidate={"ticker": "KXBTC15M-26AUG17-T115999.99", "side": "yes", "edge_pct": 15.0},
        candidate_rank=1,
        allocator_rank=1,
        allocator_selected=True,
    )
    records.append(btc)
    for asset, side, model, market, edge, robust in [
        ("ETH", "no", 0.51, 0.54, -3.0, -8.0),
        ("SOL", "yes", 0.57, 0.55, 2.0, -3.0),
        ("XRP", "no", 0.49, 0.52, -3.0, -8.0),
        ("DOGE", "yes", 0.57, 0.56, 1.0, -6.0),
    ]:
        records.append(dt.build_asset_record(
            cycle_id=cycle_id,
            asset=asset,
            decision=_decision(
                selected_side=side, model_prob=model, market_prob=market,
                raw_edge_cents=edge, robust_ev_cents=robust, ev_net_cents=robust,
                rejection_reason="ev_gate_non_positive",
            ),
            waterfall=_waterfall(final_reason="ev_gate_non_positive"),
            candidate=None,
        ))
    return records


def test_five_asset_cycle_produces_five_records(telemetry_tmp_path):
    records = _make_five_asset_records()
    assert dt.emit_cycle(842, records)
    lines = _read_records(telemetry_tmp_path)
    decision_records = [r for r in lines if r["type"] == "decision_record"]
    scorecards = [r for r in lines if r["type"] == "decision_scorecard"]
    assert len(decision_records) == 5
    assert len(scorecards) == 1
    assert {r["asset"] for r in decision_records} == {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    assert all(r["cycle_id"] == 842 for r in decision_records)
    assert all(r["schema_version"] == 1 for r in decision_records)
    assert all(r["run_id"] == dt.RUN_ID for r in decision_records)


def test_zero_candidate_cycle_still_produces_five_records(telemetry_tmp_path):
    records = [
        dt.build_asset_record(
            cycle_id=1,
            asset=asset,
            decision={"rejection_reason": "ev_gate_non_positive"},
            waterfall=_waterfall(final_reason="ev_gate_non_positive"),
            candidate=None,
        )
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    ]
    assert dt.emit_cycle(1, records)
    decision_records = [r for r in _read_records(telemetry_tmp_path) if r["type"] == "decision_record"]
    assert len(decision_records) == 5
    assert all(not r["candidate_generated"] for r in decision_records)


def test_btc_only_selection_attributes_alt_rejections(telemetry_tmp_path):
    records = _make_five_asset_records()
    dt.emit_cycle(842, records)
    by_asset = {r["asset"]: r for r in _read_records(telemetry_tmp_path) if r["type"] == "decision_record"}
    assert by_asset["BTC"]["allocator_selected"] is True
    for asset in ["ETH", "SOL", "XRP", "DOGE"]:
        rec = by_asset[asset]
        assert rec["allocator_selected"] is False
        assert rec["rejection_reason"] == "ev_gate_non_positive"
        assert rec["rejection_stage"] == "economics_failure"
        assert rec["robust_ev_cents"] is not None


def test_two_candidates_records_allocator_loser():
    wf = _waterfall()
    winner = dt.build_asset_record(
        cycle_id=9, asset="BTC", decision=_decision(), waterfall=wf,
        candidate={"ticker": "T1", "side": "yes", "edge_pct": 15.0},
        candidate_rank=1, allocator_rank=1, allocator_selected=True,
    )
    loser = dt.build_asset_record(
        cycle_id=9, asset="ETH", decision=_decision(robust_ev_cents=4.0, ev_net_cents=6.0),
        waterfall=wf,
        candidate={"ticker": "T2", "side": "yes", "edge_pct": 9.0},
        candidate_rank=2, allocator_rank=None, allocator_selected=False,
    )
    loser["rejection_stage"] = "allocator_loss"
    loser["rejection_reason"] = "allocator_loss"
    assert winner["allocator_rank"] == 1 and winner["allocator_selected"]
    assert loser["candidate_rank"] == 2
    assert loser["allocator_rank"] is None
    assert loser["rejection_stage"] == "allocator_loss"
    scorecard = dt.format_scorecard(9, [winner, loser])
    assert "allocator_loss" in scorecard
    assert "candidate_rank=2" in scorecard


def test_missing_market_generates_precise_rejection_code():
    stages = {
        "market_discovered": {"status": False, "reason": "no_current_15m_market"},
        "spot_price": {"status": True, "reason": ""},
        "market_open": {"status": False, "reason": "no_current_15m_market"},
        "signal_generated": {"status": False, "reason": "no_current_15m_market"},
        "candidate_generated": {"status": False, "reason": "no_current_15m_market"},
    }
    rec = dt.build_asset_record(
        cycle_id=3,
        asset="SOL",
        decision={"rejection_reason": "no_current_15m_market"},
        waterfall=_waterfall(final_reason="no_current_15m_market", stages=stages),
        candidate=None,
    )
    assert rec["market_available"] is False
    assert rec["rejection_stage"] == "no_market_data"
    assert rec["rejection_reason"] == "no_current_15m_market"
    scorecard = dt.format_scorecard(3, [rec])
    assert "no_market_data" in scorecard


def test_telemetry_write_failure_is_nonfatal(telemetry_tmp_path, monkeypatch):
    writer = dt._get_writer()
    monkeypatch.setattr(writer, "append", lambda record: False)
    records = _make_five_asset_records()
    ok = dt.emit_cycle(842, records)
    assert ok is False
    assert dt.stats()["write_failures"] >= 1
    # Raising writer must also be contained
    def _boom(record):
        raise OSError("disk full")
    monkeypatch.setattr(writer, "append", _boom)
    assert dt.emit_cycle(843, records) is False


def test_serialization_of_special_types():
    class Side(enum.Enum):
        YES = "yes"

    class FloatEnum(enum.Enum):
        EDGE = 1.5

    record = {
        "decimal_value": Decimal("0.49"),
        "decimal_negative": Decimal("-1.55"),
        "enum_str": Side.YES,
        "enum_float": FloatEnum.EDGE,
        "dt_utc": datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        "none_value": None,
        "nan_value": float("nan"),
        "inf_value": float("inf"),
        "neg_inf": float("-inf"),
        "nested": {"decimal": Decimal("63.5"), "items": [Decimal("0.01"), None]},
    }
    sanitized = dt.sanitize(record)
    # Must round-trip through strict JSON (allow_nan=False rejects NaN/Inf)
    encoded = json.dumps(sanitized, allow_nan=False)
    decoded = json.loads(encoded)
    assert decoded["decimal_value"] == pytest.approx(0.49)
    assert decoded["decimal_negative"] == pytest.approx(-1.55)
    assert decoded["enum_str"] == "yes"
    assert decoded["enum_float"] == pytest.approx(1.5)
    assert decoded["dt_utc"] == "2026-08-17T12:00:00+00:00"
    assert decoded["none_value"] is None
    assert decoded["nan_value"] is None
    assert decoded["inf_value"] is None
    assert decoded["neg_inf"] is None
    assert decoded["nested"]["decimal"] == pytest.approx(63.5)
    assert math.isfinite(decoded["decimal_value"])


def test_replay_fixture_stable_scorecard():
    records = _make_five_asset_records()
    scorecard = dt.format_scorecard(842, records)
    lines = scorecard.splitlines()
    assert lines[0] == "DECISION-SCORECARD cycle=842"
    assert "BTC: PASS | robust_ev=+8c | rank=1 | selected" in lines[1]
    eth_line = next(l for l in lines if l.startswith("ETH:"))
    assert "ev_gate_non_positive" in eth_line
    assert "robust_ev=-8c" in eth_line
    doge_line = next(l for l in lines if l.startswith("DOGE:"))
    assert "raw_edge=+1c" in doge_line
    assert "robust_ev=-6c" in doge_line
    # Stability: identical input produces identical output
    assert dt.format_scorecard(842, _make_five_asset_records()) == scorecard


def test_record_has_decision_id_terminal_stage_rejection_chain():
    record = dt.build_asset_record(
        cycle_id=1,
        asset="BTC",
        decision={"ticker": "KXBTC15M-T1", "selected_side": "yes"},
        waterfall={
            "stages": {
                "market_discovered": {"status": True, "reason": ""},
                "spot_price": {"status": True, "reason": ""},
                "market_open": {"status": True, "reason": ""},
                "signal_generated": {"status": False, "reason": "velocity_threshold"},
                "candidate_generated": {"status": False, "reason": ""},
            },
            "selected": False,
            "final_reason": "",
        },
        candidate=None,
    )
    assert record["decision_id"] == "KXBTC15M-T1:yes"
    assert record["terminal_stage"] == "signal_generated"
    assert record["rejection_chain"] == [{"stage": "signal_generated", "reason": "velocity_threshold"}]


def test_pre_side_record_has_no_decision_id():
    record = dt.build_asset_record(
        cycle_id=1,
        asset="DOGE",
        decision={},
        waterfall={
            "stages": {"market_discovered": {"status": False, "reason": "no_market"}},
            "selected": False,
            "final_reason": "no_market",
        },
        candidate=None,
    )
    assert record["decision_id"] is None
    assert record["terminal_stage"] == "market_discovered"


def test_record_exposes_macd_edge_components_and_spot_price():
    record = dt.build_asset_record(
        cycle_id=1,
        asset="BTC",
        decision={
            "ticker": "KXBTC15M-T1",
            "selected_side": "yes",
            "spot_price": 95000.0,
            "macd_histogram": 1.49,
            "macd_hist_pct": 0.001568,
            "base_edge_yes": 1.0,
            "macd_edge_component_yes": 0.0157,
            "edge_yes_pct": 1.0157,
            "base_edge_no": 1.0,
            "macd_edge_component_no": -0.0157,
            "edge_no_pct": 0.9843,
            "edge_pct": 1.0157,
            "capped_edge_pct": 1.0157,
        },
        waterfall={"stages": {"candidate_generated": {"status": True}}, "selected": False},
        candidate={"ticker": "KXBTC15M-T1", "side": "yes"},
        allocator_selected=True,
    )
    assert record["spot_price"] == 95000.0
    assert record["macd_hist_pct"] == 0.001568
    assert record["macd_edge_component_yes"] == 0.0157
    assert record["macd_edge_component_no"] == -0.0157
    assert record["capped_edge_pct"] == 1.0157


def test_selected_terminal_stage():
    record = dt.build_asset_record(
        cycle_id=1,
        asset="BTC",
        decision={"ticker": "KXBTC15M-T1", "selected_side": "yes"},
        waterfall={"stages": {"candidate_generated": {"status": True, "reason": ""}}, "selected": False},
        candidate={"ticker": "KXBTC15M-T1", "side": "yes"},
        allocator_selected=True,
    )
    assert record["decision_id"] == "KXBTC15M-T1:yes"
    assert record["terminal_stage"] == "selected"


def test_disabled_telemetry_is_noop(telemetry_tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_DECISION_TELEMETRY", "0")
    assert dt.emit_cycle(1, _make_five_asset_records()) is True
    assert not telemetry_tmp_path.exists()
