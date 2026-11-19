"""Staleness-conditioned market-anchor precision (2026-11-19).

``_anchor_staleness_factor`` scales market authority down as quote age and
spread grow; ``shadow`` mode (default) must be behavior-inert — it records
indicators without touching ``market_anchor_weight``.
"""

import os

import pytest

from merid.prediction import trade_decision as td


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (
        "MERID_ANCHOR_STALENESS_MODE",
        "MERID_ANCHOR_STALENESS_HALFLIFE_MS",
        "MERID_ANCHOR_SPREAD_REF_C",
        "MERID_ANCHOR_STALENESS_FLOOR",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_fresh_tight_quote_gives_full_authority():
    assert td._anchor_staleness_factor(0, 2.0) == pytest.approx(1.0)
    assert td._anchor_staleness_factor(100, 4.0) == pytest.approx(1.0, abs=0.02)


def test_age_halves_weight_per_halflife():
    # default halflife 3000ms
    assert td._anchor_staleness_factor(3000, 0) == pytest.approx(0.5)
    assert td._anchor_staleness_factor(6000, 0) == pytest.approx(0.25)


def test_floor_binds_on_very_stale_quote():
    # 30s quote age: 0.5**10 ≈ 0.001 -> clipped to floor 0.25
    assert td._anchor_staleness_factor(30_000, 0) == pytest.approx(0.25)


def test_wide_spread_scales_linearly():
    # spread 8c vs ref 4c -> 0.5, age 0 -> factor 0.5
    assert td._anchor_staleness_factor(0, 8.0) == pytest.approx(0.5)
    # narrow spread never amplifies (capped at 1.0)
    assert td._anchor_staleness_factor(0, 1.0) == pytest.approx(1.0)


def test_composes_age_and_spread():
    # 3000ms (0.5) x spread 8c (0.5) = 0.25 = floor boundary
    assert td._anchor_staleness_factor(3000, 8.0) == pytest.approx(0.25)


def test_none_inputs_are_safe():
    assert td._anchor_staleness_factor(None, None) == pytest.approx(1.0)
    assert td._anchor_staleness_factor(None, 8.0) == pytest.approx(0.5)


def test_default_mode_is_shadow_and_inert(monkeypatch):
    assert td._anchor_staleness_mode() == "shadow"
    monkeypatch.setenv("MERID_ANCHOR_STALENESS_MODE", "live")
    assert td._anchor_staleness_mode() == "live"
    monkeypatch.setenv("MERID_ANCHOR_STALENESS_MODE", "garbage")
    assert td._anchor_staleness_mode() == "off"  # fail-closed
