"""Regression tests for price-banded edge-bias cohorts.

2026-11-22 audit finding: the pooled ``ASSET|side|src`` edge-bias cohort
mixes favorite-band under-claims (FLB: px>=90 evals realized well above
their claim) with cheap-band over-claims, so its signed gap is not
transportable across the price axis.  Live measurement on the decision
spine: rebate-cap (``edge_bias_correction_c <= -3.9``) deduped evals
realized +9.5c at px90-101 but ~0c with 0.6% win rate at px0-10 — the
same -4c rebate was simultaneously correct and fabricated.

``MERID_EDGE_BIAS_PRICE_BANDS`` (default off) makes the lookup prefer
``ASSET|side|src|price_bucket`` / ``ASSET|side|*|price_bucket`` keys that
the evidence refresh now emits alongside the pooled keys, falling back
through banded-* -> pooled-src -> pooled-* by effective sample size.
"""
from __future__ import annotations

import pytest

from merid.prediction import evidence_policy as ep


def _rec(n_eff, gap_wsum, gap_sq=0.0, n_post=None, wsum_post=None, sq_post=None):
    return {
        "n_eff": float(n_eff),
        "gap_wsum": float(gap_wsum),
        "gap_sq_wsum": float(gap_sq),
        "n_eff_post": float(n_eff if n_post is None else n_post),
        "gap_wsum_post": float(gap_wsum if wsum_post is None else wsum_post),
        "gap_sq_wsum_post": float(gap_sq if sq_post is None else sq_post),
    }


def _evidence(by_source):
    return {"edge_bias": {"by_source": by_source}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("MERID_EVIDENCE_EPOCH_TS", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_CORRECTION", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_MIN_NEFF", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_PRIOR_K", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_CAP_CENTS", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_REBATE_CAP_CENTS", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_REBATE_Z", raising=False)
    monkeypatch.delenv("MERID_EDGE_BIAS_PRICE_BANDS", raising=False)


# Pooled DOGE|no|no_ask (side=no, ask basis): strong measured under-claim
# -> -4c rebate.  (wsum=-300 on n=30 -> mean -10c, zero variance.)
_POOLED_REBATE = _rec(30, -300.0, 3000.0)


class TestFlagOffLegacyPath:
    def test_banded_keys_ignored_when_flag_off(self):
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|01-09": _rec(30, 600.0),  # +20c over-claim band
        })
        # Even with a price supplied, flag off => pooled rebate exactly as
        # before the banded keys existed.
        c = ep.edge_bias_correction_cents(
            ev, "DOGE", "no", "ask", price_cents=5.0
        )
        assert c == -4.0

    def test_no_price_arg_still_legacy(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|90-100": _rec(30, 600.0),
        })
        # Flag on but caller passed no price -> pooled path, unchanged.
        assert ep.edge_bias_correction_cents(ev, "DOGE", "no", "ask") == -4.0


class TestBandedLookup:
    def test_band_overrides_pooled_rebate(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|01-09": _rec(30, 600.0),  # +20c mean over-claim
        })
        # Cheap-band eval: pooled would rebate -4c; the measured band
        # says this cohort OVER-claims -> charge instead.
        c = ep.edge_bias_correction_cents(
            ev, "DOGE", "no", "ask", price_cents=5.0
        )
        assert c > 0.0
        assert c == pytest.approx(min(8.0, 600.0 / 38.0))

    def test_pooled_fallback_when_band_absent(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|01-09": _rec(30, 600.0),
        })
        # Favorite-band eval: no 90-100 band keys -> pooled rebate survives
        # (the working favorite under-claim correction is preserved).
        c = ep.edge_bias_correction_cents(
            ev, "DOGE", "no", "ask", price_cents=95.0
        )
        assert c == -4.0

    def test_thin_band_falls_to_banded_star(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|01-09": _rec(3.0, 90.0),      # too thin alone
            "DOGE|no|*|01-09": _rec(20, 400.0),            # +20c, n_eff ok
        })
        c = ep.edge_bias_correction_cents(
            ev, "DOGE", "no", "ask", price_cents=5.0
        )
        # banded-src thin -> banded-* wins over pooled-src rebate.
        assert c > 0.0
        assert c == pytest.approx(min(8.0, 400.0 / 28.0))

    def test_all_bands_thin_falls_to_pooled_src(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|01-09": _rec(3.0, 90.0),
            "DOGE|no|*|01-09": _rec(5.0, 100.0),
        })
        c = ep.edge_bias_correction_cents(
            ev, "DOGE", "no", "ask", price_cents=5.0
        )
        assert c == -4.0  # pooled rebate is the status-quo fallback

    def test_bid_basis_band_key(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        ev = _evidence({
            "DOGE|no|yes_bid_complement": _POOLED_REBATE,
            "DOGE|no|yes_bid_complement|75-89": _rec(25, 500.0),
        })
        c = ep.edge_bias_correction_cents(
            ev, "DOGE", "no", "bid", price_cents=80.0
        )
        assert c > 0.0

    def test_epoch_uses_post_mass_for_bands(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        monkeypatch.setenv("MERID_EVIDENCE_EPOCH_TS", "1700000000")
        ev = _evidence({
            # Pre-epoch mass only on the band -> not eligible; pooled has
            # post mass -> pooled rebate applies.
            "DOGE|no|no_ask": _rec(30, -300.0),
            "DOGE|no|no_ask|01-09": _rec(
                30, 600.0, n_post=0.0, wsum_post=0.0
            ),
        })
        c = ep.edge_bias_correction_cents(
            ev, "DOGE", "no", "ask", price_cents=5.0
        )
        assert c == -4.0


class TestProvenance:
    def test_provenance_reports_banded_key(self, monkeypatch):
        monkeypatch.setenv("MERID_EDGE_BIAS_PRICE_BANDS", "1")
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|90-100": _rec(25, -500.0),
        })
        prov = ep.edge_bias_provenance(
            ev, "DOGE", "no", "ask", price_cents=96.0
        )
        assert prov["key"] == "DOGE|no|no_ask|90-100"
        assert prov["n_eff"] == pytest.approx(25.0)
        assert prov["correction_cents"] < 0.0

    def test_provenance_pooled_key_when_flag_off(self):
        ev = _evidence({
            "DOGE|no|no_ask": _POOLED_REBATE,
            "DOGE|no|no_ask|90-100": _rec(25, -500.0),
        })
        prov = ep.edge_bias_provenance(
            ev, "DOGE", "no", "ask", price_cents=96.0
        )
        assert prov["key"] == "DOGE|no|no_ask"
