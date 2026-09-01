"""Focused tests for the golden record rollup."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

from merid.monitoring.golden_record_rollup import (
    GoldenRecordBuilder,
    build_golden_records,
)


# Schema from merid.monitoring.trade_attribution_fact_table.
_TRADE_ATTRIBUTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_attribution_fact (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    event_ts TEXT,
    run_id TEXT,
    process_id TEXT,
    signal_id TEXT,
    intent_id TEXT,
    client_order_id TEXT,
    order_id TEXT,
    fill_id TEXT,
    ticker TEXT,
    asset TEXT,
    side TEXT,
    action TEXT,
    price_cents INTEGER,
    count_fp TEXT,
    quantity_cc INTEGER,
    order_type TEXT,
    time_in_force TEXT,
    post_only INTEGER,
    reduce_only INTEGER,
    cancel_order_on_pause INTEGER,
    self_trade_prevention_type TEXT,
    max_execution_cost_cents INTEGER,
    take_profit_price_cents INTEGER,
    stop_loss_price_cents INTEGER,
    source TEXT,
    order_status TEXT,
    fill_quantity_cc INTEGER,
    avg_fill_price_cents INTEGER,
    fee_cost_cents INTEGER,
    realized_pnl_cents INTEGER,
    settlement_outcome TEXT,
    settlement_price_cents INTEGER,
    settlement_ts TEXT,
    rejection_reason TEXT,
    error TEXT,
    metadata TEXT
)
"""


@dataclass
class _FixturePaths:
    fact_db: Path
    decision_telemetry: Path
    settlement_outcomes: Path
    out_jsonl: Path
    out_db: Path


@pytest.fixture
def fixture_paths():
    with tempfile.TemporaryDirectory() as tmp:
        fact_db = Path(tmp) / "trade_attribution_fact.db"
        decision_telemetry = Path(tmp) / "decision_telemetry.jsonl"
        settlement_outcomes = Path(tmp) / "settlement_outcomes.jsonl"
        out_jsonl = Path(tmp) / "golden_records.jsonl"
        out_db = Path(tmp) / "golden_records.db"

        # Create empty source files.
        decision_telemetry.write_text("", encoding="utf-8")
        settlement_outcomes.write_text("", encoding="utf-8")

        yield _FixturePaths(
            fact_db=fact_db,
            decision_telemetry=decision_telemetry,
            settlement_outcomes=settlement_outcomes,
            out_jsonl=out_jsonl,
            out_db=out_db,
        )


def _insert_event(conn: sqlite3.Connection, row: Dict[str, Any]) -> None:
    columns = [
        "event_type", "event_ts", "run_id", "process_id", "signal_id",
        "intent_id", "client_order_id", "order_id", "fill_id", "ticker",
        "asset", "side", "action", "price_cents", "count_fp", "quantity_cc",
        "order_type", "time_in_force", "post_only", "reduce_only",
        "cancel_order_on_pause", "self_trade_prevention_type",
        "max_execution_cost_cents", "take_profit_price_cents",
        "stop_loss_price_cents", "source", "order_status", "fill_quantity_cc",
        "avg_fill_price_cents", "fee_cost_cents", "realized_pnl_cents",
        "settlement_outcome", "settlement_price_cents", "settlement_ts",
        "rejection_reason", "error", "metadata",
    ]
    placeholders = ",".join("?" * len(columns))
    sql = f"INSERT INTO trade_attribution_fact ({','.join(columns)}) VALUES ({placeholders})"
    values = [row.get(c) for c in columns]
    conn.execute(sql, values)


def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, default=str) + "\n")


def _build_fact_db(fact_db: Path, rows: List[Dict[str, Any]]) -> None:
    conn = sqlite3.connect(str(fact_db))
    try:
        conn.execute(_TRADE_ATTRIBUTION_SCHEMA)
        for row in rows:
            _insert_event(conn, row)
        conn.commit()
    finally:
        conn.close()


def test_golden_record_build_full_lifecycle(fixture_paths: _FixturePaths):
    """A happy-path intent -> order -> fill -> settlement becomes one golden record."""
    ts = datetime.now(timezone.utc).isoformat()
    intent_meta = {
        "decision_id": "KXBTC15M-TEST-000000-00:yes",
        "parent_entry_intent_id": None,
        "entry_or_exit": "entry",
    }
    fill_meta = {
        "canonical_position_side": "yes",
        "canonical_position_action": "buy",
        "entry_or_exit": "entry",
        "unmatched": False,
    }
    settlement_meta = {
        "avg_price_cents": 55,
        "entry_intent_id": "intent-1",
        "fill_source": "alpha",
    }

    rows = [
        {
            "event_type": "intent",
            "event_ts": ts,
            "run_id": "run-1",
            "process_id": "pid-1",
            "signal_id": "signal-1",
            "intent_id": "intent-1",
            "client_order_id": "coid-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "asset": "BTC",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "count_fp": "1",
            "quantity_cc": 100,
            "order_type": "limit",
            "time_in_force": "GTC",
            "post_only": 0,
            "reduce_only": 0,
            "metadata": json.dumps(intent_meta),
        },
        {
            "event_type": "order",
            "event_ts": ts,
            "intent_id": "intent-1",
            "client_order_id": "coid-1",
            "order_id": "order-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "quantity_cc": 100,
            "order_status": "resting",
            "metadata": json.dumps({"client_order_id": "coid-1"}),
        },
        {
            "event_type": "fill",
            "event_ts": ts,
            "run_id": "run-1",
            "intent_id": "intent-1",
            "client_order_id": "coid-1",
            "order_id": "order-1",
            "fill_id": "fill-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "asset": "BTC",
            "side": "yes",
            "action": "buy",
            "fill_quantity_cc": 100,
            "avg_fill_price_cents": 55,
            "fee_cost_cents": 2,
            "source": "websocket",
            "metadata": json.dumps(fill_meta),
        },
        {
            "event_type": "settlement",
            "event_ts": ts,
            "intent_id": "intent-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "settlement_outcome": "yes",
            "settlement_price_cents": 100,
            "realized_pnl_cents": 45,
            "settlement_ts": ts,
            "metadata": json.dumps(settlement_meta),
        },
    ]
    _build_fact_db(fixture_paths.fact_db, rows)

    _write_jsonl(
        fixture_paths.decision_telemetry,
        [
            {
                "type": "decision_record",
                "event_ts_utc": ts,
                "run_id": "run-1",
                "ticker": "KXBTC15M-TEST-000000-00",
                "selected_side": "yes",
                "decision_id": "KXBTC15M-TEST-000000-00:yes",
                "model_prob_selected": 0.65,
                "market_p_selected": 0.55,
                "raw_edge_cents": 10.0,
                "gross_edge_cents": 10.0,
                "net_edge_cents": 8.0,
                "robust_ev_cents": 5.0,
                "tte_seconds": 600.0,
            }
        ],
    )

    _write_jsonl(
        fixture_paths.settlement_outcomes,
        [
            {
                "event_type": "settlement_outcome",
                "observed_at_utc": ts,
                "ticker": "KXBTC15M-TEST-000000-00",
                "outcome": "yes",
                "resolved_yes": 1,
            }
        ],
    )

    records, summary = build_golden_records(
        fact_db=str(fixture_paths.fact_db),
        decision_telemetry=str(fixture_paths.decision_telemetry),
        settlement_outcomes=str(fixture_paths.settlement_outcomes),
        lookback_hours=24,
        out_jsonl=str(fixture_paths.out_jsonl),
        out_db=str(fixture_paths.out_db),
    )

    assert len(records) == 1, summary.errors
    rec = records[0]
    assert rec.lifecycle_status == "settled"
    assert rec.ticker == "KXBTC15M-TEST-000000-00"
    assert rec.intent_id == "intent-1"
    assert rec.has_fill is True
    assert rec.has_settlement is True
    assert rec.fill_quantity_cc == 100
    assert rec.fill_price_cents == 55
    assert rec.fee_cents == 2
    assert rec.realized_pnl_cents == 45
    assert rec.settlement_outcome == "yes"
    assert rec.authoritative_settlement_outcome == "yes"
    assert rec.settlement_mismatch is False
    assert rec.decision_model_prob_selected == 0.65
    assert rec.decision_market_p == 0.55
    assert rec.decision_side == "yes"
    assert rec.divergence_flags == []

    # JSONL and DB outputs exist.
    assert fixture_paths.out_jsonl.exists()
    assert fixture_paths.out_db.exists()


def test_golden_record_detects_missing_settlement(fixture_paths: _FixturePaths):
    """If the market is settled authoritatively but we have no settlement event, flag it."""
    ts = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "event_type": "intent",
            "event_ts": ts,
            "intent_id": "intent-1",
            "client_order_id": "coid-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "asset": "BTC",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "count_fp": "1",
            "quantity_cc": 100,
            "metadata": json.dumps({"entry_or_exit": "entry"}),
        },
        {
            "event_type": "fill",
            "event_ts": ts,
            "intent_id": "intent-1",
            "fill_id": "fill-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "side": "yes",
            "action": "buy",
            "fill_quantity_cc": 100,
            "avg_fill_price_cents": 55,
            "fee_cost_cents": 2,
            "metadata": json.dumps({"canonical_position_side": "yes", "canonical_position_action": "buy", "entry_or_exit": "entry"}),
        },
    ]
    _build_fact_db(fixture_paths.fact_db, rows)

    _write_jsonl(
        fixture_paths.settlement_outcomes,
        [
            {
                "event_type": "settlement_outcome",
                "observed_at_utc": ts,
                "ticker": "KXBTC15M-TEST-000000-00",
                "outcome": "yes",
                "resolved_yes": 1,
            }
        ],
    )

    records, _ = build_golden_records(
        fact_db=str(fixture_paths.fact_db),
        decision_telemetry=str(fixture_paths.decision_telemetry),
        settlement_outcomes=str(fixture_paths.settlement_outcomes),
        lookback_hours=24,
        out_jsonl=str(fixture_paths.out_jsonl),
        out_db=str(fixture_paths.out_db),
    )

    assert len(records) == 1
    assert records[0].has_fill is True
    assert records[0].has_settlement is False
    assert records[0].has_authoritative_settlement is True
    assert "missing_settlement_for_settled_market" in records[0].divergence_flags


def test_golden_record_detects_side_mismatch(fixture_paths: _FixturePaths):
    """A fill whose canonical side differs from the intent side should be flagged."""
    ts = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "event_type": "intent",
            "event_ts": ts,
            "intent_id": "intent-1",
            "client_order_id": "coid-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "quantity_cc": 100,
            "metadata": json.dumps({}),
        },
        {
            "event_type": "fill",
            "event_ts": ts,
            "intent_id": "intent-1",
            "fill_id": "fill-1",
            "ticker": "KXBTC15M-TEST-000000-00",
            "fill_quantity_cc": 100,
            "avg_fill_price_cents": 55,
            "fee_cost_cents": 2,
            "metadata": json.dumps({"canonical_position_side": "no", "canonical_position_action": "buy", "entry_or_exit": "entry"}),
        },
    ]
    _build_fact_db(fixture_paths.fact_db, rows)

    records, _ = build_golden_records(
        fact_db=str(fixture_paths.fact_db),
        decision_telemetry=str(fixture_paths.decision_telemetry),
        settlement_outcomes=str(fixture_paths.settlement_outcomes),
        lookback_hours=24,
        out_jsonl=str(fixture_paths.out_jsonl),
        out_db=str(fixture_paths.out_db),
    )

    assert len(records) == 1
    assert records[0].lifecycle_status == "filled"
    assert "side_mismatch" in records[0].divergence_flags


def test_golden_record_exits_attach_to_parent(fixture_paths: _FixturePaths):
    """An exit order's fill_ids are attached to the parent entry record."""
    ts = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "event_type": "intent",
            "event_ts": ts,
            "intent_id": "intent-entry",
            "client_order_id": "coid-entry",
            "ticker": "KXBTC15M-TEST-000000-00",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "quantity_cc": 100,
            "metadata": json.dumps({"entry_or_exit": "entry"}),
        },
        {
            "event_type": "fill",
            "event_ts": ts,
            "intent_id": "intent-entry",
            "fill_id": "fill-entry",
            "ticker": "KXBTC15M-TEST-000000-00",
            "fill_quantity_cc": 100,
            "avg_fill_price_cents": 55,
            "fee_cost_cents": 2,
            "metadata": json.dumps({"canonical_position_side": "yes", "canonical_position_action": "buy", "entry_or_exit": "entry"}),
        },
        {
            "event_type": "intent",
            "event_ts": ts,
            "intent_id": "intent-exit",
            "client_order_id": "coid-exit",
            "ticker": "KXBTC15M-TEST-000000-00",
            "side": "yes",
            "action": "sell",
            "price_cents": 75,
            "quantity_cc": 100,
            "reduce_only": 1,
            "metadata": json.dumps({
                "parent_entry_intent_id": "intent-entry",
                "entry_or_exit": "exit",
            }),
        },
        {
            "event_type": "fill",
            "event_ts": ts,
            "intent_id": "intent-exit",
            "fill_id": "fill-exit",
            "ticker": "KXBTC15M-TEST-000000-00",
            "fill_quantity_cc": 100,
            "avg_fill_price_cents": 75,
            "fee_cost_cents": 2,
            "metadata": json.dumps({"canonical_position_side": "yes", "canonical_position_action": "sell", "entry_or_exit": "exit"}),
        },
    ]
    _build_fact_db(fixture_paths.fact_db, rows)

    records, _ = build_golden_records(
        fact_db=str(fixture_paths.fact_db),
        decision_telemetry=str(fixture_paths.decision_telemetry),
        settlement_outcomes=str(fixture_paths.settlement_outcomes),
        lookback_hours=24,
        out_jsonl=str(fixture_paths.out_jsonl),
        out_db=str(fixture_paths.out_db),
    )

    by_intent = {r.intent_id: r for r in records}
    assert "intent-entry" in by_intent
    assert "fill-exit" in by_intent["intent-entry"].exit_fill_ids


def test_golden_record_flags_exit_reversal(fixture_paths: _FixturePaths):
    """An exit that overshoots the parent's signed-YES exposure is critical."""
    ts = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "event_type": "intent",
            "event_ts": ts,
            "intent_id": "intent-entry",
            "client_order_id": "coid-entry",
            "ticker": "KXBTC15M-TEST-000000-00",
            "side": "no",
            "action": "buy",
            "price_cents": 45,
            "quantity_cc": 100,
            "metadata": json.dumps({"entry_or_exit": "entry"}),
        },
        {
            "event_type": "fill",
            "event_ts": ts,
            "intent_id": "intent-entry",
            "fill_id": "fill-entry",
            "ticker": "KXBTC15M-TEST-000000-00",
            "fill_quantity_cc": 100,
            "avg_fill_price_cents": 45,
            "fee_cost_cents": 2,
            "metadata": json.dumps({
                "canonical_position_side": "no",
                "canonical_position_action": "buy",
                "canonical_yes_delta_cc": -100,
                "entry_or_exit": "entry",
            }),
        },
        {
            "event_type": "intent",
            "event_ts": ts,
            "intent_id": "intent-exit",
            "client_order_id": "coid-exit",
            "ticker": "KXBTC15M-TEST-000000-00",
            "side": "yes",
            "action": "buy",
            "price_cents": 47,
            "quantity_cc": 200,
            "reduce_only": 1,
            "metadata": json.dumps({
                "parent_entry_intent_id": "intent-entry",
                "entry_or_exit": "exit",
            }),
        },
        {
            "event_type": "fill",
            "event_ts": ts,
            "intent_id": "intent-exit",
            "fill_id": "fill-exit",
            "ticker": "KXBTC15M-TEST-000000-00",
            "fill_quantity_cc": 200,
            "avg_fill_price_cents": 47,
            "fee_cost_cents": 2,
            "metadata": json.dumps({
                "canonical_position_side": "yes",
                "canonical_position_action": "buy",
                "canonical_yes_delta_cc": 200,
                "entry_or_exit": "exit",
            }),
        },
    ]
    _build_fact_db(fixture_paths.fact_db, rows)

    records, summary = build_golden_records(
        fact_db=str(fixture_paths.fact_db),
        decision_telemetry=str(fixture_paths.decision_telemetry),
        settlement_outcomes=str(fixture_paths.settlement_outcomes),
        lookback_hours=24,
        out_jsonl=str(fixture_paths.out_jsonl),
        out_db=str(fixture_paths.out_db),
    )

    by_intent = {r.intent_id: r for r in records}
    assert "intent-exit" in by_intent
    rec = by_intent["intent-exit"]
    assert "exit_exposure_reversal" in rec.divergence_flags
    assert rec.alert_level == "critical"
