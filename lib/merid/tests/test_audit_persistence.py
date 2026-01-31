from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from db.audit_store import append_audit, list_audit, clear_store


def test_file_backend_persists(tmp_path: Path, monkeypatch):
    f = tmp_path / "audits.log"
    monkeypatch.setenv("MERID_AUDIT_FILE", str(f))

    # reload module to pick up env var and backend
    import importlib
    import db.audit_store as audit_store
    importlib.reload(audit_store)

    # start clean
    audit_store.clear_store()

    append_audit("alice", "test.persist", {"k": "v"})
    # reload again and verify entry still present
    importlib.reload(audit_store)
    entries = audit_store.list_audit()
    assert len(entries) == 1
    assert entries[0]["actor"] == "alice"
    # clear store and ensure file truncated
    audit_store.clear_store()
    importlib.reload(audit_store)
    assert audit_store.list_audit() == []
