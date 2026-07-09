"""Test market catalog filter fix for max_minutes_to_expiry parameter.

This test verifies that the market catalog correctly filters markets
using the 0.5-15 minute entry window from the profile configuration.
"""

import pytest
from datetime import datetime, timezone, timedelta
from merid.event_venues.kalshi.kalshi_15m_time import select_live_markets_by_ts


class TestMarketCatalogFilterFix:
    """Test market catalog filter fix for max_minutes_to_expiry."""
    
    def test_select_live_markets_default_max_15_minutes(self):
        """Test that select_live_markets_by_ts defaults to 15 minute max window."""
        # Create mock market objects
        class MockMarket:
            def __init__(self, market_id, close_time, asset="BTC"):
                self.market_id = market_id
                self.close_time = close_time
                self.expires_at = close_time
                self.asset = asset
                self.market = type('obj', (object,), {
                    'market_id': market_id,
                    'close_time': close_time,
                    'open_time': None
                })()
        
        now_utc = datetime.now(timezone.utc)
        
        # Create markets at different expiry times
        markets = [
            MockMarket("market_0min", now_utc + timedelta(seconds=30)),  # Too early (0.5 min)
            MockMarket("market_1min", now_utc + timedelta(minutes=1)),  # In window (1 min)
            MockMarket("market_3min", now_utc + timedelta(minutes=3)),  # In window (3 min)
            MockMarket("market_10min", now_utc + timedelta(minutes=10)),  # In window (10 min)
            MockMarket("market_15min", now_utc + timedelta(minutes=15)),  # At edge (15 min)
            MockMarket("market_16min", now_utc + timedelta(minutes=16)),  # Too late (16 min)
        ]
        
        # Test with default parameters (0.5-15 minute window)
        live_markets = select_live_markets_by_ts(markets, now_utc=now_utc)
        
        # Should include markets at 1, 3, 10, and 15 minutes
        assert len(live_markets) == 4, f"Expected 4 live markets, got {len(live_markets)}"
        market_ids = [m.market_id for m in live_markets]
        assert "market_1min" in market_ids
        assert "market_3min" in market_ids
        assert "market_10min" in market_ids
        assert "market_15min" in market_ids
        assert "market_0min" not in market_ids  # Below min
        assert "market_16min" not in market_ids  # Above max
    
    def test_select_live_markets_custom_max_15_minutes(self):
        """Test that select_live_markets_by_ts accepts custom max_minutes_to_expiry=15.0."""
        class MockMarket:
            def __init__(self, market_id, close_time, asset="BTC"):
                self.market_id = market_id
                self.close_time = close_time
                self.expires_at = close_time
                self.asset = asset
                self.market = type('obj', (object,), {
                    'market_id': market_id,
                    'close_time': close_time,
                    'open_time': None
                })()
        
        now_utc = datetime.now(timezone.utc)
        
        markets = [
            MockMarket("market_0min", now_utc + timedelta(seconds=30)),
            MockMarket("market_1min", now_utc + timedelta(minutes=1)),
            MockMarket("market_10min", now_utc + timedelta(minutes=10)),
            MockMarket("market_15min", now_utc + timedelta(minutes=15)),
            MockMarket("market_20min", now_utc + timedelta(minutes=20)),
        ]
        
        # Test with explicit 0.5-15 minute window
        live_markets = select_live_markets_by_ts(
            markets,
            min_minutes_to_expiry=0.5,
            max_minutes_to_expiry=15.0,
            now_utc=now_utc
        )
        
        # Should include markets at 1, 10, and 15 minutes (0.5 min is below min, 20 min is above max)
        assert len(live_markets) == 3, f"Expected 3 live markets, got {len(live_markets)}"
        market_ids = [m.market_id for m in live_markets]
        assert "market_1min" in market_ids
        assert "market_10min" in market_ids
        assert "market_15min" in market_ids
        assert "market_0min" not in market_ids
        assert "market_20min" not in market_ids
    
    def test_select_live_markets_keyword_argument_order(self):
        """Test that select_live_markets_by_ts works with keyword arguments in correct order."""
        class MockMarket:
            def __init__(self, market_id, close_time, asset="BTC"):
                self.market_id = market_id
                self.close_time = close_time
                self.expires_at = close_time
                self.asset = asset
                self.market = type('obj', (object,), {
                    'market_id': market_id,
                    'close_time': close_time,
                    'open_time': None
                })()
        
        now_utc = datetime.now(timezone.utc)
        
        markets = [
            MockMarket("market_1min", now_utc + timedelta(minutes=1)),
            MockMarket("market_5min", now_utc + timedelta(minutes=5)),
            MockMarket("market_12min", now_utc + timedelta(minutes=12)),
        ]
        
        # Test with keyword arguments (as called from market_catalog.py)
        live_markets = select_live_markets_by_ts(
            markets,
            now_utc=None,  # Use current time
            min_minutes_to_expiry=0.5,
            max_minutes_to_expiry=15.0,
            require_exactly_one_per_asset=False
        )
        
        # Should include all three markets
        assert len(live_markets) == 3, f"Expected 3 live markets, got {len(live_markets)}"
    
    def test_max_entry_mins_in_profile(self):
        """Test that max_entry_mins is configured as 15.0 in profile."""
        import yaml
        
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check guardrails section exists
        assert "guardrails" in profile
        
        guardrails = profile["guardrails"]
        
        # Check max_entry_mins is 15.0
        assert "max_entry_mins" in guardrails
        assert guardrails["max_entry_mins"] == 15.0, \
            f"Expected max_entry_mins=15.0, got {guardrails['max_entry_mins']}"
        
        # Check min_entry_mins is 0.5 (relaxed from 2.0 to allow full window trading)
        assert "min_entry_mins" in guardrails
        assert guardrails["min_entry_mins"] == 0.5, \
            f"Expected min_entry_mins=0.5, got {guardrails['min_entry_mins']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
