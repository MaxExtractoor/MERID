"""Warn-band stale-decision MODEL revalidation (2026-09-29).

Covers ``_revalidate_entry_economics``: when the intent carries immutable
``probability_inputs`` the router re-runs the Bachelier + market-anchor +
walkforward + tail-cap chain on a fresh RTI spot and fresh BBO, then gates on
the recomputed net EV.  Without inputs it falls back to price-only
revalidation, and a calibration-TTE-bucket crossing fails closed.

Heavy venue/data modules are stubbed via ``sys.modules`` injection so the
function's lazy ``from X import name`` resolves to fakes without triggering
live network initialization at import time.
"""

import asyncio
import os
import sys
import time
import types
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merid.prediction.trade_decision as _td_mod
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _revalidate_entry_economics,
)


def _ob(yes_bid, no_bid):
    lvl = lambda p: SimpleNamespace(price_cents=p)
    return SimpleNamespace(
        success=True,
        yes_levels=[lvl(yes_bid)],
        no_levels=[lvl(no_bid)],
        timestamp=time.time(),
    )


def _rti(value, eligible=True):
    return SimpleNamespace(
        execution_eligible=eligible,
        value=value,
        observed_ts_mono_ns=time.monotonic_ns(),
    )


def _pin(**kw):
    base = dict(
        model="bachelier_digital_anchor_wf_tailcap",
        asset="DOGE",
        side="no",
        spot_price_decision=100.0,
        strike_price=100.0,
        reference_price=100.0,
        seconds_to_expiry_decision=600.0,
        annualized_vol=0.5,
        p_yes_calibrated=0.45,
        p_no_calibrated=0.55,
        p_selected=0.55,
    )
    base.update(kw)
    return base


def _intent(**kw):
    base = dict(
        ticker="KXDOGE15M-T",
        price_cents=50,
        count=1,
        side="no",
        action="buy",
        execution_mode="maker",
        post_only=True,
        selected_outcome_price_cents=50,
        ev_net_cents=4.0,
        p_selected=0.55,
        min_required_edge=0.01,
        fee_cents=0.5,
        time_to_expiry_seconds=600.0,
        snapshot_ts=time.time() - 2.0,
        probability_inputs=_pin(),
    )
    base.update(kw)
    return OrderIntent(**base)


def _wire(monkeypatch, *, book, rti, spot=None):
    class _Port:
        async def get_orderbook(self, ticker):
            return book

    fake_port = types.ModuleType("merid.event_venues.kalshi.port")
    fake_port.get_kalshi_execution_port = lambda: _Port()
    monkeypatch.setitem(sys.modules, "merid.event_venues.kalshi.port", fake_port)

    fake_rti = types.ModuleType("merid.data.cf_rti_adapter")
    fake_rti.get_live_rti = lambda asset: rti
    fake_rti.get_rti_history = lambda *a, **k: []
    monkeypatch.setitem(sys.modules, "merid.data.cf_rti_adapter", fake_rti)

    fake_tc = types.ModuleType("merid.risk.probability.tail_calibrator")
    fake_tc.load_tail_calibrator = lambda: None
    monkeypatch.setitem(
        sys.modules, "merid.risk.probability.tail_calibrator", fake_tc
    )

    fake_uss = types.ModuleType("data.unified_spot_service")
    fake_uss.get_unified_spot_service = lambda: SimpleNamespace(
        get=lambda asset: spot
    )

    class _SpotError(Exception):
        pass

    fake_uss.SpotError = _SpotError
    monkeypatch.setitem(sys.modules, "data.unified_spot_service", fake_uss)

    # Neutralize the walkforward artifact -> identity calibration.
    monkeypatch.setattr(
        _td_mod, "_walkforward_calibrate_p_yes", lambda *a, **k: None
    )


def _run(intent):
    return asyncio.run(
        _revalidate_entry_economics(intent, mode=None, t0=time.monotonic())
    )


def test_model_revalidation_passes_and_rebinds(monkeypatch):
    # Spot sits at the strike with a NO-side book near 50c: fresh p_no stays
    # supportive, EV holds, economics are rebound.
    _wire(monkeypatch, book=_ob(yes_bid=48, no_bid=50), rti=_rti(99.9))
    intent = _intent()
    res = _run(intent)
    assert res is None
    assert intent._execution_revalidated is True
    assert intent.p_selected is not None
    assert intent.ev_net_cents is not None
    assert intent.p_hat_yes_cents is not None


def test_model_revalidation_rejects_when_spot_crushes_edge(monkeypatch):
    # Spot rips above the strike and the YES book agrees: fresh p_no
    # collapses, recomputed EV goes deeply negative -> model edge decay.
    _wire(monkeypatch, book=_ob(yes_bid=92, no_bid=6), rti=_rti(103.0))
    res = _run(_intent())
    assert res is not None and res.status == "rejected"
    assert "stale_decision_model_edge_decayed" in res.reason


def test_model_revalidation_buy_no_wire_format_side(monkeypatch):
    # 2026-10-09 regression: production intents carry Kalshi wire sides
    # ("BUY_NO"), but the model-revalidation branch compared
    # ``intent.side.lower() == "no"`` — never true for "buy_no" — so every
    # BUY_NO intent was scored with the freshly recomputed p_yes (the held
    # side's complement) and vetoed on phantom edge decay.  Same supportive
    # read as the canonical test must now pass and rebind the NO-side fields.
    _wire(monkeypatch, book=_ob(yes_bid=48, no_bid=50), rti=_rti(99.9))
    intent = _intent(side="BUY_NO")
    res = _run(intent)
    assert res is None
    assert intent._execution_revalidated is True
    # p_selected must remain a NO-side probability (supportive, >0.5):
    # pre-fix it rebinds to p_yes (<0.5) and the trade dies on inverted EV.
    assert intent.p_selected is not None and float(intent.p_selected) > 0.5


def test_model_revalidation_buy_no_rejects_on_real_decay(monkeypatch):
    # Wire-format BUY_NO still vetoes when the fresh spot actually crushes
    # the NO thesis — the fix normalizes the side, it does not weaken the gate.
    _wire(monkeypatch, book=_ob(yes_bid=92, no_bid=6), rti=_rti(103.0))
    res = _run(_intent(side="BUY_NO"))
    assert res is not None and res.status == "rejected"
    assert "stale_decision_model_edge_decayed" in res.reason


def test_model_revalidation_spot_stale_when_rti_ineligible(monkeypatch):
    _wire(
        monkeypatch,
        book=_ob(yes_bid=48, no_bid=50),
        rti=_rti(99.9, eligible=False),
    )
    res = _run(_intent())
    assert res is not None and "stale_decision_spot_stale" in res.reason


def test_model_revalidation_fails_closed_without_vol(monkeypatch):
    _wire(monkeypatch, book=_ob(yes_bid=48, no_bid=50), rti=_rti(99.9))
    res = _run(_intent(probability_inputs=_pin(annualized_vol=None)))
    assert res is not None and "stale_decision_volatility_stale" in res.reason


def test_partial_path_rejects_tte_regime_crossing(monkeypatch):
    # No probability_inputs: tte 610s decided 'early', ~350s elapsed -> 'late'
    # bucket.  Price-only revalidation cannot carry probability across a
    # calibration cell boundary -> fail closed.
    _wire(
        monkeypatch,
        book=_ob(yes_bid=48, no_bid=50),
        rti=None,
        spot=SimpleNamespace(timestamp=time.time()),
    )
    res = _run(
        _intent(
            probability_inputs=None,
            time_to_expiry_seconds=610.0,
            snapshot_ts=time.time() - 350.0,
        )
    )
    assert res is not None and "stale_decision_tte_regime_changed" in res.reason


def test_partial_path_price_decay_rejected(monkeypatch):
    # Price-only path with EV below the required edge -> price edge decay.
    _wire(
        monkeypatch,
        book=_ob(yes_bid=48, no_bid=50),
        rti=None,
        spot=SimpleNamespace(timestamp=time.time()),
    )
    res = _run(_intent(probability_inputs=None, ev_net_cents=0.2))
    assert res is not None
    assert "stale_decision_price_edge_decayed" in res.reason
