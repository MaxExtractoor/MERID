from __future__ import annotations

from db.audit_store import append_audit, list_audit, clear_store


def test_append_and_list_audit():
    clear_store()
    e = append_audit("admin", "test.action", {"k": "v"})
    assert e["id"] == 1
    assert e["action"] == "test.action"
    assert list_audit(10, 0)[0]["id"] == 1


def test_list_limit_offset():
    clear_store()
    for i in range(5):
        append_audit("a", f"act{i}", {})
    page = list_audit(limit=2, offset=1)
    assert len(page) == 2
    assert page[0]["action"] == "act1"
