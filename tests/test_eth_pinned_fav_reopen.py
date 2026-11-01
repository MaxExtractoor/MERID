"""ETH pinned-fav reopen validation (2026-10-31, cohort eth_pf_reopen_2026-10-31).

The audit-directed quarantine set ``MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_
{YES,NO}_ETH=0`` so every ETH in-band candidate vetoed as
``pinned_fav_moneyness_cap``.  The operator-directed reopen restores the
pre-quarantine resolution:

- ``NO_ETH`` back to 98 (the 2026-10-27 NO-side mirror group value).
- ``YES_ETH`` intentionally UNSET -> lane cap falls through to the
  per-asset ``..._YES_ETH`` (also unset) -> ``None`` -> no in-lane
  moneyness cap, identical to BTC/DOGE/SOL YES semantics.

These tests pin (a) the resolved-cap matrix for all assets x sides,
(b) ETH reaching downstream gates instead of dying at the quarantine
reason, and (c) that shared controls (band, EV floor, TTE, contract cap,
settlement-health gating) are untouched.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import directional_regime as dr

ASSETS = ("BTC", "ETH", "DOGE", "SOL", "XRP")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Pin the lane env explicitly; durable state isolated to tmp."""
    monkeypatch.setenv("MERID_PINNED_FAV_STATE_PATH", str(tmp_path / "pf.json"))
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_LO", "94")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_HI", "98")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_TTE_S", "90")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MAX_TTE_S", "840")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_P", "0.90")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_EV_CENTS", "-12.0")
    monkeypatch.setenv("MERID_PINNED_FAV_HONOR_MONEYNESS_CAPS", "1")
    # Post-reopen .env state: NO mirrors at 98 (incl. ETH), XRP probe 98/98,
    # YES side has no lane caps for any asset.
    for side in ("YES", "NO"):
        for asset in ASSETS:
            monkeypatch.delenv(
                f"MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_{side}_{asset}",
                raising=False,
            )
    for asset in ASSETS:
        monkeypatch.setenv(
            f"MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_NO_{asset}", "98"
        )
    monkeypatch.setenv("MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_YES_XRP", "98")
    # Per-asset normal-path caps that feed the fallback (production .env).
    monkeypatch.delenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_YES_ETH", raising=False)
    monkeypatch.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_ETH", "89")
    yield


def _cap(side: str, asset: str):
    return dr._moneyness_max_entry_price_cents(side, asset)


@pytest.mark.parametrize(
    "asset,expected",
    [("BTC", 98.0), ("ETH", 98.0), ("DOGE", 98.0), ("SOL", 98.0), ("XRP", 98.0)],
)
def test_no_side_lane_caps_resolve(asset, expected):
    assert _cap("no", asset) == expected


@pytest.mark.parametrize(
    "asset,expected",
    [("BTC", None), ("ETH", None), ("DOGE", None), ("SOL", None), ("XRP", 98.0)],
)
def test_yes_side_lane_caps_resolve(asset, expected):
    """ETH YES must resolve like BTC/DOGE/SOL YES: no lane cap (None).

    XRP keeps its operator-directed probe cap of 98.
    """
    assert _cap("yes", asset) == expected


def test_eth_inband_candidate_passes_moneyness_gate():
    """Synthetic in-band ETH YES candidate clears the moneyness stage —
    the gate no longer dies at pinned_fav_moneyness_cap."""
    blk = dr.pinned_fav_block(
        side_price_cents=96.0,
        net_ev_cents=1.5,
        tte_seconds=300.0,
        p_selected=0.95,
        held_side="yes",
        asset="ETH",
    )
    assert blk is None


def test_eth_inband_no_candidate_passes_moneyness_gate():
    blk = dr.pinned_fav_block(
        side_price_cents=96.0,
        net_ev_cents=1.5,
        tte_seconds=300.0,
        p_selected=0.95,
        held_side="no",
        asset="ETH",
    )
    assert blk is None


def test_eth_out_of_band_still_vetoed():
    for px in (93.9, 98.5):
        blk = dr.pinned_fav_block(
            side_price_cents=px,
            net_ev_cents=5.0,
            tte_seconds=300.0,
            p_selected=0.95,
            held_side="yes",
            asset="ETH",
        )
        assert blk == "pinned_fav_band"


def test_eth_negative_ev_still_vetoed():
    blk = dr.pinned_fav_block(
        side_price_cents=96.0,
        net_ev_cents=-20.0,
        tte_seconds=300.0,
        p_selected=0.95,
        held_side="yes",
        asset="ETH",
    )
    assert blk == "pinned_fav_low_ev"


def test_eth_low_p_still_vetoed():
    blk = dr.pinned_fav_block(
        side_price_cents=96.0,
        net_ev_cents=5.0,
        tte_seconds=300.0,
        p_selected=0.80,
        held_side="yes",
        asset="ETH",
    )
    assert blk == "pinned_fav_maker_low_p"


def test_eth_tte_out_of_window_still_vetoed():
    blk = dr.pinned_fav_block(
        side_price_cents=96.0,
        net_ev_cents=5.0,
        tte_seconds=30.0,
        p_selected=0.95,
        held_side="yes",
        asset="ETH",
    )
    assert blk == "pinned_fav_tte"


def test_quarantine_values_still_veto(monkeypatch):
    """The rollback path works: restoring 0/0 re-vetoes ETH in-band."""
    monkeypatch.setenv("MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_YES_ETH", "0")
    monkeypatch.setenv("MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_NO_ETH", "0")
    for side in ("yes", "no"):
        blk = dr.pinned_fav_block(
            side_price_cents=96.0,
            net_ev_cents=5.0,
            tte_seconds=300.0,
            p_selected=0.95,
            held_side=side,
            asset="ETH",
        )
        assert blk == "pinned_fav_moneyness_cap"


def test_other_assets_unaffected_by_eth_reopen():
    """BTC/DOGE/SOL/XRP resolution is independent of the ETH values."""
    assert _cap("no", "BTC") == 98.0
    assert _cap("yes", "BTC") is None
    assert _cap("no", "XRP") == 98.0
    assert _cap("yes", "XRP") == 98.0
    # Their in-band candidates still pass the moneyness stage.
    for asset, side in (("BTC", "yes"), ("DOGE", "no"), ("SOL", "yes")):
        blk = dr.pinned_fav_block(
            side_price_cents=96.0,
            net_ev_cents=1.5,
            tte_seconds=300.0,
            p_selected=0.95,
            held_side=side,
            asset=asset,
        )
        assert blk is None


def test_moneyness_control_itself_still_on():
    """The cap mechanism is not disabled — reopening removed the 0/0
    values, not the control.  A hypothetical cap still binds."""
    assert dr.pinned_fav_honor_moneyness_caps() is True
