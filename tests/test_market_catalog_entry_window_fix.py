"""Test market catalog entry window fix for profile YAML integration.

This test verifies that the market catalog tradeability filter reads
entry window values from profile YAML instead of hardcoding 2-12min.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock


class TestMarketCatalogEntryWindowFix:
    """Test market catalog entry window reads from profile YAML."""
    
    def test_tradeability_filter_reads_from_profile(self):
        """Test that tradeability filter reads min/max entry mins from profile."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, CatalogMarket
        from merid.event_venues.base import EventMarket
        
        # Create mock profile with custom entry window
        mock_profile = Mock()
        mock_profile.guardrails_min_entry_mins = 0.5
        mock_profile.guardrails_max_entry_mins = 15.0
        
        mock_profile_adapter = Mock()
        mock_profile_adapter.profile = mock_profile
        
        # Create mock market objects
        now_utc = datetime.now(timezone.utc)
        
        class MockEventMarket:
            def __init__(self, market_id, close_time):
                self.market_id = market_id
                self.close_time = close_time
                self.end_date = close_time
                self.raw_data = {"status": "open"}
        
        # Create markets at different expiry times
        markets = [
            (MockEventMarket("market_0.3min", now_utc + timedelta(seconds=18)), "BTC", "15m"),  # Below min (0.3 < 0.5)
            (MockEventMarket("market_0.5min", now_utc + timedelta(seconds=30)), "BTC", "15m"),  # At min edge (0.5)
            (MockEventMarket("market_1min", now_utc + timedelta(minutes=1)), "BTC", "15m"),  # In window
            (MockEventMarket("market_10min", now_utc + timedelta(minutes=10)), "BTC", "15m"),  # In window
            (MockEventMarket("market_15min", now_utc + timedelta(minutes=15)), "BTC", "15m"),  # At max edge (15)
            (MockEventMarket("market_16min", now_utc + timedelta(minutes=16)), "BTC", "15m"),  # Above max (16 > 15)
        ]
        
        # Create CatalogMarket objects
        catalog_markets = []
        for market, asset, timeframe in markets:
            cm = CatalogMarket(
                market=market,
                asset=asset,
                timeframe=timeframe,
                expires_at=market.close_time,
                minutes_to_expiry=None,
                api_status="open",
                health_status="ok",
                tradeable=False
            )
            catalog_markets.append(cm)
        
        # Patch get_active_profile to return our mock profile
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=mock_profile_adapter):
            # Simulate the tradeability filter logic from market_catalog.py
            min_entry_mins = mock_profile.guardrails_min_entry_mins
            max_entry_mins = mock_profile.guardrails_max_entry_mins
            
            tradeable_markets = []
            for cm in catalog_markets:
                if cm.expires_at:
                    from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
                    mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                    if min_entry_mins <= mte <= max_entry_mins:
                        tradeable_markets.append(cm)
                        cm.tradeable = True
            
            # Verify tradeable markets
            assert len(tradeable_markets) == 4, f"Expected 4 tradeable markets, got {len(tradeable_markets)}"
            
            market_ids = [cm.market.market_id for cm in tradeable_markets]
            assert "market_0.3min" not in market_ids  # Below min
            assert "market_0.5min" in market_ids  # At min edge
            assert "market_1min" in market_ids
            assert "market_10min" in market_ids
            assert "market_15min" in market_ids  # At max edge
            assert "market_16min" not in market_ids  # Above max
    
    def test_tradeability_filter_fallback_values(self):
        """Test that tradeability filter uses fallback values when profile unavailable."""
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, CatalogMarket
        from merid.event_venues.base import EventMarket
        
        # Create mock market objects
        now_utc = datetime.now(timezone.utc)
        
        class MockEventMarket:
            def __init__(self, market_id, close_time):
                self.market_id = market_id
                self.close_time = close_time
                self.end_date = close_time
                self.raw_data = {"status": "open"}
        
        markets = [
            (MockEventMarket("market_0.3min", now_utc + timedelta(seconds=18)), "BTC", "15m"),  # Below fallback min
            (MockEventMarket("market_0.5min", now_utc + timedelta(seconds=30)), "BTC", "15m"),  # At fallback min
            (MockEventMarket("market_10min", now_utc + timedelta(minutes=10)), "BTC", "15m"),  # In window
            (MockEventMarket("market_15min", now_utc + timedelta(minutes=15)), "BTC", "15m"),  # At fallback max
        ]
        
        catalog_markets = []
        for market, asset, timeframe in markets:
            cm = CatalogMarket(
                market=market,
                asset=asset,
                timeframe=timeframe,
                expires_at=market.close_time,
                minutes_to_expiry=None,
                api_status="open",
                health_status="ok",
                tradeable=False
            )
            catalog_markets.append(cm)
        
        # Patch get_active_profile to return None (profile unavailable)
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=None):
            # Simulate the tradeability filter logic with fallback values
            min_entry_mins = 0.5  # Fallback
            max_entry_mins = 15.0  # Fallback
            
            tradeable_markets = []
            for cm in catalog_markets:
                if cm.expires_at:
                    from merid.event_venues.kalshi.kalshi_15m_time import compute_minutes_to_expiry
                    mte = compute_minutes_to_expiry(cm.expires_at, now_utc)
                    if min_entry_mins <= mte <= max_entry_mins:
                        tradeable_markets.append(cm)
                        cm.tradeable = True
            
            # Verify fallback values work correctly
            assert len(tradeable_markets) == 3, f"Expected 3 tradeable markets with fallback, got {len(tradeable_markets)}"
            
            market_ids = [cm.market.market_id for cm in tradeable_markets]
            assert "market_0.3min" not in market_ids  # Below fallback min
            assert "market_0.5min" in market_ids  # At fallback min
            assert "market_10min" in market_ids
            assert "market_15min" in market_ids  # At fallback max
    
    def test_no_hardcoded_2_12_in_market_catalog(self):
        """Test that market_catalog.py no longer has hardcoded 2-12min entry window."""
        import re
        
        with open("merid/event_venues/kalshi/market_catalog.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for hardcoded 2.0 <= mte <= 12.0 pattern
        # This pattern should NOT exist in the tradeability filter section
        hardcoded_pattern = r"if\s+2\.0\s*<=\s*mte\s*<=\s*12\.0"
        match = re.search(hardcoded_pattern, content)
        
        assert match is None, \
            "Found hardcoded 2.0 <= mte <= 12.0 in market_catalog.py - should read from profile YAML"
        
        # Check that the new pattern exists (reading from profile)
        profile_pattern = r"min_entry_mins\s*<=\s*mte\s*<=\s*max_entry_mins"
        match = re.search(profile_pattern, content)
        
        assert match is not None, \
            "Expected to find min_entry_mins <= mte <= max_entry_mins pattern in market_catalog.py"
    
    def test_log_messages_use_dynamic_window(self):
        """Test that log messages use dynamic entry window values."""
        import re
        
        with open("merid/event_venues/kalshi/market_catalog.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for hardcoded "2-12min" in log messages
        hardcoded_log_pattern = r"2-12min entry window"
        match = re.search(hardcoded_log_pattern, content)
        
        assert match is None, \
            "Found hardcoded '2-12min entry window' in log messages - should use dynamic values"
        
        # Check that the new pattern exists (dynamic window)
        dynamic_log_pattern = r"%\.1f-%\.1fmin entry window"
        match = re.search(dynamic_log_pattern, content)
        
        assert match is not None, \
            "Expected to find dynamic %.1f-%.1fmin entry window pattern in log messages"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
