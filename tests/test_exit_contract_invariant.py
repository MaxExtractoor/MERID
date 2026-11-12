"""2026-11-12 incident regression: positions reaching the monitor without
policy provenance (REST sync, external fills, startup cache loads) were
stored with ``exit_policy=None`` — every exit attempt then recorded
``policy_missing=true`` with an empty ``policy_snapshot``.

The upsert funnel now guarantees every monitored position carries an exit
contract: real provenance is preserved across equal-trust upserts, a
synthesized placeholder never displaces a real recorded policy, and any
remaining gap is filled by an honest synthesized contract describing the
exits actually armed (TP/SL fields, trailing state, settlement guard,
pre-expiry closeout).
"""

from decimal import Decimal

import pytest

from merid.position_management.position import (
    Position,
    PositionSide,
    TrailingType,
    ensure_exit_contract,
)
from merid.position_management.position_monitor import PositionMonitor


def _pos(**kw):
    base = dict(
        market_id="KXETH15M-27JAN011200-00",
        side=PositionSide.YES,
        size=Decimal("3"),
        avg_entry_price_cents=70,
    )
    base.update(kw)
    return Position(**base)


def _monitor(monkeypatch) -> PositionMonitor:
    mon = PositionMonitor(poll_interval=60)
    monkeypatch.setattr(mon, "_is_expired_market", lambda m: False)
    return mon


# ------------------------------------------------------- unit contract ----

def test_ensure_exit_contract_passthrough_real_policy():
    real = {"mode": "ACTIVE_MANAGEMENT", "version": 3, "take_profit_enabled": True}
    out, synth = ensure_exit_contract(real)
    assert out is real
    assert synth is False


def test_ensure_exit_contract_synthesizes_missing():
    for empty in (None, {}, "not-a-dict", 0):
        out, synth = ensure_exit_contract(empty)
        assert synth is True, empty
        assert isinstance(out, dict) and out
        assert out["synthesized"] is True
        assert out["provenance"] == "exit_contract_synthesized"
        assert out["reason"] == "missing_policy_provenance"
        assert out["settlement_guard_enabled"] is True
    # Mode reflects the exits actually armed.
    assert (
        ensure_exit_contract(None, take_profit_enabled=True, stop_loss_enabled=False)[0]["mode"]
        == "ACTIVE_MANAGEMENT"
    )
    assert (
        ensure_exit_contract(None, take_profit_enabled=False, stop_loss_enabled=False)[0]["mode"]
        == "PRE_SETTLEMENT_CLOSEOUT"
    )


# ---------------------------------------------------- monitor upsert ------

def test_upsert_attaches_contract_to_policyless_position(monkeypatch):
    mon = _monitor(monkeypatch)
    # Trusted provenance keeps the explicit SL armed; the synthesized
    # contract must report the exits actually in force.
    pos = _pos(
        exit_policy=None,
        take_profit_price_cents=90,
        stop_loss_price_cents=60,
        risk_params_state="original_persisted",
        risk_params_schema_version=2,
        entry_fill_id="fill_test_123",
    )
    mon.upsert_position(pos, caller="test")
    stored = mon._open_positions[pos.position_id]
    assert isinstance(stored.exit_policy, dict) and stored.exit_policy
    assert stored.exit_policy["synthesized"] is True
    assert stored.exit_policy["take_profit_enabled"] is True
    assert stored.exit_policy["stop_loss_enabled"] is True


def test_synthesized_contract_honestly_reports_unarmed_sl(monkeypatch):
    """Unknown-provenance positions legitimately carry no stop (the
    post-init quarantine disables invented stops).  The synthesized
    contract must say so — it describes reality, not aspiration."""
    mon = _monitor(monkeypatch)
    pos = _pos(exit_policy=None, take_profit_price_cents=90, stop_loss_price_cents=60)
    mon.upsert_position(pos, caller="test")
    stored = mon._open_positions[pos.position_id]
    assert stored.exit_policy["synthesized"] is True
    assert stored.exit_policy["stop_loss_enabled"] is False
    assert stored.exit_policy["settlement_guard_enabled"] is True


def test_upsert_preserves_real_policy(monkeypatch):
    mon = _monitor(monkeypatch)
    real = {"mode": "ACTIVE_MANAGEMENT", "version": 7, "take_profit_enabled": False}
    pos = _pos(exit_policy=real)
    mon.upsert_position(pos, caller="test")
    stored = mon._open_positions[pos.position_id]
    assert stored.exit_policy is real


def test_upsert_empty_dict_policy_is_treated_as_missing(monkeypatch):
    """REST-reconstructed positions arrive with exit_policy={} — that is a
    gap, not a policy, and must be synthesized like None."""
    mon = _monitor(monkeypatch)
    pos = _pos(exit_policy={})
    mon.upsert_position(pos, caller="rest_sync")
    stored = mon._open_positions[pos.position_id]
    assert stored.exit_policy["synthesized"] is True


def test_real_policy_survives_policyless_reupsert(monkeypatch):
    """A trusted record's real exit contract must not be displaced by a
    later policy-less (REST-style) upsert of the same position."""
    mon = _monitor(monkeypatch)
    real = {"mode": "ACTIVE_MANAGEMENT", "version": 9, "take_profit_enabled": True}
    first = _pos(exit_policy=real, risk_params_state="original_persisted", risk_params_schema_version=2, entry_fill_id="fill_test_123")
    mon.upsert_position(first, caller="live_fill")

    second = _pos(exit_policy=None, size=Decimal("3"))
    second.position_id = first.position_id
    mon.upsert_position(second, caller="rest_sync")

    stored = mon._open_positions[first.position_id]
    assert isinstance(stored.exit_policy, dict)
    assert stored.exit_policy.get("version") == 9
    assert not stored.exit_policy.get("synthesized")


def test_synthesized_placeholder_never_displaces_real_policy(monkeypatch):
    """If an incoming record carries only a synthesized placeholder while
    the stored record holds real provenance, the real policy wins."""
    mon = _monitor(monkeypatch)
    real = {"mode": "ACTIVE_MANAGEMENT", "version": 11, "take_profit_enabled": True}
    first = _pos(exit_policy=real, risk_params_state="original_persisted", risk_params_schema_version=2, entry_fill_id="fill_test_123")
    mon.upsert_position(first, caller="live_fill")

    placeholder = {
        "mode": "PRE_SETTLEMENT_CLOSEOUT",
        "version": 0,
        "synthesized": True,
        "provenance": "exit_contract_synthesized",
    }
    second = _pos(exit_policy=placeholder, size=Decimal("3"))
    second.position_id = first.position_id
    mon.upsert_position(second, caller="rest_sync")

    stored = mon._open_positions[first.position_id]
    assert stored.exit_policy.get("version") == 11
    assert not stored.exit_policy.get("synthesized")
