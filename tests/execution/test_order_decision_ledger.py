"""Tests for the order decision ledger."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from merid.execution.order_decision_ledger import (
    OrderDecisionLedger,
    get_order_decision_ledger,
    reset_order_decision_ledger,
)
from merid.execution.order_decision_schema import (
    ExitEvent,
    FillEvent,
    MarkoutEvent,
    OrderDecisionRecord,
)


@pytest.fixture
def ledger(tmp_path):
    return reset_order_decision_ledger(log_dir=tmp_path)


class TestOrderDecisionLedger:
    """The ledger is the durable source of truth for post-trade analytics."""

    def test_start_writes_decision_time_snapshot(self, ledger: OrderDecisionLedger, tmp_path: Path):
        """A decision record is written before any order is submitted."""
        record = OrderDecisionRecord(
            decision_id="dec-001",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            timestamp_utc=datetime.now(timezone.utc),
            p_selected=Decimal("0.60"),
            executable_price_cents=50,
            intended_qty_cc=200,
            selected_side="yes",
            config_hash="config-hash-abc",
            build_sha="build-sha-123",
        )

        ledger.start(record)

        assert ledger.get("dec-001") is record
        log_file = tmp_path / "order_decisions.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "start"
        assert event["decision_id"] == "dec-001"
        assert event["payload"]["config_hash"] == "config-hash-abc"

    def test_start_rejects_duplicate_decision_id(self, ledger: OrderDecisionLedger):
        """A decision_id can only be started once per process."""
        record = OrderDecisionRecord(
            decision_id="dec-001",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            timestamp_utc=datetime.now(timezone.utc),
        )

        ledger.start(record)
        with pytest.raises(ValueError):
            ledger.start(record)

    def test_record_submission_appends_order_details(self, ledger: OrderDecisionLedger):
        """The ledger records the submitted price, qty, and ids."""
        record = OrderDecisionRecord(
            decision_id="dec-002",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            timestamp_utc=datetime.now(timezone.utc),
        )
        ledger.start(record)
        ledger.record_submission(
            "dec-002",
            entry_mode="aggressive",
            submitted_price_cents=51,
            intended_qty_cc=200,
            client_order_id="coid-002",
            order_id="order-002",
            intent_id="intent-002",
        )

        updated = ledger.get("dec-002")
        assert updated.order_status == "submitted"
        assert updated.entry_mode == "aggressive"
        assert updated.submitted_price_cents == 51
        assert updated.intended_qty_cc == 200
        assert updated.client_order_id == "coid-002"
        assert updated.order_id == "order-002"
        assert updated.intent_id == "intent-002"

    def test_record_fill_appends_and_aggregates(self, ledger: OrderDecisionLedger):
        """Fills are appended and the record tracks filled quantity."""
        record = OrderDecisionRecord(
            decision_id="dec-003",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            timestamp_utc=datetime.now(timezone.utc),
        )
        ledger.start(record)

        fill1 = FillEvent(
            fill_id="fill-1",
            fill_at=datetime.now(timezone.utc),
            side="yes",
            action="buy",
            qty_cc=100,
            price_cents=50,
            fee_cents=1,
        )
        fill2 = FillEvent(
            fill_id="fill-2",
            fill_at=datetime.now(timezone.utc),
            side="yes",
            action="buy",
            qty_cc=100,
            price_cents=50,
            fee_cents=1,
        )
        ledger.record_fill("dec-003", fill1)
        ledger.record_fill("dec-003", fill2)

        updated = ledger.get("dec-003")
        assert len(updated.fills) == 2
        assert updated.filled_qty_cc == 200
        assert updated.order_status == "filled"

    def test_record_markout_updates_pnl_by_horizon(self, ledger: OrderDecisionLedger):
        """Markouts are recorded and the P&L by horizon is materialized."""
        record = OrderDecisionRecord(
            decision_id="dec-004",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            timestamp_utc=datetime.now(timezone.utc),
        )
        ledger.start(record)

        markout = MarkoutEvent(
            horizon_s=5,
            observed_at=datetime.now(timezone.utc),
            pnl_cents=10,
        )
        ledger.record_markout("dec-004", markout)

        updated = ledger.get("dec-004")
        assert len(updated.markouts) == 1
        assert updated.markout_pnl_5s == Decimal("10")

    def test_record_exit_appends_and_sets_realized_pnl(self, ledger: OrderDecisionLedger):
        """Exits are appended and the realized P&L is captured."""
        record = OrderDecisionRecord(
            decision_id="dec-005",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            timestamp_utc=datetime.now(timezone.utc),
        )
        ledger.start(record)

        exit = ExitEvent(
            exit_at=datetime.now(timezone.utc),
            reason="STOP_LOSS",
            order_id="order-005",
            exit_price_cents=45,
            qty_cc=100,
            stop_candidate_id="sc-005",
        )
        ledger.record_exit("dec-005", exit, realized_pnl_cents=-5)

        updated = ledger.get("dec-005")
        assert len(updated.exits) == 1
        assert updated.exits[0].reason == "STOP_LOSS"
        assert updated.realized_pnl_cents == -5
        assert updated.stop_candidate_id == "sc-005"
        assert updated.order_status == "exited"

    def test_provenance_carried_in_record(self, ledger: OrderDecisionLedger):
        """The ledger record carries provenance: intent, order, fill, and parent ids."""
        record = OrderDecisionRecord(
            decision_id="dec-006",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            timestamp_utc=datetime.now(timezone.utc),
            parent_decision_id="dec-000",
            intent_id="intent-006",
        )
        ledger.start(record)
        ledger.record_submission(
            "dec-006",
            client_order_id="coid-006",
            order_id="order-006",
        )

        updated = ledger.get("dec-006")
        assert updated.parent_decision_id == "dec-000"
        assert updated.intent_id == "intent-006"
        assert updated.client_order_id == "coid-006"
        assert updated.order_id == "order-006"

    def test_singleton_reset_isolated_per_test(self, tmp_path: Path):
        """reset_order_decision_ledger creates a fresh singleton for each test."""
        ledger1 = reset_order_decision_ledger(log_dir=tmp_path)
        ledger2 = get_order_decision_ledger()
        assert ledger1 is ledger2
