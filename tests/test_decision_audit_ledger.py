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
            "SELECT decision, primary_reason_code, selected_side FROM strategy_decisions WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        assert rows[0]["decision"] == "ENTER"
        assert rows[0]["primary_reason_code"] == "selected"
        assert rows[0]["selected_side"] == "yes"


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
