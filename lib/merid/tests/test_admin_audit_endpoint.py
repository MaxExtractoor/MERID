from __future__ import annotations

from fastapi.testclient import TestClient
from merid_web import app
from db.audit_store import clear_store, list_audit


def test_audit_endpoints_require_auth(monkeypatch):
    client = TestClient(app)
    r = client.post("/admin/audit", json={"action": "x"})
    assert r.status_code == 401


def test_post_and_get_audit(monkeypatch):
    monkeypatch.setenv("MERID_ADMIN_TOKEN", "t123")
    client = TestClient(app)
    headers = {"Authorization": "Bearer t123"}
    clear_store()
    r = client.post("/admin/audit", json={"action": "lockdown.set", "details": {"lock": True}}, headers=headers)
    assert r.status_code == 201
    r2 = client.get("/admin/audit", headers=headers)
    assert r2.status_code == 200
    data = r2.json()
    assert isinstance(data, list)
    assert any(e["action"] == "lockdown.set" for e in data)
