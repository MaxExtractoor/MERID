"""Tests for the decision lifecycle/audit extensions:

- ``strategy_decision_events`` append-only lifecycle table + idempotent writes
- stable ``candidate_id``/route-suffixed ``decision_id`` identity
- pre-decision rejection rows + events (no fake TradeDecision)
- pure gate-vector evaluation persisted on the decision row
- counterfactual executability classification + depth-scaled settlement P&L
- terminal ``UNRESOLVED`` outcome transition after grace
"""

import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from merid.execution.decision_audit_ledger import (
    CF_FULLY_EXECUTABLE,
    CF_NOT_EXECUTABLE_STALE_BOOK,
    CF_PARTIALLY_EXECUTABLE,
    CF_UNKNOWN_EXECUTABILITY,
    DecisionAuditLedger,
    _candidate_id_from_decision_id,
    _route_from_decision_id,
)
from merid.prediction.gate_evaluation import evaluate_all_gates


@dataclass
class _FakeBD:
    p_selected: float = 0.5
    p_opposite: float = 0.5
    executable_entry_price: float = 0.33
    entry_fee: float = 0.01
    exit_cost_reserve: float = 0.01
    model_risk_reserve: float = 0.02
    gross_edge: float = 0.17
    net_edge: float = 0.13


@dataclass
class _FakeDecision:
    decision_id: str = "cand_abc123:t"
    run_id: str = "run_t1"
    ticker: str = "KXBTC15M-TEST-45"
    asset: str = "BTC"
    timestamp_utc: Any = None
    seconds_to_expiry: Any = 900
    p_yes_raw: Any = 0.55
    p_yes_calibrated: Any = 0.50
    p_no_calibrated: Any = 0.50
    indicators: Dict[str, Any] = field(default_factory=dict)
    data_state: str = "healthy"
    regime_label: str = "known"
    selected_outcome: Optional[str] = None
    selected_action: Optional[str] = None
    gross_edge: Optional[float] = None
    net_edge: Optional[float] = None
    no_trade_reason: Optional[str] = None
    confidence_valid: bool = True
    confidence: Any = 0.7
    confidence_source: str = "test"
    confidence_reasons: List[str] = field(default_factory=list)
    yes_edge_breakdown: Optional[_FakeBD] = None
    no_edge_breakdown: Optional[_FakeBD] = None
    yes_depth_cc: Any = 500.0
    no_depth_cc: Any = 600.0
    min_required_edge: Any = 0.05
    edge_threshold: Any = 0.05
    approved_size_cc: Any = None
    policy_version: str = "trade_decision_v2"
    build_sha: str = "testsha"

    def __post_init__(self):
        if self.timestamp_utc is None:
            from datetime import datetime, timezone

            self.timestamp_utc = datetime.now(timezone.utc)


@dataclass
class _GoodBook:
    book_initialized: bool = True
    data_quality: str = "GOOD"
    best_bid_cents: int = 30
    best_ask_cents: int = 33
    best_no_bid_cents: int = 65
    best_no_ask_cents: int = 70


@dataclass
class _CrossedBook:
    book_initialized: bool = True
    data_quality: str = "GOOD"
    best_bid_cents: int = 40
    best_ask_cents: int = 33  # crossed
    best_no_bid_cents: int = 60
    best_no_ask_cents: int = 70


@pytest.fixture
def tmp_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


@pytest.fixture(autouse=True)
def _enable():
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    yield
    os.environ.pop("MERID_DECISION_AUDIT_LEDGER_ENABLED", None)


def _mk_decision(**kw) -> _FakeDecision:
    d = _FakeDecision(**kw)
    d.indicators.setdefault("bachelier_spot", 65000.0)
    d.indicators.setdefault("strike", 65050.0)
    d.yes_edge_breakdown = _FakeBD()
    d.no_edge_breakdown = _FakeBD(executable_entry_price=0.27)
    return d


# ── Identity ──────────────────────────────────────────────────────────────


def test_identity_split_and_route() -> None:
    assert _candidate_id_from_decision_id("cand_abc123:t") == "cand_abc123"
    assert _candidate_id_from_decision_id("cand_abc123:pre") == "cand_abc123"
    assert _candidate_id_from_decision_id("legacy_decision_1") == "legacy_decision_1"
    assert _route_from_decision_id("cand_abc123:m") == "m"
    assert _route_from_decision_id("legacy_decision_1") is None


def test_routes_share_candidate_id(tmp_db: Path) -> None:
    """Taker/maker/shadow passes of one observation share candidate_id."""
    ledger = DecisionAuditLedger(db_path=tmp_db)
    for route in ("t", "m", "b"):
        dec = _mk_decision(decision_id=f"cand_shared:{route}")
        dec.no_trade_reason = "no_edge_below_threshold"
        ledger.record_trade_decision(dec)
    with sqlite3.connect(str(tmp_db)) as conn:
        rows = conn.execute(
            "SELECT decision_id, candidate_id FROM strategy_decisions "
            "WHERE candidate_id = 'cand_shared' ORDER BY decision_id"
        ).fetchall()
        assert len(rows) == 3
        assert {r[0] for r in rows} == {
            "cand_shared:t",
            "cand_shared:m",
            "cand_shared:b",
        }


# ── Lifecycle events ──────────────────────────────────────────────────────


def test_append_event_idempotent_and_orderable(tmp_db: Path) -> None:
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _mk_decision()
    dec.no_trade_reason = None
    dec.selected_outcome = "yes"
    ledger.record_trade_decision(dec)

    # Post-decision rejection; same call twice must dedupe.
    kwargs = dict(
        decision_id=dec.decision_id,
        event_type="ALLOCATION_REJECTED",
        stage="ALLOCATION",
        event_ts_utc=time.time(),
        reason_code="NOT_TOP_RANKED",
        run_id="run_t1",
        ticker=dec.ticker,
        asset="BTC",
    )
    e1 = ledger.append_decision_event(**kwargs)
    e2 = ledger.append_decision_event(**kwargs)
    assert e1 is not None

    # Out-of-order: an earlier-timestamped event still inserts.
    ledger.append_decision_event(
        **{**kwargs, "event_type": "MODEL_SELECTED", "stage": "MODEL",
           "event_ts_utc": time.time() - 5.0, "reason_code": "selected"}
    )

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event_type, reason_code FROM strategy_decision_events "
            "WHERE decision_id = ? ORDER BY event_ts",
            (dec.decision_id,),
        ).fetchall()
        types = [r["event_type"] for r in rows]
        # one MODEL_SELECTED from insert + appended events; no dup ALLOCATION_REJECTED
        assert types.count("ALLOCATION_REJECTED") == 1
        assert types.count("MODEL_SELECTED") == 2  # insert-time + appended
        dec_row = conn.execute(
            "SELECT primary_reason_code FROM strategy_decisions WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        # The allocator rejection must NOT overwrite the model-stage outcome.
        assert dec_row["primary_reason_code"] == "selected"


def test_pre_decision_rejection_persists_row_event_outcome(tmp_db: Path) -> None:
    ledger = DecisionAuditLedger(db_path=tmp_db)
    ok = ledger.record_pre_decision_rejection(
        cycle_id="42",
        run_id="run_t1",
        ticker="KXBTC15M-TEST-45",
        asset="BTC",
        reason="cooldown: time_since_last=10s < cooldown=30s",
        seconds_to_expiry=700.0,
        spot_price=65000.0,
        strike_price=65050.0,
        candidate_id="cand_pre1",
        event_type="COOLDOWN_REJECTED",
        event_stage="RISK",
    )
    assert ok
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        dec = conn.execute(
            "SELECT decision_id, candidate_id, run_id, decision, "
            "primary_reason_code, gate_results_json, all_failed_gates_json "
            "FROM strategy_decisions WHERE candidate_id = 'cand_pre1'"
        ).fetchone()
        assert dec["decision_id"] == "cand_pre1:pre"
        assert dec["run_id"] == "run_t1"
        assert dec["decision"] == "NO_TRADE"
        gates = json.loads(dec["gate_results_json"])
        assert "pre_decision_pipeline" in gates
        evs = conn.execute(
            "SELECT event_type, stage FROM strategy_decision_events "
            "WHERE decision_id = 'cand_pre1:pre'"
        ).fetchall()
        assert (evs[0]["event_type"], evs[0]["stage"]) == ("COOLDOWN_REJECTED", "RISK")
        oc = conn.execute(
            "SELECT outcome_status FROM strategy_decision_outcomes "
            "WHERE decision_id = 'cand_pre1:pre'"
        ).fetchone()
        assert oc["outcome_status"] == "PENDING"


# ── Gate evaluation ───────────────────────────────────────────────────────


def test_gate_evaluation_is_pure_and_additive(tmp_db: Path) -> None:
    dec = _mk_decision()
    dec.no_trade_reason = "edge_below_threshold_yes"
    dec.indicators.update({
        "yes_depth_ok": True,
        "no_depth_ok": True,
        "yes_regime_block": "trend_against",
        "yes_conviction_block": None,
        "yes_ev_net_cents": 0.4,
        "yes_min_edge": 1.0,
        "yes_qualifies": False,
        "no_qualifies": False,
    })
    before = dict(dec.indicators)
    ev = evaluate_all_gates(dec, market_state=_GoodBook())
    assert ev is not None
    assert dec.indicators == before  # no mutation
    names = {g.gate_name: g for g in ev.gate_results}
    # Multiple simultaneous failures captured, not just the live first-failure.
    assert "yes_regime" in ev.all_failed_gates
    assert "yes_edge_threshold" in ev.all_failed_gates
    assert names["yes_edge_threshold"].blocking_in_live_path
    # Regime co-failed but did not own the live rejection reason.
    assert not names["yes_regime"].blocking_in_live_path
    assert names["yes_depth"].passed is True
    assert names["market_time"].passed is True  # seconds_to_expiry present
    # Persisted vector lands on the decision row.
    ledger = DecisionAuditLedger(db_path=tmp_db)
    ledger.record_trade_decision(dec, market_state=_GoodBook())
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT gate_results_json, all_failed_gates_json, "
            "gate_evaluation_schema_version FROM strategy_decisions "
            "WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        gates = json.loads(row["gate_results_json"])
        assert "yes_edge_threshold" in gates
        assert json.loads(row["all_failed_gates_json"]) == list(ev.all_failed_gates)
        assert row["gate_evaluation_schema_version"] == 1


# ── Executability + scaled counterfactuals ────────────────────────────────


def test_executability_and_depth_scaled_pnl(tmp_db: Path) -> None:
    ledger = DecisionAuditLedger(db_path=tmp_db)
    # Depth cap: yes_depth_cc=50fp = 0.5 contract, requested 1.0 -> partial.
    dec = _mk_decision(decision_id="cand_exec:t")
    dec.no_trade_reason = "edge_below_threshold_yes"
    dec.yes_depth_cc = 50.0  # fp units -> 0.5 contract
    ledger.record_trade_decision(dec, market_state=_GoodBook())

    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT side, requested_contracts, top_of_book_executable_contracts, "
            "counterfactual_assumed_filled_contracts, counterfactual_execution_status "
            "FROM strategy_decision_side_ev WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchall()
        yes = [r for r in rows if r["side"] == "yes"][0]
        assert yes["counterfactual_assumed_filled_contracts"] == pytest.approx(0.5)
        assert yes["counterfactual_execution_status"] == CF_PARTIALLY_EXECUTABLE

    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    ledger.record_settlement(
        ticker=dec.ticker, close_ts=close_ts,
        settled_yes=True, settlement_value_cents=100,
    )
    with sqlite3.connect(str(tmp_db)) as conn:
        oc = conn.execute(
            "SELECT counterfactual_yes_pnl_cents FROM strategy_decision_outcomes "
            "WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        # 0.5 * (100 - 33 - 1 - 1) = 32.5 — scaled, not the full-contract 65.
        assert oc[0] == pytest.approx(32.5)


def test_absent_book_is_unknown_not_stale(tmp_db: Path) -> None:
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _mk_decision(decision_id="cand_nobook:t")
    ledger.record_trade_decision(dec, market_state=None)
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT counterfactual_execution_status, "
            "counterfactual_assumed_filled_contracts "
            "FROM strategy_decision_side_ev WHERE decision_id = ? AND side='yes'",
            (dec.decision_id,),
        ).fetchone()
        assert row[0] == CF_UNKNOWN_EXECUTABILITY
        assert row[1] == pytest.approx(1.0)


def test_known_bad_book_marks_stale(tmp_db: Path) -> None:
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _mk_decision(decision_id="cand_badbook:t")
    ledger.record_trade_decision(dec, market_state=_CrossedBook())
    with sqlite3.connect(str(tmp_db)) as conn:
        row = conn.execute(
            "SELECT counterfactual_execution_status, "
            "counterfactual_assumed_filled_contracts "
            "FROM strategy_decision_side_ev WHERE decision_id = ? AND side='yes'",
            (dec.decision_id,),
        ).fetchone()
        assert row[0] == CF_NOT_EXECUTABLE_STALE_BOOK
        assert row[1] == 0.0


# ── Terminal unresolved ───────────────────────────────────────────────────


def test_mark_outcome_unresolved(tmp_db: Path) -> None:
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _mk_decision()
    ledger.record_trade_decision(dec)
    close_ts = dec.timestamp_utc.timestamp() + float(dec.seconds_to_expiry)
    n = ledger.mark_outcome_unresolved(
        dec.ticker, close_ts, reason="market_status_closed_after_4000s"
    )
    assert n == 1
    with sqlite3.connect(str(tmp_db)) as conn:
        conn.row_factory = sqlite3.Row
        oc = conn.execute(
            "SELECT outcome_status, unresolved_reason "
            "FROM strategy_decision_outcomes WHERE decision_id = ?",
            (dec.decision_id,),
        ).fetchone()
        assert oc["outcome_status"] == "UNRESOLVED"
        assert "closed" in oc["unresolved_reason"]
        ev = conn.execute(
            "SELECT event_type FROM strategy_decision_events "
            "WHERE decision_id = ? AND event_type = 'OUTCOME_UNRESOLVED'",
            (dec.decision_id,),
        ).fetchone()
        assert ev is not None
    # Second call is a no-op (row no longer PENDING).
    assert ledger.mark_outcome_unresolved(dec.ticker, close_ts) == 0


def test_migration_idempotent(tmp_db: Path) -> None:
    """Reopening the same DB must not fail on existing columns/tables."""
    DecisionAuditLedger(db_path=tmp_db)
    ledger = DecisionAuditLedger(db_path=tmp_db)
    dec = _mk_decision()
    assert ledger.record_trade_decision(dec)
