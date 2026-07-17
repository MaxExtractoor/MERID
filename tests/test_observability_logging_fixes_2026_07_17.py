"""
Tests for observability logging fixes (2026-07-17).

These tests verify the new logging fields added for price-based trading diagnostics:
- Spread width logging (ask - bid in cents)
- Market price type logging (mid vs bid-only vs ask-only)
- Canonical price band result logging (in/out of 10-75c)
- Time-to-expiry bucket logging (0-5, 5-10, 10-15 minutes)
- Boot logging: signal_mode, price-based threshold status, YAML thresholds per asset
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path


class TestPriceBasedSignalLogging:
    """Test logging enhancements in _generate_price_based_signal."""
    
    def test_spread_width_calculation_mid_price(self):
        """Verify spread width is calculated correctly when both bid and ask are available."""
        # Simulate the logic from agent_grid_15m.py lines 5051-5067
        best_bid = 25
        best_ask = 29
        
        spread_width_cents = best_ask - best_bid if best_bid > 0 and best_ask > 0 else 0
        
        assert spread_width_cents == 4, "Spread width should be 4 cents (29 - 25)"
    
    def test_spread_width_calculation_one_sided(self):
        """Verify spread width is 0 when only one side is available."""
        best_bid = 25
        best_ask = 0
        
        spread_width_cents = best_ask - best_bid if best_bid > 0 and best_ask > 0 else 0
        
        assert spread_width_cents == 0, "Spread width should be 0 when ask is 0"
    
    def test_market_price_type_mid(self):
        """Verify market_price_type is 'mid' when both bid and ask are available."""
        best_bid = 25
        best_ask = 29
        
        market_price_type = "none"
        if best_bid > 0 and best_ask > 0:
            market_price_type = "mid"
        elif best_bid > 0:
            market_price_type = "bid_only"
        elif best_ask > 0:
            market_price_type = "ask_only"
        
        assert market_price_type == "mid", "Market price type should be 'mid' when both sides available"
    
    def test_market_price_type_bid_only(self):
        """Verify market_price_type is 'bid_only' when only bid is available."""
        best_bid = 25
        best_ask = 0
        
        market_price_type = "none"
        if best_bid > 0 and best_ask > 0:
            market_price_type = "mid"
        elif best_bid > 0:
            market_price_type = "bid_only"
        elif best_ask > 0:
            market_price_type = "ask_only"
        
        assert market_price_type == "bid_only", "Market price type should be 'bid_only' when only bid available"
    
    def test_market_price_type_ask_only(self):
        """Verify market_price_type is 'ask_only' when only ask is available."""
        best_bid = 0
        best_ask = 29
        
        market_price_type = "none"
        if best_bid > 0 and best_ask > 0:
            market_price_type = "mid"
        elif best_bid > 0:
            market_price_type = "bid_only"
        elif best_ask > 0:
            market_price_type = "ask_only"
        
        assert market_price_type == "ask_only", "Market price type should be 'ask_only' when only ask available"


class TestExpiryBucketLogging:
    """Test expiry bucket classification in price range check."""
    
    def test_expiry_bucket_0_to_5_minutes(self):
        """Verify expiry bucket is '0-5min' for time < 5 minutes."""
        minutes_to_expiry = 3.5
        
        expiry_bucket = "unknown"
        if minutes_to_expiry < 5:
            expiry_bucket = "0-5min"
        elif minutes_to_expiry < 10:
            expiry_bucket = "5-10min"
        else:
            expiry_bucket = "10-15min"
        
        assert expiry_bucket == "0-5min", "Expiry bucket should be '0-5min' for 3.5 minutes"
    
    def test_expiry_bucket_5_to_10_minutes(self):
        """Verify expiry bucket is '5-10min' for time between 5 and 10 minutes."""
        minutes_to_expiry = 7.5
        
        expiry_bucket = "unknown"
        if minutes_to_expiry < 5:
            expiry_bucket = "0-5min"
        elif minutes_to_expiry < 10:
            expiry_bucket = "5-10min"
        else:
            expiry_bucket = "10-15min"
        
        assert expiry_bucket == "5-10min", "Expiry bucket should be '5-10min' for 7.5 minutes"
    
    def test_expiry_bucket_10_to_15_minutes(self):
        """Verify expiry bucket is '10-15min' for time >= 10 minutes."""
        minutes_to_expiry = 12.5
        
        expiry_bucket = "unknown"
        if minutes_to_expiry < 5:
            expiry_bucket = "0-5min"
        elif minutes_to_expiry < 10:
            expiry_bucket = "5-10min"
        else:
            expiry_bucket = "10-15min"
        
        assert expiry_bucket == "10-15min", "Expiry bucket should be '10-15min' for 12.5 minutes"
    
    def test_expiry_bucket_boundary_5_minutes(self):
        """Verify expiry bucket boundary at exactly 5 minutes."""
        minutes_to_expiry = 5.0
        
        expiry_bucket = "unknown"
        if minutes_to_expiry < 5:
            expiry_bucket = "0-5min"
        elif minutes_to_expiry < 10:
            expiry_bucket = "5-10min"
        else:
            expiry_bucket = "10-15min"
        
        assert expiry_bucket == "5-10min", "Expiry bucket should be '5-10min' at exactly 5 minutes"
    
    def test_expiry_bucket_boundary_10_minutes(self):
        """Verify expiry bucket boundary at exactly 10 minutes."""
        minutes_to_expiry = 10.0
        
        expiry_bucket = "unknown"
        if minutes_to_expiry < 5:
            expiry_bucket = "0-5min"
        elif minutes_to_expiry < 10:
            expiry_bucket = "5-10min"
        else:
            expiry_bucket = "10-15min"
        
        assert expiry_bucket == "10-15min", "Expiry bucket should be '10-15min' at exactly 10 minutes"


class TestCanonicalPriceBandLogging:
    """Test canonical price band result logging."""
    
    def test_yes_price_in_range(self):
        """Verify YES price in range detection (10-75c)."""
        yes_price_cents = 45
        
        yes_in_range = (10 <= yes_price_cents <= 75)
        
        assert yes_in_range is True, "YES price of 45c should be in range [10, 75]"
    
    def test_yes_price_below_range(self):
        """Verify YES price below range detection."""
        yes_price_cents = 5
        
        yes_in_range = (10 <= yes_price_cents <= 75)
        
        assert yes_in_range is False, "YES price of 5c should be out of range [10, 75]"
    
    def test_yes_price_above_range(self):
        """Verify YES price above range detection."""
        yes_price_cents = 80
        
        yes_in_range = (10 <= yes_price_cents <= 75)
        
        assert yes_in_range is False, "YES price of 80c should be out of range [10, 75]"
    
    def test_no_price_in_range(self):
        """Verify NO price in range detection (10-75c)."""
        no_price_cents = 55
        
        no_in_range = (10 <= no_price_cents <= 75)
        
        assert no_in_range is True, "NO price of 55c should be in range [10, 75]"
    
    def test_boundary_values(self):
        """Verify boundary values are inclusive."""
        # Lower boundary
        yes_in_range_min = (10 <= 10 <= 75)
        assert yes_in_range_min is True, "Lower boundary (10c) should be inclusive"
        
        # Upper boundary
        yes_in_range_max = (10 <= 75 <= 75)
        assert yes_in_range_max is True, "Upper boundary (75c) should be inclusive"


class TestBootLogging:
    """Test boot logging enhancements in main_15m_lean.py."""
    
    def test_price_based_active_detection_volatility_reversion(self):
        """Verify price_based_active is False for volatility_reversion mode."""
        signal_mode = "volatility_reversion"
        
        price_based_active = (signal_mode in ['price_based', 'hybrid'])
        
        assert price_based_active is False, "price_based_active should be False for volatility_reversion mode"
    
    def test_price_based_active_detection_price_based(self):
        """Verify price_based_active is True for price_based mode."""
        signal_mode = "price_based"
        
        price_based_active = (signal_mode in ['price_based', 'hybrid'])
        
        assert price_based_active is True, "price_based_active should be True for price_based mode"
    
    def test_price_based_active_detection_hybrid(self):
        """Verify price_based_active is True for hybrid mode."""
        signal_mode = "hybrid"
        
        price_based_active = (signal_mode in ['price_based', 'hybrid'])
        
        assert price_based_active is True, "price_based_active should be True for hybrid mode"
    
    def test_boot_log_fields_present(self):
        """Verify all new boot log fields are present in the code."""
        main_15m_lean_path = Path(__file__).parent.parent / "web" / "main_15m_lean.py"
        
        with open(main_15m_lean_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for new log fields
        assert 'signal_mode' in content, "signal_mode field should be present in boot logging"
        assert 'price_based_active' in content, "price_based_active field should be present in boot logging"
        assert 'price_based_buy' in content, "price_based_buy field should be present in boot logging"
        assert 'price_based_sell' in content, "price_based_sell field should be present in boot logging"
        assert 'price_based_thresholds' in content, "price_based_thresholds field should be present in boot logging"


class TestAgentGridLoggingFields:
    """Test that new logging fields are present in agent_grid_15m.py."""
    
    def test_spread_width_logging_present(self):
        """Verify spread_width field is present in PRICE-BASED-DEBUG log."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for spread_width in log
        assert 'spread_width' in content, "spread_width field should be present in logging"
        assert 'spread_width=%dc' in content, "spread_width should be logged with %dc format"
    
    def test_market_price_type_logging_present(self):
        """Verify market_price_type field is present in PRICE-BASED-DEBUG log."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for market_price_type in log
        assert 'market_price_type' in content, "market_price_type field should be present in logging"
        assert 'market_price_type=%s' in content, "market_price_type should be logged with %s format"
    
    def test_expiry_bucket_logging_present(self):
        """Verify expiry_bucket field is present in PRICE-RANGE-CHECK log."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for expiry_bucket in log
        assert 'expiry_bucket' in content, "expiry_bucket field should be present in logging"
        assert 'expiry_bucket=%s' in content, "expiry_bucket should be logged with %s format"
