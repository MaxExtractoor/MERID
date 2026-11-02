"""Bounded-maintenance tests for decision_audit_ledger.prune_old_rows.

Runs against a temp SQLite DB — never the live store.  Exercises:
  - yield-before-batch when ingestion queue is already hot
  - yield between batches when queue crosses threshold mid-sweep
  - cooperative deadline interrupt leaves committed batches intact and no
    partial deletes; progress handler cleared on every exit path
  - a normal write succeeds immediately after interruption
  - retention resumes and advances the backlog on the next invocation
"""
import os
import queue
import sqlite3
import threading
import time
from unittest.mock import MagicMock

import pytest

from merid.execution import decision_audit_ledger as dal


def _make_db(path, n=40, with_children=True):
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE strategy_decisions (decision_id TEXT PRIMARY KEY, decision_ts REAL, ticker TEXT)"
    )
    for t in ("strategy_decision_events", "strategy_decision_side_ev",
              "strategy_decision_outcomes", "strategy_decision_snapshots"):
        con.execute(f"CREATE TABLE {t} (decision_id TEXT, v INT)")
    con.execute(
        "CREATE TABLE decision_audit_heartbeats ("
        "cycle_id TEXT PRIMARY KEY, tick INTEGER, assets_evaluated INTEGER, "
        "decisions_expected INTEGER, decisions_persisted INTEGER, "
        "snapshots_persisted INTEGER, side_ev_expected INTEGER, "
        "side_ev_persisted INTEGER, ledger_write_latency_ms REAL, "
        "ledger_error_count INTEGER, created_at REAL)"
    )
    old = time.time() - 30 * 86400  # all expired under any 7d retention
    for i in range(n):
        did = f"d{i}"
        con.execute("INSERT INTO strategy_decisions VALUES (?,?,?)", (did, old, "T"))
        if with_children:
            for t in ("strategy_decision_events", "strategy_decision_side_ev",
                      "strategy_decision_outcomes", "strategy_decision_snapshots"):
                con.execute(f"INSERT INTO {t} VALUES (?,?)", (did, i))
    con.commit()
    return con


def _ledger(tmp_path, monkeypatch, n=40):
    monkeypatch.setattr(dal, "_is_enabled", lambda: True)
    db = tmp_path / "audit.db"
    _make_db(db, n=n)
    led = dal.DecisionAuditLedger.__new__(dal.DecisionAuditLedger)
    led.db_path = db
    led._lock = threading.Lock()
    led._write_queue = queue.Queue()
    led._shared_conn = None
    led._last_prune = 0.0
    con = sqlite3.connect(str(db), check_same_thread=False)
    con.execute("PRAGMA busy_timeout = 5000")
    led._conn = lambda *a, **k: con
    led._test_conn = con
    return led, con


def _depths(led):
    return (
        led._test_conn.execute("SELECT COUNT(*) FROM strategy_decisions").fetchone()[0],
        led._test_conn.execute("SELECT COUNT(*) FROM strategy_decision_events").fetchone()[0],
    )


def test_heartbeat_preserves_history_and_uses_passive_checkpoint(tmp_path, monkeypatch):
    led, con = _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("MERID_AUDIT_PRUNE_S", "1")
    monkeypatch.setattr(dal, "_WAL_CHECKPOINT_INTERVAL_S", 1)
    led._last_wal_checkpoint = 0.0
    led._ensure_db = MagicMock()
    led.prune_old_rows = MagicMock()
    led.wal_checkpoint = MagicMock(return_value=False)

    led.record_heartbeat(
        cycle_id="test", tick=1, assets_evaluated=1,
        decisions_expected=1, decisions_persisted=1,
        snapshots_persisted=0, side_ev_expected=0, side_ev_persisted=0,
        ledger_write_latency_ms=1, ledger_error_count=0,
    )

    assert con.execute("SELECT COUNT(*) FROM decision_audit_heartbeats").fetchone()[0] == 1
    assert _depths(led) == (40, 40)
    led.prune_old_rows.assert_not_called()
    led.wal_checkpoint.assert_called_once_with("PASSIVE")


def test_yield_before_first_batch(tmp_path, monkeypatch):
    led, _ = _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("MERID_AUDIT_PRUNE_YIELD_QUEUE_DEPTH", "0")  # any queued item => yield
    led._write_queue.put(lambda: None)
    assert led.prune_old_rows(batch=10, max_batches=3) == 0
    assert _depths(led) == (40, 40)


def test_yields_between_batches(tmp_path, monkeypatch):
    led, _ = _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("MERID_AUDIT_PRUNE_YIELD_QUEUE_DEPTH", "1")
    # Script ingestion pressure: calm for the first check (batch 1 may run),
    # hot thereafter -> the sweep must yield after exactly one committed
    # batch.  Deterministic: no mid-sweep enqueue timing is needed.
    checks = {"n": 0}

    def _qsize():
        checks["n"] += 1
        return 0 if checks["n"] <= 1 else 999

    monkeypatch.setattr(led._write_queue, "qsize", _qsize)
    assert led.prune_old_rows(batch=10, max_batches=10) == 10
    assert _depths(led) == (30, 30)
    # Pressure cleared by the next interval: the sweep resumes where it
    # stopped and drains the remaining backlog rather than revisiting.
    monkeypatch.setattr(led._write_queue, "qsize", lambda: 0)
    assert led.prune_old_rows(batch=10, max_batches=10) == 30
    assert _depths(led) == (0, 0)


def test_interrupt_preserves_commits_and_no_partial(tmp_path, monkeypatch):
    led, con = _ledger(tmp_path, monkeypatch)
    # Stride 1: the handler fires on the first VM opcode of any statement, so
    # an already-expired deadline interrupts deterministically.  (At larger
    # strides a small batch finishes before the first tick.)
    monkeypatch.setenv("MERID_AUDIT_PRUNE_PROGRESS_STRIDE", "1")
    monkeypatch.setenv("MERID_AUDIT_PRUNE_BATCH_BUDGET_S", "0")  # deadline already passed
    removed = led.prune_old_rows(batch=10, max_batches=5)
    assert removed == 0            # every batch interrupted before commit
    assert _depths(led) == (40, 40)  # nothing partially deleted
    # progress handler cleared: the shared conn must serve a normal statement
    con.execute("SELECT 1").fetchone()
    # a normal ingestion-style write succeeds immediately afterward
    con.execute("INSERT INTO strategy_decisions VALUES ('new1', ?, 'T')", (time.time(),))
    con.commit()
    assert _depths(led)[0] == 41


def test_deadline_allows_small_batch(tmp_path, monkeypatch):
    led, _ = _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("MERID_AUDIT_PRUNE_BATCH_BUDGET_S", "60")
    removed = led.prune_old_rows(batch=10, max_batches=2)
    assert removed == 20
    assert _depths(led) == (20, 20)


def test_backlog_advances_across_invocations(tmp_path, monkeypatch):
    led, _ = _ledger(tmp_path, monkeypatch)
    total = 0
    for _ in range(10):
        total += led.prune_old_rows(batch=10, max_batches=1)
        if led._test_conn.execute("SELECT COUNT(*) FROM strategy_decisions").fetchone()[0] == 0:
            break
    assert total == 40
    assert _depths(led) == (0, 0)


def test_committed_batch_survives_later_interrupt(tmp_path, monkeypatch):
    """Batch 1 commits, batch 2 is interrupted: batch 1's deletions persist,
    the interrupted batch leaves nothing partial."""
    led, _ = _ledger(tmp_path, monkeypatch)
    monkeypatch.setenv("MERID_AUDIT_PRUNE_BATCH_BUDGET_S", "60")
    assert led.prune_old_rows(batch=10, max_batches=1) == 10
    assert _depths(led) == (30, 30)
    monkeypatch.setenv("MERID_AUDIT_PRUNE_PROGRESS_STRIDE", "1")
    monkeypatch.setenv("MERID_AUDIT_PRUNE_BATCH_BUDGET_S", "0")
    assert led.prune_old_rows(batch=10, max_batches=5) == 0
    assert _depths(led) == (30, 30)  # committed work kept; no partial deletes


def test_consumer_survives_interrupted_maintenance(tmp_path, monkeypatch):
    """Drive the real queue consumer: a raising 'maintenance' item must not
    kill the writer thread, and the next queued write must commit."""
    led, con = _ledger(tmp_path, monkeypatch)
    led._writer_started = True
    led._writer_thread = None
    led._last_commit_mono = 0.0
    led._inflight = None

    t = threading.Thread(target=led._writer_main, daemon=True)
    t.start()
    led._write_queue.put((lambda: (_ for _ in ()).throw(RuntimeError("boom")),
                          time.monotonic(), "low"))
    led._write_queue.put((
        lambda: con.execute(
            "INSERT INTO strategy_decisions VALUES ('post', ?, 'T')", (time.time(),)
        ).connection.commit(),
        time.monotonic(), "normal"))
    # Queue.join() takes no timeout: poll unfinished tasks with a deadline.
    _deadline = time.monotonic() + 30
    while led._write_queue.unfinished_tasks and time.monotonic() < _deadline:
        time.sleep(0.01)
    assert led._write_queue.unfinished_tasks == 0
    assert t.is_alive()
    other = sqlite3.connect(str(led.db_path))
    assert other.execute(
        "SELECT COUNT(*) FROM strategy_decisions WHERE decision_id='post'"
    ).fetchone()[0] == 1
    other.close()
    h = led.writer_health()
    assert h["failed_required_writes"] == 0  # 'low' item is not required


def test_failed_required_write_and_inflight_health(tmp_path, monkeypatch):
    led, _ = _ledger(tmp_path, monkeypatch)
    led._writer_started = True
    led._writer_thread = threading.Thread(target=lambda: time.sleep(30), daemon=True)
    led._writer_thread.start()
    # empty queue + stale in-flight required item => unhealthy
    led._inflight = (time.monotonic(), time.monotonic() - 999, "normal")
    monkeypatch.setenv("MERID_AUDIT_WRITER_LAG_BUDGET_S", "120")
    assert led.writer_health()["unhealthy"] is True
    # failed required write persists as unhealthy even with empty queue
    led._inflight = None
    led._failed_required_writes = 1
    h = led.writer_health()
    assert h["unhealthy"] is True and h["failed_required_writes"] == 1
    # healthy idle writer: started, alive, empty queue, no failures
    led._failed_required_writes = 0
    led._last_commit_mono = time.monotonic()
    assert led.writer_health()["unhealthy"] is False
