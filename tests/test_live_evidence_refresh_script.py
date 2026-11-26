"""Regression test for scripts/live_evidence_refresh.py (2026-11-26).

The script drives ``DecisionAuditLedger._refresh_live_entry_evidence`` in a
separate process.  It previously passed a ``SimpleNamespace`` fake; the
method gained writer-status/backoff dependencies
(``_write_evidence_refresh_status``, ``_wal_size_bytes``, ``_writer_started``,
``_evidence_refresh_strikes``) and the fake crashed with AttributeError
before touching the DB.  The script now constructs a real ledger —
``__init__`` only sets attributes, so no writer thread or DB connection
starts on this path — and this test locks that contract in.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from merid.execution.decision_audit_ledger import DecisionAuditLedger
from merid.prediction import evidence_health as _evh

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "live_evidence_refresh.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "live_evidence_refresh", _SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refresh_script_runs_against_real_ledger(tmp_path, monkeypatch):
    _evh._reset_for_tests()
    db = tmp_path / "audit.db"
    DecisionAuditLedger(db_path=db)._ensure_db()
    artifact = tmp_path / "live_entry_evidence.json"

    mod = _load_script()
    # main() assigns MERID_LIVE_EVIDENCE_PATH itself; delenv first so the
    # monkeypatch teardown restores whatever the ambient env had.
    monkeypatch.delenv("MERID_LIVE_EVIDENCE_PATH", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "live_evidence_refresh.py",
            "--db", str(db),
            "--path", str(artifact),
        ],
    )

    assert mod.main() == 0

    payload = json.loads(artifact.read_text())
    assert payload["version"] == 2
    status = json.loads(artifact.with_suffix(".refresh.json").read_text())
    assert status["event"] == "success"
    assert status["ok"] is True
