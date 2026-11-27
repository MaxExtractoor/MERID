"""Regression coverage for the 2026-11-27 pf fade/book gates.

Postmortem KXDOGE15M-26NOV261915-15: a pinned_fav YES@93 maker entry filled
~12s after submit into a -0.2%/80s DOGE spot dump (emergency exit @5c,
-530c).  The Kalshi book lagged CF-RTI by seconds — the resting bid was
picked off mid-collapse.  The defense has three layers sharing
``directional_regime.pinned_fav_fade_return``:

* submit-time veto in ``order_router._pinned_fav_submit_gate_reason``
  (pf_fade shadow|enforce, pf_locked_book enforce, pf_decision_stale 30s)
* the same helper re-run inside ``_revalidate_entry_economics``
* a resting-order RTI fade cancel in ``resting_order_monitor``

These tests pin the helper's sign convention, fail-open behavior, and
each gate's enforce/shadow/off semantics.
"""
import os
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import directional_regime as dr
from merid.event_venues.kalshi import order_router as orr


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key, value in {
        "MERID_PINNED_FAV_FADE_VETO": "shadow",
        "MERID_PINNED_FAV_FADE_BP": "10",
        "MERID_PINNED_FAV_LOCKED_BOOK_VETO": "enforce",
        "MERID_PINNED_FAV_MAX_DECISION_AGE_S": "30",
        "MERID_RESTING_PF_FADE_MODE": "shadow",
        "MERID_RESTING_PF_FADE_BP": "10",
    }.items():
        monkeypatch.setenv(key, value)


def _intent(**kw):
    d = dict(
        ticker="KXDOGE15M-26NOV261915-15",
        side="BUY_YES",
        price_cents=93,
        snapshot_ts=time.time(),
        intent_id="test_intent",
        decision_lane="pinned_fav",
    )
    d.update(kw)
    return SimpleNamespace(**d)


# ---------------------------------------------------------------------------
# pinned_fav_fade_return — adverse-signed fast-leg RTI return
# ---------------------------------------------------------------------------

def test_fade_return_yes_held_spot_down_is_adverse(monkeypatch):
    import merid.data.cf_rti_adapter as ad
    monkeypatch.setattr(ad, "get_rti_return", lambda a, lb: -0.002 if lb == 10.0 else None)
    assert dr.pinned_fav_fade_return("DOGE", "BUY_YES") == pytest.approx(0.002)


def test_fade_return_no_held_spot_down_is_favorable(monkeypatch):
    import merid.data.cf_rti_adapter as ad
    monkeypatch.setattr(ad, "get_rti_return", lambda a, lb: -0.002 if lb == 10.0 else None)
    assert dr.pinned_fav_fade_return("DOGE", "BUY_NO") == pytest.approx(-0.002)


def test_fade_return_no_held_spot_up_is_adverse(monkeypatch):
    import merid.data.cf_rti_adapter as ad
    monkeypatch.setattr(ad, "get_rti_return", lambda a, lb: 0.003 if lb == 10.0 else None)
    assert dr.pinned_fav_fade_return("DOGE", "no") == pytest.approx(0.003)


def test_fade_return_falls_back_to_30s(monkeypatch):
    import merid.data.cf_rti_adapter as ad
    calls = []

    def _fake(asset, lb):
        calls.append(lb)
        return -0.0015 if lb == 30.0 else None

    monkeypatch.setattr(ad, "get_rti_return", _fake)
    assert dr.pinned_fav_fade_return("DOGE", "BUY_YES") == pytest.approx(0.0015)
    assert calls == [10.0, 30.0]


def test_fade_return_none_when_no_history(monkeypatch):
    import merid.data.cf_rti_adapter as ad
    monkeypatch.setattr(ad, "get_rti_return", lambda a, lb: None)
    assert dr.pinned_fav_fade_return("DOGE", "BUY_YES") is None


def test_fade_return_fail_open_on_adapter_error(monkeypatch):
    import merid.data.cf_rti_adapter as ad

    def _boom(asset, lb):
        raise RuntimeError("rti down")

    monkeypatch.setattr(ad, "get_rti_return", _boom)
    assert dr.pinned_fav_fade_return("DOGE", "BUY_YES") is None


# ---------------------------------------------------------------------------
# _pinned_fav_submit_gate_reason — the three submit gates
# ---------------------------------------------------------------------------

def test_locked_book_enforce_rejects():
    r = orr._pinned_fav_submit_gate_reason(
        _intent(), {"bid_cents": 93, "ask_cents": 93}
    )
    assert r is not None and r.startswith("pf_locked_book")


def test_crossed_book_enforce_rejects():
    r = orr._pinned_fav_submit_gate_reason(
        _intent(), {"bid_cents": 94, "ask_cents": 93}
    )
    assert r is not None and r.startswith("pf_locked_book")


def test_normal_book_passes():
    assert (
        orr._pinned_fav_submit_gate_reason(
            _intent(), {"bid_cents": 92, "ask_cents": 94}
        )
        is None
    )


def test_locked_book_off_mode_passes(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_LOCKED_BOOK_VETO", "off")
    assert (
        orr._pinned_fav_submit_gate_reason(
            _intent(), {"bid_cents": 93, "ask_cents": 93}
        )
        is None
    )


def test_locked_book_shadow_mode_passes(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_LOCKED_BOOK_VETO", "shadow")
    assert (
        orr._pinned_fav_submit_gate_reason(
            _intent(), {"bid_cents": 93, "ask_cents": 93}
        )
        is None
    )


def test_missing_book_fails_open():
    assert orr._pinned_fav_submit_gate_reason(_intent(), None) is None


def test_stale_decision_rejects():
    r = orr._pinned_fav_submit_gate_reason(
        _intent(snapshot_ts=time.time() - 45.0),
        {"bid_cents": 92, "ask_cents": 94},
    )
    assert r is not None and r.startswith("pf_decision_stale")


def test_fresh_decision_passes():
    assert (
        orr._pinned_fav_submit_gate_reason(
            _intent(snapshot_ts=time.time() - 5.0),
            {"bid_cents": 92, "ask_cents": 94},
        )
        is None
    )


def test_fade_shadow_logs_but_passes(monkeypatch):
    monkeypatch.setattr(dr, "pinned_fav_fade_return", lambda a, s: 0.0025)
    assert (
        orr._pinned_fav_submit_gate_reason(
            _intent(), {"bid_cents": 92, "ask_cents": 94}
        )
        is None
    )


def test_fade_enforce_rejects(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_FADE_VETO", "enforce")
    monkeypatch.setattr(dr, "pinned_fav_fade_return", lambda a, s: 0.0025)
    r = orr._pinned_fav_submit_gate_reason(
        _intent(), {"bid_cents": 92, "ask_cents": 94}
    )
    assert r is not None and r.startswith("pf_fade")


def test_fade_below_threshold_passes(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_FADE_VETO", "enforce")
    monkeypatch.setattr(dr, "pinned_fav_fade_return", lambda a, s: 0.0005)
    assert (
        orr._pinned_fav_submit_gate_reason(
            _intent(), {"bid_cents": 92, "ask_cents": 94}
        )
        is None
    )


def test_fade_favorable_move_passes(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_FADE_VETO", "enforce")
    # adverse-signed return negative = spot moving WITH the held side
    monkeypatch.setattr(dr, "pinned_fav_fade_return", lambda a, s: -0.005)
    assert (
        orr._pinned_fav_submit_gate_reason(
            _intent(), {"bid_cents": 92, "ask_cents": 94}
        )
        is None
    )


def test_gate_helper_is_lane_agnostic_but_callers_scope():
    """The helper itself does not check decision_lane — callers do.
    Verify a non-pf intent still evaluates (callers gate on lane)."""
    r = orr._pinned_fav_submit_gate_reason(
        _intent(decision_lane="settlement_convergence"),
        {"bid_cents": 93, "ask_cents": 93},
    )
    # locked-book gate fires on book state alone; lane scoping is the
    # caller's responsibility (documented in the helper docstring).
    assert r is not None and r.startswith("pf_locked_book")
