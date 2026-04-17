"""Kalshi Continuous Trader — edge pipeline and risk-profile wiring."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest


def test_ct_reference_price_falls_back_to_mid() -> None:
    from merid.trading.kalshi_continuous_trader import MarketCandidate, ct_reference_price_cents

    c = MarketCandidate(
        ticker="KXBTC15M-T",
        underlying="BTC",
        timeframe="15m",
        mid_price_cents=44,
        limit_price_cents=0,
    )
    assert ct_reference_price_cents(c) == 44


def test_get_tiered_min_edge_initial_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KALSHI_CT_PROFILE", "initial_live")
    from merid.event_venues.kalshi.market_filter import get_tiered_min_edge

    me = get_tiered_min_edge("BTC", "KXBTC15M-26JAN011200-00")
    assert me <= Decimal("0.02")
    monkeypatch.setenv("KALSHI_CT_PROFILE", "production")
    me_prod = get_tiered_min_edge("BTC", "KXBTC15M-26JAN011200-00")
    # Modern crypto_edge_production profile blends with threshold matrix
    # (directional_min_edge 0.011 for BTC/15m); above the modern floor (0.005).
    assert me_prod >= Decimal("0.005")


def test_compute_edge_directional_uses_mid_when_no_orderbook(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without orderbook, implied prob must track REST mid (not 0.5) or edge is mis-ranked."""
    monkeypatch.setenv("KALSHI_CT_PROFILE", "initial_live")
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, MarketCandidate

    t = KalshiContinuousTrader()
    t._indicator_last_updated["BTC"] = time.time()
    c = MarketCandidate(
        ticker="KXBTC15M-26JAN011200-00",
        underlying="BTC",
        timeframe="15m",
        mid_price_cents=35,
        is_directional=True,
        spot=95_000.0,
        strike=0.0,
    )
    out = t._compute_edge(c)
    assert out.best_side == "yes"
    assert out.best_edge is not None
    assert out.best_edge > Decimal("0.02")
    assert out.model_yes_prob is not None
    assert abs(float(out.model_yes_prob) - 0.5) < 0.01
    assert out.implied_yes_prob is not None
    assert abs(float(out.implied_yes_prob) - 0.35) < 0.001


def test_resolve_trader_min_edge_initial_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KALSHI_CT_PROFILE", "initial_live")
    monkeypatch.delenv("KALSHI_TRADER_MIN_EDGE", raising=False)
    from merid.trading.kalshi_continuous_trader import _resolve_trader_min_edge

    assert _resolve_trader_min_edge(False) == Decimal("0.012")


def test_synthetic_edge_passes_bankroll_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity: positive edge at cheap mid clears tiered + min_edge_for_price for initial_live."""
    monkeypatch.setenv("KALSHI_CT_PROFILE", "initial_live")
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader, MarketCandidate
    from merid.event_venues.kalshi.market_filter import get_tiered_min_edge
    from merid.trading.kalshi_continuous_trader import ct_reference_price_cents

    t = KalshiContinuousTrader()
    t._indicator_last_updated["BTC"] = time.time()
    c = MarketCandidate(
        ticker="KXBTC15M-26JAN011200-00",
        underlying="BTC",
        timeframe="15m",
        mid_price_cents=35,
        is_directional=True,
        spot=95_000.0,
        strike=0.0,
    )
    t._compute_edge(c)
    ref = ct_reference_price_cents(c)
    tiered = float(get_tiered_min_edge("BTC", c.ticker))
    dyn = float(t.bankroll.min_edge_for_price(ref))
    required = max(tiered, dyn)
    assert float(c.best_edge) >= required - 1e-9
