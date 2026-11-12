"""Capital sleeve + shadow fractional-Kelly telemetry tests.

Phase A instrumentation: the sleeve computes E_t = min(E_sleeve, E_backed)
from cached, freshness-bounded sources; shadow Kelly records what a 0.10
fractional-Kelly policy WOULD size without influencing order flow.
"""

import os
import sys
from decimal import Decimal
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.risk import capital_sleeve as cs
from merid.risk import scalp_return_model as srm


def test_sleeve_unavailable_when_nothing_known():
    with patch.object(cs, "_equity_total_usd", return_value=None), \
         patch.object(cs, "_shard_cash_usd", return_value=None), \
         patch.object(cs, "_open_exposure_usd", return_value=None):
        snap = cs.compute_capital_sleeve()
    assert snap.state == "unavailable"
    assert snap.effective_equity_usd is None


def test_sleeve_effective_is_min_of_sleeve_and_backed():
    with patch.object(cs, "_equity_total_usd", return_value=100.0), \
         patch.object(cs, "_shard_cash_usd", return_value=30.0), \
         patch.object(cs, "_open_exposure_usd", return_value=20.0):
        snap = cs.compute_capital_sleeve()
    # sleeve = 100 - 0 reserve = 100; backed = 30 + 20 = 50; E = min = 50
    assert snap.sleeve_equity_usd == pytest.approx(100.0)
    assert snap.backed_equity_usd == pytest.approx(50.0)
    assert snap.effective_equity_usd == pytest.approx(50.0)
    assert snap.state == "ok"


def test_sleeve_reserve_ring_fences_capital(monkeypatch):
    monkeypatch.setenv("MERID_STRATEGY_CAPITAL_RESERVE_USD", "25")
    with patch.object(cs, "_equity_total_usd", return_value=100.0), \
         patch.object(cs, "_shard_cash_usd", return_value=90.0), \
         patch.object(cs, "_open_exposure_usd", return_value=0.0):
        snap = cs.compute_capital_sleeve()
    # sleeve = 100 - 25 = 75; backed = 90; E = 75
    assert snap.sleeve_equity_usd == pytest.approx(75.0)
    assert snap.effective_equity_usd == pytest.approx(75.0)


def test_sleeve_partial_when_only_equity_known():
    with patch.object(cs, "_equity_total_usd", return_value=80.0), \
         patch.object(cs, "_shard_cash_usd", return_value=None), \
         patch.object(cs, "_open_exposure_usd", return_value=None):
        snap = cs.compute_capital_sleeve()
    assert snap.state == "partial"
    assert snap.effective_equity_usd == pytest.approx(80.0)


def test_return_model_registry_empty_by_default():
    srm.reset_for_tests()
    assert srm.get_active_return_model() is None


def test_shadow_kelly_metadata_provisional():
    """Shadow target uses settlement-proxy f* and the capital sleeve;
    labeled provisional until the empirical model is registered."""
    from merid.prediction.unified_sizing import _shadow_kelly_metadata

    fake_snap = cs.CapitalSleeveSnapshot(
        state="ok",
        sleeve_equity_usd=100.0,
        backed_equity_usd=100.0,
        effective_equity_usd=100.0,
        equity_total_usd=100.0,
        cash_trading_shard_usd=100.0,
        open_exposure_usd=0.0,
        non_strategy_reserve_usd=0.0,
    )
    # The helper imports compute_capital_sleeve lazily from the module, so
    # patching the module attribute intercepts the call.
    with patch("merid.risk.capital_sleeve.compute_capital_sleeve", return_value=fake_snap):
        meta = _shadow_kelly_metadata(
                model_prob=0.60,
                price_cents=50,
                fee_cents=1.75,
                existing_exposure_usd=Decimal("0"),
                available_exposure_usd=Decimal("6.00"),
                final_contracts=2.0,
            )
    assert meta is not None
    assert meta["state"] == "ok"
    assert meta["return_model"] == "settlement_proxy_provisional"
    assert meta["empirical_return_model"] == "unavailable"
    assert meta["fractional_kelly_multiplier"] == pytest.approx(0.10)
    # c_acq = (50 + 1.75)/100 = 0.5175; f* = (0.60-0.5175)/(1-0.5175) ≈ 0.1711
    assert meta["full_kelly_fraction"] == pytest.approx(0.1711, abs=1e-3)
    # target_capital = 0.10 * 0.1711 * 100 = $1.711; contracts = 1.711/0.5175 ≈ 3.31
    assert meta["kelly_target_contracts"] == pytest.approx(3.31, abs=0.02)
    assert meta["shadow_final_contracts"] <= meta["kelly_target_contracts"] + 1e-9


def test_shadow_kelly_unavailable_without_equity():
    from merid.prediction.unified_sizing import _shadow_kelly_metadata

    fake_snap = cs.CapitalSleeveSnapshot(
        state="unavailable",
        sleeve_equity_usd=None,
        backed_equity_usd=None,
        effective_equity_usd=None,
        equity_total_usd=None,
        cash_trading_shard_usd=None,
        open_exposure_usd=None,
        non_strategy_reserve_usd=0.0,
    )
    with patch("merid.risk.capital_sleeve.compute_capital_sleeve", return_value=fake_snap):
        meta = _shadow_kelly_metadata(
            model_prob=0.60,
            price_cents=50,
            fee_cents=1.75,
            existing_exposure_usd=Decimal("0"),
            available_exposure_usd=Decimal("6.00"),
            final_contracts=2.0,
        )
    assert meta["state"] == "unavailable"
    assert meta["reason"] == "equity_unavailable"


def test_shadow_kelly_disabled_by_env(monkeypatch):
    from merid.prediction.unified_sizing import _shadow_kelly_metadata
    monkeypatch.setenv("MERID_SHADOW_KELLY_SIZING", "0")
    assert _shadow_kelly_metadata(
        model_prob=0.6, price_cents=50, fee_cents=1.0,
        existing_exposure_usd=Decimal("0"),
        available_exposure_usd=Decimal("6"),
        final_contracts=1.0,
    ) is None


def test_shadow_kelly_incremental_subtracts_existing_exposure():
    """Held/working exposure reduces the incremental target, never adds."""
    from merid.prediction.unified_sizing import _shadow_kelly_metadata

    fake_snap = cs.CapitalSleeveSnapshot(
        state="ok",
        sleeve_equity_usd=100.0,
        backed_equity_usd=100.0,
        effective_equity_usd=100.0,
        equity_total_usd=100.0,
        cash_trading_shard_usd=100.0,
        open_exposure_usd=1.70,
        non_strategy_reserve_usd=0.0,
    )
    with patch("merid.risk.capital_sleeve.compute_capital_sleeve", return_value=fake_snap):
        meta = _shadow_kelly_metadata(
            model_prob=0.60,
            price_cents=50,
            fee_cents=1.75,
            existing_exposure_usd=Decimal("1.70"),
            available_exposure_usd=Decimal("4.30"),
            final_contracts=1.0,
        )
    # target_capital ≈ $1.711; incremental ≈ $0.011 -> ~0.02 contracts -> 0.02
    assert meta["incremental_capital_usd"] == pytest.approx(0.011, abs=0.01)
    assert meta["kelly_target_contracts"] <= 0.05
