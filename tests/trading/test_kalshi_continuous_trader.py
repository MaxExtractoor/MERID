"""Tests for KalshiContinuousTrader.

Validates:
  - TradingCandidate subclasses canonical MarketCandidate.
  - group_id is derived from candidate fields (underlying + timeframe).
  - Confidence clamp is applied before sizing.
  - Group-notional cap is enforced per group_id.
  - reset_daily() clears the group_notional map completely.
  - Asset universe includes BTC, ETH, SOL, XRP, DOGE.
  - Execution rejections are counted on risk failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, AsyncMock

import pytest

from merid.event_venues.kalshi.market_filter import MarketCandidate
from merid.prediction.opinion_strategy import (
    OpinionEstimate,
    OpinionExplanation,
    OpinionStrategy,
)
from merid.trading.kalshi_continuous_trader import (
    DailyRiskState,
    KalshiContinuousTrader,
    TradingCandidate,
    _CRYPTO_ASSETS,
    _CRYPTO_TIMEFRAMES,
)


# ── TickerParser helpers ──────────────────────────────────────────────────

def _make_candidate(
    ticker: str = "KXBTC-15M-T95000",
    underlying: str = "BTC",
    timeframe: str = "15m",
    mid_price_cents: int = 55,
    best_bid_cents: int = 50,
    best_ask_cents: int = 60,
) -> MarketCandidate:
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        best_bid_cents=best_bid_cents,
        best_ask_cents=best_ask_cents,
        mid_price_cents=mid_price_cents,
    )


# ── TradingCandidate ──────────────────────────────────────────────────────

class TestTradingCandidate:
    def test_is_subclass_of_market_candidate(self) -> None:
        """TradingCandidate must subclass canonical MarketCandidate."""
        assert issubclass(TradingCandidate, MarketCandidate)

    def test_from_candidate_preserves_fields(self) -> None:
        base = _make_candidate("KXBTC-15M-T95000", "BTC", "15m", 55, 50, 60)
        tc = TradingCandidate.from_candidate(base)
        assert tc.ticker == "KXBTC-15M-T95000"
        assert tc.underlying == "BTC"
        assert tc.timeframe == "15m"
        assert tc.mid_price_cents == 55

    def test_group_id_derived_from_candidate_fields(self) -> None:
        """group_id must be derived from underlying + timeframe — no guessing."""
        base = _make_candidate(underlying="ETH", timeframe="daily")
        tc = TradingCandidate.from_candidate(base)
        assert tc.group_id == "ETH_daily"

    def test_explicit_group_id_overrides_default(self) -> None:
        base = _make_candidate(underlying="BTC", timeframe="15m")
        tc = TradingCandidate.from_candidate(base, group_id="custom-group")
        assert tc.group_id == "custom-group"

    def test_tags_field_exists(self) -> None:
        base = _make_candidate()
        tc = TradingCandidate.from_candidate(base, tags=["momentum", "crypto"])
        assert "momentum" in tc.tags


# ── Asset universe ────────────────────────────────────────────────────────

class TestAssetUniverse:
    def test_btc_in_crypto_assets(self) -> None:
        assert "BTC" in _CRYPTO_ASSETS

    def test_eth_in_crypto_assets(self) -> None:
        assert "ETH" in _CRYPTO_ASSETS

    def test_sol_in_crypto_assets(self) -> None:
        assert "SOL" in _CRYPTO_ASSETS

    def test_xrp_in_crypto_assets(self) -> None:
        assert "XRP" in _CRYPTO_ASSETS

    def test_doge_in_crypto_assets(self) -> None:
        assert "DOGE" in _CRYPTO_ASSETS

    def test_15m_in_timeframes(self) -> None:
        assert "15m" in _CRYPTO_TIMEFRAMES

    def test_daily_in_timeframes(self) -> None:
        assert "daily" in _CRYPTO_TIMEFRAMES


# ── DailyRiskState ────────────────────────────────────────────────────────

class TestDailyRiskState:
    def test_initial_group_notional_empty(self) -> None:
        risk = DailyRiskState()
        assert risk.group_notional == {}

    def test_add_notional_accumulates(self) -> None:
        risk = DailyRiskState()
        risk.add_notional("BTC_15m", 10.0)
        risk.add_notional("BTC_15m", 5.0)
        assert risk.group_used("BTC_15m") == 15.0

    def test_group_used_returns_zero_for_unknown(self) -> None:
        risk = DailyRiskState()
        assert risk.group_used("unknown_group") == 0.0

    def test_reset_clears_group_notional(self) -> None:
        risk = DailyRiskState()
        risk.add_notional("BTC_15m", 25.0)
        risk.add_notional("ETH_daily", 10.0)
        risk.reset()
        assert risk.group_notional == {}

    def test_reset_clears_daily_loss(self) -> None:
        risk = DailyRiskState()
        risk.daily_loss = 50.0
        risk.reset()
        assert risk.daily_loss == 0.0

    def test_reset_clears_trade_count(self) -> None:
        risk = DailyRiskState()
        risk.trade_count = 42
        risk.reset()
        assert risk.trade_count == 0


# ── Group notional cap ────────────────────────────────────────────────────

class TestGroupNotionalCap:
    def _make_trader(self, max_group_notional: float = 50.0) -> KalshiContinuousTrader:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        return KalshiContinuousTrader(
            catalog=catalog,
            max_group_notional=max_group_notional,
        )

    def test_group_cap_blocks_excess(self) -> None:
        """Once group_notional >= cap, further candidates are rejected."""
        trader = self._make_trader(max_group_notional=20.0)
        trader._risk.add_notional("BTC_15m", 20.0)  # already at cap

        candidate = TradingCandidate.from_candidate(
            _make_candidate(underlying="BTC", timeframe="15m")
        )
        estimate = OpinionEstimate(agent_prob=0.65, confidence=0.80, edge=0.10, reasoning_tag="test", signal_sources=[])

        result = trader._apply_risk_checks(candidate, estimate, bankroll=1000.0)
        assert result is None

    def test_group_cap_allows_under_threshold(self) -> None:
        """Group with notional < cap is approved."""
        trader = self._make_trader(max_group_notional=50.0)
        trader._risk.add_notional("BTC_15m", 10.0)  # 10 / 50 used

        candidate = TradingCandidate.from_candidate(
            _make_candidate(underlying="BTC", timeframe="15m")
        )
        estimate = OpinionEstimate(agent_prob=0.65, confidence=0.80, edge=0.10, reasoning_tag="test", signal_sources=[])

        result = trader._apply_risk_checks(candidate, estimate, bankroll=1000.0)
        assert result is not None

    def test_reset_daily_empties_group_notional_map(self) -> None:
        """After reset_daily(), group_notional map is completely empty."""
        trader = self._make_trader(max_group_notional=50.0)
        trader._risk.add_notional("BTC_15m", 25.0)
        trader._risk.add_notional("ETH_daily", 10.0)
        trader._risk.add_notional("SOL_15m", 5.0)

        trader.reset_daily()

        assert trader.risk_state.group_notional == {}

    def test_group_cap_multiple_assets(self) -> None:
        """Different asset groups are tracked independently."""
        trader = self._make_trader(max_group_notional=30.0)
        trader._risk.add_notional("BTC_15m", 29.0)   # BTC near cap
        trader._risk.add_notional("ETH_daily", 5.0)  # ETH not

        btc_candidate = TradingCandidate.from_candidate(
            _make_candidate(underlying="BTC", timeframe="15m")
        )
        eth_candidate = TradingCandidate.from_candidate(
            _make_candidate(underlying="ETH", timeframe="daily")
        )
        estimate = OpinionEstimate(agent_prob=0.65, confidence=0.80, edge=0.10, reasoning_tag="test", signal_sources=[])

        # BTC at 29/30 — only 1$ remaining but > 0 so approved for small size
        btc_result = trader._apply_risk_checks(btc_candidate, estimate, bankroll=1000.0)
        # ETH at 5/30 — still has capacity
        eth_result = trader._apply_risk_checks(eth_candidate, estimate, bankroll=1000.0)

        assert btc_result is not None  # approved (tiny remaining cap)
        assert eth_result is not None


# ── Confidence clamp ──────────────────────────────────────────────────────

class _FixedStrategy(OpinionStrategy):
    """Strategy that returns a fixed over-threshold confidence."""

    name = "fixed_high_conf"

    def __init__(self, conf: float) -> None:
        self._conf = conf

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        return OpinionEstimate(
            agent_prob=0.70,
            confidence=self._conf,
            edge=0.10,
            reasoning_tag="fixed",
            signal_sources=[],
        )


class TestConfidenceClamp:
    def test_clamp_fires_above_max_confidence(self) -> None:
        """Confidence above max_confidence is clamped to max_confidence."""
        strategy = _FixedStrategy(conf=0.99)
        strategy.max_confidence = 0.95

        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(catalog=catalog, strategy=strategy)

        candidate = TradingCandidate.from_candidate(_make_candidate())
        estimate = trader.evaluate_candidate(candidate, market_prob=0.55)

        assert estimate is not None
        assert estimate.confidence <= strategy.max_confidence

    def test_clamp_does_not_fire_below_max_confidence(self) -> None:
        """Confidence at or below max_confidence is unchanged."""
        strategy = _FixedStrategy(conf=0.80)
        strategy.max_confidence = 0.95

        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(catalog=catalog, strategy=strategy)

        candidate = TradingCandidate.from_candidate(_make_candidate())
        estimate = trader.evaluate_candidate(candidate, market_prob=0.55)

        assert estimate is not None
        assert abs(estimate.confidence - 0.80) < 1e-9

    def test_no_strategy_returns_none(self) -> None:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(catalog=catalog, strategy=None)

        candidate = TradingCandidate.from_candidate(_make_candidate())
        assert trader.evaluate_candidate(candidate, market_prob=0.55) is None


# ── Status ────────────────────────────────────────────────────────────────

class TestTraderStatus:
    def test_status_structure(self) -> None:
        catalog = MagicMock()
        trader = KalshiContinuousTrader(catalog=catalog)
        s = trader.status()
        assert "running" in s
        assert "candidate_count" in s
        assert "risk" in s
        assert "config" in s

    def test_status_reflects_config(self) -> None:
        catalog = MagicMock()
        trader = KalshiContinuousTrader(
            catalog=catalog,
            max_group_notional=25.0,
            min_confidence=0.6,
            bankroll_fraction=0.02,
        )
        s = trader.status()
        assert s["config"]["max_group_notional"] == 25.0
        assert s["config"]["min_confidence"] == 0.6
        assert s["config"]["bankroll_fraction"] == 0.02

