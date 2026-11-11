"""Regression tests: WAL checkpoints must not run on the writer's shared conn.

Production incident (2026-11-10): ``wal_checkpoint`` is serviced as a queued
write item, so it executes on the writer thread — usually inside
``_run_queued_batch``'s open ``BEGIN IMMEDIATE`` on ``_shared_conn``.
``PRAGMA wal_checkpoint`` on a connection with an active transaction fails
instantly with ``SQLITE_LOCKED`` ("database table is locked"; busy_timeout
does not apply).  Every scheduled checkpoint failed for ~3h, the WAL grew
past 1GB, the writer fell behind, and ``audit_writer_unhealthy`` blocked all
entries.  The fix gives checkpoints a dedicated connection.
"""

import os
import sqlite3
from pathlib import Path

import pytest

from merid.execution.decision_audit_ledger import DecisionAuditLedger


@pytest.fixture
def tmp_db() -> Path:
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Path(path)


def _ledger(tmp_db: Path) -> DecisionAuditLedger:
    os.environ["MERID_DECISION_AUDIT_LEDGER_ENABLED"] = "1"
    ledger = DecisionAuditLedger(db_path=tmp_db)
    ledger._ensure_db()
    return ledger


def test_wal_checkpoint_uses_dedicated_connection_not_shared(tmp_db: Path) -> None:
    """wal_checkpoint must never touch ``_shared_conn``.

    With the old code path the pragma ran on the shared writer connection;
    inside a batch transaction that is SQLITE_LOCKED every time.
    """
    ledger = _ledger(tmp_db)
    shared_calls = []
    orig_conn = ledger._conn

    def _spy_conn(*args, **kwargs):
        shared_calls.append((args, kwargs))
        return orig_conn(*args, **kwargs)

    ledger._conn = _spy_conn  # type: ignore[assignment]
    try:
        deferred = ledger.wal_checkpoint("PASSIVE")
    finally:
        ledger._conn = orig_conn  # type: ignore[assignment]

    assert isinstance(deferred, bool)
    assert shared_calls == [], "wal_checkpoint must not use the shared writer conn"
    assert ledger._ckpt_conn_obj is not None, "dedicated checkpoint conn not opened"


def test_wal_checkpoint_succeeds_inside_open_write_transaction(tmp_db: Path) -> None:
    """Reproduces the production failure: an open BEGIN IMMEDIATE on the
    shared conn (the batch state checkpoints run inside) must not break the
    checkpoint — it runs on the dedicated conn instead."""
    ledger = _ledger(tmp_db)
    with ledger._lock:
        conn = ledger._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Old behavior: PRAGMA wal_checkpoint on this conn ->
            # sqlite3.OperationalError: database table is locked.
            deferred = ledger.wal_checkpoint("PASSIVE")
        finally:
            if conn.in_transaction:
                conn.rollback()
    assert isinstance(deferred, bool)
    assert ledger._ckpt_conn_obj is not None


def test_wal_checkpoint_inside_queued_batch_context(tmp_db: Path) -> None:
    """End-to-end: drive a real queued batch containing a checkpoint item.

    ``_run_queued_batch`` holds ``self._lock`` and an open transaction on
    ``_shared_conn`` while servicing items — the exact state in which the
    production failures occurred.
    """
    import time

    ledger = _ledger(tmp_db)

    def _noop() -> None:
        return None

    ledger._write_queue.put_nowait((_noop, time.monotonic(), "normal"))
    ledger._write_queue.put_nowait(
        (lambda: ledger.wal_checkpoint("PASSIVE"), time.monotonic(), "low")
    )
    items = [
        ledger._write_queue.get_nowait(),
        ledger._write_queue.get_nowait(),
    ]
    ledger._run_queued_batch(items)
    assert ledger._ckpt_conn_obj is not None


def test_wal_checkpoint_drops_poisoned_connection(tmp_db: Path) -> None:
    """A checkpoint conn that fails fatally (readonly/closed) is dropped so
    the next attempt reconnects — same recovery contract as _shared_conn."""
    ledger = _ledger(tmp_db)
    ledger.wal_checkpoint("PASSIVE")
    assert ledger._ckpt_conn_obj is not None

    class _BadConn:
        def execute(self, *args, **kwargs):
            raise sqlite3.OperationalError("attempt to write a readonly database")

    ledger._ckpt_conn_obj = _BadConn()  # type: ignore[assignment]
    deferred = ledger.wal_checkpoint("PASSIVE")
    assert deferred is True  # failure reported as deferred, not silent success
    assert ledger._ckpt_conn_obj is None, "poisoned checkpoint conn not dropped"

    # Next call recreates a healthy connection.
    deferred2 = ledger.wal_checkpoint("PASSIVE")
    assert isinstance(deferred2, bool)
    assert ledger._ckpt_conn_obj is not None


def test_wal_checkpoint_missing_db_returns_false(tmp_db: Path) -> None:
    ledger = DecisionAuditLedger(db_path=tmp_db / "does_not_exist.db")
    assert ledger.wal_checkpoint("PASSIVE") is False


def test_writer_conn_uses_configured_cache_size(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared writer conn must carry the raised page cache — the stock
    ~2MiB default forced every queued write to re-read index pages from the
    spindle on the multi-GB store (audit_write_exec_ms p95 ~1.7s/item)."""
    monkeypatch.setenv("MERID_AUDIT_WRITER_CACHE_KIB", "65536")
    ledger = _ledger(tmp_db)
    conn = ledger._conn()
    cache_kib = conn.execute("PRAGMA cache_size").fetchone()[0]
    # Negative value = KiB units.
    assert cache_kib == -65536
    temp_store = conn.execute("PRAGMA temp_store").fetchone()[0]
    assert temp_store == 2  # MEMORY


def test_writer_conn_cache_size_zero_keeps_default(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MERID_AUDIT_WRITER_CACHE_KIB=0 disables the override (SQLite default)."""
    monkeypatch.setenv("MERID_AUDIT_WRITER_CACHE_KIB", "0")
    ledger = _ledger(tmp_db)
    conn = ledger._conn()
    cache_kib = conn.execute("PRAGMA cache_size").fetchone()[0]
    assert cache_kib != -262144


def test_read_and_ckpt_conns_use_configured_cache_size(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MERID_AUDIT_READER_CACHE_KIB", "32768")
    monkeypatch.setenv("MERID_AUDIT_CKPT_CACHE_KIB", "16384")
    ledger = _ledger(tmp_db)
    ledger.wal_checkpoint("PASSIVE")  # opens the ckpt conn
    read_conn = ledger._read()
    assert read_conn.execute("PRAGMA cache_size").fetchone()[0] == -32768
    ckpt_conn = ledger._ckpt_conn()
    assert ckpt_conn.execute("PRAGMA cache_size").fetchone()[0] == -16384


def test_writer_conn_uses_configured_mmap_size(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mmap_size (bytes) lets the OS page cache serve cold reads on the
    multi-GB store instead of 4KiB pager I/O on the spindle."""
    monkeypatch.setenv("MERID_AUDIT_MMAP_BYTES", "1048576")
    ledger = _ledger(tmp_db)
    conn = ledger._conn()
    assert conn.execute("PRAGMA mmap_size").fetchone()[0] == 1048576


def test_read_and_ckpt_conns_use_configured_mmap_size(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MERID_AUDIT_MMAP_BYTES", "2097152")
    ledger = _ledger(tmp_db)
    ledger.wal_checkpoint("PASSIVE")  # opens the ckpt conn
    assert ledger._read().execute("PRAGMA mmap_size").fetchone()[0] == 2097152
    assert ledger._ckpt_conn().execute("PRAGMA mmap_size").fetchone()[0] == 2097152


def test_mmap_size_zero_keeps_default_disabled(
    tmp_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MERID_AUDIT_MMAP_BYTES=0 disables the override entirely."""
    monkeypatch.setenv("MERID_AUDIT_MMAP_BYTES", "0")
    ledger = _ledger(tmp_db)
    conn = ledger._conn()
    assert conn.execute("PRAGMA mmap_size").fetchone()[0] == 0
