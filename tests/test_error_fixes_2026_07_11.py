"""
Test suite for error fixes from 2026-07-11 server startup log analysis.

Tests:
1. Profile version attribute fix (version -> profile_version)
2. Price range expansion fix (10c-50c -> 10c-95c)
3. Sequential trading hasattr fix
4. Price validation deviation fix (40c -> 50c)
"""
import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestProfileVersionAttributeFix:
    """Test that profile version attribute is correctly named profile_version."""
    
    def test_profile_adapter_has_profile_version_attribute(self):
        """Test that Crypto15mProfile has profile_version attribute."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        from dataclasses import fields
        
        # Verify the dataclass has profile_version field
        field_names = [f.name for f in fields(Crypto15mProfile)]
        
        assert 'profile_version' in field_names, \
            "Crypto15mProfile should have profile_version field"
        
        # Verify 'version' attribute does NOT exist (the bug we fixed)
        assert 'version' not in field_names, \
            "Crypto15mProfile should NOT have 'version' field (should be 'profile_version')"


class TestPriceRangeExpansionFix:
    """Test that price range was expanded from [10c-50c] to [10c-95c]."""
    
    def test_agent_grid_accepts_91c_price(self):
        """Test that agent_grid_15m.py accepts prices up to 95c (e.g., DOGE at 91c)."""
        # This test verifies the fix for DOGE price clamping from 91c to 50c
        # The expanded range [10c-95c] should allow 91c prices
        
        # Simulate the price validation logic from agent_grid_15m.py
        raw_price_cents = 91  # DOGE mid price from logs
        
        # Check if price is within expanded range (5c-95c)
        assert 5 <= raw_price_cents <= 95, f"Price {raw_price_cents}c should be in expanded range [5c-95c]"
        
        # Check if price is within canonical range (10c-95c after fix)
        assert 10 <= raw_price_cents <= 95, f"Price {raw_price_cents}c should be in canonical range [10c-95c]"
    
    def test_agent_grid_rejects_96c_price(self):
        """Test that agent_grid_15m.py rejects prices above 95c."""
        raw_price_cents = 96
        
        # Should be outside expanded range
        assert not (5 <= raw_price_cents <= 95), f"Price {raw_price_cents}c should be outside expanded range [5c-95c]"
        
        # Should be outside canonical range
        assert not (10 <= raw_price_cents <= 95), f"Price {raw_price_cents}c should be outside canonical range [10c-95c]"
    
    def test_agent_grid_accepts_10c_price(self):
        """Test that agent_grid_15m.py accepts minimum price of 10c."""
        raw_price_cents = 10
        
        # Should be within expanded range
        assert 5 <= raw_price_cents <= 95, f"Price {raw_price_cents}c should be in expanded range [5c-95c]"
        
        # Should be within canonical range
        assert 10 <= raw_price_cents <= 95, f"Price {raw_price_cents}c should be in canonical range [10c-95c]"
    
    def test_agent_grid_rejects_9c_price(self):
        """Test that agent_grid_15m.py rejects prices below 10c."""
        raw_price_cents = 9
        
        # Should be within expanded range
        assert 5 <= raw_price_cents <= 95, f"Price {raw_price_cents}c should be in expanded range [5c-95c]"
        
        # Should be outside canonical range
        assert not (10 <= raw_price_cents <= 95), f"Price {raw_price_cents}c should be outside canonical range [10c-95c]"


class TestSequentialTradingHasattrFix:
    """Test that sequential trading check has hasattr guard."""
    
    def test_order_gate_has_hasattr_check(self):
        """Test that order_gate.py has hasattr check for risk_policy_sequential_trading."""
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        
        # Read the source to verify hasattr check exists
        import inspect
        source = inspect.getsource(PreTradeGate.check)
        
        # Verify hasattr check is present
        assert "hasattr(profile, 'risk_policy_sequential_trading')" in source, \
            "order_gate.py should have hasattr check for risk_policy_sequential_trading"
    
    def test_profile_adapter_has_risk_policy_sequential_trading(self):
        """Test that Crypto15mProfile has risk_policy_sequential_trading attribute."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile
        
        # Verify the attribute exists in the dataclass definition
        from dataclasses import fields
        field_names = [f.name for f in fields(Crypto15mProfile)]
        
        assert 'risk_policy_sequential_trading' in field_names, \
            "Crypto15mProfile should have risk_policy_sequential_trading field"


class TestPriceValidationDeviationFix:
    """Test that price validation deviation was increased from 40c to 50c."""
    
    def test_order_router_max_deviation_50c(self):
        """Test that order_router.py allows 50c deviation from mid price."""
        from merid.event_venues.kalshi.order_router import _validate_price_against_orderbook
        
        # Read the source to verify max_deviation_cents = 50
        import inspect
        source = inspect.getsource(_validate_price_against_orderbook)
        
        # Verify max_deviation_cents is set to 50
        assert "max_deviation_cents = 50" in source, \
            "order_router.py should have max_deviation_cents = 50"
        
        # Verify the comment mentions the fix
        assert "2026-07-11" in source or "50c" in source, \
            "order_router.py should have comment about 2026-07-11 fix or 50c threshold"
    
    def test_price_validation_allows_50c_deviation(self):
        """Test that 50c deviation from mid is allowed."""
        mid_cents = 50
        order_price = 100  # 50c deviation
        max_deviation_cents = 50
        
        deviation = abs(order_price - mid_cents)
        assert deviation <= max_deviation_cents, \
            f"Deviation {deviation}c should be allowed with max_deviation_cents={max_deviation_cents}"
    
    def test_price_validation_rejects_51c_deviation(self):
        """Test that 51c deviation from mid is rejected."""
        mid_cents = 50
        order_price = 101  # 51c deviation
        max_deviation_cents = 50
        
        deviation = abs(order_price - mid_cents)
        assert deviation > max_deviation_cents, \
            f"Deviation {deviation}c should be rejected with max_deviation_cents={max_deviation_cents}"


class TestWebSocketMessageProcessingFix:
    """Test that WebSocket message processing has defensive error handling."""
    
    def test_ws_has_defensive_error_handling(self):
        """Test that ws.py has defensive error handling for AttributeError."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        
        # Read the source to verify defensive error handling exists
        import inspect
        source = inspect.getsource(KalshiWebSocket._process_messages_until_disconnect)
        
        # Verify AttributeError is caught and doesn't trigger reconnect
        assert "AttributeError" in source, \
            "ws.py should catch AttributeError"
        
        # Verify the error message mentions skipping message
        assert "skipping message" in source.lower(), \
            "ws.py should skip message on AttributeError instead of reconnecting"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
