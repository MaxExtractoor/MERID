"""Tests for the incremental evidence-outcome store (2026-11-18).

The live-entry evidence refresh used to rescan the whole configured window
of the multi-GB audit DB every cycle; on the production spindle the scan
repeatedly exceeded the query deadline, so the artifact aged toward the
staleness cliff and cells starved.  ``evidence_outcome_store`` extracts
each settlement's evidence rows once, watermark-bounded, and the refresh
rebuilds the artifact from the small companion store.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from merid.execution.evidence_outcome_store import (
    EvidenceOutcomeStore,
    store_path_for,
)


@pytest.fixture()
def audit_db(tmp_path):
    """Minimal audit schema with the tables/columns the extract queries use."""
    path = tmp_path / "audit.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE strategy_decisions (
          decision_id TEXT PRIMARY KEY, decision_ts REAL,
          observed_at_ts REAL, decision_ts_iso TEXT,
          strategy_name TEXT, strategy_version TEXT, model_version TEXT,
          config_version TEXT, ticker TEXT, asset TEXT, close_ts REAL,
          close_ts_iso TEXT, seconds_to_close REAL,
          settlement_reference TEXT, settlement_rule_version TEXT,
          selected_side TEXT, decision TEXT, primary_reason_code TEXT,
          created_at REAL, admission_lane TEXT,
          is_eligible_for_research INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE strategy_decision_side_ev (
          decision_id TEXT, side TEXT,
          executable_entry_price_cents REAL, decision_lane TEXT,
          calibrated_probability REAL, expected_entry_slippage_cents REAL,
          exclusion_reason TEXT, passed_edge_gate INTEGER,
          counterfactual_execution_status TEXT,
          expected_net_ev_cents REAL, counterfactual_entry_source TEXT,
          counterfactual_assumed_filled_contracts REAL
        );
        CREATE TABLE strategy_decision_outcomes (
          decision_id TEXT PRIMARY KEY, settled_at REAL, settled_yes INTEGER,
          outcome_status TEXT, actual_fill_price_cents REAL,
          counterfactual_yes_pnl_cents REAL,
          counterfactual_no_pnl_cents REAL
        );
        CREATE INDEX idx_outcomes_settled_at
          ON strategy_decision_outcomes(settled_at);
        """
    )
    conn.commit()
    conn.close()
    return path


def _seed_market(conn, did, asset, side, px, settled_at, settled_yes,
                 decision="ENTER", cf_status=None, net_ev=None):
    conn.execute(
        "INSERT INTO strategy_decisions (decision_id, decision_ts, ticker,"
        " asset, seconds_to_close, selected_side, decision)"
        " VALUES (?,?,?,?,?,?,?)",
        (did, settled_at, f"KX{asset}15M-{did}", asset, 400.0,
         side if decision == "ENTER" else "yes", decision),
    )
    conn.execute(
        "INSERT INTO strategy_decision_side_ev (decision_id, side,"
        " executable_entry_price_cents, counterfactual_execution_status,"
        " expected_net_ev_cents) VALUES (?,?,?,?,?)",
        (did, side, px, cf_status, net_ev),
    )
    conn.execute(
        "INSERT INTO strategy_decision_outcomes (decision_id, settled_at,"
        " settled_yes, outcome_status, counterfactual_yes_pnl_cents,"
        " counterfactual_no_pnl_cents) VALUES (?,?,?,'SETTLED',?,?)",
        (did, settled_at, settled_yes, 10, -10),
    )


def _ro(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _rw(path):
    return sqlite3.connect(str(path))


def test_store_path_derives_from_audit_db(tmp_path):
    assert store_path_for(tmp_path / "decision_audit.db").name == (
        "decision_audit_evidence_outcomes.db"
    )


def test_extract_range_writes_all_three_srcs(tmp_path, audit_db):
    now = time.time()
    audit = _rw(audit_db)
    _seed_market(audit, "f1", "BTC", "no", 55, now - 100, 0)
    _seed_market(audit, "v1", "ETH", "yes", 40, now - 100, 1,
                 decision="NO_TRADE", cf_status="FULLY_EXECUTABLE",
                 net_ev=3.0)
    _seed_market(audit, "e1", "SOL", "yes", 60, now - 100, 1,
                 decision="NO_TRADE", cf_status="FULLY_EXECUTABLE",
                 net_ev=-2.0)
    audit.commit()
    audit.close()

    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = _ro(audit_db)
    n = store.extract_range(audit, sconn, now - 3600, now + 1)
    audit.close()

    # fill row + veto row + ebias row (v1 and e1 each produce veto+ebias)
    rows = store.read_since(sconn, now - 86400)
    srcs = sorted(r["src"] for r in rows)
    assert srcs == ["ebias", "ebias", "fill", "veto", "veto"]
    fill = next(r for r in rows if r["src"] == "fill")
    assert fill["asset"] == "BTC" and fill["side"] == "no"
    assert fill["entry_cents"] == 55 and fill["mkey"] == "KXBTC15M-f1"
    eb = next(r for r in rows if r["src"] == "ebias")
    assert eb["net_ev"] in (3.0, -2.0) and eb["cf_yes"] == 10
    sconn.close()


def test_extract_range_is_idempotent(tmp_path, audit_db):
    now = time.time()
    audit = _rw(audit_db)
    _seed_market(audit, "f1", "BTC", "no", 55, now - 100, 0)
    audit.commit()
    audit.close()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = _ro(audit_db)
    store.extract_range(audit, sconn, now - 3600, now + 1)
    store.extract_range(audit, sconn, now - 3600, now + 1)
    audit.close()
    rows = store.read_since(sconn, now - 86400)
    assert len(rows) == 1
    sconn.close()


def test_settled_at_equal_to_hi_is_included(tmp_path, audit_db):
    """Frozen-clock regression: settled_at == extraction hi must match.

    Production refreshes pass ``hi=now``; under frozen test clocks
    ``settled_at == now`` exactly, and an exclusive ``< hi`` bound dropped
    every row (2026-11-18 test failure)."""
    now = time.time()
    audit = _rw(audit_db)
    _seed_market(audit, "f1", "BTC", "no", 55, now, 0)  # settled_at == now
    audit.commit()
    audit.close()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = _ro(audit_db)
    store.extract_range(audit, sconn, now - 3600, now)
    audit.close()
    assert len(store.read_since(sconn, now - 86400)) == 1
    sconn.close()


def test_read_since_window_and_veto_filter(tmp_path, audit_db):
    now = time.time()
    audit = _rw(audit_db)
    _seed_market(audit, "old", "BTC", "no", 55, now - 90000, 0)
    _seed_market(audit, "new", "BTC", "no", 55, now - 100, 0)
    _seed_market(audit, "v1", "ETH", "yes", 40, now - 100, 1,
                 decision="NO_TRADE")
    audit.commit()
    audit.close()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = _ro(audit_db)
    store.extract_range(audit, sconn, now - 200000, now + 1)
    audit.close()
    recent = store.read_since(sconn, now - 3600)
    assert {r["ticker"] for r in recent} == {"KXBTC15M-new", "KXETH15M-v1"}
    no_veto = store.read_since(sconn, now - 3600, include_vetoes=False)
    assert all(r["src"] != "veto" for r in no_veto)
    sconn.close()


def test_prune_and_state(tmp_path, audit_db):
    now = time.time()
    audit = _rw(audit_db)
    _seed_market(audit, "f1", "BTC", "no", 55, now - 100, 0)
    audit.commit()
    audit.close()
    store = EvidenceOutcomeStore(store_path_for(audit_db))
    sconn = store._connect()
    audit = _ro(audit_db)
    store.extract_range(audit, sconn, now - 3600, now + 1)
    audit.close()
    assert store.prune(sconn, now - 50) == 1
    assert store.read_since(sconn, 0) == []
    store.state_set(sconn, "live_ts", "123.5")
    sconn.commit()
    assert store.state_get(sconn, "live_ts") == "123.5"
    sconn.close()
