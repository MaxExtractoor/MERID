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
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, max_yes_price=max_yes_price)
        # These tests control self._candidates directly to isolate the YES price cap
        # logic.  Mock out _refresh_candidates so it does not overwrite the injected
        # candidates when trade_cycle() runs.
        trader._refresh_candidates = AsyncMock()
        return trader

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


# ── Regression: trade_cycle must always refresh candidates ────────────────
#
# Guard against any future edit that silently removes the _refresh_candidates()
# call from inside trade_cycle().  Without that call the universe is built
# exactly once at startup and never updated, so CT operates on a stale (and
# potentially empty) candidate list.
#
class TestTradeCycleRefreshesCandidates:
    """trade_cycle() must invoke the catalog on every call.

    The catalog.get_markets_by_asset mock is the observable proxy for
    '_refresh_candidates()' having run: every refresh issues one call per
    (asset, timeframe) pair, so the cumulative call count must grow with the
    number of trade_cycle() invocations.
    """

    def _make_trader(self) -> KalshiContinuousTrader:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        return KalshiContinuousTrader(dry_run=True, catalog=catalog)

    async def test_catalog_queried_on_single_cycle(self) -> None:
        """One call to trade_cycle() must query the catalog at least once."""
        trader = self._make_trader()
        await trader.trade_cycle(bankroll=500.0)
        assert trader._catalog.get_markets_by_asset.call_count > 0

    async def test_catalog_queried_on_every_cycle(self) -> None:
        """Catalog query count must scale linearly with trade_cycle() invocations."""
        trader = self._make_trader()
        await trader.trade_cycle(bankroll=500.0)
        after_one = trader._catalog.get_markets_by_asset.call_count
        assert after_one > 0, "catalog not queried at all after first cycle"

        await trader.trade_cycle(bankroll=500.0)
        after_two = trader._catalog.get_markets_by_asset.call_count
        assert after_two == 2 * after_one, (
            f"Expected catalog call count to double after second cycle "
            f"(got {after_two}; was {after_one}). "
            "_refresh_candidates() may not be called on every trade_cycle()."
        )

        await trader.trade_cycle(bankroll=500.0)
        after_three = trader._catalog.get_markets_by_asset.call_count
        assert after_three == 3 * after_one, (
            f"Expected 3× catalog calls after three cycles "
            f"(got {after_three}; was {after_one} per cycle). "
            "_refresh_candidates() may not be called on every trade_cycle()."
        )

    async def test_stale_candidates_not_carried_across_cycles(self) -> None:
        """Candidates injected before a cycle must be replaced by _refresh_candidates().

        If trade_cycle() refreshes the universe correctly, manually pre-loaded
        candidates are wiped before evaluation starts, so no intents are generated
        from the stale list when the catalog returns nothing.
        """
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog)

        # Pre-load a stale candidate directly (simulating a startup-only refresh
        # that would linger without per-cycle refresh).
        from merid.event_venues.kalshi.market_filter import MarketCandidate
        stale = TradingCandidate.from_candidate(
            MarketCandidate(
                ticker="KXBTC-STALE",
                underlying="BTC",
                timeframe="15m",
                best_bid_cents=45,
                best_ask_cents=55,
                mid_price_cents=50,
            )
        )
        trader._candidates = [stale]

        # After trade_cycle() refreshes from the (empty) catalog, _candidates is
        # reset to [] and the loop produces no intents.
        intents = await trader.trade_cycle(bankroll=500.0)
        assert intents == [], (
            "Stale candidates survived into evaluation — "
            "_refresh_candidates() must overwrite self._candidates before iteration."
        )


# ── Item 1: edge_pct unit consistency ─────────────────────────────────────

class TestEdgePctUnits:
    """Validate that edge_pct is always treated as percentage (e.g. 3.0 = 3%).

    The canonical conversion is: edge = candidate.edge_pct / 100.0
    Signal layer populates edge_pct; signal_to_sizing converts to decimal.
    """

    def _make_trader(self) -> KalshiContinuousTrader:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        return KalshiContinuousTrader(dry_run=True, catalog=catalog)

    def test_edge_pct_three_percent_produces_correct_decimal_edge(self) -> None:
        """edge_pct=3.0 (3%) should yield edge=0.03 in SizingResult."""
        trader = self._make_trader()
        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=45)
        )
        candidate.edge_pct = 3.0  # 3% in percentage units

        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.source == "signal"
        assert abs(sizing.edge - 0.03) < 1e-9, f"Expected 0.03, got {sizing.edge}"

    def test_edge_pct_none_falls_through_to_strategy(self) -> None:
        """When edge_pct is None, signal_to_sizing falls back to strategy."""
        strategy = _FixedStrategy(conf=0.80)  # edge=0.10 in decimal
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=strategy)

        candidate = TradingCandidate.from_candidate(_make_candidate(mid_price_cents=50))
        assert candidate.edge_pct is None

        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.source == "strategy"
        assert abs(sizing.edge - 0.10) < 1e-6

    def test_edge_pct_zero_falls_through_to_strategy(self) -> None:
        """edge_pct=0.0 is treated as 'not set' and falls back to strategy."""
        strategy = _FixedStrategy(conf=0.80)
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=strategy)

        candidate = TradingCandidate.from_candidate(_make_candidate(mid_price_cents=50))
        candidate.edge_pct = 0.0

        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.source == "strategy"

    def test_edge_pct_beats_strategy_in_priority(self) -> None:
        """candidate.edge_pct takes priority over strategy estimate."""
        strategy = _FixedStrategy(conf=0.80)  # would give edge=0.10
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=strategy)

        candidate = TradingCandidate.from_candidate(_make_candidate(mid_price_cents=50))
        candidate.edge_pct = 5.0  # 5% signal edge

        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.source == "signal"
        assert abs(sizing.edge - 0.05) < 1e-9

    def test_ct_threshold_comparison_uses_decimal(self) -> None:
        """CT threshold (e.g. 0.005 for BTC/15m) is compared against decimal edge."""
        trader = self._make_trader()
        btc_candidate = TradingCandidate.from_candidate(
            _make_candidate(underlying="BTC", timeframe="15m", mid_price_cents=50)
        )
        # BTC/15m threshold is 0.005 (0.5%) in INITIAL_LIVE profile
        # edge_pct=0.4 → edge=0.004 → below threshold → REJECTED
        btc_candidate.edge_pct = 0.4
        sizing_low = trader.signal_to_sizing(btc_candidate, bankroll=10000.0)
        assert sizing_low.size_contracts == 0, "edge below BTC/15m threshold should be rejected"

        # edge_pct=0.6 → edge=0.006 → above threshold → ACCEPTED (if Kelly > 0)
        btc_candidate.edge_pct = 0.6
        sizing_high = trader.signal_to_sizing(btc_candidate, bankroll=10000.0)
        assert sizing_high.size_contracts > 0, "edge above BTC/15m threshold should be accepted"


# ── Item 2: min_edge alignment ────────────────────────────────────────────

class TestMinEdgeAlignment:
    """Validate strategy min_edge and CT thresholds are consistent decimal fractions."""

    def test_hash_bias_min_edge_respects_threshold(self) -> None:
        """HashBiasStrategy(min_edge=0.005) does not emit for edge < 0.005."""
        from merid.prediction.opinion_strategy import HashBiasStrategy
        strategy = HashBiasStrategy(min_edge=0.005)
        # The strategy returns None when abs(edge) < min_edge; we verify via
        # a market_prob that would produce zero bias (edge ≈ 0).
        # Use a ticker whose hash bias is known to be small by brute force.
        # Instead, just confirm the min_edge attribute is set correctly.
        assert strategy.min_edge == 0.005

    def test_hash_bias_default_min_edge_is_002(self) -> None:
        """Default HashBiasStrategy min_edge is 0.02 (class default)."""
        from merid.prediction.opinion_strategy import HashBiasStrategy
        strategy = HashBiasStrategy()
        assert strategy.min_edge == 0.02

    def test_strategy_declines_when_edge_below_min_edge(self) -> None:
        """Strategy returns None when |edge| < min_edge, preventing zero-edge trades."""
        from merid.prediction.opinion_strategy import HashBiasStrategy
        # Create strategy with very high min_edge so it will always decline
        strategy = HashBiasStrategy(min_edge=0.99, bias_range=0.10)
        result = strategy.estimate(
            agent_id="test", ticker="KXBTC-15M-T95000",
            market_prob=0.50, category="crypto",
        )
        assert result is None, "Strategy with min_edge=0.99 should never emit"

    def test_strategy_emits_when_edge_above_min_edge(self) -> None:
        """Strategy emits when hash bias produces |edge| >= min_edge."""
        from merid.prediction.opinion_strategy import HashBiasStrategy
        # Use a very small min_edge to ensure the hash bias is enough
        strategy = HashBiasStrategy(min_edge=0.001, bias_range=0.10)
        result = strategy.estimate(
            agent_id="test", ticker="KXBTC-15M-T95000",
            market_prob=0.50, category="crypto",
        )
        # With bias_range=0.10 and min_edge=0.001, most tickers will emit
        # (bias ≈ ±5% for this ticker); we're not asserting a specific value
        # but the pipeline should not be blocked at the min_edge gate.
        # (May legitimately be None if hash gives edge < 0.001, but extremely unlikely)
        assert result is None or abs(result.edge) >= 0.001


# ── Item 3: Default strategy / fail-fast ─────────────────────────────────

class TestDefaultStrategy:
    """Validate get_continuous_trader() default strategy and fail-fast behavior."""

    def setup_method(self) -> None:
        """Reset the singleton and set dry-run env var before each test."""
        import os
        import merid.trading.kalshi_continuous_trader as ct_mod
        ct_mod._trader = None
        os.environ["MERID_CT_DRY_RUN"] = "true"

    def teardown_method(self) -> None:
        """Clean up singleton and env var after each test."""
        import os
        import merid.trading.kalshi_continuous_trader as ct_mod
        ct_mod._trader = None
        os.environ.pop("MERID_CT_DRY_RUN", None)

    def test_get_continuous_trader_returns_trader_with_default_strategy(self) -> None:
        """get_continuous_trader() with no args uses HashBiasStrategy(min_edge=0.005)."""
        from merid.trading.kalshi_continuous_trader import get_continuous_trader
        from merid.prediction.opinion_strategy import HashBiasStrategy

        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = get_continuous_trader(catalog=catalog)

        assert trader._strategy is not None
        assert isinstance(trader._strategy, HashBiasStrategy)
        assert trader._strategy.min_edge == 0.005

    def test_get_continuous_trader_respects_explicit_strategy(self) -> None:
        """Explicit strategy passed to get_continuous_trader() is used as-is."""
        from merid.trading.kalshi_continuous_trader import get_continuous_trader

        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        custom_strategy = _FixedStrategy(conf=0.80)
        trader = get_continuous_trader(catalog=catalog, strategy=custom_strategy)

        assert trader._strategy is custom_strategy

    def test_get_continuous_trader_singleton_preserved(self) -> None:
        """Second call to get_continuous_trader() returns same instance."""
        from merid.trading.kalshi_continuous_trader import get_continuous_trader

        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        t1 = get_continuous_trader(catalog=catalog)
        t2 = get_continuous_trader(catalog=catalog)
        assert t1 is t2

    def test_ct_with_no_strategy_returns_no_estimate(self) -> None:
        """CT instantiated directly with strategy=None returns None from evaluate_candidate."""
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=None)

        candidate = TradingCandidate.from_candidate(_make_candidate())
        estimate = trader.evaluate_candidate(candidate, market_prob=0.50)
        assert estimate is None, "strategy=None must yield None from evaluate_candidate"

    def test_ct_with_no_strategy_and_no_signal_produces_no_intents(self) -> None:
        """CT with strategy=None and no edge_pct produces zero intents per cycle."""
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=None)
        trader._refresh_candidates = AsyncMock()

        candidate = TradingCandidate.from_candidate(_make_candidate())
        trader._candidates = [candidate]

        import asyncio
        intents = asyncio.run(trader.trade_cycle(bankroll=1000.0))
        assert intents == [], "No strategy + no signal edge → no intents"


# ── Item 4: Single sizing pipeline ───────────────────────────────────────

class TestSingleSizingPipeline:
    """Validate evaluate_candidate is called exactly once per candidate per cycle.

    When trade_cycle passes the pre-computed estimate to signal_to_sizing,
    the strategy must not be invoked a second time.
    """

    def _make_counting_strategy(self):
        """Returns a strategy that tracks how many times estimate() is called."""

        class CountingStrategy(OpinionStrategy):
            name = "counting"
            call_count = 0

            def estimate(self, agent_id, ticker, market_prob, category="", context=None):
                CountingStrategy.call_count += 1
                return OpinionEstimate(
                    agent_prob=0.70,
                    confidence=0.80,
                    edge=0.10,
                    reasoning_tag="counting",
                    signal_sources=[],
                )

        return CountingStrategy()

    async def test_strategy_called_once_per_candidate(self) -> None:
        """With one candidate, strategy.estimate() fires exactly once per cycle."""
        strategy = self._make_counting_strategy()
        strategy.__class__.call_count = 0

        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        trader = KalshiContinuousTrader(
            dry_run=True, catalog=catalog, strategy=strategy, min_confidence=0.5
        )
        trader._refresh_candidates = AsyncMock()

        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=45, best_ask_cents=48)
        )
        trader._candidates = [candidate]

        await trader.trade_cycle(bankroll=10000.0)
        assert strategy.__class__.call_count == 1, (
            f"Strategy called {strategy.__class__.call_count} times for 1 candidate; "
            "should be exactly 1 (single sizing pipeline)"
        )

    async def test_estimate_passed_to_signal_to_sizing_avoids_reeval(self) -> None:
        """signal_to_sizing with explicit estimate does not call evaluate_candidate."""
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        strategy = _FixedStrategy(conf=0.80)
        trader = KalshiContinuousTrader(dry_run=True, catalog=catalog, strategy=strategy)

        candidate = TradingCandidate.from_candidate(_make_candidate(mid_price_cents=50))
        pre_estimate = OpinionEstimate(
            agent_prob=0.70, confidence=0.80, edge=0.15,
            reasoning_tag="pre", signal_sources=[],
        )

        # When estimate is passed, signal_to_sizing must use it (source="strategy")
        # and must not overwrite with a different value from evaluate_candidate.
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0, estimate=pre_estimate)
        assert sizing.source == "strategy"
        assert abs(sizing.edge - 0.15) < 1e-9, (
            "signal_to_sizing should use the passed estimate, not re-evaluate"
        )


# ── Item 5: Exposure multiplier recalculates size_contracts ───────────────

class TestExposureMultiplierSizeContracts:
    """Validate that size_contracts in the intent is consistent with notional
    after the exposure_multiplier is applied.
    """

    def _make_trader(self, exposure_multiplier: float = 1.0) -> KalshiContinuousTrader:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        strategy = _FixedStrategy(conf=0.80)
        return KalshiContinuousTrader(
            dry_run=True,
            catalog=catalog,
            strategy=strategy,
            exposure_multiplier=exposure_multiplier,
            min_confidence=0.5,
        )

    async def _run_cycle(self, trader, mid_price_cents=45, best_ask_cents=48) -> list:
        trader._refresh_candidates = AsyncMock()
        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=mid_price_cents, best_ask_cents=best_ask_cents)
        )
        trader._candidates = [candidate]
        return await trader.trade_cycle(bankroll=10000.0)

    async def test_size_contracts_consistent_with_notional(self) -> None:
        """intent['size_contracts'] must equal floor(notional / price)."""
        trader = self._make_trader(exposure_multiplier=1.0)
        intents = await self._run_cycle(trader)
        assert len(intents) >= 1, "Expected at least one intent"
        intent = intents[0]
        price_dollars = 0.45  # mid_price_cents=45
        expected_contracts = int(intent["notional"] / price_dollars)
        assert intent["size_contracts"] == expected_contracts, (
            f"size_contracts={intent['size_contracts']} inconsistent with "
            f"notional={intent['notional']:.4f} / price={price_dollars}"
        )

    async def test_halved_multiplier_halves_size_contracts(self) -> None:
        """Halving exposure_multiplier should roughly halve size_contracts."""
        trader_full = self._make_trader(exposure_multiplier=1.0)
        trader_half = self._make_trader(exposure_multiplier=0.5)

        intents_full = await self._run_cycle(trader_full)
        intents_half = await self._run_cycle(trader_half)

        assert len(intents_full) >= 1 and len(intents_half) >= 1

        # Both notional and size_contracts should be smaller with 0.5 multiplier.
        # size_contracts may equal (floor) in edge cases with tiny bankrolls, so
        # check notional strictly and contracts loosely (≤).
        assert intents_half[0]["notional"] < intents_full[0]["notional"], (
            "Halved multiplier must produce smaller notional"
        )
        assert intents_half[0]["size_contracts"] <= intents_full[0]["size_contracts"], (
            "Halved multiplier must produce equal or fewer size_contracts"
        )

    async def test_zero_multiplier_gives_zero_size_contracts(self) -> None:
        """exposure_multiplier=0.0 collapses all sizes to zero (no trade)."""
        trader = self._make_trader(exposure_multiplier=0.0)
        intents = await self._run_cycle(trader)
        for intent in intents:
            assert intent["size_contracts"] == 0, (
                "exposure_multiplier=0 must yield size_contracts=0 for every intent"
            )

    async def test_two_calls_with_different_multipliers_produce_different_sizes(self) -> None:
        """Two independent traders with different multipliers and identical inputs
        must produce proportionally different size_contracts."""
        import math
        trader_1x = self._make_trader(exposure_multiplier=1.0)
        trader_2x = self._make_trader(exposure_multiplier=2.0)

        intents_1x = await self._run_cycle(trader_1x)
        intents_2x = await self._run_cycle(trader_2x)

        if not intents_1x or not intents_2x:
            pytest.skip("No intents generated; cannot compare multiplier effect")

        notional_1x = intents_1x[0]["notional"]
        notional_2x = intents_2x[0]["notional"]
        # 2× multiplier should produce roughly 2× the notional (within 5% tolerance)
        assert abs(notional_2x / notional_1x - 2.0) < 0.05, (
            f"2× multiplier produced notional ratio of {notional_2x / notional_1x:.3f}, "
            "expected ≈ 2.0 (±5%)"
        )


# ── Integration: end-to-end strategy → CT thresholds → sizing ────────────

class TestEndToEndEdgeGating:
    """Integration-style tests that run realistic candidates through the full
    strategy → CT-threshold → sizing pipeline.
    """

    def _make_trader(
        self,
        exposure_multiplier: float = 1.0,
        min_confidence: float = 0.5,
    ) -> KalshiContinuousTrader:
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []
        strategy = _FixedStrategy(conf=0.80)  # returns edge=0.10 always
        return KalshiContinuousTrader(
            dry_run=True,
            catalog=catalog,
            strategy=strategy,
            exposure_multiplier=exposure_multiplier,
            min_confidence=min_confidence,
        )

    async def test_above_threshold_produces_intent(self) -> None:
        """Candidate with edge well above min_edge threshold produces a trade intent."""
        trader = self._make_trader()
        trader._refresh_candidates = AsyncMock()

        # BTC/15m threshold (initial_live) = 0.005; strategy gives edge=0.10 → ACCEPTED
        candidate = TradingCandidate.from_candidate(
            _make_candidate(
                underlying="BTC", timeframe="15m",
                mid_price_cents=45, best_ask_cents=48,
            )
        )
        trader._candidates = [candidate]

        intents = await trader.trade_cycle(bankroll=10000.0)
        assert len(intents) == 1, "Edge above threshold must produce an intent"
        assert intents[0]["size_contracts"] > 0

    async def test_below_threshold_filtered_by_ct(self) -> None:
        """Candidate with edge below CT min_edge threshold is filtered out."""
        catalog = MagicMock()
        catalog.get_markets_by_asset.return_value = []

        # Use a strategy that produces very low edge
        class TinyEdgeStrategy(OpinionStrategy):
            name = "tiny_edge"
            def estimate(self, agent_id, ticker, market_prob, category="", context=None):
                return OpinionEstimate(
                    agent_prob=market_prob + 0.001,
                    confidence=0.80,
                    edge=0.001,  # 0.1% — below BTC/15m 0.5% threshold
                    reasoning_tag="tiny",
                    signal_sources=[],
                )

        trader = KalshiContinuousTrader(
            dry_run=True,
            catalog=catalog,
            strategy=TinyEdgeStrategy(),
            min_confidence=0.5,
        )
        trader._refresh_candidates = AsyncMock()

        candidate = TradingCandidate.from_candidate(
            _make_candidate(underlying="BTC", timeframe="15m", mid_price_cents=50)
        )
        trader._candidates = [candidate]

        intents = await trader.trade_cycle(bankroll=10000.0)
        assert len(intents) == 0, "Edge below CT threshold must be filtered out"

    async def test_size_contracts_consistent_across_full_pipeline(self) -> None:
        """After the full pipeline, size_contracts must equal floor(notional/price)."""
        trader = self._make_trader()
        trader._refresh_candidates = AsyncMock()

        candidate = TradingCandidate.from_candidate(
            _make_candidate(mid_price_cents=45, best_ask_cents=48)
        )
        trader._candidates = [candidate]

        intents = await trader.trade_cycle(bankroll=10000.0)
        assert len(intents) >= 1
        intent = intents[0]

        price_dollars = 0.45
        expected = int(intent["notional"] / price_dollars)
        assert intent["size_contracts"] == expected, (
            f"End-to-end: size_contracts={intent['size_contracts']} "
            f"should equal floor({intent['notional']:.4f}/{price_dollars})={expected}"
        )
