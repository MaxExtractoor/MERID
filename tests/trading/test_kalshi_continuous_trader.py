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
        return KalshiContinuousTrader(dry_run=True, catalog=catalog,
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
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=strategy)

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
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=strategy)

        candidate = TradingCandidate.from_candidate(_make_candidate())
        estimate = trader.evaluate_candidate(candidate, market_prob=0.55)

        assert estimate is not None
        assert abs(estimate.confidence - 0.80) < 1e-9

    def test_no_strategy_returns_none(self) -> None:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=None)

        candidate = TradingCandidate.from_candidate(_make_candidate())
        assert trader.evaluate_candidate(candidate, market_prob=0.55) is None


# ── Status ────────────────────────────────────────────────────────────────

class TestTraderStatus:
    def test_status_structure(self) -> None:
        catalog = MagicMock()
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)
        s = trader.status()
        assert "running" in s
        assert "candidate_count" in s
        assert "risk" in s
        assert "config" in s

    def test_status_reflects_config(self) -> None:
        catalog = MagicMock()
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog,
            max_group_notional=25.0,
            min_confidence=0.6,
            bankroll_fraction=0.02,
        )
        s = trader.status()
        assert s["config"]["max_group_notional"] == 25.0
        assert s["config"]["min_confidence"] == 0.6
        assert s["config"]["bankroll_fraction"] == 0.02

    def test_status_includes_max_yes_price(self) -> None:
        """status() must expose max_yes_price so operators can audit it."""
        catalog = MagicMock()
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, max_yes_price=0.40)
        s = trader.status()
        assert "max_yes_price" in s["config"]
        assert s["config"]["max_yes_price"] == 0.40

    def test_status_includes_filter_key(self) -> None:
        """status() must include a 'filter' key for volume-band telemetry."""
        catalog = MagicMock()
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)
        s = trader.status()
        assert "filter" in s

    def test_filter_empty_before_first_scan(self) -> None:
        """Before _refresh_candidates() runs, filter telemetry is an empty dict."""
        catalog = MagicMock()
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)
        assert trader.status()["filter"] == {}


# ── Filter telemetry ──────────────────────────────────────────────────────

def _make_catalog_with_volumes(volumes: List[int], asset: str = "BTC", timeframe: str = "15m"):
    """Return a mock catalog that yields one market per volume entry for a single (asset, timeframe)."""

    class FakeMarket:
        def __init__(self, vol: int) -> None:
            self.market_id = f"KXBTC-{vol}"
            self.volume = vol
            self.open_interest = 50

    class FakeCatalogMarket:
        def __init__(self, vol: int) -> None:
            self.market = FakeMarket(vol)
            self.expires_at = None
            self.category = ""
            self.strike_price = None

    _asset, _timeframe = asset, timeframe

    def _get(a: str, timeframe: str = "") -> list:
        if a == _asset and timeframe == _timeframe:
            return [FakeCatalogMarket(v) for v in volumes]
        return []

    catalog = MagicMock()
    catalog.get_markets_by_asset.side_effect = _get
    return catalog


class TestFilterTelemetry:
    """Validate that _refresh_candidates() surfaces volume-band metrics in status()."""

    def _run(self, trader):
        """Run _refresh_candidates() synchronously using a fresh event loop."""
        import asyncio
        asyncio.run(trader._refresh_candidates())

    def test_filter_key_populated_after_scan(self) -> None:
        """After a scan, status()['filter'] contains the telemetry keys."""
        catalog = _make_catalog_with_volumes([100, 500, 1000])
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)
        self._run(trader)
        f = trader.status()["filter"]
        assert "scan_total_input" in f
        assert "scan_rejected_volume_band" in f
        assert "volume_band_block_rate" in f
        assert "volume_band_block_rate_rolling_avg" in f
        assert "rolling_window_scans" in f

    def test_no_band_rejects_when_filter_disabled(self) -> None:
        """Default filter (band disabled: 0.0/1.0) → zero volume-band rejections."""
        catalog = _make_catalog_with_volumes([10, 500, 1000])
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)
        self._run(trader)
        f = trader.status()["filter"]
        assert f["scan_rejected_volume_band"] == 0
        assert f["volume_band_block_rate"] == 0.0

    def test_band_rejects_counted_in_scan_stats(self) -> None:
        """When volume_band_min=0.4 is active, out-of-band markets are counted."""
        from merid.event_venues.kalshi.market_filter import MarketFilterConfig

        catalog = _make_catalog_with_volumes(
            [10, 600, 1000],   # rel: 0.01, 0.6, 1.0 → only 0.6 is in [0.4, 0.8]
            asset="BTC", timeframe="15m",
        )
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)
        trader._filter_config = MarketFilterConfig(
            allowed_underlyings=["BTC"],
            allowed_timeframes=["15m"],
            volume_band_min=0.4,
            volume_band_max=0.8,
        )
        from merid.event_venues.kalshi.market_filter import MarketFilter
        trader._filter = MarketFilter(trader._filter_config)

        self._run(trader)
        f = trader.status()["filter"]
        assert f["scan_rejected_volume_band"] == 2      # outlier + spike
        assert f["volume_band_block_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_block_rate_rolling_avg_accumulates_over_scans(self) -> None:
        """volume_band_block_rate_rolling_avg is the mean over past N scans."""
        # Default band (disabled) → block rate always 0.0, so rolling_avg stays 0.0
        catalog = _make_catalog_with_volumes([100, 500, 1000])
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)

        for _ in range(3):
            self._run(trader)

        f = trader.status()["filter"]
        assert f["rolling_window_scans"] == 3
        assert f["volume_band_block_rate_rolling_avg"] == pytest.approx(0.0)

    def test_rolling_window_caps_at_maxlen(self) -> None:
        """Rolling history is capped at _VOLUME_BAND_RATE_HISTORY_MAXLEN entries."""
        from merid.trading.kalshi_continuous_trader import _VOLUME_BAND_RATE_HISTORY_MAXLEN

        catalog = _make_catalog_with_volumes([100, 500])
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)

        for _ in range(_VOLUME_BAND_RATE_HISTORY_MAXLEN + 5):
            self._run(trader)

        f = trader.status()["filter"]
        assert f["rolling_window_scans"] == _VOLUME_BAND_RATE_HISTORY_MAXLEN

    def test_empty_catalog_still_produces_filter_stats(self) -> None:
        """A scan over a completely empty catalog yields all-zero filter stats."""
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)

        self._run(trader)
        f = trader.status()["filter"]
        assert f["scan_total_input"] == 0
        assert f["scan_rejected_volume_band"] == 0
        assert f["volume_band_block_rate"] == 0.0
        assert f["volume_band_block_rate_rolling_avg"] == 0.0
        assert f["rolling_window_scans"] == 1


# ── Max YES price cap ─────────────────────────────────────────────────────

# NOTE: These tests drive async code via `await` in `async def` test methods.
# Do NOT revert to `asyncio.get_event_loop().run_until_complete()` — that
# pattern is broken when tests run after other async tests that close or
# swap the loop. pytest-asyncio (asyncio_mode=auto) manages the loop; just
# use `async def` and `await`.

class TestMaxYesPriceCap:
    """Unit tests for the max_yes_price cap in trade_cycle()."""

    def _make_trader(self, max_yes_price: float = 0.50) -> KalshiContinuousTrader:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        return KalshiContinuousTrader(dry_run=True, catalog=catalog, max_yes_price=max_yes_price)

    def _strategy_with_yes_signal(self, agent_prob: float = 0.75) -> _FixedStrategy:
        """Return a strategy that signals a YES trade (agent_prob > market prob)."""
        s = _FixedStrategy(conf=0.80)
        s._agent_prob = agent_prob
        return s

    async def test_yes_intent_below_cap_is_accepted(self) -> None:
        """YES intents whose ask price is at or below max_yes_price are included."""
        trader = self._make_trader(max_yes_price=0.50)
        strategy = _FixedStrategy(conf=0.80)
        trader._strategy = strategy

        # Candidate: mid=45¢, ask=48¢ — both below 50¢ cap
        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=45, best_ask_cents=48)
        )
        trader._candidates = [candidate]

        intents = await trader.trade_cycle(bankroll=1000.0)
        # agent_prob=0.70 > market_prob=0.45 → YES direction, ask=48¢ < 50¢ cap
        yes_intents = [i for i in intents if i["direction"] == "yes"]
        assert len(yes_intents) == 1

    async def test_yes_intent_above_cap_is_dropped(self) -> None:
        """YES intents whose ask price exceeds max_yes_price are dropped."""
        trader = self._make_trader(max_yes_price=0.40)
        strategy = _FixedStrategy(conf=0.80)
        trader._strategy = strategy

        # Candidate: ask=65¢ — above 40¢ cap
        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=60, best_ask_cents=65)
        )
        trader._candidates = [candidate]

        intents = await trader.trade_cycle(bankroll=1000.0)
        yes_intents = [i for i in intents if i["direction"] == "yes"]
        assert len(yes_intents) == 0

    async def test_yes_cap_rejection_increments_counter(self) -> None:
        """Dropping a YES intent above the cap increments execution_rejections."""
        trader = self._make_trader(max_yes_price=0.30)
        strategy = _FixedStrategy(conf=0.80)
        trader._strategy = strategy

        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=50, best_ask_cents=55)
        )
        trader._candidates = [candidate]

        await trader.trade_cycle(bankroll=1000.0)
        assert trader.risk_state.execution_rejections >= 1

    async def test_no_intent_not_affected_by_yes_cap(self) -> None:
        """NO direction intents are not dropped by the YES price cap."""
        trader = self._make_trader(max_yes_price=0.10)  # very tight cap
        # agent_prob < mid_prob → NO direction
        # Override: make strategy return agent_prob=0.20, market mid=0.50 → NO trade
        strategy = _FixedStrategy(conf=0.80)  # returns agent_prob=0.70 > 0.50 → YES
        # Use a mid_price_cents > agent_prob*100 to force NO direction
        # _FixedStrategy returns agent_prob=0.70; if market mid=0.80 → NO direction
        trader._strategy = strategy
        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=80, best_ask_cents=85)
        )
        trader._candidates = [candidate]

        intents = await trader.trade_cycle(bankroll=1000.0)
        no_intents = [i for i in intents if i["direction"] == "no"]
        assert len(no_intents) == 1

    async def test_yes_cap_uses_best_ask_when_available(self) -> None:
        """best_ask_cents is used (not mid_price_cents) for the YES price check."""
        # best_ask=55¢ > cap=50¢ → dropped even though mid=45¢ < cap
        trader = self._make_trader(max_yes_price=0.50)
        strategy = _FixedStrategy(conf=0.80)
        trader._strategy = strategy

        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=45, best_ask_cents=55)
        )
        trader._candidates = [candidate]

        intents = await trader.trade_cycle(bankroll=1000.0)
        yes_intents = [i for i in intents if i["direction"] == "yes"]
        assert len(yes_intents) == 0

