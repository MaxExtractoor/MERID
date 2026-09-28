"""Live rolling entry-evidence gate tests (2026-09-28).

Covers the gate added to compute_trade_decision that fails closed on *recent*
settled-outcome evidence: the static tail-calibration artifact is only refit
offline, so a regime break (BTC NO-side win rate collapsed 77% -> 45% over
48h on 2026-09-26..28) kept passing the frozen floor for days.  The audit
ledger rebuilds data/live_entry_evidence.json per settlement; these tests
cover the artifact refresh, the asset/cell gate semantics, fail-open on
missing data, and the decision-path rejection reason.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction.trade_decision import (
    _clear_live_evidence_cache,
    _live_evidence_allows,
    _load_live_evidence,
    compute_trade_decision,
)
from merid.execution.decision_audit_ledger import DecisionAuditLedger


@pytest.fixture(autouse=True)
def _isolate_evidence(monkeypatch, tmp_path):
    """Point the evidence artifact at a tmp path and reset the mtime cache so
    no machine-local artifact can leak into these tests (or be written by them)."""
    path = tmp_path / "live_entry_evidence.json"
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_PATH", str(path))
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_GATE", True)
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_MARGIN", 0.03)
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_MIN_ASSET_SAMPLES", 30)
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_MIN_CELL_SAMPLES", 15)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    _clear_live_evidence_cache()
    yield path
    _clear_live_evidence_cache()


def _write_evidence(path: Path, assets: dict) -> Path:
    payload = {
        "version": 1,
        "generated_at": time.time(),
        "window_hours": 48,
        "assets": assets,
    }
    path.write_text(json.dumps(payload))
    _clear_live_evidence_cache()
    return path


def _decision(**kwargs):
    args = dict(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-26SEP282100-00",
        asset="BTC",
        spot_price=99.5,
        strike_price=100.0,
        seconds_to_expiry=900.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=56.0,
        no_ask_cents=58.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        data_quality="live",
        regime="normal",
        settlement_reference="cfb_rti_live",
    )
    args.update(kwargs)
    return compute_trade_decision(**args)


# ── _live_evidence_allows unit semantics ─────────────────────────────


def test_asset_level_blocks_decayed_cohort():
    """BTC no-side: wr .40 over 40 settled at avg entry 55c -> floor .59."""
    ev = {"assets": {"BTC": {"no": {"n": 40, "wr": 0.40, "avg_entry_cents": 55.0, "buckets": {}}}}}
    ok, det = _live_evidence_allows(ev, "BTC", "no", 58, 0.01)
    assert ok is False
    assert det["level"] == "asset"
    assert det["n"] == 40


def test_asset_level_passes_healthy_cohort():
    ev = {"assets": {"BTC": {"no": {"n": 40, "wr": 0.80, "avg_entry_cents": 55.0, "buckets": {}}}}}
    ok, det = _live_evidence_allows(ev, "BTC", "no", 58, 0.01)
    assert ok is True
    assert det is None


def test_cell_level_blocks_decayed_bucket():
    """Under-sampled at asset level but the 50-59c bucket itself is toxic."""
    ev = {"assets": {"BTC": {"no": {
        "n": 20, "wr": 0.80, "avg_entry_cents": 55.0,
        "buckets": {"50": {"n": 20, "wr": 0.30}},
    }}}}
    ok, det = _live_evidence_allows(ev, "BTC", "no", 58, 0.01)
    assert ok is False
    assert det["level"] == "cell"
    assert det["bucket"] == "50"


def test_fail_open_missing_and_undersampled():
    ev = {"assets": {"BTC": {"no": {"n": 5, "wr": 0.0, "avg_entry_cents": 55.0, "buckets": {}}}}}
    # missing asset, missing side, and under-sampled cohorts all defer
    assert _live_evidence_allows(ev, "DOGE", "no", 58, 0.01)[0] is True
    assert _live_evidence_allows(ev, "BTC", "yes", 42, 0.01)[0] is True
    assert _live_evidence_allows(ev, "BTC", "no", 58, 0.01)[0] is True
    assert _live_evidence_allows({}, "BTC", "no", 58, 0.01)[0] is True


def test_opposite_side_not_affected():
    """The gate is per (asset, side): a decayed NO cohort leaves YES open."""
    ev = {"assets": {"BTC": {
        "no": {"n": 40, "wr": 0.40, "avg_entry_cents": 55.0, "buckets": {}},
        "yes": {"n": 40, "wr": 0.85, "avg_entry_cents": 55.0, "buckets": {}},
    }}}
    assert _live_evidence_allows(ev, "BTC", "no", 58, 0.01)[0] is False
    assert _live_evidence_allows(ev, "BTC", "yes", 42, 0.01)[0] is True


# ── _load_live_evidence ──────────────────────────────────────────────


def test_loader_missing_file_returns_none(_isolate_evidence):
    assert _load_live_evidence() is None


def test_loader_reads_and_caches(_isolate_evidence):
    _write_evidence(_isolate_evidence, {"BTC": {"no": {"n": 40, "wr": 0.4, "avg_entry_cents": 55.0, "buckets": {}}}})
    first = _load_live_evidence()
    assert first["assets"]["BTC"]["no"]["n"] == 40
    # cached object returned on same mtime
    assert _load_live_evidence() is first


# ── compute_trade_decision integration ───────────────────────────────


def test_decision_blocked_by_decayed_asset_cohort(_isolate_evidence):
    """A decision that would select NO is rejected when the asset+side cohort
    decayed below its mean entry price — reason live_evidence_asset_no."""
    _write_evidence(_isolate_evidence, {
        "BTC": {"no": {"n": 40, "wr": 0.40, "avg_entry_cents": 55.0, "buckets": {}}}
    })
    d = _decision()
    assert d.selected_outcome is None
    assert d.no_trade_reason == "live_evidence_asset_no"
    assert d.indicators["live_evidence_evaluated"] is True
    assert d.indicators["live_evidence_asset_no"]["level"] == "asset"


def test_decision_blocked_by_decayed_price_cell(_isolate_evidence):
    _write_evidence(_isolate_evidence, {
        "BTC": {"no": {
            "n": 20, "wr": 0.80, "avg_entry_cents": 55.0,
            "buckets": {"50": {"n": 20, "wr": 0.30}},
        }}
    })
    d = _decision()
    assert d.selected_outcome is None
    assert d.no_trade_reason == "live_evidence_cell_no"


def test_decision_unaffected_when_healthy(_isolate_evidence):
    """Healthy trailing evidence leaves the normal selection intact."""
    _write_evidence(_isolate_evidence, {
        "BTC": {"no": {"n": 40, "wr": 0.80, "avg_entry_cents": 55.0, "buckets": {}}}
    })
    d = _decision()
    assert d.selected_outcome == "no"


def test_decision_unaffected_without_artifact(_isolate_evidence):
    """No artifact -> fail-open (mirrors the absent-calibrator convention)."""
    d = _decision()
    assert d.selected_outcome == "no"


def test_gate_disabled_by_env(_isolate_evidence, monkeypatch):
    _write_evidence(_isolate_evidence, {
        "BTC": {"no": {"n": 40, "wr": 0.40, "avg_entry_cents": 55.0, "buckets": {}}}
    })
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_GATE", False)
    d = _decision()
    assert d.selected_outcome == "no"


# ── audit-ledger artifact refresh ────────────────────────────────────


def _seed_audit_db(ledger: DecisionAuditLedger) -> None:
    """Insert minimal ENTER decisions + side-EV + SETTLED outcomes."""
    now = time.time()
    with ledger._lock, ledger._conn() as conn:
        for i in range(40):
            did = f"btc-no-{i}"
            won = i < 16  # wr = 16/40 = 0.40
            conn.execute(
                """INSERT INTO strategy_decisions
                   (decision_id, decision_ts, observed_at_ts, decision_ts_iso,
                    strategy_name, strategy_version, model_version, config_version,
                    ticker, asset, close_ts, close_ts_iso, seconds_to_close,
                    settlement_reference, settlement_rule_version, selected_side,
                    decision, primary_reason_code, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    did, now, now, "2026-09-28T00:00:00+00:00",
                    "kalshi_crypto_15m_v2", "v1", "bachelier", "cfg",
                    f"KXBTC15M-{i}", "BTC", now + 900, "2026-09-28T00:15:00+00:00", 900.0,
                    "cfb_rti_live", "v1", "no",
                    "ENTER", "enter", now,
                ),
            )
            conn.execute(
                "INSERT INTO strategy_decision_side_ev (decision_id, side, executable_entry_price_cents) VALUES (?,?,?)",
                (did, "no", 55),
            )
            conn.execute(
                "INSERT INTO strategy_decision_outcomes (decision_id, settled_at, settled_yes, outcome_status) VALUES (?,?,?,?)",
                (did, now, 0 if won else 1, "SETTLED"),
            )
        # One ETH yes-side row that wins, to verify multi-asset aggregation.
        conn.execute(
            """INSERT INTO strategy_decisions
               (decision_id, decision_ts, observed_at_ts, decision_ts_iso,
                strategy_name, strategy_version, model_version, config_version,
                ticker, asset, close_ts, close_ts_iso, seconds_to_close,
                settlement_reference, settlement_rule_version, selected_side,
                decision, primary_reason_code, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "eth-yes-0", now, now, "2026-09-28T00:00:00+00:00",
                "kalshi_crypto_15m_v2", "v1", "bachelier", "cfg",
                "KXETH15M-0", "ETH", now + 900, "2026-09-28T00:15:00+00:00", 900.0,
                "cfb_rti_live", "v1", "yes",
                "ENTER", "enter", now,
            ),
        )
        conn.execute(
            "INSERT INTO strategy_decision_side_ev (decision_id, side, executable_entry_price_cents) VALUES (?,?,?)",
            ("eth-yes-0", "yes", 60),
        )
        conn.execute(
            "INSERT INTO strategy_decision_outcomes (decision_id, settled_at, settled_yes, outcome_status) VALUES (?,?,?,?)",
            ("eth-yes-0", now, 1, "SETTLED"),
        )


def test_ledger_refresh_writes_evidence_artifact(_isolate_evidence, tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "1")
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()
    _seed_audit_db(ledger)

    ledger._maybe_refresh_live_entry_evidence()

    out_path = Path(os.environ["MERID_LIVE_EVIDENCE_PATH"])
    data = json.loads(out_path.read_text())
    btc_no = data["assets"]["BTC"]["no"]
    assert btc_no["n"] == 40
    assert btc_no["wr"] == pytest.approx(0.40)
    assert btc_no["avg_entry_cents"] == pytest.approx(55.0)
    assert btc_no["buckets"]["50"] == {"n": 40, "wr": pytest.approx(0.40)}
    assert data["assets"]["ETH"]["yes"]["wr"] == pytest.approx(1.0)

    # The produced artifact feeds the gate: BTC/no at 55c avg is below floor.
    ok, det = _live_evidence_allows(data, "BTC", "no", 55, 0.01)
    assert ok is False and det["level"] == "asset"


def test_ledger_refresh_throttled(_isolate_evidence, tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_REFRESH_S", "3600")
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()
    _seed_audit_db(ledger)
    ledger._maybe_refresh_live_entry_evidence()
    path = Path(os.environ["MERID_LIVE_EVIDENCE_PATH"])
    assert path.exists()
    # Second call inside the throttle window is a no-op (mtime unchanged).
    mtime = path.stat().st_mtime_ns
    ledger._maybe_refresh_live_entry_evidence()
    assert path.stat().st_mtime_ns == mtime


def test_ledger_refresh_respects_export_flag(_isolate_evidence, tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "0")
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()
    _seed_audit_db(ledger)
    ledger._maybe_refresh_live_entry_evidence()
    assert not Path(os.environ["MERID_LIVE_EVIDENCE_PATH"]).exists()
