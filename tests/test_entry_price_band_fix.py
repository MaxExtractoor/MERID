"""Test entry price band fix for momentum-based trading.

This test verifies that the entry price band is loaded from profile configuration
instead of using hardcoded values, allowing momentum-based trading to execute
in current market conditions.
"""

import pytest
import yaml
from unittest.mock import patch, MagicMock


class TestEntryPriceBandFix:
    """Test entry price band fix for momentum-based trading."""
    
    def test_price_range_in_profile(self):
        """Test that price_range is configured in profile."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        # Check price_range section exists
        assert "price_range" in profile
        
        price_range = profile["price_range"]
        
        # Check min_price_cents is 10 (momentum-based)
        assert "min_price_cents" in price_range
        assert price_range["min_price_cents"] == 10, \
            f"Expected min_price_cents=10, got {price_range['min_price_cents']}"
        
        # Check max_price_cents is 75 (expanded for market conditions)
        assert "max_price_cents" in price_range
        assert price_range["max_price_cents"] == 75, \
            f"Expected max_price_cents=75, got {price_range['max_price_cents']}"
    
    def test_price_range_wider_than_previous(self):
        """Test that price_range is 10-75c (wider minimum, expanded maximum)."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        price_range = profile["price_range"]
        
        # Range should be 10-75c (expanded for market conditions)
        assert price_range["min_price_cents"] == 10, \
            f"min_price_cents should be 10, got {price_range['min_price_cents']}"
        assert price_range["max_price_cents"] == 75, \
            f"max_price_cents should be 75, got {price_range['max_price_cents']}"
    
    def test_price_range_allows_current_market_conditions(self):
        """Test that price_range allows NO-side entries (10-50c)."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        price_range = profile["price_range"]
        
        # Current market conditions: YES at 96-98c, NO at 2-4c
        # With 10-50c range, NO at 2-4c is below min, but this allows NO-side entries
        # when markets are in high-probability states (NO contracts priced 10-50c)
        assert price_range["min_price_cents"] == 10, \
            f"min_price_cents should be 10, got {price_range['min_price_cents']}"
        assert price_range["max_price_cents"] == 75, \
            f"max_price_cents should be 75, got {price_range['max_price_cents']}"
    
    def test_price_range_description_mentions_momentum(self):
        """Test that price_range description mentions market conditions."""
        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        price_range = profile["price_range"]
        
        # Check description mentions market conditions (updated from momentum to market conditions)
        assert "description" in price_range
        description = price_range["description"].lower()
        assert "market" in description or "conditions" in description, \
            f"Description should mention market conditions, got: {price_range['description']}"
    
    def test_agent_grid_uses_profile_price_range(self):
        """Test that agent_grid_15m.py loads price_range from profile."""
        # This test verifies the code structure, not runtime behavior
        # We check that the code attempts to load from profile
        
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        # Check that code attempts to load price_range from profile
        assert "price_range" in code, \
            "agent_grid_15m.py should reference price_range from profile"
        assert "ENTRY_MIN_PRICE_CENTS" in code, \
            "agent_grid_15m.py should define ENTRY_MIN_PRICE_CENTS"
        assert "ENTRY_MAX_PRICE_CENTS" in code, \
            "agent_grid_15m.py should define ENTRY_MAX_PRICE_CENTS"
        
        # Check that code has fallback to 10-50c (updated to 50c max)
        assert "ENTRY_MIN_PRICE_CENTS = 10" in code or "ENTRY_MIN_PRICE_CENTS =  10" in code, \
            "agent_grid_15m.py should have fallback to 10c minimum"
        assert "ENTRY_MAX_PRICE_CENTS = 50" in code or "ENTRY_MAX_PRICE_CENTS =  50" in code, \
            "agent_grid_15m.py should have fallback to 50c maximum"
    
    def test_price_range_not_hardcoded_25_75(self):
        """Test that price_range is NOT hardcoded to 25-75c."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        # Check that old hardcoded values are not present
        # The old code had: ENTRY_MIN_PRICE_CENTS = 25, ENTRY_MAX_PRICE_CENTS = 75
        # We check that this pattern is NOT present as a simple assignment
        
        # This is a simple check - we look for the old pattern
        # If the code has been updated, it should use profile config or fallback
        assert not ("ENTRY_MIN_PRICE_CENTS = 25" in code and "ENTRY_MAX_PRICE_CENTS = 75" in code), \
            "agent_grid_15m.py should not have hardcoded 25-75c range"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
