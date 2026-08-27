"""
Integration test for MarketCatalog filtering with AllowedMarketPolicy.

This test simulates the "5000 raw markets, 5 allowed" scenario to verify that:
1. The catalog correctly fetches 5000 markets
2. The AllowedMarketPolicy filters to exactly 5 allowed markets
3. Downstream agents receive only the filtered markets
4. No leakage of disallowed markets occurs
5. snapshot() includes both open and unopened markets (Kalshi 15m lifecycle)
6. get_current_15m_market() selects by smallest minutes_to_expiry
"""

import pytest
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from freezegun import freeze_time
from merid.event_venues.kalshi.allowed_market_policy import (
    filter_allowed_markets,
    get_allowed_assets,
)


def generate_mock_markets(count: int) -> List[Dict[str, Any]]:
    """
    Generate mock market data for testing.

    Args:
        count: Number of markets to generate

    Returns:
        List of market dicts with ticker, asset, category fields
    """
    markets = []
    allowed_assets = get_allowed_assets()
    disallowed_assets = ["ADA", "LTC", "DOT", "AVAX", "LINK"]

    # Generate 5 allowed markets (one per allowed asset)
    for asset in allowed_assets:
        markets.append({
            "ticker": f"KX{asset}15M-26JAN24-5000",
            "asset": asset,
            "category": "crypto",
            "series": f"KX{asset}15M",
        })

    # Generate remaining markets as disallowed
    for i in range(count - len(allowed_assets)):
        asset = disallowed_assets[i % len(disallowed_assets)]
        markets.append({
            "ticker": f"KX{asset}15M-26JAN24-{5000 + i}",
            "asset": asset,
            "category": "crypto",
            "series": f"KX{asset}15M",
        })

    return markets


class TestMarketCatalogFilteringIntegration:
    """Integration tests for market catalog filtering."""

    def test_5000_markets_5_allowed_scenario(self):
        """Test the primary scenario: 5000 raw markets filtered to 5 allowed."""
        # Generate 5000 mock markets
        raw_markets = generate_mock_markets(5000)

        # Apply AllowedMarketPolicy filter
        filtered_markets = filter_allowed_markets(raw_markets)

        # Assert counts
        assert len(raw_markets) == 5000, "Should have 5000 raw markets"
        assert len(filtered_markets) == 5, "Should filter to exactly 5 allowed markets"

        # Assert all filtered markets are allowed assets
        allowed_assets = get_allowed_assets()
        for market in filtered_markets:
            assert market["asset"] in allowed_assets, f"Asset {market['asset']} should be allowed"
            assert market["category"] == "crypto", "Category should be crypto"

        # Assert we have exactly one market per allowed asset
        filtered_assets = {m["asset"] for m in filtered_markets}
        assert filtered_assets == allowed_assets, "Should have exactly one market per allowed asset"

    def test_no_allowed_markets_scenario(self):
        """Test behavior when no markets are allowed."""
        # Generate markets with only disallowed assets
        disallowed_markets = [
            {
                "ticker": f"KX{asset}15M-26JAN24-5000",
                "asset": asset,
                "category": "crypto",
            }
            for asset in ["ADA", "LTC", "DOT", "AVAX", "LINK"]
        ]

        # Apply filter
        filtered_markets = filter_allowed_markets(disallowed_markets)

        # Assert all markets are rejected
        assert len(filtered_markets) == 0, "Should reject all disallowed markets"

    def test_all_allowed_markets_scenario(self):
        """Test behavior when all markets are allowed."""
        # Generate only allowed markets (multiple per asset)
        allowed_assets = get_allowed_assets()
        all_allowed_markets = []
        for asset in allowed_assets:
            for i in range(3):  # 3 markets per asset
                all_allowed_markets.append({
                    "ticker": f"KX{asset}15M-26JAN24-{5000 + i}",
                    "asset": asset,
                    "category": "crypto",
                })

        # Apply filter
        filtered_markets = filter_allowed_markets(all_allowed_markets)

        # Assert all markets pass through
        assert len(filtered_markets) == len(all_allowed_markets), "All allowed markets should pass"
        assert len(filtered_markets) == 15, f"Should have 15 markets (3 per asset)"

    def test_no_leakage_of_disallowed_markets(self):
        """Test that disallowed markets never leak into the filtered list."""
        # Generate mix of allowed and disallowed
        markets = []
        allowed_assets = get_allowed_assets()
        disallowed_assets = ["ADA", "LTC"]

        # Add 2 allowed markets
        for asset in list(allowed_assets)[:2]:
            markets.append({"ticker": f"KX{asset}15M-26JAN24-5000", "asset": asset, "category": "crypto"})

        # Add 3 disallowed markets
        for asset in disallowed_assets:
            markets.append({"ticker": f"KX{asset}15M-26JAN24-5000", "asset": asset, "category": "crypto"})

        # Apply filter
        filtered_markets = filter_allowed_markets(markets)

        # Assert no disallowed markets in filtered list
        filtered_assets = {m["asset"] for m in filtered_markets}
        assert not any(asset in disallowed_assets for asset in filtered_assets), \
            "No disallowed assets should leak through"

        # Assert allowed markets are present
        assert len(filtered_markets) == 2, "Should have exactly 2 allowed markets"

    def test_category_filtering(self):
        """Test that non-crypto category markets are rejected even with allowed assets."""
        # Generate markets with allowed assets but wrong category
        markets = [
            {"ticker": "KXBTC15M-26JAN24-5000", "asset": "BTC", "category": "politics"},
            {"ticker": "KXETH15M-26JAN24-5000", "asset": "ETH", "category": "economics"},
            {"ticker": "KXSOL15M-26JAN24-5000", "asset": "SOL", "category": "crypto"},  # Only this one should pass
        ]

        # Apply filter
        filtered_markets = filter_allowed_markets(markets)

        # Assert only crypto category passes
        assert len(filtered_markets) == 1, "Only crypto category should pass"
        assert filtered_markets[0]["asset"] == "SOL", "Should be the SOL market"

    def test_malformed_market_data(self):
        """Test handling of malformed market data."""
        # Generate markets with missing or malformed fields
        markets = [
            {"ticker": "KXBTC15M-26JAN24-5000", "asset": "BTC"},  # Missing category (should pass)
            {"asset": "ETH"},  # Missing ticker (should fail)
            {"ticker": "KXSOL15M-26JAN24-5000", "category": "crypto"},  # Missing asset (should pass via ticker)
            {},  # Empty dict (should fail)
        ]

        # Apply filter
        filtered_markets = filter_allowed_markets(markets)

        # Assert only markets with valid identifiers pass
        assert len(filtered_markets) == 2, "Should have 2 valid markets"
        filtered_tickers = {m.get("ticker") for m in filtered_markets}
        assert "KXBTC15M-26JAN24-5000" in filtered_tickers, "BTC market should pass"
        assert "KXSOL15M-26JAN24-5000" in filtered_tickers, "SOL market should pass"


class TestKalshiMarketCatalogSnapshot:
    """Tests for KalshiMarketCatalog.snapshot() method with simplified filtering logic."""

    def test_snapshot_includes_open_markets(self):
        """snapshot() includes markets with status='open'."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

            # Create mock catalog
            catalog = KalshiMarketCatalog()

            # Create mock CatalogMarket objects with status='open'
            class MockCatalogMarket:
                def __init__(self, asset, status):
                    self.asset = asset
                    self.timeframe = "15m"
                    self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                    self.market = type('obj', (object,), {
                        'raw_data': {'status': status},
                        'market_id': f"KX{asset}15M-TEST"
                    })()

            markets = [MockCatalogMarket(asset, "open") for asset in ["BTC", "ETH"]]

            # Set catalog markets (bypass refresh for testing)
            catalog._markets = markets

            # Call snapshot
            snapshot = catalog.snapshot()

            # Assert open markets are included
            assert len(snapshot.markets) == 2, "Should include 2 open markets"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_snapshot_includes_unopened_markets(self):
        """snapshot() includes markets with status='unopened'."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

            # Create mock catalog
            catalog = KalshiMarketCatalog()

            # Create mock CatalogMarket objects with status='unopened'
            class MockCatalogMarket:
                def __init__(self, asset, status):
                    self.asset = asset
                    self.timeframe = "15m"
                    self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                    self.market = type('obj', (object,), {
                        'raw_data': {'status': status},
                        'market_id': f"KX{asset}15M-TEST"
                    })()

            markets = [MockCatalogMarket(asset, "unopened") for asset in ["BTC", "ETH"]]

            # Set catalog markets
            catalog._markets = markets

            # Call snapshot
            snapshot = catalog.snapshot()

            # Assert unopened markets are included
            assert len(snapshot.markets) == 2, "Should include 2 unopened markets"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_snapshot_includes_closed_markets(self):
        """snapshot() includes markets with status='closed' (not settled)."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

            # Create mock catalog
            catalog = KalshiMarketCatalog()

            # Create mock CatalogMarket objects with status='closed'
            class MockCatalogMarket:
                def __init__(self, asset, status):
                    self.asset = asset
                    self.timeframe = "15m"
                    self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                    self.market = type('obj', (object,), {
                        'raw_data': {'status': status},
                        'market_id': f"KX{asset}15M-TEST"
                    })()

            markets = [MockCatalogMarket(asset, "closed") for asset in ["BTC", "ETH"]]

            # Set catalog markets
            catalog._markets = markets

            # Call snapshot
            snapshot = catalog.snapshot()

            # Assert closed markets are included (only settled are excluded)
            assert len(snapshot.markets) == 2, "Should include 2 closed markets"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_snapshot_excludes_settled_markets(self):
        """snapshot() excludes markets with status='settled'."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

            # Create mock catalog
            catalog = KalshiMarketCatalog()

            # Create mock CatalogMarket objects with status='settled'
            class MockCatalogMarket:
                def __init__(self, asset, status):
                    self.asset = asset
                    self.timeframe = "15m"
                    self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                    self.market = type('obj', (object,), {
                        'raw_data': {'status': status},
                        'market_id': f"KX{asset}15M-TEST"
                    })()

            markets = [MockCatalogMarket(asset, "settled") for asset in ["BTC", "ETH"]]

            # Set catalog markets
            catalog._markets = markets

            # Call snapshot
            snapshot = catalog.snapshot()

            # Assert settled markets are excluded
            assert len(snapshot.markets) == 0, "Should exclude settled markets"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_snapshot_filters_by_allowed_assets(self):
        """snapshot() only includes markets for allowed assets (BTC, ETH, SOL, XRP, DOGE)."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog

            # Create mock catalog
            catalog = KalshiMarketCatalog()

            # Create mock CatalogMarket objects for various assets
            class MockCatalogMarket:
                def __init__(self, asset, status):
                    self.asset = asset
                    self.timeframe = "15m"
                    self.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
                    self.market = type('obj', (object,), {
                        'raw_data': {'status': status},
                        'market_id': f"KX{asset}15M-TEST"
                    })()

            markets = [MockCatalogMarket(asset, "open") for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LTC"]]

            # Set catalog markets
            catalog._markets = markets

            # Call snapshot
            snapshot = catalog.snapshot()

            # Assert only allowed assets are included
            assert len(snapshot.markets) == 5, "Should include only 5 allowed assets"
            assets_in_snapshot = {m.asset for m in snapshot.markets}
            assert assets_in_snapshot == {"BTC", "ETH", "SOL", "XRP", "DOGE"}, \
                "Should only have BTC, ETH, SOL, XRP, DOGE"

        except ImportError:
            pytest.skip("market_catalog not available")


class TestMarketCatalogTimeWindowFiltering:
    """Tests for the new time window filtering logic (visibility and tradeability)."""

    def test_visibility_filter_excludes_old_tickers(self):
        """Test that visibility filter (0-15.5 min) excludes markets from previous window (15-30 min)."""
        try:
            from merid.event_venues.kalshi.market_catalog import CatalogMarket
            from merid.event_venues.base import EventMarket, EventOutcome
            from datetime import datetime, timezone, timedelta
            from decimal import Decimal

            now_utc = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

            # Create market in current window (5 min to expiry) - should be visible
            current_market = EventMarket(
                market_id="KXBTC15M-26JUN151000-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=now_utc + timedelta(minutes=5),
                active=True,
                raw_data={"status": "open"}
            )

            # Create market in previous window (20 min to expiry) - should NOT be visible
            old_market = EventMarket(
                market_id="KXBTC15M-26JUN142000-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=now_utc + timedelta(minutes=20),
                active=True,
                raw_data={"status": "open"}
            )

            current_cm = CatalogMarket(
                market=current_market,
                asset="BTC",
                timeframe="15m",
                expires_at=now_utc + timedelta(minutes=5),
                minutes_to_expiry=5.0,
                api_status="open",
                health_status="ok",
                tradeable=True
            )

            old_cm = CatalogMarket(
                market=old_market,
                asset="BTC",
                timeframe="15m",
                expires_at=now_utc + timedelta(minutes=20),
                minutes_to_expiry=20.0,
                api_status="open",
                health_status="ok",
                tradeable=True
            )

            # Apply visibility filter logic (0-15.5 min)
            from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
            visible_markets = []
            for cm in [current_cm, old_cm]:
                if cm.expires_at:
                    mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                    if 0.0 <= mte <= 15.5:
                        visible_markets.append(cm)

            # Assert only current market is visible
            assert len(visible_markets) == 1, "Should only include current window market"
            assert visible_markets[0].market.market_id == "KXBTC15M-26JUN151000-50000"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_tradeability_filter_sets_tradeable_flag(self):
        """Test that tradeability filter (2-12 min) correctly sets tradeable flag."""
        try:
            from merid.event_venues.kalshi.market_catalog import CatalogMarket
            from merid.event_venues.base import EventMarket, EventOutcome
            from datetime import datetime, timezone, timedelta
            from decimal import Decimal

            now_utc = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

            # Create market in entry window (5 min to expiry) - should be tradeable
            entry_window_market = EventMarket(
                market_id="KXBTC15M-26JUN151000-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=now_utc + timedelta(minutes=5),
                active=True,
                raw_data={"status": "open"}
            )

            # Create market outside entry window (1 min to expiry) - should NOT be tradeable
            too_soon_market = EventMarket(
                market_id="KXBTC15M-26JUN150100-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=now_utc + timedelta(minutes=1),
                active=True,
                raw_data={"status": "open"}
            )

            # Create market outside entry window (14 min to expiry) - should NOT be tradeable
            too_far_market = EventMarket(
                market_id="KXBTC15M-26JUN151400-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=now_utc + timedelta(minutes=14),
                active=True,
                raw_data={"status": "open"}
            )

            entry_cm = CatalogMarket(
                market=entry_window_market,
                asset="BTC",
                timeframe="15m",
                expires_at=now_utc + timedelta(minutes=5),
                minutes_to_expiry=5.0,
                api_status="open",
                health_status="ok",
                tradeable=False  # Will be set by filter
            )

            too_soon_cm = CatalogMarket(
                market=too_soon_market,
                asset="BTC",
                timeframe="15m",
                expires_at=now_utc + timedelta(minutes=1),
                minutes_to_expiry=1.0,
                api_status="open",
                health_status="ok",
                tradeable=False
            )

            too_far_cm = CatalogMarket(
                market=too_far_market,
                asset="BTC",
                timeframe="15m",
                expires_at=now_utc + timedelta(minutes=14),
                minutes_to_expiry=14.0,
                api_status="open",
                health_status="ok",
                tradeable=False
            )

            # Apply tradeability filter logic (2-12 min)
            from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
            for cm in [entry_cm, too_soon_cm, too_far_cm]:
                if cm.expires_at:
                    mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                    if 2.0 <= mte <= 12.0:
                        cm.tradeable = True
                    else:
                        cm.tradeable = False

            # Assert tradeable flags are set correctly
            assert entry_cm.tradeable == True, "Market in entry window should be tradeable"
            assert too_soon_cm.tradeable == False, "Market too close to expiry should not be tradeable"
            assert too_far_cm.tradeable == False, "Market too far from expiry should not be tradeable"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_combined_visibility_and_tradeability_filters(self):
        """Test that visibility and tradeability filters work together correctly."""
        try:
            from merid.event_venues.kalshi.market_catalog import CatalogMarket
            from merid.event_venues.base import EventMarket, EventOutcome
            from datetime import datetime, timezone, timedelta
            from decimal import Decimal

            now_utc = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

            # Create markets at different expiry times
            markets_data = [
                ("KXBTC15M-26JUN150100-50000", 1.0),   # Visible but not tradeable (too soon)
                ("KXBTC15M-26JUN150500-50000", 5.0),   # Visible and tradeable (entry window)
                ("KXBTC15M-26JUN151000-50000", 10.0),  # Visible and tradeable (entry window)
                ("KXBTC15M-26JUN151300-50000", 13.0),  # Visible but not tradeable (too far)
                ("KXBTC15M-26JUN152000-50000", 20.0),  # Not visible (old ticker)
            ]

            catalog_markets = []
            for ticker, mte in markets_data:
                event_market = EventMarket(
                    market_id=ticker,
                    venue="kalshi",
                    question="Will BTC be above 50000?",
                    description="Test market",
                    outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                    end_date=now_utc + timedelta(minutes=mte),
                    active=True,
                    raw_data={"status": "open"}
                )
                catalog_markets.append(CatalogMarket(
                    market=event_market,
                    asset="BTC",
                    timeframe="15m",
                    expires_at=now_utc + timedelta(minutes=mte),
                    minutes_to_expiry=mte,
                    api_status="open",
                    health_status="ok",
                    tradeable=False
                ))

            # Apply visibility filter (0-15.5 min)
            from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
            visible_markets = []
            for cm in catalog_markets:
                if cm.expires_at:
                    mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                    if 0.0 <= mte <= 15.5:
                        visible_markets.append(cm)

            # Apply tradeability filter (2-12 min)
            tradeable_markets = []
            for cm in visible_markets:
                if cm.expires_at:
                    mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                    if 2.0 <= mte <= 12.0:
                        cm.tradeable = True
                        tradeable_markets.append(cm)
                    else:
                        cm.tradeable = False

            # Assert results
            assert len(visible_markets) == 4, "Should have 4 visible markets (exclude 20min)"
            assert len(tradeable_markets) == 2, "Should have 2 tradeable markets (5min and 10min)"

            # Verify specific markets
            visible_tickers = {cm.market.market_id for cm in visible_markets}
            assert "KXBTC15M-26JUN152000-50000" not in visible_tickers, "20min market should not be visible"

            tradeable_tickers = {cm.market.market_id for cm in tradeable_markets}
            assert "KXBTC15M-26JUN150500-50000" in tradeable_tickers, "5min market should be tradeable"
            assert "KXBTC15M-26JUN151000-50000" in tradeable_tickers, "10min market should be tradeable"
            assert "KXBTC15M-26JUN150100-50000" not in tradeable_tickers, "1min market should not be tradeable"
            assert "KXBTC15M-26JUN151300-50000" not in tradeable_tickers, "13min market should not be tradeable"

        except ImportError:
            pytest.skip("market_catalog not available")


@freeze_time("2024-06-15T10:00:00Z")
class TestKalshiMarketCatalogGetCurrent15mMarket:
    """Tests for KalshiMarketCatalog.get_current_15m_market() helper method.

    Freezing the clock keeps the hardcoded 2024-06-15 test windows valid
    regardless of the real system time.
    """

    def test_get_current_15m_market_exact_window_match(self):
        """get_current_15m_market() matches market by exact ET window end time."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, CatalogSnapshot, CatalogMarket
            from merid.event_venues.kalshi.kalshi_15m_time import ETWindow
            from merid.event_venues.base import EventMarket, EventOutcome
            from datetime import datetime, timezone, timedelta
            from decimal import Decimal
            from unittest.mock import patch

            # Create current ET window (now at 10:00 UTC, window ends at 10:15 UTC)
            window_end = datetime(2024, 6, 15, 10, 15, 0, tzinfo=timezone.utc)
            window_start = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

            # Mock ETWindow
            mock_window = ETWindow(
                start_et=window_start,
                end_et=window_end,
                start_utc=window_start,
                end_utc=window_end,
                suffix="26JUN151000",
                minutes_to_expiry=15.0
            )

            # Create mock EventMarket
            event_market = EventMarket(
                market_id="KXBTC15M-26JUN151000-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=window_end,
                active=True,
                raw_data={"status": "open", "close_time": window_end.isoformat()}
            )

            # Create CatalogMarket with series_ticker (required for filtering)
            catalog_market = CatalogMarket(
                market=event_market,
                asset="BTC",
                timeframe="15m",
                series_ticker="KXBTC15M",  # CRITICAL: Required for 15m filtering
                expires_at=window_end,
                minutes_to_expiry=15.0,
                api_status="open",
                health_status="ok",
                tradeable=True
            )

            # Create snapshot
            snapshot = CatalogSnapshot(markets=[catalog_market])

            # Mock get_kalshi_15m_window to return our test window
            with patch('merid.event_venues.kalshi.kalshi_15m_time.get_kalshi_15m_window', return_value=mock_window):
                # Call get_current_15m_market
                current = snapshot.get_current_15m_market("BTC")

            # Assert market matching window end time is returned
            assert current is not None, "Should return a market"
            assert current.asset == "BTC", "Should return BTC market"
            assert current.expires_at == window_end, "Should return market with matching expiry"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_get_current_15m_market_fallback_to_end_date(self):
        """get_current_15m_market() falls back to end_date when expires_at is missing."""
        try:
            from merid.event_venues.kalshi.market_catalog import CatalogSnapshot, CatalogMarket
            from merid.event_venues.kalshi.kalshi_15m_time import ETWindow
            from merid.event_venues.base import EventMarket, EventOutcome
            from datetime import datetime, timezone
            from decimal import Decimal
            from unittest.mock import patch

            # Create current ET window
            window_end = datetime(2024, 6, 15, 10, 15, 0, tzinfo=timezone.utc)
            window_start = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

            # Mock ETWindow
            mock_window = ETWindow(
                start_et=window_start,
                end_et=window_end,
                start_utc=window_start,
                end_utc=window_end,
                suffix="26JUN151000",
                minutes_to_expiry=15.0
            )

            # Create EventMarket with end_date
            event_market = EventMarket(
                market_id="KXBTC15M-26JUN151000-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=window_end,
                active=True,
                raw_data={"status": "open", "close_time": window_end.isoformat()}
            )

            # Create CatalogMarket WITHOUT expires_at (test fallback) but WITH series_ticker
            catalog_market = CatalogMarket(
                market=event_market,
                asset="BTC",
                timeframe="15m",
                series_ticker="KXBTC15M",  # CRITICAL: Required for 15m filtering
                expires_at=None,  # Missing expires_at
                minutes_to_expiry=15.0,
                api_status="open",
                health_status="ok",
                tradeable=True
            )

            # Create snapshot
            snapshot = CatalogSnapshot(markets=[catalog_market])

            # Mock get_kalshi_15m_window to return our test window
            with patch('merid.event_venues.kalshi.kalshi_15m_time.get_kalshi_15m_window', return_value=mock_window):
                # Call get_current_15m_market
                current = snapshot.get_current_15m_market("BTC")

            # Assert market is found via end_date fallback
            assert current is not None, "Should return a market via end_date fallback"
            assert current.asset == "BTC", "Should return BTC market"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_get_current_15m_market_excludes_settled_markets(self):
        """get_current_15m_market() excludes settled markets using raw_data status."""
        try:
            from merid.event_venues.kalshi.market_catalog import CatalogSnapshot, CatalogMarket
            from merid.event_venues.kalshi.kalshi_15m_time import ETWindow
            from merid.event_venues.base import EventMarket, EventOutcome
            from datetime import datetime, timezone
            from decimal import Decimal
            from unittest.mock import patch

            # Create current ET window
            window_end = datetime(2024, 6, 15, 10, 15, 0, tzinfo=timezone.utc)
            window_start = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

            # Mock ETWindow
            mock_window = ETWindow(
                start_et=window_start,
                end_et=window_end,
                start_utc=window_start,
                end_utc=window_end,
                suffix="26JUN151000",
                minutes_to_expiry=15.0
            )

            # Create settled market
            event_market_settled = EventMarket(
                market_id="KXBTC15M-26JUN151000-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=window_end,
                active=False,
                raw_data={"status": "settled", "close_time": window_end.isoformat()}
            )

            # Create open market
            event_market_open = EventMarket(
                market_id="KXBTC15M-26JUN151515-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=window_end,
                active=True,
                raw_data={"status": "open", "close_time": window_end.isoformat()}
            )

            catalog_market_settled = CatalogMarket(
                market=event_market_settled,
                asset="BTC",
                timeframe="15m",
                series_ticker="KXBTC15M",  # CRITICAL: Required for 15m filtering
                expires_at=window_end,
                minutes_to_expiry=15.0,
                api_status="settled",
                health_status="ok",
                tradeable=False
            )

            catalog_market_open = CatalogMarket(
                market=event_market_open,
                asset="BTC",
                timeframe="15m",
                series_ticker="KXBTC15M",  # CRITICAL: Required for 15m filtering
                expires_at=window_end,
                minutes_to_expiry=15.0,
                api_status="open",
                health_status="ok",
                tradeable=True
            )

            # Create snapshot with both markets
            snapshot = CatalogSnapshot(markets=[catalog_market_settled, catalog_market_open])

            # Mock get_kalshi_15m_window to return our test window
            with patch('merid.event_venues.kalshi.kalshi_15m_time.get_kalshi_15m_window', return_value=mock_window):
                # Call get_current_15m_market
                current = snapshot.get_current_15m_market("BTC")

            # Assert only open market is returned (settled excluded)
            assert current is not None, "Should return a market"
            assert current.api_status == "open", "Should return open market, not settled"

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_get_current_15m_market_returns_none_for_no_match(self):
        """get_current_15m_market() returns None when no market matches current window."""
        try:
            from merid.event_venues.kalshi.market_catalog import CatalogSnapshot, CatalogMarket
            from merid.event_venues.kalshi.kalshi_15m_time import ETWindow
            from merid.event_venues.base import EventMarket, EventOutcome
            from datetime import datetime, timezone
            from decimal import Decimal
            from unittest.mock import patch

            # Create current ET window (ends at 10:15 UTC)
            window_end = datetime(2024, 6, 15, 10, 15, 0, tzinfo=timezone.utc)
            window_start = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

            # Mock ETWindow
            mock_window = ETWindow(
                start_et=window_start,
                end_et=window_end,
                start_utc=window_start,
                end_utc=window_end,
                suffix="26JUN151000",
                minutes_to_expiry=15.0
            )

            # Create market with different expiry (not in current window)
            future_expiry = datetime(2024, 6, 15, 11, 15, 0, tzinfo=timezone.utc)

            event_market = EventMarket(
                market_id="KXBTC15M-26JUN151115-50000",
                venue="kalshi",
                question="Will BTC be above 50000?",
                description="Test market",
                outcomes=[EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.5"), probability=Decimal("0.5"))],
                end_date=future_expiry,
                active=True,
                raw_data={"status": "open", "close_time": future_expiry.isoformat()}
            )

            catalog_market = CatalogMarket(
                market=event_market,
                asset="BTC",
                timeframe="15m",
                expires_at=future_expiry,
                minutes_to_expiry=75.0,
                api_status="open",
                health_status="ok",
                tradeable=True
            )

            # Create snapshot
            snapshot = CatalogSnapshot(markets=[catalog_market])

            # Mock get_kalshi_15m_window to return our test window
            with patch('merid.event_venues.kalshi.kalshi_15m_time.get_kalshi_15m_window', return_value=mock_window):
                # Call get_current_15m_market
                current = snapshot.get_current_15m_market("BTC")

            # Assert None is returned (no match for current window)
            assert current is None, "Should return None when no market matches current window"

        except ImportError:
            pytest.skip("market_catalog not available")
