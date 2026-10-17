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
        seconds_to_expiry=400.0,
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
    # 2026-10-09 fail-closed change: a missing artifact returns an explicit
    # marker (never silent None) so admission can distinguish "no file" from
    # "file passed" -- the marker itself must not qualify anything.
    ev = _load_live_evidence()
    assert ev is not None and ev.get("artifact_missing") is True


def test_loader_reads_and_caches(_isolate_evidence):
    _write_evidence(_isolate_evidence, {"BTC": {"no": {"n": 40, "wr": 0.4, "avg_entry_cents": 55.0, "buckets": {}}}})
    first = _load_live_evidence()
    assert first["assets"]["BTC"]["no"]["n"] == 40
    # cached object returned on same mtime
    assert _load_live_evidence() is first


# ── compute_trade_decision integration ───────────────────────────────


def test_decision_blocked_by_decayed_asset_cohort(_isolate_evidence):
    """A decision that would select NO is rejected when the asset+side cohort
    decayed below its mean entry price — reason live_evidence_asset_no.

    TTE 900s keeps this outside the provisional lane's domain: inside it, a
    legacy evidence verdict is demoted to a label and the cbp cell's own
    caps/threshold own admission — that is the intended demotion, not a bug.
    """
    _write_evidence(_isolate_evidence, {
        "BTC": {"no": {"n": 40, "wr": 0.40, "avg_entry_cents": 55.0, "buckets": {}}}
    })
    d = _decision(seconds_to_expiry=900.0)
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
    # Legacy veto path: outside the provisional domain (>600s) the formula
    # lane owns the point and a decayed cell still hard-blocks.
    d = _decision(seconds_to_expiry=900.0)
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


def test_background_refresh_never_holds_ledger_lock(_isolate_evidence, tmp_path, monkeypatch):
    """2026-10-05: the settlement-thread refresh held ``ledger._lock`` through a
    10+ minute query on the production DB, parking every decision write behind
    it.  Background refresh must leave the lock free and be single-flight."""
    import threading as _th

    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "1")
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_REFRESH_S", "0")
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()

    started = _th.Event()
    release = _th.Event()
    calls = {"n": 0}

    def _slow_refresh(now, window_hours):
        calls["n"] += 1
        started.set()
        release.wait(5.0)

    monkeypatch.setattr(ledger, "_refresh_live_entry_evidence", _slow_refresh)
    ledger._maybe_refresh_live_entry_evidence(background=True)
    assert started.wait(2.0)
    try:
        assert ledger._lock.acquire(timeout=1.0), "refresh must not hold the ledger lock"
        ledger._lock.release()
        ledger._maybe_refresh_live_entry_evidence(background=True)
        assert calls["n"] == 1, "a second refresh must not start while one is in flight"
    finally:
        release.set()


# ── refresh robustness (2026-10-17) ──────────────────────────────────
#
# Production incident: an unbounded refresh query held a WAL read snapshot
# for ~4.5h on the 21GB audit DB — checkpointing starved, the WAL grew to
# 612MB, the writer fell ~14min behind, record_settlement starved, and the
# artifact aged past UNUSABLE so evidence-dependent entries failed closed.
# These tests pin the watchdog, backoff, backpressure, and durable status
# bookkeeping that prevent recurrence.


def test_refresh_query_deadline_aborts_and_records_failure(
    _isolate_evidence, tmp_path, monkeypatch
):
    """A refresh query that blows its deadline is aborted by the progress
    handler, recorded as a failure, and bumps the backoff strike counter —
    it must never hold a WAL snapshot for hours again."""
    import merid.execution.decision_audit_ledger as _dal
    from merid.prediction import evidence_health as _evh

    _evh._reset_for_tests()
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "1")
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_QUERY_TIMEOUT_S", "0")
    # Fire the handler on every VM instruction so the abort is deterministic
    # even on a tiny test DB whose queries finish in microseconds.
    monkeypatch.setattr(_dal, "_EVIDENCE_PROGRESS_STEPS", 1)
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()
    _seed_audit_db(ledger)

    ledger._refresh_live_entry_evidence(time.time(), 48.0)

    assert ledger._evidence_refresh_strikes == 1
    assert _evh.refresh_status()["failure_streak"] >= 1
    assert not _isolate_evidence.exists(), "timed-out refresh must not write an artifact"
    sidecar = _isolate_evidence.with_suffix(".refresh.json")
    status = json.loads(sidecar.read_text())
    assert status["ok"] is False
    assert status["event"] == "failure"
    assert "query" in status["error"]
    assert status["fail_streak"] == 1


def test_refresh_backoff_interval_after_failures(
    _isolate_evidence, tmp_path, monkeypatch
):
    """Consecutive failures double the retry interval (capped), so a sick
    disk is not re-scanned at the nominal cadence."""
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "1")
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_REFRESH_S", "120")
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_MAX_BACKOFF_S", "1800")
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()

    calls = {"n": 0}
    monkeypatch.setattr(
        ledger, "_refresh_live_entry_evidence", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
    )
    ledger._evidence_refresh_strikes = 3  # interval = 120 * 2^3 = 960s

    ledger._last_evidence_refresh = time.time() - 500  # inside backoff window
    ledger._maybe_refresh_live_entry_evidence()
    assert calls["n"] == 0

    ledger._last_evidence_refresh = time.time() - 1000  # past backoff window
    ledger._maybe_refresh_live_entry_evidence()
    assert calls["n"] == 1


def test_refresh_deferred_under_critical_writer_backlog(
    _isolate_evidence, tmp_path, monkeypatch
):
    """Do not start a minutes-long analytics scan while the writer queue is
    at critical depth — its WAL snapshot pins the frames the writer needs to
    checkpoint.  The trigger retries on the next cycle once the queue drains."""
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "1")
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_REFRESH_S", "0")
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_DEFER_QUEUE_DEPTH", "3")
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()

    calls = {"n": 0}
    monkeypatch.setattr(
        ledger, "_refresh_live_entry_evidence", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
    )

    ledger._writer_started = True
    for _ in range(3):
        ledger._write_queue.put_nowait((lambda: None, time.monotonic(), "low"))

    ledger._maybe_refresh_live_entry_evidence()
    assert calls["n"] == 0, "refresh must defer while writer queue is critical"

    for _ in range(3):
        ledger._write_queue.get_nowait()
    ledger._maybe_refresh_live_entry_evidence()
    assert calls["n"] == 1


def test_refresh_success_writes_sidecar_and_resets_strikes(
    _isolate_evidence, tmp_path, monkeypatch
):
    """A successful refresh clears the strike counter and leaves a durable
    status record next to the artifact."""
    from merid.prediction import evidence_health as _evh

    _evh._reset_for_tests()
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "1")
    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()
    _seed_audit_db(ledger)
    ledger._evidence_refresh_strikes = 2

    ledger._refresh_live_entry_evidence(time.time(), 48.0)

    assert _isolate_evidence.exists()
    assert ledger._evidence_refresh_strikes == 0
    status = json.loads(
        _isolate_evidence.with_suffix(".refresh.json").read_text()
    )
    assert status["ok"] is True
    assert status["event"] == "success"
    assert status["rows"] > 0
    assert status["duration_s"] >= 0
    assert status["fail_streak"] == 0


def test_evidence_health_seeds_refresh_status_from_sidecar(
    _isolate_evidence, tmp_path, monkeypatch
):
    """A restarted process still reports the previous process's last refresh
    result instead of 'no attempt observed'."""
    from merid.prediction import evidence_health as _evh

    success_ts = time.time() - 300
    _isolate_evidence.with_suffix(".refresh.json").write_text(json.dumps({
        "event": "success",
        "ok": True,
        "attempt_at": success_ts - 2.0,
        "finished_at": success_ts,
        "duration_s": 2.0,
    }))
    _evh._reset_for_tests()
    status = _evh.refresh_status()
    assert status["last_success_at"] == pytest.approx(success_ts)
    assert status["last_attempt_at"] == pytest.approx(success_ts - 2.0)
    assert status["failure_streak"] == 0

