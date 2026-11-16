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
    adverse_selection_reserve: float = 0.0
    policy_giveback_reserve: float = 0.0
    implementation_shortfall_reserve: float = 0.0
    edge_bias_correction: float = 0.0


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
    # tmp_db lives in the shared system temp dir, so the default reconcile
    # state sidecar leaks watermarks across tests/runs — pin it per-test.
    monkeypatch.setenv(
        "MERID_RECONCILE_STATE_PATH", str(tmp_path / "reconcile_state.json")
    )

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


def test_outcome_sweep_columns_populated_at_insert(tmp_db: Path) -> None:
    """2026-11-11: sweep_ticker/sweep_close_ts are denormalized onto the
    outcome row at insert so the settlement sweep lanes never join the
    multi-GB decisions table (the join held a WAL read snapshot for minutes
    per poll and starved checkpoints)."""
    import time
    from datetime import datetime, timezone

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)

    # Trade-decision path.
    dec = _no_trade_decision("no_edge_below_threshold")
    dec.decision_id = "dec_sweep_cols"
    dec.ticker = "KXBTC15M-SWEEP-TEST"
    ledger.record_trade_decision(dec)
    expected_close = (
        dec.timestamp_utc.replace(tzinfo=timezone.utc).timestamp()
        + float(dec.seconds_to_expiry)
    )

    # Pre-decision rejection path.
    assert ledger.record_pre_decision_rejection(
        cycle_id="c_sweep",
        run_id="run_x",
        ticker="KXETH15M-SWEEP-REJ",
        asset="ETH",
        reason="market_not_entry_ready",
        seconds_to_expiry=300.0,
        decision_id="rej_sweep_cols",
        candidate_id="rej_sweep_cols",
    ) is True

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT sweep_ticker, sweep_close_ts FROM strategy_decision_outcomes "
            "WHERE decision_id = 'dec_sweep_cols'"
        ).fetchone()
        assert row["sweep_ticker"] == dec.ticker
        assert row["sweep_close_ts"] == pytest.approx(expected_close, abs=1.0)

        rej = conn.execute(
            "SELECT sweep_ticker, sweep_close_ts FROM strategy_decision_outcomes "
            "WHERE decision_id = 'rej_sweep_cols'"
        ).fetchone()
        assert rej["sweep_ticker"] == "KXETH15M-SWEEP-REJ"
        assert rej["sweep_close_ts"] is not None

    # And the sweep surfaces the trade-decision ticker once its market closed.
    pending = ledger.pending_unsettled_tickers(now=time.time() + 3600)
    assert dec.ticker in [t for t, _ in pending]


def test_sweep_column_backfill_repairs_null_rows(tmp_db: Path) -> None:
    """Rows written before the sweep-column migration carry NULL sweep cols;
    the bounded backfill must populate them from strategy_decisions while
    leaving SETTLED rows untouched (terminal — never swept)."""
    import time

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)

    dec = _no_trade_decision("no_edge_below_threshold")
    dec.decision_id = "dec_backfill_pending"
    dec.ticker = "KXSOL15M-BACKFILL-TEST"
    ledger.record_trade_decision(dec)

    # Simulate a pre-migration row: strip the sweep columns, then settle a
    # second decision so one SETTLED and one PENDING row exist.
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.execute(
            "UPDATE strategy_decision_outcomes SET sweep_ticker = NULL, "
            "sweep_close_ts = NULL WHERE decision_id = ?",
            (dec.decision_id,),
        )
        conn.commit()

    dec2 = _no_trade_decision("no_edge_below_threshold")
    dec2.decision_id = "dec_backfill_settled"
    dec2.ticker = "KXXRP15M-BACKFILL-SETTLED"
    ledger.record_trade_decision(dec2)
    close2 = dec2.timestamp_utc.timestamp() + float(dec2.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec2.ticker,
        close_ts=close2,
        settled_yes=True,
        settlement_value_cents=100,
    )

    # Run the backfill synchronously (the production path runs it on a
    # daemon thread after _ensure_db).
    ledger._run_sweep_backfill()

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        pending_row = conn.execute(
            "SELECT sweep_ticker, sweep_close_ts FROM strategy_decision_outcomes "
            "WHERE decision_id = 'dec_backfill_pending'"
        ).fetchone()
        assert pending_row["sweep_ticker"] == dec.ticker
        assert pending_row["sweep_close_ts"] is not None

        # SETTLED rows are skipped by the backfill — they can never re-enter
        # a sweep lane, so NULL sweep cols are harmless there.
        settled_row = conn.execute(
            "SELECT outcome_status, sweep_ticker FROM strategy_decision_outcomes "
            "WHERE decision_id = 'dec_backfill_settled'"
        ).fetchone()
        assert settled_row["outcome_status"] == "SETTLED"

    # The repaired PENDING row is visible to the hot sweep again.
    pending = ledger.pending_unsettled_tickers(now=time.time() + 3600)
    assert dec.ticker in [t for t, _ in pending]


# ── Capital-realized vs thesis P&L (2026-10-13) ──────────────────────────────


def _make_ticker_fills_db(path: Path, ticker: str, rows: List[Dict[str, Any]]) -> None:
    """kalshi_fills with the per-ticker columns capital attribution reads."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE kalshi_fills (
            fill_id TEXT PRIMARY KEY, order_id TEXT, market_ticker TEXT,
            decision_trace_id TEXT, execution_outcome_side TEXT,
            execution_action TEXT, execution_price_cents INTEGER,
            quantity_cc INTEGER DEFAULT 100, fee_cost REAL DEFAULT 0,
            is_exit INTEGER DEFAULT 0, reduce_only INTEGER DEFAULT 0,
            entry_or_exit TEXT DEFAULT 'entry',
            canonicalization_state TEXT DEFAULT 'TRUSTED_LIVE_V1',
            created_time TEXT
        )
        """
    )
    for r in rows:
        conn.execute(
            "INSERT INTO kalshi_fills (fill_id, market_ticker, decision_trace_id, "
            "execution_outcome_side, execution_action, execution_price_cents, "
            "quantity_cc, fee_cost, is_exit, entry_or_exit, created_time) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["fill_id"], ticker, r.get("decision_trace_id"),
                r["side"], r["action"], r["price"], r.get("qty_cc", 100),
                r.get("fee_cost", 0.0), int(r.get("is_exit", 0)),
                "exit" if r.get("is_exit") else "entry", r["created_time"],
            ),
        )
    conn.commit()
    conn.close()


def _settle_no_position(
    tmp_db: Path,
    tmp_path: Path,
    monkeypatch,
    *,
    dec_id: str,
    exit_rows: List[Dict[str, Any]],
    settled_yes: bool,
) -> Dict[str, Any]:
    """NO entry at 54 (venue sell-YES@46), optional exits, then settlement.

    Returns the persisted outcome row plus what the safety consumers saw.
    """
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    dec = _enter_decision_no()
    dec.decision_id = dec_id
    fills_db = tmp_path / f"{dec_id}_fills.db"
    _make_ticker_fills_db(
        fills_db,
        dec.ticker,
        [
            {"fill_id": f"{dec_id}_entry", "decision_trace_id": dec_id,
             "side": "yes", "action": "sell", "price": 46,
             "created_time": "2026-10-13T10:00:00+00:00"},
            *exit_rows,
        ],
    )
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(fills_db))

    seen: Dict[str, Any] = {}
    import merid.prediction.directional_regime as _dr
    import merid.prediction.marginal_band_lane as _mb

    monkeypatch.setattr(
        _dr, "record_side_settlement",
        lambda side, pnl, **kw: seen.__setitem__("side_throttle", (side, pnl)),
    )
    monkeypatch.setattr(_mb, "marginal_band_for_decision", lambda did: {"asset": "btc"})
    monkeypatch.setattr(
        _mb, "record_settlement",
        lambda *, decision_id, net_pnl_cents: seen.__setitem__("mband", net_pnl_cents),
    )

    ledger = DecisionAuditLedger(db_path=tmp_db)
    ledger.record_trade_decision(dec)
    assert ledger.record_entry_fill(
        decision_id=dec_id,
        fill_id=f"{dec_id}_entry",
        execution_outcome_side="yes",
        execution_action="sell",
        execution_price_cents=46,
        entry_fee_cents=0.0,
    )
    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec.ticker,
        close_ts=close_ts,
        settled_yes=settled_yes,
        settlement_value_cents=100 if settled_yes else 0,
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute(
            "SELECT realized_net_pnl_cents, capital_realized_pnl_cents, "
            "exit_attribution FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec_id,),
        ).fetchone())
    row.update(seen)
    return row


def test_catastrophic_exit_books_realized_loss_and_keeps_thesis(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """Stopped out of NO@54 at 9c (venue buy-YES@91, 1c fee); NO then wins.

    Thesis (evidence) label stays +46 — the entry was right.  Capital
    counters must see the -46 the account actually realized.
    """
    monkeypatch.delenv("MERID_SAFETY_PNL_SOURCE", raising=False)
    row = _settle_no_position(
        tmp_db, tmp_path, monkeypatch,
        dec_id="dec_cap_stop",
        exit_rows=[{"fill_id": "x1", "side": "yes", "action": "buy", "price": 91,
                    "fee_cost": 0.01, "is_exit": True,
                    "created_time": "2026-10-13T10:05:00+00:00"}],
        settled_yes=False,
    )
    assert row["realized_net_pnl_cents"] == pytest.approx(46.0)
    assert row["capital_realized_pnl_cents"] == pytest.approx(-46.0)
    assert row["exit_attribution"] == "exited"
    assert row["side_throttle"] == ("no", pytest.approx(-46.0))
    assert row["mband"] == pytest.approx(-46.0)


def test_profitable_early_exit_does_not_count_as_loss(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """Exited NO@54 at 70c (venue buy-YES@30) before NO lost at settlement.

    The thesis was wrong (-54) but the account realized +16: loss-streak
    and suspension counters must receive the realized gain, not a loss.
    """
    monkeypatch.delenv("MERID_SAFETY_PNL_SOURCE", raising=False)
    row = _settle_no_position(
        tmp_db, tmp_path, monkeypatch,
        dec_id="dec_cap_tp",
        exit_rows=[{"fill_id": "x2", "side": "yes", "action": "buy", "price": 30,
                    "is_exit": True, "created_time": "2026-10-13T10:05:00+00:00"}],
        settled_yes=True,
    )
    assert row["realized_net_pnl_cents"] == pytest.approx(-54.0)
    assert row["capital_realized_pnl_cents"] == pytest.approx(16.0)
    assert row["side_throttle"][1] > 0
    assert row["mband"] > 0


def test_held_to_settlement_capital_equals_thesis(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("MERID_SAFETY_PNL_SOURCE", raising=False)
    row = _settle_no_position(
        tmp_db, tmp_path, monkeypatch,
        dec_id="dec_cap_hold", exit_rows=[], settled_yes=True,
    )
    assert row["realized_net_pnl_cents"] == pytest.approx(-54.0)
    assert row["capital_realized_pnl_cents"] == pytest.approx(-54.0)
    assert row["exit_attribution"] == "held_to_settlement"
    assert row["side_throttle"] == ("no", pytest.approx(-54.0))


def test_safety_pnl_source_thesis_rollback(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """MERID_SAFETY_PNL_SOURCE=thesis restores legacy consumer inputs while
    still persisting the capital-realized column."""
    monkeypatch.setenv("MERID_SAFETY_PNL_SOURCE", "thesis")
    row = _settle_no_position(
        tmp_db, tmp_path, monkeypatch,
        dec_id="dec_cap_rollback",
        exit_rows=[{"fill_id": "x3", "side": "yes", "action": "buy", "price": 91,
                    "is_exit": True, "created_time": "2026-10-13T10:05:00+00:00"}],
        settled_yes=False,
    )
    assert row["capital_realized_pnl_cents"] == pytest.approx(-45.0)
    assert row["side_throttle"] == ("no", pytest.approx(46.0))


def test_capital_realized_falls_back_to_thesis_when_fills_unresolvable(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """Legacy fills DB without market_ticker/quantity_cc: attribution must
    not go silent — consumers get the thesis value, row marked unresolved."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    monkeypatch.delenv("MERID_SAFETY_PNL_SOURCE", raising=False)
    fills_db = tmp_path / "legacy_fills.db"
    _make_fills_db(fills_db, [{"fill_id": "lf1", "decision_trace_id": "dec_cap_legacy",
                               "execution_price_cents": 46}])
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(fills_db))
    seen: Dict[str, Any] = {}
    import merid.prediction.directional_regime as _dr
    monkeypatch.setattr(
        _dr, "record_side_settlement",
        lambda side, pnl, **kw: seen.__setitem__("side_throttle", (side, pnl)),
    )
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _enter_decision_no()
    dec.decision_id = "dec_cap_legacy"
    ledger.record_trade_decision(dec)
    ledger.record_entry_fill(
        decision_id=dec.decision_id, fill_id="lf1",
        execution_outcome_side="yes", execution_action="sell",
        execution_price_cents=46, entry_fee_cents=0.0,
    )
    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(ticker=dec.ticker, close_ts=close_ts,
                             settled_yes=True, settlement_value_cents=100)
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT realized_net_pnl_cents, capital_realized_pnl_cents, exit_attribution "
            "FROM strategy_decision_outcomes WHERE decision_id = ?",
            ("dec_cap_legacy",),
        ).fetchone()
    assert row[0] == pytest.approx(-54.0)
    assert row[1] is None and row[2] == "unresolved"
    assert seen["side_throttle"] == ("no", pytest.approx(-54.0))


def test_compute_capital_realized_fifo_partial() -> None:
    """Two YES lots, one exit contract: FIFO closes the first lot only."""
    from merid.execution.decision_audit_ledger import compute_capital_realized_pnl

    fills = [
        {"fill_id": "e1", "execution_outcome_side": "yes", "execution_action": "buy",
         "execution_price_cents": 40, "quantity_cc": 100, "created_time": "t1"},
        {"fill_id": "e2", "execution_outcome_side": "yes", "execution_action": "buy",
         "execution_price_cents": 50, "quantity_cc": 100, "created_time": "t2"},
        # Sell YES @ 60 reported as buy NO @ 40 (same YES-delta direction).
        {"fill_id": "x", "execution_outcome_side": "no", "execution_action": "buy",
         "execution_price_cents": 40, "quantity_cc": 100, "created_time": "t3"},
    ]
    first = compute_capital_realized_pnl(
        fills=fills, target_fill_id="e1", held_side="yes", settle_value_yes_cents=0)
    second = compute_capital_realized_pnl(
        fills=fills, target_fill_id="e2", held_side="yes", settle_value_yes_cents=0)
    assert first["attribution"] == "exited"
    assert first["realized_pnl_cents"] == pytest.approx(20.0)
    assert first["exit_vwap_cents"] == pytest.approx(60.0)
    assert second["attribution"] == "held_to_settlement"
    assert second["realized_pnl_cents"] == pytest.approx(-50.0)
    assert compute_capital_realized_pnl(
        fills=fills, target_fill_id="missing", held_side="yes",
        settle_value_yes_cents=0) is None


def _full_reserve_decision() -> _FakeTradeDecision:
    """Decision with all seven EdgeBreakdown cost components populated."""
    dec = _FakeTradeDecision(decision_id="run_reserve_full")
    dec.indicators = {
        "yes_min_edge": 0.05,
        "no_min_edge": 0.05,
        "yes_formula_required_edge_cents": 2.6638,
        "no_formula_required_edge_cents": 3.1,
        "yes_effective_required_edge_cents": -12.0,
        "yes_effective_gate_edge_cents": -12.0,
        "yes_gate_ev_cents": -11.1974347697,
        "yes_formula_gate_passed": False,
        "yes_effective_edge_gate_passed": True,
        "yes_effective_required_source": "lane_floor:pinned_fav",
        "yes_admission_owner": "pinned_fav",
        "reserve_snapshot_id": "live_entry_evidence@1761000000.5:abc123def4567890",
        "reserve_artifact_hash": "abc123def4567890deadbeef",
        "reserve_artifact_asof": 1761000000.5,
        "reserve_estimator_version": "cell_aware_v1|giveback:exit_markouts_v1",
        "yes_reserve_cohort_key": '{"giveback":"DOGE","impl_evidence":"DOGE|yes|bid","edge_bias":"DOGE|yes|no_bid_complement"}',
        "yes_reserve_cohort_sample_count": '{"giveback_n":12,"impl_evidence_n":14,"edge_bias_n_eff":8.9}',
    }
    dec.yes_edge_breakdown = _FakeEdgeBreakdown(
        p_selected=0.9041756523,
        p_opposite=0.0958243477,
        executable_entry_price=0.91,
        entry_fee=0.0015,
        exit_cost_reserve=0.00045,
        model_risk_reserve=0.02,
        adverse_selection_reserve=0.055,
        policy_giveback_reserve=0.0292,
        implementation_shortfall_reserve=0.0,
        edge_bias_correction=0.0,
        gross_edge=-0.0058243477,
        net_edge=-0.1119743477,
    )
    dec.no_edge_breakdown = _FakeEdgeBreakdown(
        p_selected=0.4,
        executable_entry_price=0.27,
        gross_edge=0.13,
        net_edge=0.09,
    )
    dec.selected_outcome = "yes"
    dec.selected_action = "buy"
    dec.selected_outcome_price = Decimal("0.91")
    return dec


def test_side_ev_persists_reserve_components_and_split_gates(tmp_db: Path) -> None:
    """The three hidden reserve charges + split gate semantics + cohort
    provenance must persist so net_edge reconstructs without re-reading a
    mutable evidence artifact."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _full_reserve_decision()
    ledger.record_trade_decision(dec)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        yes = conn.execute(
            "SELECT * FROM strategy_decision_side_ev WHERE decision_id = ? AND side = 'yes'",
            (dec.decision_id,),
        ).fetchone()
        assert yes is not None

        assert yes["policy_giveback_reserve_c"] == pytest.approx(2.92)
        assert yes["implementation_shortfall_reserve_c"] == pytest.approx(0.0)
        assert yes["edge_bias_correction_c"] == pytest.approx(0.0)
        assert yes["adverse_selection_haircut_cents"] == pytest.approx(5.5)

        r = (
            yes["gross_edge_cents"]
            - yes["entry_fee_cents"]
            - yes["exit_or_settlement_fee_cents"]
            - yes["model_uncertainty_haircut_cents"]
            - yes["adverse_selection_haircut_cents"]
            - yes["policy_giveback_reserve_c"]
            - yes["implementation_shortfall_reserve_c"]
            - yes["edge_bias_correction_c"]
            - yes["expected_net_ev_cents"]
        )
        assert r == pytest.approx(0.0, abs=1e-6)

        assert yes["formula_required_c"] == pytest.approx(2.6638)
        assert yes["effective_required_c"] == pytest.approx(-12.0)
        assert yes["formula_gate_passed"] == 0
        assert yes["effective_edge_gate_passed"] == 1
        assert yes["effective_required_source"] == "lane_floor:pinned_fav"
        assert yes["passed_edge_gate"] == 1

        assert yes["reserve_snapshot_id"].startswith("live_entry_evidence@")
        assert yes["reserve_artifact_hash"] == "abc123def4567890deadbeef"
        assert yes["reserve_artifact_asof"] == pytest.approx(1761000000.5)
        assert "DOGE|yes|bid" in yes["reserve_cohort_key"]
        assert "giveback_n" in yes["reserve_cohort_sample_count"]
        assert yes["reserve_estimator_version"].startswith("cell_aware_v1")


def test_side_ev_missing_component_snapshot_stays_null(tmp_db: Path) -> None:
    """A decision without the new indicator/breakdown stamps must persist
    NULLs for cohort provenance, never a fabricated cohort."""
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    ledger.record_trade_decision(dec)

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        yes = conn.execute(
            "SELECT * FROM strategy_decision_side_ev WHERE decision_id = ? AND side = 'yes'",
            (dec.decision_id,),
        ).fetchone()
        assert yes["reserve_snapshot_id"] is None
        assert yes["reserve_cohort_key"] is None
        assert yes["reserve_estimator_version"] is None
        assert yes["formula_gate_passed"] is None
        assert yes["effective_edge_gate_passed"] == 1


# ── Settlement sweep lanes (2026-11-07 starvation fix) ─────────────────────


def test_reconcile_persists_scan_frontier_when_no_rows_healed(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """BUG A: a completed scan with an empty heal cohort must persist the
    scan frontier (MAX(rowid) at scan start) as complete_through_rowid —
    not the last *candidate* rowid (0), which used to force a full-table
    rescan on every restart."""
    import json

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    fills_db = tmp_path / "kalshi_fills.db"
    _make_fills_db(fills_db, [])
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(fills_db))
    monkeypatch.setenv(
        "MERID_RECONCILE_STATE_PATH", str(tmp_path / "reconcile_state.json")
    )

    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    dec.decision_id = "dec_frontier"
    ledger.record_trade_decision(dec)
    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec.ticker,
        close_ts=close_ts,
        settled_yes=True,
        settlement_value_cents=100,
    )

    with sqlite3.connect(str(tmp_db)) as conn:
        max_rid = conn.execute(
            "SELECT MAX(rowid) FROM strategy_decision_outcomes"
        ).fetchone()[0]
        assert max_rid > 0

    # No entry fill -> not a heal candidate -> healed == 0.
    assert ledger.reconcile_fill_outcomes() == 0

    state = json.loads((tmp_path / "reconcile_state.json").read_text())
    assert state["complete_through_rowid"] == max_rid
    assert state.get("last_full_scan_ts")


def test_pending_unsettled_tickers_aged_covers_beyond_hot_lookback(
    tmp_db: Path,
) -> None:
    """BUG C: PENDING rows older than the hot sweep's lookback must surface
    on the deep lane — the hot query's floor previously stranded them
    PENDING forever (permanently excluded from SETTLED-only evidence)."""
    import time
    from datetime import datetime, timedelta, timezone

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    dec.decision_id = "dec_aged_pending"
    dec.ticker = "KXBTC15M-AGED-TEST"
    dec.timestamp_utc = datetime.now(timezone.utc) - timedelta(days=2)
    dec.seconds_to_expiry = Decimal("60")
    ledger.record_trade_decision(dec)

    now = time.time()
    hot = ledger.pending_unsettled_tickers(
        now=now, grace_s=120.0, lookback_s=12 * 3600.0, limit=100
    )
    assert all(t != dec.ticker for t, _ in hot)

    deep = ledger.pending_unsettled_tickers_aged(
        now=now, older_than_s=12 * 3600.0, limit=100
    )
    assert dec.ticker in [t for t, _ in deep]


def test_unresolved_recheck_requeue_and_resurrection(tmp_db: Path) -> None:
    """BUG D: a transiently-marked UNRESOLVED outcome requeues to PENDING on
    a definitive exchange result and settles through the canonical path —
    with the prior reason preserved on the audit event."""
    import time

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _no_trade_decision("no_edge_below_threshold")
    dec.decision_id = "dec_recheck"
    dec.ticker = "KXBTC15M-RECHECK-TEST"
    ledger.record_trade_decision(dec)
    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)

    assert ledger.mark_outcome_unresolved(
        dec.ticker, close_ts, reason="lookup_failed_after_grace"
    ) == 1

    candidates = ledger.unresolved_recheck_candidates(
        now=time.time(), max_age_s=7 * 86400.0, max_rechecks=3, limit=50
    )
    match = [c for c in candidates if c[0] == dec.ticker]
    assert match and match[0][2] == "lookup_failed_after_grace"

    assert ledger.requeue_unresolved_outcomes(dec.ticker, close_ts) == 1
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT outcome_status, unresolved_reason, unresolved_at, "
            "unresolved_recheck_count FROM strategy_decision_outcomes "
            "WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert row["outcome_status"] == "PENDING"
        assert row["unresolved_reason"] is None
        assert row["unresolved_at"] is None
        evt = conn.execute(
            "SELECT reason_detail_json FROM strategy_decision_events "
            "WHERE decision_id = ? AND event_type = 'OUTCOME_RECHECK_REQUEUED'",
            (dec.decision_id,),
        ).fetchone()
        assert evt is not None
        assert "lookup_failed_after_grace" in evt["reason_detail_json"]

    # Canonical settle path now resurrects the row.
    ledger.record_settlement(
        ticker=dec.ticker,
        close_ts=close_ts,
        settled_yes=True,
        settlement_value_cents=100,
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        status = conn.execute(
            "SELECT outcome_status FROM strategy_decision_outcomes "
            "WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()[0]
        assert status == "SETTLED"


def test_unresolved_recheck_excludes_permanent_reasons_and_bounds_attempts(
    tmp_db: Path,
) -> None:
    """Permanently-voided markets and exhausted recheck budgets are never
    requeued."""
    import time

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)

    # Permanently voided market: reason matches market_status_voided_*.
    dec_void = _no_trade_decision("no_edge_below_threshold")
    dec_void.decision_id = "dec_recheck_void"
    dec_void.ticker = "KXBTC15M-VOID-TEST"
    ledger.record_trade_decision(dec_void)
    close_void = (
        dec_void.timestamp_utc.timestamp() + float(dec_void.seconds_to_expiry)
    )
    ledger.mark_outcome_unresolved(
        dec_void.ticker, close_void, reason="market_status_voided_after_4000s"
    )

    # Retryable reason but attempt budget already exhausted.
    dec_max = _no_trade_decision("no_edge_below_threshold")
    dec_max.decision_id = "dec_recheck_max"
    dec_max.ticker = "KXBTC15M-MAXTRY-TEST"
    ledger.record_trade_decision(dec_max)
    close_max = (
        dec_max.timestamp_utc.timestamp() + float(dec_max.seconds_to_expiry)
    )
    ledger.mark_outcome_unresolved(
        dec_max.ticker, close_max, reason="lookup_failed_after_grace"
    )
    ledger.bump_outcome_recheck(dec_max.ticker, close_max)
    ledger.bump_outcome_recheck(dec_max.ticker, close_max)
    ledger.bump_outcome_recheck(dec_max.ticker, close_max)

    candidates = ledger.unresolved_recheck_candidates(
        now=time.time(), max_age_s=7 * 86400.0, max_rechecks=3, limit=50
    )
    tickers = [c[0] for c in candidates]
    assert dec_void.ticker not in tickers
    assert dec_max.ticker not in tickers

    # The budget bounds API calls in the candidates query, not the requeue
    # itself: once the exchange has answered definitively, settling every
    # retryable row in the window is correct — the attempt counter is
    # preserved so a settle that fails again stays bounded.
    assert ledger.requeue_unresolved_outcomes(dec_max.ticker, close_max) == 1


def test_reconcile_fill_outcomes_windowed_scan_heals_all_candidates(
    tmp_db: Path, tmp_path: Path, monkeypatch
) -> None:
    """MERID_RECONCILE_SCAN_SPAN=1 forces one-rowid windows: the scan must
    still visit every candidate and heal all of them (no skips at window
    boundaries), and the I/O yield must not break completion even with a
    stale item sitting in the write queue."""
    import time as _t

    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    monkeypatch.setenv("MERID_RECONCILE_SCAN_SPAN", "1")
    monkeypatch.setenv("MERID_RECONCILE_YIELD_MAX_S", "0.2")
    monkeypatch.setenv("MERID_RECONCILE_YIELD_AGE_S", "180")
    fills_db = tmp_path / "kalshi_fills.db"
    _make_fills_db(
        fills_db,
        [
            {
                "fill_id": "fill_wa",
                "decision_trace_id": "dec_win_a",
                "execution_outcome_side": "yes",
                "execution_action": "sell",
                "execution_price_cents": 46,
                "fee_cost": 0.0,
            },
            {
                "fill_id": "fill_wb",
                "decision_trace_id": "dec_win_b",
                "execution_outcome_side": "yes",
                "execution_action": "sell",
                "execution_price_cents": 47,
                "fee_cost": 0.0,
            },
        ],
    )
    monkeypatch.setenv(
        "MERID_RECONCILE_STATE_PATH", str(tmp_path / "reconcile_state.json")
    )

    ledger = DecisionAuditLedger(db_path=tmp_db)
    # Settle with the fills DB unreachable so both rows go SETTLED with
    # NULL fill attribution -> heal candidates once fills are visible.
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(tmp_path / "absent.db"))
    for i, did in enumerate(("dec_win_a", "dec_win_b")):
        dec = _enter_decision_no()
        dec.decision_id = did
        dec.ticker = f"KXBTC15M-WIN-{i:02d}"
        ledger.record_trade_decision(dec)
        close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
        ledger.record_settlement(
            ticker=dec.ticker,
            close_ts=close_ts,
            settled_yes=True,
            settlement_value_cents=100,
        )

    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(fills_db))
    # A stale queued write makes the yield pause (bounded by YIELD_MAX_S)
    # on every window — the scan must still run to completion.
    ledger._write_queue.put((lambda: None, _t.monotonic() - 9999.0, "low"))

    assert ledger.reconcile_fill_outcomes() == 2

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        for did, px in (("dec_win_a", 54), ("dec_win_b", 53)):
            row = conn.execute(
                "SELECT actual_fill_price_cents, realized_net_pnl_cents "
                "FROM strategy_decision_outcomes WHERE decision_id = ?",
                (did,),
            ).fetchone()
            assert row["actual_fill_price_cents"] == px


def test_writer_health_oldest_required_tracks_non_low(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: oldest_required must track non-'low' queue items.

    'required' was never an actual priority value, so the literal check left
    oldest_required permanently 0 and the configured lag budget unenforced
    for real work.  Required evidence = everything except 'low' priority —
    the same rule shedding and failure accounting already use.
    """
    import time as _t
    from unittest.mock import MagicMock

    monkeypatch.setenv("MERID_AUDIT_WRITER_LAG_BUDGET_S", "60")
    ledger = DecisionAuditLedger(db_path=tmp_db)
    ledger._writer_started = True
    ledger._writer_thread = MagicMock()
    ledger._writer_thread.is_alive.return_value = True
    ledger._failures_loaded = True
    ledger._failed_required_writes = 0

    now = _t.monotonic()
    # FIFO head is a stale low-priority item (110s) — under the 2x any-item
    # bound (120s) so only the required-age branch can trip.  The oldest
    # non-low item is 90s old: past the 60s required budget.
    ledger._write_queue.put((lambda: None, now - 110.0, "low"))
    ledger._write_queue.put((lambda: None, now - 90.0, "high"))
    ledger._write_queue.put((lambda: None, now - 30.0, "normal"))

    wh = ledger.writer_health()
    assert wh["oldest_queued_age_s"] == pytest.approx(110.0, abs=1.0)
    assert wh["oldest_required_age_s"] == pytest.approx(90.0, abs=1.0)
    assert wh["unhealthy"] is True

    # Fresh queue: nothing near the budget -> healthy.
    ledger2 = DecisionAuditLedger(db_path=tmp_db)
    ledger2._writer_started = True
    ledger2._writer_thread = MagicMock()
    ledger2._writer_thread.is_alive.return_value = True
    ledger2._failures_loaded = True
    ledger2._failed_required_writes = 0
    ledger2._write_queue.put((lambda: None, now - 5.0, "high"))
    wh2 = ledger2.writer_health()
    assert wh2["unhealthy"] is False


def test_shed_admit_emergency_tier_bounds_normal_telemetry(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: 2026-11-16 audit_writer_unhealthy entry halt.

    Rejected-candidate telemetry submitted at ``priority="high"`` never shed,
    so under writer backlog its arrival permanently exceeded drain; the queue
    reached ~3900 and oldest_queued_age crossed the 2x lag budget, halting all
    entries for ~40min.  Two-part fix under test:

    1. Candidate terminal transitions and RISK_REJECTED events now submit at
       ``priority="normal"`` so ``_shed_admit`` can sample them.
    2. ``_shed_admit`` gained an emergency tier: past
       ``MERID_AUDIT_SHED_EMERGENCY_DEPTH`` NORMAL writes keep only
       ``1/MERID_AUDIT_EMERGENCY_SAMPLE_DIV`` so the backlog can drain.

    HIGH (fills/orders/settlements/decision spine) must remain never-shed.
    """
    monkeypatch.setenv("MERID_AUDIT_SHED_DEPTH", "100")
    monkeypatch.setenv("MERID_AUDIT_SHED_CRIT_DEPTH", "200")
    monkeypatch.setenv("MERID_AUDIT_SHED_EMERGENCY_DEPTH", "400")
    monkeypatch.setenv("MERID_AUDIT_NORMAL_SAMPLE_DIV", "4")
    monkeypatch.setenv("MERID_AUDIT_EMERGENCY_SAMPLE_DIV", "16")

    ledger = DecisionAuditLedger(db_path=tmp_db)

    # Below soft depth: everything admitted.
    assert ledger._shed_admit("normal", 50) is True
    assert ledger._shed_admit("low", 50) is True
    assert ledger._shed_admit("high", 50) is True

    # Soft band [100,200): low samples, normal+high admit.
    admitted_normal_soft = sum(
        1 for _ in range(40) if ledger._shed_admit("normal", 150)
    )
    assert admitted_normal_soft == 40  # normal unshed below crit

    # Crit band [200,400): normal keeps ~1/4.
    admitted_normal_crit = sum(
        1 for _ in range(400) if ledger._shed_admit("normal", 300)
    )
    # Deterministic modulo sampling: exactly ceil/floor of 400/4 kept.
    assert 90 <= admitted_normal_crit <= 110

    # Emergency band [400,inf): normal keeps ~1/16 — far fewer survive so the
    # queue can actually drain instead of growing unboundedly.
    admitted_normal_emerg = sum(
        1 for _ in range(1600) if ledger._shed_admit("normal", 500)
    )
    assert 80 <= admitted_normal_emerg <= 120  # ~1/16 of 1600

    # HIGH never sheds at any depth — financial truth is never dropped.
    assert all(ledger._shed_admit("high", d) for d in (500, 3900, 100000))


def _priority_after_anchor(src: str, anchor: str, span: int = 3000) -> Optional[str]:
    """Return the ``priority="..."`` literal nearest after ``anchor``."""
    import re

    idx = src.find(anchor)
    if idx < 0:
        return None
    window = src[idx: idx + span]
    m = re.search(r'priority="(high|normal|low)"', window)
    return m.group(1) if m else None


def test_candidate_terminal_and_risk_rejected_submit_normal_priority() -> None:
    """Regression: rejected-path telemetry must be sheddable.

    Candidate terminal transitions (loop_15m) and RISK_REJECTED events
    (agent_grid) were submitted at ``priority="high"`` — never shed — which
    let rejected-path telemetry flood the audit writer until
    ``audit_writer_unhealthy`` halted all entries (2026-11-16).  They must be
    ``priority="normal"`` so ``_shed_admit`` can sample them under backlog.
    """
    from pathlib import Path as _P

    root = _P(__file__).resolve().parent.parent
    loop_src = (root / "merid" / "loop_15m.py").read_text(encoding="utf-8")
    grid_src = (
        root / "merid" / "prediction" / "agent_grid_15m.py"
    ).read_text(encoding="utf-8")

    # Candidate terminal block: anchor on the terminal event_type kwarg.
    assert (
        _priority_after_anchor(loop_src, 'event_type=_audit_terminal[0]')
        == "normal"
    ), "candidate terminal audit must submit priority='normal'"

    # RISK_REJECTED block in agent_grid.
    assert (
        _priority_after_anchor(grid_src, 'event_type="RISK_REJECTED"')
        == "normal"
    ), "RISK_REJECTED audit must submit priority='normal'"

    # The decision spine (record_trade_decision) and fills/orders stay "high" —
    # financial truth is never shed.  Guard against an accidental downgrade.
    assert (
        _priority_after_anchor(grid_src, "ledger.record_trade_decision")
        == "high"
    ), "decision spine must remain priority='high'"
