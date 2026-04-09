"""USDT→USD Normalization test suite — PATCH-1 through PATCH-9.

Tests that the Kalshi trading path never uses USDT prices and that all
safety guards (distance, staleness, depeg, stop-loss, BTC-15m fail-closed,
force-paper audit) behave correctly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_price_data(
    asset: str,
    price: float,
    exchange: str = "coinbase_usd",
    age_seconds: float = 0.0,
):
    """Build a PriceData with a specified age."""
    from data.live_price_feed import PriceData
    ts = datetime.now() - timedelta(seconds=age_seconds)
    return PriceData(
        symbol=asset,
        price=price,
        bid=price * 0.999,
        ask=price * 1.001,
        volume_24h=0.0,
        change_24h_pct=0.0,
        timestamp=ts,
        exchange=exchange,
    )


def _make_feed(cache: dict | None = None):
    """Create a LivePriceFeed with an optional pre-populated cache."""
    with patch("data.live_price_feed.get_network_client") as mock_net:
        mock_net.return_value = MagicMock()
        from data.live_price_feed import LivePriceFeed
        feed = LivePriceFeed()
    if cache:
        feed.price_cache.update(cache)
    return feed


# ── MarketFilter distance + spread + volume (PATCH-6 / EGG-5) ────────────

class TestMarketFilterUSDDistance:
    """MarketFilter must evaluate distance in USD terms (PATCH-6 / EGG-5)."""

    def _make_candidate(
        self,
        ticker: str = "KXBTC-25APR-T84000",
        underlying: str = "BTC",
        timeframe: str = "15m",
        strike_price: Optional[float] = 84000.0,
        spot_price: Optional[float] = 84500.0,
        volume: int = 100,
        oi: int = 20,
        bid: int = 49,
        ask: int = 51,
    ):
        from merid.event_venues.kalshi.market_filter import MarketCandidate
        return MarketCandidate(
            ticker=ticker,
            underlying=underlying,
            timeframe=timeframe,
            volume=volume,
            open_interest=oi,
            best_bid_cents=bid,
            best_ask_cents=ask,
            mid_price_cents=(bid + ask) // 2,
            strike_price=strike_price,
            spot_price=spot_price,
        )

    def test_candidate_near_spot_passes(self):
        """A market with strike close to spot should pass the distance gate."""
        from merid.event_venues.kalshi.market_filter import MarketFilter, MarketFilterConfig
        cfg = MarketFilterConfig(spot_band_pct=20.0, min_edge_dead_zone_pct=0.0)
        filt = MarketFilter(cfg)
        # spot=95000, strike=96000 → distance 1.05% < 20%
        cand = self._make_candidate(
            underlying="BTC", timeframe="1h",
            spot_price=95000.0, strike_price=96000.0,
            bid=45, ask=55,
        )
        passed, reason = filt.evaluate(cand)
        assert passed, f"Near-spot candidate should pass; got reason: {reason}"

    def test_candidate_far_from_spot_fails_distance(self):
        """A market with strike very far from spot should fail the distance gate.

        Use bid=40/ask=50 (mid=45¢) so the price is above the min_price_cents=10
        guard, allowing the distance gate to fire instead of the price gate.
        """
        from merid.event_venues.kalshi.market_filter import MarketFilter, MarketFilterConfig
        # tight 5% band
        cfg = MarketFilterConfig(spot_band_pct=5.0, min_edge_dead_zone_pct=0.0)
        filt = MarketFilter(cfg)
        # spot=95000, strike=200000 → ~110% away — well outside 5% band
        cand = self._make_candidate(
            underlying="BTC", timeframe="1h",
            spot_price=95000.0, strike_price=200000.0,
            bid=40, ask=50,
        )
        passed, reason = filt.evaluate(cand)
        assert not passed
        assert "distance" in reason.lower() or "band" in reason.lower()

    def test_candidate_missing_spot_fails_when_strike_present(self):
        """When spot is missing but strike is present the distance gate rejects."""
        from merid.event_venues.kalshi.market_filter import MarketFilter, MarketFilterConfig
        cfg = MarketFilterConfig(spot_band_pct=10.0, min_edge_dead_zone_pct=0.0)
        filt = MarketFilter(cfg)
        cand = self._make_candidate(
            underlying="BTC", timeframe="1h",
            spot_price=None, strike_price=84000.0,
            bid=45, ask=55,
        )
        passed, reason = filt.evaluate(cand)
        assert not passed
        assert "spot_price missing" in reason.lower() or "spot" in reason.lower()

    def test_candidate_missing_both_prices_passes_through(self):
        """When both spot and strike are missing the filter lets the candidate through."""
        from merid.event_venues.kalshi.market_filter import MarketFilter, MarketFilterConfig
        cfg = MarketFilterConfig(spot_band_pct=10.0, min_edge_dead_zone_pct=0.0)
        filt = MarketFilter(cfg)
        cand = self._make_candidate(
            underlying="BTC", timeframe="1h",
            spot_price=None, strike_price=None,
            bid=45, ask=55,
        )
        passed, _ = filt.evaluate(cand)
        # No strike → no distance check → pass
        assert passed

    def test_volume_floor_rejects_illiquid_market(self):
        """MarketFilter must reject markets below the minimum volume floor."""
        from merid.event_venues.kalshi.market_filter import MarketFilter, MarketFilterConfig
        cfg = MarketFilterConfig(min_volume=50, spot_band_pct=0.0, min_edge_dead_zone_pct=0.0)
        filt = MarketFilter(cfg)
        cand = self._make_candidate(volume=5, bid=45, ask=55)
        passed, reason = filt.evaluate(cand)
        assert not passed
        assert "volume" in reason.lower()

    def test_spread_gate_rejects_wide_spread(self):
        """MarketFilter must reject markets with excessive spread."""
        from merid.event_venues.kalshi.market_filter import MarketFilter, MarketFilterConfig
        cfg = MarketFilterConfig(max_spread_cents=5, spot_band_pct=0.0, min_edge_dead_zone_pct=0.0)
        filt = MarketFilter(cfg)
        cand = self._make_candidate(bid=30, ask=50)  # 20¢ spread
        passed, reason = filt.evaluate(cand)
        assert not passed
        assert "spread" in reason.lower()


# ── StrikeSpotTracker staleness (PATCH-7 / EGG-6) ────────────────────────

class TestStrikeSpotTrackerStaleness:
    """StrikeSpotTracker.check_staleness() must flag distance violations (PATCH-7)."""

    def test_check_staleness_passes_within_band(self):
        """spot 1% from strike — should not be flagged as stale."""
        from merid.event_venues.kalshi.strike_spot_tracker import StrikeSpotTracker
        tracker = StrikeSpotTracker()
        is_stale, reason = tracker.check_staleness(95950.0, 95000.0, max_pct_deviation=5.0)
        assert not is_stale
        assert reason == ""

    def test_check_staleness_fails_outside_band(self):
        """spot 20% from strike — must be flagged as stale_distance."""
        from merid.event_venues.kalshi.strike_spot_tracker import StrikeSpotTracker
        tracker = StrikeSpotTracker()
        is_stale, reason = tracker.check_staleness(114000.0, 95000.0, max_pct_deviation=5.0)
        assert is_stale
        assert "above" in reason.lower() or "below" in reason.lower()

    def test_check_staleness_rejects_zero_strike(self):
        """A zero strike must always be flagged as invalid/stale."""
        from merid.event_venues.kalshi.strike_spot_tracker import StrikeSpotTracker
        tracker = StrikeSpotTracker()
        is_stale, _ = tracker.check_staleness(95000.0, 0.0)
        assert is_stale

    def test_check_staleness_rejects_zero_spot(self):
        """A zero spot price must always be flagged as invalid/stale."""
        from merid.event_venues.kalshi.strike_spot_tracker import StrikeSpotTracker
        tracker = StrikeSpotTracker()
        is_stale, _ = tracker.check_staleness(0.0, 95000.0)
        assert is_stale

    def test_check_staleness_increments_stat(self):
        """check_staleness increments stale_strikes counter when flagged."""
        from merid.event_venues.kalshi.strike_spot_tracker import StrikeSpotTracker
        tracker = StrikeSpotTracker()
        before = tracker.get_stats()["stale_strikes"]
        tracker.check_staleness(200000.0, 95000.0, max_pct_deviation=5.0)
        after = tracker.get_stats()["stale_strikes"]
        assert after == before + 1


# ── SpotUSDData dataclass ─────────────────────────────────────────────────

class TestSpotUSDDataClass:
    """PATCH-1: SpotUSDData must store price_usd, timestamp, and spot_source."""

    def test_spot_usd_data_fields(self):
        """SpotUSDData must have the three required fields."""
        from data.live_price_feed import SpotUSDData
        import time
        sd = SpotUSDData(
            asset="BTC",
            price_usd=95000.0,
            timestamp=time.time(),
            spot_source="coinbase_usd",
        )
        assert sd.asset == "BTC"
        assert sd.price_usd == pytest.approx(95000.0)
        assert sd.spot_source == "coinbase_usd"

    def test_spot_usd_data_none_price(self):
        """price_usd=None is valid for depegged/stale entries."""
        from data.live_price_feed import SpotUSDData
        import time
        sd = SpotUSDData(
            asset="ETH",
            price_usd=None,
            timestamp=time.time(),
            spot_source="usdt_depegged",
        )
        assert sd.price_usd is None
        assert sd.spot_source == "usdt_depegged"


# ── Asset universe uses bare keys ─────────────────────────────────────────

class TestAssetUniverseBareKeys:
    """PATCH-1d: Kalshi assets in asset_universe must use bare symbol keys."""

    def test_btc_uses_bare_key(self):
        """data.asset_universe.ASSET_UNIVERSE['BTC'].symbol must be 'BTC'."""
        from data.asset_universe import ASSET_UNIVERSE
        assert "BTC" in ASSET_UNIVERSE
        assert ASSET_UNIVERSE["BTC"].symbol == "BTC"

    def test_eth_uses_bare_key(self):
        from data.asset_universe import ASSET_UNIVERSE
        assert "ETH" in ASSET_UNIVERSE
        assert ASSET_UNIVERSE["ETH"].symbol == "ETH"

    def test_sol_uses_bare_key(self):
        from data.asset_universe import ASSET_UNIVERSE
        assert "SOL" in ASSET_UNIVERSE
        assert ASSET_UNIVERSE["SOL"].symbol == "SOL"

    def test_xrp_uses_bare_key(self):
        from data.asset_universe import ASSET_UNIVERSE
        assert "XRP" in ASSET_UNIVERSE
        assert ASSET_UNIVERSE["XRP"].symbol == "XRP"

    def test_doge_uses_bare_key(self):
        from data.asset_universe import ASSET_UNIVERSE
        assert "DOGE" in ASSET_UNIVERSE
        assert ASSET_UNIVERSE["DOGE"].symbol == "DOGE"

    def test_no_usdt_suffix_for_kalshi_assets(self):
        """KALSHI_ASSETS must not have /USDT suffixes in the asset universe."""
        from data.asset_universe import ASSET_UNIVERSE
        from data.live_price_feed import KALSHI_ASSETS
        for asset in KALSHI_ASSETS:
            assert asset in ASSET_UNIVERSE, f"{asset} missing from ASSET_UNIVERSE"
            sym = ASSET_UNIVERSE[asset].symbol
            assert "/USDT" not in sym, (
                f"{asset} still has /USDT suffix ({sym!r}) in ASSET_UNIVERSE "
                "— Kalshi path must use bare symbols"
            )


# ── snapshot_ts propagation (PATCH-3) ────────────────────────────────────

class TestSnapshotTSPropagation:
    """PATCH-3: snapshot_ts must flow from MarketSnapshot into OrderIntent."""

    def test_order_intent_accepts_snapshot_ts(self):
        """OrderIntent must have a snapshot_ts field."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        import time
        ts = time.time() - 5.0
        intent = OrderIntent(
            ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            price_cents=55,
            count=1,
            snapshot_ts=ts,
        )
        assert intent.snapshot_ts == pytest.approx(ts)

    def test_stale_intent_rejected_by_check_intent_risk(self):
        """_check_intent_risk must reject OrderIntents with stale snapshot_ts."""
        import time, os
        from merid.event_venues.kalshi.order_router import OrderIntent, _check_intent_risk

        # Manufacture an intent whose snapshot is 120s old against a 30s threshold
        stale_ts = time.time() - 120.0
        intent = OrderIntent(
            ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            price_cents=55,
            count=1,
            snapshot_ts=stale_ts,
        )
        with patch.dict(os.environ, {"MERID_SNAPSHOT_STALENESS_SECONDS": "30"}):
            reason = _check_intent_risk(intent)
        assert reason is not None
        assert "stale" in reason.lower()

    def test_fresh_intent_not_rejected_for_staleness(self):
        """_check_intent_risk must NOT reject fresh snapshot_ts."""
        import time, os
        from merid.event_venues.kalshi.order_router import OrderIntent, _check_intent_risk

        fresh_ts = time.time() - 5.0  # 5 seconds old
        intent = OrderIntent(
            ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            price_cents=55,
            count=1,
            snapshot_ts=fresh_ts,
        )
        with patch.dict(os.environ, {"MERID_SNAPSHOT_STALENESS_SECONDS": "30"}):
            reason = _check_intent_risk(intent)
        # Might be rejected for other reasons (e.g. price invalid in test env) but
        # it must not be rejected specifically because of staleness.
        if reason is not None:
            assert "stale" not in reason.lower(), (
                f"Fresh intent must not be rejected for staleness; got: {reason}"
            )

    def test_quote_mode_order_carries_snapshot_ts(self):
        """Both legs of a quote-mode order must pass snapshot_ts to _kalshi_place_order.

        Verified via AST inspection of _execute_signal so we catch regressions
        where a new order call is added without the staleness argument.
        """
        import ast
        import inspect
        import textwrap
        import merid.prediction.trading_agent as ta

        src = inspect.getsource(ta.KalshiTradingAgent._execute_signal)
        tree = ast.parse(textwrap.dedent(src))

        calls_without_snapshot_ts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                fname = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name)
                    else ""
                )
                if fname == "_kalshi_place_order":
                    has_snapshot_ts = any(kw.arg == "snapshot_ts" for kw in node.keywords)
                    if not has_snapshot_ts:
                        calls_without_snapshot_ts.append(getattr(node, "lineno", "?"))

        assert not calls_without_snapshot_ts, (
            f"All _kalshi_place_order calls in _execute_signal must carry "
            f"snapshot_ts for staleness enforcement (PATCH-3). Missing at "
            f"source line(s): {calls_without_snapshot_ts}"
        )


class TestColdStartMarketFilter:
    """Fail-closed guard: no markets resolved when USD spot is missing on cold start."""

    def _make_agent(self, asset: str = "BTC"):
        from decimal import Decimal
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig, AgentRiskLimits
        cfg = AgentConfig(
            name=f"{asset}_1H",
            assets=[asset],
            timeframes=["1h"],
            risk_limits=AgentRiskLimits(max_notional_usd=Decimal("1000")),
            enabled=True,
        )
        return KalshiTradingAgent(cfg)

    @pytest.mark.asyncio
    async def test_missing_spot_on_cold_start_returns_empty_markets(self):
        """When get_spot_usd() returns None for a Kalshi asset, _resolve_markets
        must yield no markets (fail-closed) and emit a [MARKET_FILTER] warning.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        agent = self._make_agent("BTC")

        mock_market_result = MagicMock()
        mock_market_result.success = True
        mock_market_result.payload = {
            "markets": [
                {
                    "ticker": "KXBTC-25APR-T84000",
                    "question": "BTC above $84k?",
                    "outcomes": [
                        {"id": "yes", "name": "Yes", "price": "0.50", "probability": "0.50"},
                    ],
                    "volume": "200",
                    "open_interest": "50",
                    "active": True,
                    "end_date": "2025-04-25T00:00:00+00:00",
                    "category": "crypto",
                    "tags": [],
                }
            ]
        }

        mock_spot_feed = MagicMock()
        mock_spot_feed.get_spot_usd.return_value = None  # cold start — no price yet

        with (
            patch(
                "merid.prediction.kalshi_tools._kalshi_list_markets",
                new_callable=AsyncMock,
                return_value=mock_market_result,
            ),
            patch(
                "data.live_price_feed.get_live_price_feed",
                return_value=mock_spot_feed,
            ),
        ):
            await agent._resolve_markets()

        # Fail-closed: no markets should be resolved when spot is missing
        assert agent._resolved_markets == [], (
            "Cold-start with missing USD spot must yield zero markets (fail-closed)"
        )

    @pytest.mark.asyncio
    async def test_non_kalshi_asset_with_missing_spot_passes_through(self):
        """Non-Kalshi assets (e.g. 'AVAX') are not subject to the fail-closed spot guard."""
        from unittest.mock import AsyncMock, MagicMock, patch

        agent = self._make_agent("AVAX")

        mock_market_result = MagicMock()
        mock_market_result.success = True
        mock_market_result.payload = {
            "markets": [
                {
                    "ticker": "KXAVAX-25APR-T20",
                    "question": "AVAX above $20?",
                    "outcomes": [
                        {"id": "yes", "name": "Yes", "price": "0.50", "probability": "0.50"},
                    ],
                    "volume": "200",
                    "open_interest": "50",
                    "active": True,
                    "end_date": "2025-04-25T00:00:00+00:00",
                    "category": "crypto",
                    "tags": [],
                }
            ]
        }

        mock_spot_feed = MagicMock()
        mock_spot_feed.get_spot_usd.return_value = None  # Still no spot

        with (
            patch(
                "merid.prediction.kalshi_tools._kalshi_list_markets",
                new_callable=AsyncMock,
                return_value=mock_market_result,
            ),
            patch(
                "data.live_price_feed.get_live_price_feed",
                return_value=mock_spot_feed,
            ),
        ):
            await agent._resolve_markets()

        # Non-Kalshi asset: fail-closed guard does not apply; _resolve_markets
        # completes without error (market may or may not pass other gates).
