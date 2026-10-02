"""Tests for the durable point-in-time decision audit ledger."""

import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from merid.execution.decision_audit_ledger import (
    DecisionAuditLedger,
    _classify_no_trade_reason,
    _classify_trade_decision,
    _to_float,
    _to_int,
)


@dataclass
class _FakeEdgeBreakdown:
    p_yes: float = 0.0
    p_no: float = 0.0
    selected_side: str = "yes"
    p_selected: float = 0.0
    p_opposite: float = 0.0
    executable_entry_price: float = 0.0
    entry_fee: float = 0.0
    exit_cost_reserve: float = 0.0
    model_risk_reserve: float = 0.0
    gross_edge: float = 0.0
    net_edge: float = 0.0


@dataclass
class _FakeTradeDecision:
    decision_id: str = "run_123"
    run_id: str = "run_123"
    ticker: str = "KXBTC-15M-20260901-221500"
    asset: str = "BTC"
    timestamp_utc = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    seconds_to_expiry: Decimal = Decimal("900")
    p_yes_raw: Decimal = Decimal("0.55")
    p_yes_calibrated: Decimal = Decimal("0.50")
    p_yes_uncertainty: Decimal = Decimal("0.05")
    p_no_calibrated: Decimal = Decimal("0.50")
    p_selected: Optional[Decimal] = None
    p_opposite: Optional[Decimal] = None
    indicators: Dict[str, Any] = field(default_factory=dict)
    regime: str = "unknown"
    data_quality: str = "good"
    data_state: str = "healthy"
    regime_label: str = "known"
    regime_probability: Decimal = Decimal("0.8")
    regime_warmup_samples: int = 10
    settlement_reference: str = "cfb_rti_live"
    yes_entry_vwap: Decimal = Decimal("0.33")
    no_entry_vwap: Decimal = Decimal("0.27")
    yes_depth_cc: Decimal = Decimal("500")
    no_depth_cc: Decimal = Decimal("600")
    fee_yes: Decimal = Decimal("0.01")
    fee_no: Decimal = Decimal("0.01")
    expected_exit_cost_yes: Decimal = Decimal("0.01")
    expected_exit_cost_no: Decimal = Decimal("0.01")
    selected_outcome: Optional[str] = None
    selected_action: Optional[str] = None
    selected_outcome_price: Optional[Decimal] = None
    gross_edge: Optional[Decimal] = None
    net_edge: Optional[Decimal] = None
    no_trade_reason: Optional[str] = None
    confidence_valid: bool = True
    confidence: Optional[Decimal] = Decimal("0.75")
    confidence_source: str = "uncertainty_engine"
    confidence_reasons: List[str] = field(default_factory=list)
    yes_edge_breakdown: Optional[_FakeEdgeBreakdown] = None
    no_edge_breakdown: Optional[_FakeEdgeBreakdown] = None
    min_required_edge: Decimal = Decimal("0.05")
    edge_threshold: Decimal = Decimal("0.05")
    config_hash: Optional[str] = "cfg_v1"
    policy_version: str = "trade_decision_v2"


@pytest.fixture
def tmp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _no_trade_decision(reason: str) -> _FakeTradeDecision:
    dec = _FakeTradeDecision(
        decision_id=f"run_{reason}",
        no_trade_reason=reason,
    )
    dec.indicators = {
        "annualized_vol": 0.60,
        "annualized_vol_source": "default",
        "z_score": 0.5,
        "log_moneyness": 0.01,
        "bachelier_spot": 65000.0,
        "strike": 65050.0,
        "yes_min_edge": 0.05,
        "no_min_edge": 0.05,
    }
    dec.yes_edge_breakdown = _FakeEdgeBreakdown(
        p_selected=0.5,
        executable_entry_price=0.33,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.02,
        gross_edge=0.17,
        net_edge=0.13,
    )
    dec.no_edge_breakdown = _FakeEdgeBreakdown(
        p_selected=0.5,
        executable_entry_price=0.27,
        entry_fee=0.01,
        exit_cost_reserve=0.01,
        model_risk_reserve=0.02,
        gross_edge=0.23,
        net_edge=0.19,
    )
    return dec


def test_ledger_writes_decision_and_snapshot(tmp_db: Path) -> None:
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    ledger.record_trade_decision(dec)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM strategy_decisions WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["ticker"] == dec.ticker
        assert rows[0]["primary_reason_code"] == "NO_EDGE"
        assert rows[0]["record_environment"] == "test"
        assert rows[0]["record_source"] == "test"
        assert rows[0]["is_eligible_for_research"] == 0
        assert rows[0]["exclusion_reason"] == "no_edge_below_threshold"

        snaps = conn.execute(
            "SELECT * FROM strategy_decision_snapshots WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        assert len(snaps) == 1
        assert snaps[0]["vol_forecast"] == 0.60

        side_rows = conn.execute(
            "SELECT * FROM strategy_decision_side_ev WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        assert len(side_rows) == 2
        yes = [r for r in side_rows if r["side"] == "yes"][0]
        no = [r for r in side_rows if r["side"] == "no"][0]
        assert yes["executable_entry_price_cents"] == 33
        assert no["executable_entry_price_cents"] == 27
        assert yes["passed_edge_gate"] == 1
        assert no["passed_edge_gate"] == 1
        assert yes["model_evaluated"] == 1
        assert no["model_evaluated"] == 1
        assert yes["policy_eligible"] == 1
        assert no["policy_eligible"] == 1
        assert yes["passed_net_ev"] == 1
        assert no["passed_net_ev"] == 1
        assert yes["selected"] == 0
        assert no["selected"] == 0

        outcomes = conn.execute(
            "SELECT * FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        assert len(outcomes) == 1
        assert outcomes[0]["outcome_status"] == "PENDING"


def test_ledger_writes_enter_decision(tmp_db: Path) -> None:
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("")
    dec.no_trade_reason = None
    dec.selected_outcome = "yes"
    dec.selected_action = "buy"
    dec.selected_outcome_price = Decimal("0.33")
    ledger.record_trade_decision(dec)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT decision, primary_reason_code, selected_side, record_environment, is_eligible_for_research FROM strategy_decisions WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        assert rows[0]["decision"] == "ENTER"
        assert rows[0]["primary_reason_code"] == "selected"
        assert rows[0]["selected_side"] == "yes"
        assert rows[0]["record_environment"] == "test"
        assert rows[0]["is_eligible_for_research"] == 0

        side_rows = conn.execute(
            "SELECT side, selected, passed_net_ev FROM strategy_decision_side_ev WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        yes = [r for r in side_rows if r["side"] == "yes"][0]
        no = [r for r in side_rows if r["side"] == "no"][0]
        assert yes["selected"] == 1
        assert no["selected"] == 0
        assert yes["passed_net_ev"] == 1


def test_settlement_computes_counterfactuals(tmp_db: Path) -> None:
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    ledger.record_trade_decision(dec)

    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec.ticker,
        close_ts=close_ts,
        settled_yes=True,
        settlement_value_cents=100,
    )

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        outcome = conn.execute(
            "SELECT * FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert outcome["outcome_status"] == "SETTLED"
        assert outcome["settled_yes"] == 1
        assert outcome["settlement_value_cents"] == 100
        # YES side PnL = 100 - 33 - 1 - 1 = 65
        assert outcome["counterfactual_yes_pnl_cents"] == 65.0
        # NO side PnL = 0 - 27 - 1 - 1 = -29
        assert outcome["counterfactual_no_pnl_cents"] == -29.0


def test_side_ev_probabilities_are_same_side(tmp_db: Path) -> None:
    """raw_probability/calibrated_probability must record THIS side's
    probabilities.  Regression for the bug where raw_probability stored the
    post-calibration selected probability and calibrated_probability stored the
    opposite side's probability."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    dec.p_yes_raw = Decimal("0.62")
    dec.p_yes_calibrated = Decimal("0.58")
    dec.p_no_calibrated = Decimal("0.42")
    dec.yes_edge_breakdown.p_selected = 0.58
    dec.yes_edge_breakdown.p_opposite = 0.42
    dec.no_edge_breakdown.p_selected = 0.42
    dec.no_edge_breakdown.p_opposite = 0.58
    ledger.record_trade_decision(dec)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT side, raw_probability, calibrated_probability FROM strategy_decision_side_ev WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        yes = [r for r in rows if r["side"] == "yes"][0]
        no = [r for r in rows if r["side"] == "no"][0]
        assert yes["raw_probability"] == pytest.approx(0.62)
        assert yes["calibrated_probability"] == pytest.approx(0.58)
        # p_no_raw is absent from the fake indicators; it is derived as
        # 1 - p_yes_raw.
        assert no["raw_probability"] == pytest.approx(0.38)
        assert no["calibrated_probability"] == pytest.approx(0.42)


def test_snapshot_spot_price_is_model_input_not_settlement_reference(tmp_db: Path) -> None:
    """spot_price must be the instantaneous price the model consumed
    (indicators["bachelier_spot"], i.e. the latest CF RTI tick), not the
    60-second settlement reference which has its own column."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    ledger.record_trade_decision(
        dec,
        settlement_reference_price=65050.0,
        settlement_reference_source="cfb_rti_live",
    )

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        snap = conn.execute(
            "SELECT spot_price, settlement_reference_price, spot_settlement_basis FROM strategy_decision_snapshots WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert snap["spot_price"] == pytest.approx(65000.0)  # bachelier_spot
        assert snap["settlement_reference_price"] == pytest.approx(65050.0)
        assert snap["spot_settlement_basis"] == pytest.approx(-50.0)


def test_classify_reasons() -> None:
    c = _classify_no_trade_reason("data_state_not_healthy")
    assert c.decision == "NO_TRADE"
    assert c.primary_reason_code == "DATA_QUALITY_VETO"

    c = _classify_no_trade_reason("no_edge_below_threshold")
    assert c.primary_reason_code == "NO_EDGE"

    c = _classify_no_trade_reason("held_entry_price_below_floor:0.21<0.35")
    assert c.primary_reason_code == "POLICY_EXCLUDED"


@pytest.mark.parametrize(
    "value, expected",
    [
        (Decimal("0.1"), 0.1),
        ("0.5", 0.5),
        (0.5, 0.5),
        (None, None),
        ("nan", None),
    ],
)
def test_to_float(value: Any, expected: Optional[float]) -> None:
    assert _to_float(value) == expected


def test_ledger_disabled(tmp_db: Path) -> None:
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "0"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    ledger.record_trade_decision(dec)
    with sqlite3.connect(str(tmp_db)) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert not tables


def test_snapshot_records_quote_provenance(tmp_db: Path) -> None:
    """Quote-owner/freshness/divergence provenance must land on the snapshot row."""
    import time

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    dec.indicators["quote_owner"] = "REST_VERIFIED_DEGRADED"
    dec.indicators["quote_degraded_mode"] = True
    dec.indicators["ws_last_event_age_ms"] = 640.0
    dec.indicators["ws_last_queue_wait_ms"] = 12.5
    dec.indicators["ws_rest_bid_diff_ticks"] = 7
    dec.indicators["ws_rest_ask_diff_ticks"] = 9
    dec.indicators["ws_parity_healthy"] = False

    @dataclass
    class _MS:
        quote_owner: str = "REST_VERIFIED_DEGRADED"
        degraded_mode: bool = True
        ws_last_seq: int = 441
        ws_last_event_age_ms: float = 640.0
        ws_last_queue_wait_ms: float = 12.5
        ws_rest_bid_diff_ticks: int = 7
        ws_rest_ask_diff_ticks: int = 9
        ws_parity_healthy: bool = False
        last_rest_quote_update_ts: float = field(
            default_factory=lambda: time.monotonic() - 0.25
        )
        last_book_update_wall_ts: float = field(
            default_factory=lambda: time.time() - 0.1
        )
        book_initialized: bool = True
        data_quality: str = "GOOD"

    ledger.record_trade_decision(dec, market_state=_MS())

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        snap = conn.execute(
            "SELECT quote_owner, degraded_mode, ws_last_seq, ws_last_event_age_ms, "
            "ws_last_queue_wait_ms, ws_rest_bid_diff_ticks, ws_rest_ask_diff_ticks, "
            "ws_parity_healthy, rest_age_ms, book_age_ms "
            "FROM strategy_decision_snapshots WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert snap["quote_owner"] == "REST_VERIFIED_DEGRADED"
        assert snap["degraded_mode"] == 1
        assert snap["ws_last_seq"] == 441
        assert snap["ws_last_event_age_ms"] == pytest.approx(640.0)
        assert snap["ws_last_queue_wait_ms"] == pytest.approx(12.5)
        assert snap["ws_rest_bid_diff_ticks"] == 7
        assert snap["ws_rest_ask_diff_ticks"] == 9
        assert snap["ws_parity_healthy"] == 0
        assert snap["rest_age_ms"] is not None and snap["rest_age_ms"] >= 200
        assert snap["book_age_ms"] is not None and snap["book_age_ms"] < 5000


def test_snapshot_book_age_uses_wall_clock(tmp_db: Path) -> None:
    """book_age_ms must compare the wall-clock sibling, not the monotonic field."""
    import time

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")

    @dataclass
    class _MS:
        last_book_update_ts: float = field(default_factory=time.monotonic)
        last_book_update_wall_ts: float = field(
            default_factory=lambda: time.time() - 0.2
        )
        book_initialized: bool = True
        data_quality: str = "GOOD"

    ledger.record_trade_decision(dec, market_state=_MS())

    with sqlite3.connect(str(tmp_db)) as conn:
        snap = conn.execute(
            "SELECT book_age_ms FROM strategy_decision_snapshots WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        # ~200ms, not the multi-second garbage produced by mixing clocks.
        assert snap[0] is not None and 0 <= snap[0] < 5000


def test_lane_provenance_columns(tmp_db: Path) -> None:
    """admission_lane / admission_owner / provisional_cell_id / build_sha must
    persist on the decision row, and per-side owner/threshold/legacy-label on
    side_ev rows, so current-build fills are queryable apart from legacy
    counterfactual evidence."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("")
    dec.no_trade_reason = None
    dec.selected_outcome = "no"
    dec.selected_action = "buy"
    dec.selected_outcome_price = Decimal("0.27")
    dec.build_sha = "abc123def456"
    dec.indicators.update({
        "decision_lane": "current_build_provisional",
        "provisional_cell_id": "cbp_btc_no_20_30_t120_300",
        "no_admission_owner": "current_build_provisional",
        "no_threshold_source": "current_build_provisional",
        "no_legacy_risk_label": "MATCHING_TOXIC_CELL",
        "yes_admission_owner": "formula",
        "yes_threshold_source": "formula",
    })
    ledger.record_trade_decision(dec)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT admission_lane, admission_owner, provisional_cell_id, "
            "build_sha FROM strategy_decisions WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert row["admission_lane"] == "current_build_provisional"
        assert row["admission_owner"] == "current_build_provisional"
        assert row["provisional_cell_id"] == "cbp_btc_no_20_30_t120_300"
        assert row["build_sha"] == "abc123def456"

        side_rows = conn.execute(
            "SELECT side, admission_owner, threshold_source, legacy_risk_label "
            "FROM strategy_decision_side_ev WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        yes = [r for r in side_rows if r["side"] == "yes"][0]
        no = [r for r in side_rows if r["side"] == "no"][0]
        assert no["admission_owner"] == "current_build_provisional"
        assert no["threshold_source"] == "current_build_provisional"
        assert no["legacy_risk_label"] == "MATCHING_TOXIC_CELL"
        assert yes["admission_owner"] == "formula"
        assert yes["legacy_risk_label"] is None


def _enter_decision_no() -> _FakeTradeDecision:
    """ENTER decision selecting NO (implemented as sell-YES at the venue)."""
    dec = _no_trade_decision("")
    dec.decision_id = "dec_no_entry"
    dec.no_trade_reason = None
    dec.selected_outcome = "no"
    dec.selected_action = "sell"
    dec.selected_outcome_price = Decimal("0.54")
    return dec


def _make_fills_db(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Minimal kalshi_fills table for the settlement-time fill fallback."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE kalshi_fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            decision_trace_id TEXT,
            execution_outcome_side TEXT,
            execution_action TEXT,
            execution_price_cents INTEGER,
            fee_cost REAL,
            is_exit INTEGER DEFAULT 0,
            reduce_only INTEGER DEFAULT 0,
            entry_or_exit TEXT DEFAULT 'entry',
            canonicalization_state TEXT DEFAULT 'TRUSTED_LIVE_V1',
            created_time TEXT
        )
        """
    )
    for r in rows:
        conn.execute(
            "INSERT INTO kalshi_fills (fill_id, order_id, decision_trace_id, "
            "execution_outcome_side, execution_action, execution_price_cents, "
            "fee_cost, is_exit, reduce_only, entry_or_exit, "
            "canonicalization_state, created_time) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["fill_id"],
                r.get("order_id", "o1"),
                r["decision_trace_id"],
                r.get("execution_outcome_side", "yes"),
                r.get("execution_action", "sell"),
                r["execution_price_cents"],
                r.get("fee_cost", 0.0),
                r.get("is_exit", 0),
                r.get("reduce_only", 0),
                r.get("entry_or_exit", "entry"),
                r.get("canonicalization_state", "TRUSTED_LIVE_V1"),
                r.get("created_time", "2026-10-01T02:52:47Z"),
            ),
        )
    conn.commit()
    conn.close()


def test_record_entry_fill_converts_sell_leg_to_selected_side(tmp_db: Path) -> None:
    """A venue sell-YES@46 fill on a NO-selected decision must persist as
    actual_fill_price_cents=54 (selected-side space), not the leg price 46."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _enter_decision_no()
    ledger.record_trade_decision(dec)

    assert ledger.record_entry_fill(
        decision_id=dec.decision_id,
        fill_id="f1",
        exchange_order_id="oid1",
        execution_outcome_side="yes",
        execution_action="sell",
        execution_price_cents=46,
        entry_fee_cents=0.0,
    )

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actual_fill_price_cents, actual_entry_fee_cents, fill_id, "
            "exchange_order_id FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert row["actual_fill_price_cents"] == 54
        assert row["actual_entry_fee_cents"] == 0.0
        assert row["fill_id"] == "f1"
        assert row["exchange_order_id"] == "oid1"


def test_record_entry_fill_buy_leg_passthrough(tmp_db: Path) -> None:
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _enter_decision_no()
    dec.decision_id = "dec_no_buy"
    dec.selected_action = "buy"
    ledger.record_trade_decision(dec)

    assert ledger.record_entry_fill(
        decision_id=dec.decision_id,
        execution_outcome_side="no",
        execution_action="buy",
        execution_price_cents=54,
        entry_fee_cents=1.0,
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT actual_fill_price_cents FROM strategy_decision_outcomes "
            "WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert row[0] == 54


def test_record_entry_fill_side_mismatch_is_fail_closed(tmp_db: Path) -> None:
    """A buy-YES fill cannot satisfy a NO-selected decision — skip the write
    rather than record a wrong-direction price."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _enter_decision_no()
    dec.decision_id = "dec_mismatch"
    ledger.record_trade_decision(dec)

    assert not ledger.record_entry_fill(
        decision_id=dec.decision_id,
        execution_outcome_side="yes",
        execution_action="buy",
        execution_price_cents=46,
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT actual_fill_price_cents FROM strategy_decision_outcomes "
            "WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert row[0] is None


def test_settlement_persists_realized_pnl_for_filled_decision(tmp_db: Path) -> None:
    """Filled-and-held-to-settlement must write realized_net_pnl_cents on the
    outcome row, in addition to the counterfactual columns."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _enter_decision_no()
    dec.decision_id = "dec_settled_fill"
    ledger.record_trade_decision(dec)
    ledger.record_entry_fill(
        decision_id=dec.decision_id,
        execution_outcome_side="yes",
        execution_action="sell",
        execution_price_cents=46,
        entry_fee_cents=0.0,
    )

    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec.ticker,
        close_ts=close_ts,
        settled_yes=True,
        settlement_value_cents=100,
    )

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actual_fill_price_cents, realized_net_pnl_cents, "
            "outcome_status FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert row["outcome_status"] == "SETTLED"
        assert row["actual_fill_price_cents"] == 54
        # Bought NO@54, YES settled 100 -> NO leg settles 0: 0 - 54 - 0 = -54
        assert row["realized_net_pnl_cents"] == -54.0


def test_settlement_backfills_fill_from_fills_db(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """When the ingest-time bridge never ran, record_settlement resolves the
    fill from kalshi_fills via decision_trace_id and still computes PnL."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    fills_db = tmp_path / "kalshi_fills.db"
    dec_id = "dec_backfill_fill"
    _make_fills_db(
        fills_db,
        [
            {
                "fill_id": "fill_backfill_1",
                "order_id": "oid_backfill",
                "decision_trace_id": dec_id,
                "execution_outcome_side": "yes",
                "execution_action": "sell",
                "execution_price_cents": 46,
                "fee_cost": 0.0,
            }
        ],
    )
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(fills_db))

    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _enter_decision_no()
    dec.decision_id = dec_id
    ledger.record_trade_decision(dec)

    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec.ticker,
        close_ts=close_ts,
        settled_yes=True,
        settlement_value_cents=100,
    )

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actual_fill_price_cents, realized_net_pnl_cents, fill_id "
            "FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec_id,),
        ).fetchone()
        assert row["actual_fill_price_cents"] == 54
        assert row["realized_net_pnl_cents"] == -54.0
        assert row["fill_id"] == "fill_backfill_1"


def test_reconcile_fill_outcomes_heals_settled_rows(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """Rows settled before the fill bridge existed are healed by
    reconcile_fill_outcomes: fill price + realized PnL both populated."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    fills_db = tmp_path / "kalshi_fills.db"
    dec_id = "dec_reconcile_heal"
    _make_fills_db(
        fills_db,
        [
            {
                "fill_id": "fill_heal_1",
                "decision_trace_id": dec_id,
                "execution_outcome_side": "yes",
                "execution_action": "sell",
                "execution_price_cents": 46,
                "fee_cost": 0.0,
            }
        ],
    )
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(fills_db))

    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _enter_decision_no()
    dec.decision_id = dec_id
    ledger.record_trade_decision(dec)

    # Settle with NO fills DB reachable: row goes SETTLED with NULL fill.
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(tmp_path / "absent.db"))
    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec.ticker,
        close_ts=close_ts,
        settled_yes=True,
        settlement_value_cents=100,
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT actual_fill_price_cents, realized_net_pnl_cents "
            "FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec_id,),
        ).fetchone()
        assert row[0] is None and row[1] is None

    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(fills_db))
    assert ledger.reconcile_fill_outcomes() == 1

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actual_fill_price_cents, realized_net_pnl_cents, fill_id "
            "FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec_id,),
        ).fetchone()
        assert row["actual_fill_price_cents"] == 54
        assert row["realized_net_pnl_cents"] == -54.0
        assert row["fill_id"] == "fill_heal_1"


def test_heartbeat_side_ev_expected_counts_only_model_decisions(tmp_db: Path) -> None:
    """side_ev_expected must be 2 per full trade decision, not 2 per persisted
    row — pre-decision rejections legitimately write no side-EV rows, so the
    old persisted*2 derivation reported false write gaps."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)

    dec = _no_trade_decision("no_edge_below_threshold")
    dec.decision_id = "hb_model_1"
    assert ledger.record_trade_decision(dec, cycle_id="c1") is True
    assert ledger.record_pre_decision_rejection(
        cycle_id="c1",
        run_id="run_x",
        ticker="KXBTC15M-T",
        asset="BTC",
        reason="market_not_entry_ready",
        decision_id="hb_pre_1",
        candidate_id="hb_pre_1",
    ) is True

    ledger.log_cycle_heartbeat("c1", tick=1, assets_evaluated=5)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT decisions_expected, decisions_persisted, side_ev_expected, "
            "side_ev_persisted FROM decision_audit_heartbeats WHERE cycle_id = ?",
            ("c1",),
        ).fetchone()
        assert row["decisions_persisted"] == 2
        assert row["side_ev_expected"] == 2
        assert row["side_ev_persisted"] == 2

        # Physical truth matches the metric: model decision has 2 side_ev
        # rows, pre-decision rejection has none.
        ev = conn.execute(
            "SELECT COUNT(*) FROM strategy_decision_side_ev WHERE decision_id = 'hb_model_1'"
        ).fetchone()[0]
        assert ev == 2
        ev_pre = conn.execute(
            "SELECT COUNT(*) FROM strategy_decision_side_ev WHERE decision_id = 'hb_pre_1'"
        ).fetchone()[0]
        assert ev_pre == 0


def test_heartbeat_pure_pre_decision_cycle_reports_zero_side_ev(tmp_db: Path) -> None:
    """A cycle of only pre-decision rejections reports side_ev 0/0, not 0/10."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)

    for i in range(5):
        assert ledger.record_pre_decision_rejection(
            cycle_id="c2",
            run_id="run_x",
            ticker=f"KXBTC15M-T{i}",
            asset="BTC",
            reason="market_not_entry_ready",
            decision_id=f"hb2_pre_{i}",
            candidate_id=f"hb2_pre_{i}",
        ) is True

    ledger.log_cycle_heartbeat("c2", tick=2, assets_evaluated=5)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT decisions_persisted, side_ev_expected, side_ev_persisted "
            "FROM decision_audit_heartbeats WHERE cycle_id = ?",
            ("c2",),
        ).fetchone()
        assert row["decisions_persisted"] == 5
        assert row["side_ev_expected"] == 0
        assert row["side_ev_persisted"] == 0


def test_pre_decision_rejection_blank_ticker_is_terminal(tmp_db: Path) -> None:
    """A pre-decision rejection with no resolvable contract must not park a
    PENDING outcome: the orphan sweep would call /markets/ (empty ticker)
    every poll forever and the row can never receive a settlement."""
    import time
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)

    assert ledger.record_pre_decision_rejection(
        cycle_id="c3",
        run_id="run_x",
        ticker="",
        asset="BTC",
        reason="market_not_entry_ready",
        decision_id="hb3_noticker",
        candidate_id="hb3_noticker",
    ) is True

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT outcome_status, unresolved_reason FROM strategy_decision_outcomes "
            "WHERE decision_id = 'hb3_noticker'"
        ).fetchone()
        assert row["outcome_status"] == "UNRESOLVED"
        assert row["unresolved_reason"] == "no_contract_at_decision"

    # And the orphan sweep never surfaces it.
    pending = ledger.pending_unsettled_tickers(now=time.time() + 3600)
    assert all(t for t, _ in pending)


def test_pending_unsettled_tickers_skips_blank_ticker(tmp_db: Path) -> None:
    """Backstop: even a legacy blank-ticker PENDING row is excluded from the
    sweep set so it cannot generate a doomed /markets/ lookup."""
    import time
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    # Write via the API (produces UNRESOLVED under the new code) then flip to
    # PENDING to simulate a legacy row written before the fix.
    assert ledger.record_pre_decision_rejection(
        cycle_id="c4",
        run_id="run_x",
        ticker="",
        asset="BTC",
        reason="market_not_entry_ready",
        decision_id="legacy_blank",
        candidate_id="legacy_blank",
        seconds_to_expiry=300.0,
    ) is True
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.execute(
            "UPDATE strategy_decision_outcomes SET outcome_status='PENDING', "
            "unresolved_reason=NULL, unresolved_at=NULL WHERE decision_id='legacy_blank'"
        )
        conn.commit()
    pending = ledger.pending_unsettled_tickers(now=time.time() + 3600)
    assert all(t and str(t).strip() for t, _ in pending)
