"""Test CatalogMarket attribute access fixes.

Tests the fixes for the market catalog "dependencies degraded" warning:
- CatalogMarket wraps EventMarket, so attributes like raw_data, market_id, volume are on nested market.market
- CatalogMarket has direct fields: asset, timeframe, category, event_ticker, series_ticker
- _get_asset and _get_ticker must handle this nested structure correctly
"""

import pytest
from datetime import datetime, timezone
from typing import Optional

from merid.event_venues.kalshi.market_catalog import CatalogMarket, EventMarket


class TestCatalogMarketAttributeAccess:
    """Test defensive attribute access patterns for CatalogMarket objects."""

    def test_catalog_market_structure(self):
        """Verify CatalogMarket has expected structure."""
        # Create EventMarket with raw_data
        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={
                "series_ticker": "KXBTC15M",
                "event_ticker": "KXBTC15M-26MAY191545",
                "yes_bid": 50,
                "yes_ask": 52,
            },
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        # Create CatalogMarket wrapping EventMarket
        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
            category="crypto",
            event_ticker="KXBTC15M-26MAY191545",
            series_ticker="KXBTC15M",
        )

        # Verify outer CatalogMarket fields
        assert catalog_market.asset == "BTC"
        assert catalog_market.timeframe == "15m"
        assert catalog_market.category == "crypto"
        assert catalog_market.event_ticker == "KXBTC15M-26MAY191545"
        assert catalog_market.series_ticker == "KXBTC15M"

        # Verify nested EventMarket fields
        assert catalog_market.market.market_id == "KXBTC15M-26MAY191545-45"
        assert catalog_market.market.question == "Will BTC be above 50000?"
        assert catalog_market.market.raw_data is not None
        assert catalog_market.market.raw_data["series_ticker"] == "KXBTC15M"
        assert catalog_market.market.volume == 1000000
        assert catalog_market.market.active is True

    def test_catalog_market_no_ticker_field(self):
        """Verify CatalogMarket does NOT have a ticker field (uses event_ticker/series_ticker)."""
        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={"series_ticker": "KXBTC15M"},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
            event_ticker="KXBTC15M-26MAY191545",
            series_ticker="KXBTC15M",
        )

        # CatalogMarket should NOT have a ticker field
        assert not hasattr(catalog_market, "ticker")
        # But should have event_ticker and series_ticker
        assert catalog_market.event_ticker == "KXBTC15M-26MAY191545"
        assert catalog_market.series_ticker == "KXBTC15M"


class TestMarketUniverseExtraction:
    """Test _get_asset and _get_ticker methods with CatalogMarket objects."""

    def test_get_asset_from_catalog_market(self):
        """Test _get_asset extracts asset from CatalogMarket.asset field."""
        from merid.event_venues.kalshi.market_universe import MarketUniverse

        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={"series_ticker": "KXBTC15M"},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
            event_ticker="KXBTC15M-26MAY191545",
            series_ticker="KXBTC15M",
        )

        # Should extract asset from outer CatalogMarket.asset field
        asset = MarketUniverse._get_asset(catalog_market)
        assert asset == "BTC"

    def test_get_ticker_from_catalog_market(self):
        """Test _get_ticker extracts ticker from CatalogMarket.event_ticker/series_ticker."""
        from merid.event_venues.kalshi.market_universe import MarketUniverse

        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={"series_ticker": "KXBTC15M"},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
            event_ticker="KXBTC15M-26MAY191545",
            series_ticker="KXBTC15M",
        )

        # Should extract ticker from event_ticker or series_ticker
        ticker = MarketUniverse._get_ticker(catalog_market)
        # Prefers event_ticker
        assert ticker == "KXBTC15M-26MAY191545"

    def test_get_ticker_fallback_to_market_id(self):
        """Test _get_ticker falls back to nested market.market_id if event_ticker/series_ticker missing."""
        from merid.event_venues.kalshi.market_universe import MarketUniverse

        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
            # No event_ticker or series_ticker
        )

        # Should fall back to nested market.market_id
        ticker = MarketUniverse._get_ticker(catalog_market)
        assert ticker == "KXBTC15M-26MAY191545-45"

    def test_market_universe_validation_with_catalog_market(self):
        """Test market universe validation passes with CatalogMarket objects."""
        from merid.event_venues.kalshi.market_universe import MarketUniverse

        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={"series_ticker": "KXBTC15M"},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
            event_ticker="KXBTC15M-26MAY191545",
            series_ticker="KXBTC15M",
        )

        # Create universe from CatalogMarket
        universe = MarketUniverse.from_markets([catalog_market])

        # Validation should pass
        assert universe.validate_universe() is True
        assert universe.get_market_count() == 1
        assert "BTC" in universe.assets


class TestDefensiveAttributeAccess:
    """Test defensive attribute access patterns used in fixes."""

    def test_defensive_raw_data_access(self):
        """Test defensive pattern for accessing raw_data on CatalogMarket."""
        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={"series_ticker": "KXBTC15M", "event_ticker": "KXBTC15M-26MAY191545"},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
        )

        # Defensive pattern used in fixes
        if hasattr(catalog_market, "market") and hasattr(catalog_market.market, "raw_data"):
            raw = catalog_market.market.raw_data or {}
        elif hasattr(catalog_market, "raw_data"):
            raw = catalog_market.raw_data or {}
        else:
            raw = {}

        assert raw["series_ticker"] == "KXBTC15M"
        assert raw["event_ticker"] == "KXBTC15M-26MAY191545"

    def test_defensive_market_id_access(self):
        """Test defensive pattern for accessing market_id on CatalogMarket."""
        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
        )

        # Defensive pattern used in fixes
        if hasattr(catalog_market, "market") and hasattr(catalog_market.market, "market_id"):
            ticker = catalog_market.market.market_id
        elif hasattr(catalog_market, "market_id"):
            ticker = catalog_market.market_id
        else:
            ticker = ""

        assert ticker == "KXBTC15M-26MAY191545-45"

    def test_defensive_volume_access(self):
        """Test defensive pattern for accessing volume on CatalogMarket."""
        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
        )

        # Defensive pattern used in fixes
        if hasattr(catalog_market, "market") and hasattr(catalog_market.market, "volume"):
            vol = float(catalog_market.market.volume) if catalog_market.market.volume else 0.0
        elif hasattr(catalog_market, "volume"):
            vol = float(catalog_market.volume) if catalog_market.volume else 0.0
        else:
            vol = 0.0

        assert vol == 1000000.0

    def test_defensive_active_access(self):
        """Test defensive pattern for accessing active on CatalogMarket."""
        event_market = EventMarket(
            market_id="KXBTC15M-26MAY191545-45",
            venue="kalshi",
            question="Will BTC be above 50000?",
            description="Will BTC be above 50000 at 3:15 PM ET on May 26, 2026?",
            outcomes=["Yes", "No"],
            raw_data={},
            volume=1000000,
            active=True,
            end_date=datetime(2026, 5, 26, 19, 15, 45, tzinfo=timezone.utc),
        )

        catalog_market = CatalogMarket(
            market=event_market,
            asset="BTC",
            timeframe="15m",
        )

        # Defensive pattern used in fixes
        if hasattr(catalog_market, "market") and hasattr(catalog_market.market, "active"):
            active = catalog_market.market.active
        elif hasattr(catalog_market, "active"):
            active = catalog_market.active
        else:
            active = False

        assert active is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
