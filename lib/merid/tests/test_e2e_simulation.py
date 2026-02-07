from __future__ import annotations

from simulations.e2e import E2ESimulation
from db.audit_store import clear_store


def test_e2e_places_orders_and_records_audits():
    clear_store()
    sim = E2ESimulation(steps=10, threshold=20.0, actor="e2e")
    res = sim.run()
    assert isinstance(res.get("orders"), list)
    assert len(res["orders"]) >= 1
    assert res["audit_count"] >= 1
    assert any(a["action"] == "order.place" for a in res["audits"]) or any(a["action"].startswith("order.place.failed") for a in res["audits"])


def test_e2e_respects_lockdown(monkeypatch):
    # set lockdown and ensure no order is placed
    monkeypatch.setenv("MERID_ADMIN_TOKEN", "t1")
    # toggle lockdown via API
    from core.lockdown import set_lockdown

    set_lockdown(True)
    sim = E2ESimulation(steps=10, threshold=1.0, actor="e2e")
    res = sim.run()
    # no orders should be accepted while lockdown active
    assert len(res["orders"]) == 0
    assert any(a["action"].startswith("order.place.failed") for a in res["audits"]) or res["audit_count"] >= 1
    set_lockdown(False)
