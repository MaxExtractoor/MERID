"""Restart-safety of the decision-audit writer failure ledger (F0, 2026-11-01).

A restart must not masquerade as recovery: outstanding required-write failures
are derived from the append-only ledger (failures minus reconciled ids), and a
DEGRADED sentinel (failure-ledger write itself failed) forces unhealthy until
explicit reconciliation — never silently healthy.
"""
import json
import os
import queue
import sqlite3
import threading

import pytest

from merid.execution import decision_audit_ledger as dal


def _ledger(tmp_path, monkeypatch):
    """Minimal ledger bound to tmp_path; simulates a fresh process instance."""
    monkeypatch.setattr(dal, "_is_enabled", lambda: True)
    db = tmp_path / "audit.db"
    if not db.exists():
        con = sqlite3.connect(str(db))
        con.execute(
            "CREATE TABLE strategy_decisions (decision_id TEXT PRIMARY KEY, decision_ts REAL)"
        )
        con.commit()
        con.close()
    led = dal.DecisionAuditLedger.__new__(dal.DecisionAuditLedger)
    led.db_path = db
    led._lock = threading.Lock()
    led._write_queue = queue.Queue()
    # Not started: the alive-clause can't fire, so health depends purely on
    # the failure ledger — exactly what a restart must reconstruct.
    led._writer_started = False
    led._writer_thread = None
    led._inflight = None
    led._last_commit_mono = 0.0
    return led


def _failfile(led):
    return led.db_path.parent / "decision_audit_writer_failures.jsonl"


def _sentinel(led):
    return led.db_path.parent / "decision_audit_writer_failures.DEGRADED"


def _write_failures(led, ids):
    with open(_failfile(led), "a", encoding="utf-8") as fh:
        for fid in ids:
            fh.write(json.dumps({
                "kind": "failure", "failure_id": fid, "run_id": "run-x",
                "item_enqueued_mono": 1.0, "ts": 1.0,
                "priority": "normal", "error": "simulated",
            }) + "\n")


def test_failure_records_survive_restart(tmp_path, monkeypatch):
    led_a = _ledger(tmp_path, monkeypatch)
    _write_failures(led_a, ["f1"])
    # Restart: a fresh object with no in-memory state must reconstruct
    # outstanding failures from the ledger — not from process memory.
    led_b = _ledger(tmp_path, monkeypatch)
    h = led_b.writer_health()
    assert h["unhealthy"] is True
    assert h["failed_required_writes"] == 1


def test_reconcile_is_per_id_and_append_only(tmp_path, monkeypatch):
    led = _ledger(tmp_path, monkeypatch)
    _write_failures(led, ["f1", "f2"])
    led.acknowledge_failed_writes(["f1"], "recovered", note="r1")
    # f2 still outstanding — a count cannot select which failures resolved
    assert led.writer_health()["unhealthy"] is True
    led.acknowledge_failed_writes(["f2"], "accepted_loss", note="r2")
    assert led.writer_health()["unhealthy"] is False
    # Append-only: the original failure records remain on disk as evidence
    kinds = [json.loads(l)["kind"] for l in open(_failfile(led))]
    assert kinds.count("failure") == 2 and kinds.count("reconcile") == 2


def test_degraded_sentinel_blocks_until_explicit_reconcile(tmp_path, monkeypatch):
    led = _ledger(tmp_path, monkeypatch)
    _sentinel(led).write_text("1")
    h = led.writer_health()
    assert h["unhealthy"] is True
    assert h["failures_integrity_ok"] is False
    # Restart still sees the sentinel — persistence integrity unestablished
    led_b = _ledger(tmp_path, monkeypatch)
    assert led_b.writer_health()["unhealthy"] is True
    # Explicit reconciliation clears the sentinel and restores health
    led.acknowledge_failed_writes([], "accepted_loss", note="integrity reconciled")
    assert not _sentinel(led).exists()
    led_c = _ledger(tmp_path, monkeypatch)
    assert led_c.writer_health()["unhealthy"] is False


def test_unrelated_success_does_not_clear_failures(tmp_path, monkeypatch):
    led = _ledger(tmp_path, monkeypatch)
    _write_failures(led, ["f1"])
    # Any unrelated successful operation must not be recovery of the failure
    con = sqlite3.connect(str(led.db_path))
    con.execute("INSERT INTO strategy_decisions VALUES ('d1', 1.0)")
    con.commit()
    con.close()
    led_b = _ledger(tmp_path, monkeypatch)
    assert led_b.writer_health()["unhealthy"] is True


def test_reconcile_persist_failure_never_goes_silently_green(tmp_path, monkeypatch):
    """If the reconcile record cannot be persisted, the sentinel must survive
    (or be re-marked): removing it would let a restart read healthy with the
    evidence boundary erased."""
    led = _ledger(tmp_path, monkeypatch)
    _write_failures(led, ["f1"])
    # Squat a directory on the ledger filename -> append raises -> not recorded
    _failfile(led).unlink()
    os.mkdir(_failfile(led))
    led.acknowledge_failed_writes(["f1"], "recovered")
    assert _sentinel(led).exists()
    led_b = _ledger(tmp_path, monkeypatch)
    h = led_b.writer_health()
    assert h["unhealthy"] is True
    assert h["failures_integrity_ok"] is False


def test_sentinel_clear_records_evidence_boundary(tmp_path, monkeypatch):
    """Clearing DEGRADED must persist an explicit acknowledgment that the
    original failure record may never have been written — not merely delete
    the flag."""
    led = _ledger(tmp_path, monkeypatch)
    _sentinel(led).write_text("1")
    led.acknowledge_failed_writes([], "accepted_loss", note="postmortem")
    recs = [json.loads(l) for l in open(_failfile(led))]
    rec = [r for r in recs if r.get("kind") == "reconcile"][0]
    assert rec["evidence_boundary"] == "failure_record_unwritten"
    assert not _sentinel(led).exists()
    assert _ledger(tmp_path, monkeypatch).writer_health()["unhealthy"] is False


def test_sentinel_clear_leaves_unresolved_ids_blocking(tmp_path, monkeypatch):
    led = _ledger(tmp_path, monkeypatch)
    _write_failures(led, ["f1"])
    _sentinel(led).write_text("1")
    # Reconcile clears the integrity flag only; f1 remains outstanding.
    led.acknowledge_failed_writes([], "recovered")
    led_b = _ledger(tmp_path, monkeypatch)
    h = led_b.writer_health()
    assert h["unhealthy"] is True
    assert h["failed_required_writes"] == 1
