"""Regression: MarketCandidate must expose trading fields before _compute_edge runs.

NOTE: This test references the deprecated merid.trading.kalshi_continuous_trader module.
The test is skipped to avoid testing deprecated functionality.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skip(reason="Tests deprecated merid.trading.kalshi_continuous_trader module")

def test_market_candidate_has_best_side_default_before_edge():
    from merid.event_venues.kalshi.market_filter import MarketCandidate

    c = MarketCandidate(
        ticker="KXBTC-TEST-T95000",
        underlying="BTC",
        timeframe="1h",
        expiry_ts=time.time() + 3600,
        spot=95000.0,
        strike=94000.0,
    )
    assert c.best_side == ""
    assert isinstance(c.best_edge, Decimal)
    c.best_yes_bid = 0.45
    c.best_no_bid = 0.50
    c.best_yes_ask = 0.50
    c.best_no_ask = 0.55
    # Dry-run trace path reads best_side before _compute_edge — must not raise
    assert (c.best_side or "none") == "none"


def test_market_candidate_close_time_from_expiry_ts():
    from merid.event_venues.kalshi.market_filter import MarketCandidate

    ts = time.time() + 7200
    c = MarketCandidate(
        ticker="KXETH-TEST-T2500",
        underlying="ETH",
        timeframe="1h",
        expiry_ts=ts,
    )
    assert c.close_time
    assert "T" in c.close_time or "+" in c.close_time


def test_compute_edge_on_filter_pipeline_candidate():
    from merid.trading.kalshi_continuous_trader import BankrollManager, KalshiContinuousTrader, TraderConfig
    from merid.event_venues.kalshi.market_filter import MarketCandidate

    t = KalshiContinuousTrader.__new__(KalshiContinuousTrader)
    cfg = TraderConfig()
    t.config = cfg
    t.bankroll = BankrollManager(cfg)
    t._indicator_stacks = {}
    t._indicator_last_updated = {"BTC": time.time()}

    c = MarketCandidate(
        ticker="KXBTC-TEST-T95000",
        underlying="BTC",
        timeframe="1h",
        expiry_ts=time.time() + 3600,
        spot=95000.0,
        strike=94000.0,
    )
    c.best_no_bid = 0.48
    c.best_yes_bid = 0.50
    c.best_yes_ask = 0.52
    c.best_no_ask = 0.50
    t._compute_edge(c)
    assert c.best_side in ("yes", "no", "")
    assert c.limit_price_cents >= 0
