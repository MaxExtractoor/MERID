import os
from fastapi.testclient import TestClient
from merid_web import app
from core.lockdown import set_lockdown, is_lockdown


def test_lockdown_endpoint_requires_auth(monkeypatch):
    client = TestClient(app)
    # without auth should be 401
    r = client.post("/admin/lockdown", json={"lock": True})
    assert r.status_code == 401


def test_lockdown_cycle(monkeypatch):
    client = TestClient(app)
    monkeypatch.setenv("MERID_ADMIN_TOKEN", "t1")
    headers = {"Authorization": "Bearer t1"}
    r = client.post("/admin/lockdown", json={"lock": True}, headers=headers)
    assert r.status_code == 204
    assert is_lockdown() is True
    r2 = client.get("/admin/lockdown")
    assert r2.json()["lockdown"] is True
    # clear
    r3 = client.post("/admin/lockdown", json={"lock": False}, headers=headers)
    assert r3.status_code == 204
    assert is_lockdown() is False
