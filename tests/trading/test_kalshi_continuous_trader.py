"""Tests for Kalshi Continuous Trader filter pipeline."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from merid.trading.kalshi_continuous_trader import (
    TickerParser,
    DistanceCalculator,
    FilterPipeline,
    FilterPipelineConfig,
    AssetVolatilityConfig,
    MarketCandidate,
)


class TestTickerParser:
    """Test ticker parsing for various formats."""

    def test_parse_xrp_barrier(self):
        """Test parsing XRP ticker with barrier."""
        asset, series, strike = TickerParser.parse("KXXRP-26MAR2508-B1.5899500")

        assert asset == "XRP"
        assert series == "KXXRP"
        assert strike == Decimal("1.5899500")

    def test_parse_btc_threshold(self):
        """Test parsing BTC ticker with threshold."""
        asset, series, strike = TickerParser.parse("KXBTC-26MAR25-T95000")

        assert asset == "BTC"
        assert series == "KXBTC"
        assert strike == Decimal("95000")

    def test_parse_btc_15m_threshold(self):
        """Test parsing BTC 15m ticker."""
        asset, series, strike = TickerParser.parse("KXBTC-15M-26MAR25-T95000")

        assert asset == "BTC"
        assert series == "KXBTC-15M"
        assert strike == Decimal("95000")

    def test_parse_sol_barrier(self):
        """Test parsing SOL ticker."""
        asset, series, strike = TickerParser.parse("KXSOL-26MAR25-B150.50")

        assert asset == "SOL"
        assert series == "KXSOL"
        assert strike == Decimal("150.50")

    def test_parse_eth_d1(self):
        """Test parsing ETH daily ticker."""
        asset, series, strike = TickerParser.parse("KXETH-D1-26MAR25-T3500")

        assert asset == "ETH"
        assert series == "KXETH-D1"
        assert strike == Decimal("3500")

    def test_parse_doge(self):
        """Test parsing DOGE ticker."""
        asset, series, strike = TickerParser.parse("KXDOGE-26MAR25-B0.25")

        assert asset == "DOGE"
        assert series == "KXDOGE"
        assert strike == Decimal("0.25")

    def test_parse_no_strike(self):
        """Test parsing ticker without strike."""
        asset, series, strike = TickerParser.parse("KXBTC-26MAR25")

        assert asset == "BTC"
        assert series == "KXBTC"
        assert strike is None

    def test_parse_invalid_format(self):
        """Test parsing invalid ticker format."""
        asset, series, strike = TickerParser.parse("INVALID-TICKER")

        assert asset is None
        assert series is None
        assert strike is None

    def test_parse_unknown_asset(self):
        """Test parsing ticker with unknown asset."""
        # Should fail since KXUNK is not in ASSET_MAP
        asset, series, strike = TickerParser.parse("KXUNK-26MAR25-T100")

        assert asset is None


class TestDistanceCalculator:
    """Test distance calculations."""

    def test_percent_distance_above_spot(self):
        """Test percent distance for strike above spot."""
        strike = Decimal("105")
        spot = Decimal("100")

        pct_dist = DistanceCalculator.percent_distance(strike, spot)

        assert pct_dist == pytest.approx(0.05, abs=0.001)  # 5% above

    def test_percent_distance_below_spot(self):
        """Test percent distance for strike below spot."""
        strike = Decimal("95")
        spot = Decimal("100")

        pct_dist = DistanceCalculator.percent_distance(strike, spot)

        assert pct_dist == pytest.approx(-0.05, abs=0.001)  # 5% below

    def test_percent_distance_at_spot(self):
        """Test percent distance at spot."""
        strike = Decimal("100")
        spot = Decimal("100")

        pct_dist = DistanceCalculator.percent_distance(strike, spot)

        assert pct_dist == pytest.approx(0.0, abs=0.001)

    def test_vol_distance(self):
        """Test volatility-adjusted distance."""
        strike = Decimal("105")
        spot = Decimal("100")
        sigma_horizon = 0.02  # 2% horizon vol

        vol_dist = DistanceCalculator.vol_distance(strike, spot, sigma_horizon)

        # 5% move / 2% vol = 2.5 standard deviations
        assert vol_dist == pytest.approx(2.5, abs=0.1)

    def test_horizon_adjusted_vol_15min(self):
        """Test horizon-adjusted vol for 15 minute expiry."""
        daily_vol = 0.03  # 3% daily
        minutes = 15

        sigma = DistanceCalculator.horizon_adjusted_vol(daily_vol, minutes)

        # 15 min = 15/(24*60) = 0.0104 days
        # sigma = 0.03 * sqrt(0.0104) = 0.00306
        assert sigma == pytest.approx(0.00306, abs=0.0001)

    def test_horizon_adjusted_vol_1hour(self):
        """Test horizon-adjusted vol for 1 hour expiry."""
        daily_vol = 0.03
        minutes = 60

        sigma = DistanceCalculator.horizon_adjusted_vol(daily_vol, minutes)

        # 1 hour = 1/24 = 0.0417 days
        # sigma = 0.03 * sqrt(0.0417) = 0.00612
        assert sigma == pytest.approx(0.00612, abs=0.0001)

    def test_horizon_adjusted_vol_1day(self):
        """Test horizon-adjusted vol for 1 day expiry."""
        daily_vol = 0.03
        minutes = 24 * 60

        sigma = DistanceCalculator.horizon_adjusted_vol(daily_vol, minutes)

        # 1 day, sigma = daily_vol
        assert sigma == pytest.approx(0.03, abs=0.0001)


class TestFilterPipeline:
    """Test filter pipeline functionality."""

    @pytest.fixture
    def config(self):
        """Create test config."""
        return FilterPipelineConfig(
            assets=["BTC", "ETH", "SOL"],
            max_candidates_per_asset=5,
            max_candidates_global=10,
            min_volume=50,
            min_open_interest=10,
            max_spread_cents=12,
        )

    @pytest.fixture
    def pipeline(self, config):
        """Create filter pipeline."""
        return FilterPipeline(config)

    def test_set_get_spot_price(self, pipeline):
        """Test spot price caching."""
        pipeline.set_spot_price("BTC", Decimal("95000"))

        spot = pipeline.get_spot_price("BTC")

        assert spot == Decimal("95000")

    def test_parse_strikes_valid_tickers(self, pipeline):
        """Test parsing valid tickers."""
        markets = [
            {"ticker": "KXBTC-26MAR25-T95000", "volume": 100, "open_interest": 50},
            {"ticker": "KXBTC-26MAR25-T96000", "volume": 80, "open_interest": 40},
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        candidates = pipeline._parse_strikes("BTC", markets, result)

        assert len(candidates) == 2
        assert candidates[0].strike_price == Decimal("95000")
        assert candidates[1].strike_price == Decimal("96000")
        assert result.invalid_symbol_format == 0

    def test_parse_strikes_invalid_format(self, pipeline):
        """Test parsing with invalid ticker format."""
        markets = [
            {"ticker": "INVALID", "volume": 100, "open_interest": 50},
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        candidates = pipeline._parse_strikes("BTC", markets, result)

        assert len(candidates) == 0
        assert result.invalid_symbol_format == 1

    def test_parse_strikes_wrong_asset(self, pipeline):
        """Test parsing with wrong asset ticker."""
        markets = [
            {"ticker": "KXETH-26MAR25-T3500", "volume": 100, "open_interest": 50},
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        candidates = pipeline._parse_strikes("BTC", markets, result)

        assert len(candidates) == 0
        assert result.unknown_type == 1

    def test_filter_strike_distance_within_threshold(self, pipeline):
        """Test strike distance filter passes markets within threshold."""
        pipeline.set_spot_price("BTC", Decimal("100000"))

        candidates = [
            MarketCandidate(
                ticker="KXBTC-T105000",
                asset="BTC",
                series="KXBTC",
                strike_price=Decimal("105000"),  # 5% above spot
            ),
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        filtered = pipeline._filter_strike_distance("BTC", candidates, result)

        assert len(filtered) == 1
        assert result.strike_too_far == 0
        # Check distance metrics were computed
        assert filtered[0].pct_distance == pytest.approx(0.05, abs=0.01)

    def test_filter_strike_distance_exceeds_pct_threshold(self, pipeline):
        """Test strike distance filter rejects strikes too far from spot."""
        pipeline.set_spot_price("BTC", Decimal("100000"))

        # Configure tight percent threshold
        pipeline.config.asset_vol_configs["BTC"] = AssetVolatilityConfig(
            asset="BTC",
            max_pct_from_spot=0.10,  # 10% max
        )

        candidates = [
            MarketCandidate(
                ticker="KXBTC-T130000",
                asset="BTC",
                series="KXBTC",
                strike_price=Decimal("130000"),  # 30% above spot
            ),
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        filtered = pipeline._filter_strike_distance("BTC", candidates, result)

        assert len(filtered) == 0
        assert result.strike_too_far == 1

    def test_filter_strike_distance_no_spot_price(self, pipeline):
        """Test strike distance filter when no spot price available."""
        # Don't set spot price

        candidates = [
            MarketCandidate(
                ticker="KXBTC-T105000",
                asset="BTC",
                series="KXBTC",
                strike_price=Decimal("105000"),
            ),
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        filtered = pipeline._filter_strike_distance("BTC", candidates, result)

        # Should pass all candidates when no spot price
        assert len(filtered) == 1
        assert result.strike_too_far == 0

    def test_filter_liquidity_passes(self, pipeline):
        """Test liquidity filter passes liquid markets."""
        candidates = [
            MarketCandidate(
                ticker="KXBTC-T105000",
                asset="BTC",
                series="KXBTC",
                volume=100,
                open_interest=50,
                best_bid_cents=50,
                best_ask_cents=55,
                spread_cents=5,
            ),
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        filtered = pipeline._filter_liquidity(candidates, result)

        assert len(filtered) == 1
        assert result.illiquid == 0

    def test_filter_liquidity_low_volume(self, pipeline):
        """Test liquidity filter rejects low volume."""
        candidates = [
            MarketCandidate(
                ticker="KXBTC-T105000",
                asset="BTC",
                series="KXBTC",
                volume=10,  # Below min_volume=50
                open_interest=50,
                spread_cents=5,
            ),
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        filtered = pipeline._filter_liquidity(candidates, result)

        assert len(filtered) == 0
        assert result.illiquid == 1

    def test_filter_liquidity_low_oi(self, pipeline):
        """Test liquidity filter rejects low OI."""
        candidates = [
            MarketCandidate(
                ticker="KXBTC-T105000",
                asset="BTC",
                series="KXBTC",
                volume=100,
                open_interest=5,  # Below min_open_interest=10
                spread_cents=5,
            ),
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        filtered = pipeline._filter_liquidity(candidates, result)

        assert len(filtered) == 0
        assert result.illiquid == 1

    def test_filter_liquidity_wide_spread(self, pipeline):
        """Test liquidity filter rejects wide spreads."""
        candidates = [
            MarketCandidate(
                ticker="KXBTC-T105000",
                asset="BTC",
                series="KXBTC",
                volume=100,
                open_interest=50,
                spread_cents=20,  # Above max_spread_cents=12
            ),
        ]

        from merid.trading.kalshi_continuous_trader import AssetFilterResult

        result = AssetFilterResult(asset="BTC")
        filtered = pipeline._filter_liquidity(candidates, result)

        assert len(filtered) == 0
        assert result.illiquid == 1

    def test_score_candidates_distance_component(self, pipeline):
        """Test composite scoring includes distance."""
        candidates = [
            MarketCandidate(
                ticker="KXBTC-T105000",
                asset="BTC",
                series="KXBTC",
                vol_distance=1.0,  # Close to spot
                volume=100,
                open_interest=50,
                spread_cents=5,
            ),
            MarketCandidate(
                ticker="KXBTC-T110000",
                asset="BTC",
                series="KXBTC",
                vol_distance=3.0,  # Farther from spot
                volume=100,
                open_interest=50,
                spread_cents=5,
            ),
        ]

        scored = pipeline._score_candidates(candidates)

        # First candidate (closer) should score higher
        assert scored[0].vol_distance == 1.0
        assert scored[0].composite_score > scored[1].composite_score

    def test_apply_per_asset_caps(self, pipeline):
        """Test per-asset capping."""
        # Create 10 BTC candidates
        btc_candidates = [
            MarketCandidate(
                ticker=f"KXBTC-T{95000 + i * 1000}",
                asset="BTC",
                series="KXBTC",
                composite_score=100 - i,  # Descending scores
            )
            for i in range(10)
        ]

        per_asset = {"BTC": btc_candidates}
        capped = pipeline._apply_per_asset_caps(per_asset)

        # Should cap to max_candidates_per_asset=5
        assert len(capped["BTC"]) == 5
        # Should keep top 5 by score
        assert capped["BTC"][0].composite_score == 100
        assert capped["BTC"][4].composite_score == 96

    def test_apply_global_cap(self, pipeline):
        """Test global capping across assets."""
        # Create candidates for multiple assets
        btc_candidates = [
            MarketCandidate(
                ticker=f"KXBTC-T{95000 + i}",
                asset="BTC",
                series="KXBTC",
                composite_score=100 - i,
            )
            for i in range(5)
        ]
        eth_candidates = [
            MarketCandidate(
                ticker=f"KXETH-T{3500 + i}",
                asset="ETH",
                series="KXETH",
                composite_score=90 - i,
            )
            for i in range(5)
        ]

        per_asset = {"BTC": btc_candidates, "ETH": eth_candidates}
        final = pipeline._apply_global_cap(per_asset)

        # Should cap to max_candidates_global=10
        assert len(final) == 10
        # Should be sorted by composite score
        assert final[0].asset == "BTC"  # Top BTC scores higher
        assert final[0].composite_score == 100


class TestFilterPipelineIntegration:
    """Integration tests for full filter pipeline."""

    @pytest.mark.asyncio
    async def test_filter_markets_empty(self):
        """Test filtering with no markets."""
        config = FilterPipelineConfig(assets=["BTC"])
        pipeline = FilterPipeline(config)

        result = await pipeline.filter_markets({"BTC": []})

        assert result.total_raw == 0
        assert result.total_candidates_pre_cap == 0
        assert result.total_candidates_post_cap == 0
        assert len(result.final_candidates) == 0

    @pytest.mark.asyncio
    async def test_filter_markets_multi_asset(self):
        """Test filtering across multiple assets."""
        config = FilterPipelineConfig(
            assets=["BTC", "ETH"],
            max_candidates_per_asset=3,
            max_candidates_global=5,
            min_volume=10,
            min_open_interest=5,
        )
        pipeline = FilterPipeline(config)

        # Set spot prices
        pipeline.set_spot_price("BTC", Decimal("95000"))
        pipeline.set_spot_price("ETH", Decimal("3500"))

        # Create mock markets
        btc_markets = [
            {
                "ticker": f"KXBTC-26MAR25-T{95000 + i * 1000}",
                "volume": 100,
                "open_interest": 50,
                "best_bid_cents": 50,
                "best_ask_cents": 55,
            }
            for i in range(5)
        ]
        eth_markets = [
            {
                "ticker": f"KXETH-26MAR25-T{3500 + i * 100}",
                "volume": 80,
                "open_interest": 40,
                "best_bid_cents": 48,
                "best_ask_cents": 52,
            }
            for i in range(5)
        ]

        result = await pipeline.filter_markets({
            "BTC": btc_markets,
            "ETH": eth_markets,
        })

        # Should process all markets
        assert result.total_raw == 10
        # Should have candidates from both assets
        assert "BTC" in result.assets_with_candidates
        assert "ETH" in result.assets_with_candidates
        # Should cap to global limit
        assert result.total_candidates_post_cap <= config.max_candidates_global
        assert len(result.final_candidates) <= config.max_candidates_global


class TestFilterResultLogging:
    """Test filter result logging formats."""

    def test_asset_filter_result_log_dict(self):
        """Test AssetFilterResult.to_log_dict() format."""
        from merid.trading.kalshi_continuous_trader import AssetFilterResult, FilterStepTimings

        result = AssetFilterResult(
            asset="BTC",
            raw=100,
            directional=90,
            parseable_strikes=85,
            strike_too_far=20,
            illiquid=10,
            candidates=55,
            sample_tickers=["KXBTC-T95000", "KXBTC-T96000"],
            timings=FilterStepTimings(
                fetch_ms=5.0,
                directional_ms=2.0,
                parse_ms=10.0,
                strike_distance_ms=15.0,
                total_ms=35.0,
            ),
        )

        log_dict = result.to_log_dict()

        # Should include all non-zero counters
        assert log_dict["asset"] == "BTC"
        assert log_dict["raw"] == 100
        assert log_dict["directional"] == 90
        assert log_dict["parseable_strikes"] == 85
        assert log_dict["strike_too_far"] == 20
        assert log_dict["illiquid"] == 10
        assert log_dict["candidates"] == 55
        assert log_dict["latency_total_ms"] == 35.0
        assert "sample_tickers" in log_dict

    def test_multi_asset_filter_result_log_dict(self):
        """Test MultiAssetFilterResult.to_log_dict() format."""
        from merid.trading.kalshi_continuous_trader import MultiAssetFilterResult

        result = MultiAssetFilterResult(
            total_raw=669,
            total_candidates_pre_cap=72,
            total_candidates_post_cap=10,
            assets_with_candidates=["BTC", "ETH", "SOL", "XRP", "DOGE"],
            capped_to=10,
        )

        log_dict = result.to_log_dict()

        assert log_dict["total_raw"] == 669
        assert log_dict["total_candidates_pre_cap"] == 72
        assert log_dict["total_candidates_post_cap"] == 10
        assert log_dict["assets_with_candidates"] == ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        assert log_dict["capped_to"] == 10
