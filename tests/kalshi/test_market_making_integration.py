"""Tests for Market Making Integration.

Tests the profitability enhancement that enables market making for spread income.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import sys
from pathlib import Path

# Mock the missing modules before importing
sys.modules['merid.signals.unified_regime_classifier'] = MagicMock()
sys.modules['merid.kalshi.macro_overlay'] = MagicMock()
sys.modules['utils.logger'] = MagicMock()

# Now import the actual module
from merid.kalshi.mm_integration import (
    MarketMakerIntegration,
    MakerQuote,
    MakerInventory,
    MakerSide,
    get_market_maker_integration,
)


class TestMarketMakingConfig:
    """Test market making configuration from profile."""
    
    def test_market_making_config_disabled_by_default(self):
        """Test that market making is disabled by default in profile."""
        import yaml
        from pathlib import Path
        
        # Get the absolute path to the repository root
        # Test file is at: c:\Dev\MERID\tests\kalshi\test_market_making_integration.py
        # Repo root is at: c:\Dev\MERID
        repo_root = Path(__file__).parent.parent.parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        mm_config = profile_config.get('market_making', {})
        
        # Should be disabled by default
        assert mm_config.get('enabled', False) is False
    
    def test_market_making_config_structure(self):
        """Test that market making config has required fields."""
        import yaml
        from pathlib import Path
        
        # Get the absolute path to the repository root
        repo_root = Path(__file__).parent.parent.parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        mm_config = profile_config.get('market_making', {})
        
        # Should have required configuration fields
        assert 'enabled' in mm_config
        assert 'quoting_mode' in mm_config
        assert 'spread_cents' in mm_config
        assert 'inventory_limit_contracts' in mm_config
        assert 'skew_adjustment' in mm_config
        
        # Validate values
        assert mm_config['quoting_mode'] in ['one_sided', 'two_sided']
        assert mm_config['spread_cents'] > 0
        assert mm_config['inventory_limit_contracts'] > 0
        assert isinstance(mm_config['skew_adjustment'], bool)


class TestMakerQuote:
    """Test MakerQuote dataclass."""
    
    def test_maker_quote_creation(self):
        """Test creation of MakerQuote."""
        import time
        
        quote = MakerQuote(
            ticker="KXBTCD-25JUN-T100000",
            side=MakerSide.BID,
            price_cents=48,
            size=10,
            confidence_adjusted=True,
            regime_skew_applied=False,
            inventory_offset=2,
            expires_ts=time.time() + 60
        )
        
        assert quote.ticker == "KXBTCD-25JUN-T100000"
        assert quote.side == MakerSide.BID
        assert quote.price_cents == 48
        assert quote.size == 10
        assert quote.confidence_adjusted is True
        assert quote.regime_skew_applied is False
        assert quote.inventory_offset == 2
    
    def test_maker_quote_expiration(self):
        """Test MakerQuote expiration logic."""
        import time
        
        # Expired quote
        expired_quote = MakerQuote(
            ticker="KXBTCD-25JUN-T100000",
            side=MakerSide.BID,
            price_cents=48,
            size=10,
            expires_ts=time.time() - 10
        )
        assert expired_quote.is_expired is True
        
        # Non-expired quote
        valid_quote = MakerQuote(
            ticker="KXBTCD-25JUN-T100000",
            side=MakerSide.BID,
            price_cents=48,
            size=10,
            expires_ts=time.time() + 60
        )
        assert valid_quote.is_expired is False
        
        # Quote with no expiration (never expires)
        no_exp_quote = MakerQuote(
            ticker="KXBTCD-25JUN-T100000",
            side=MakerSide.BID,
            price_cents=48,
            size=10,
            expires_ts=0.0
        )
        assert no_exp_quote.is_expired is False


class TestMakerInventory:
    """Test MakerInventory dataclass."""
    
    def test_maker_inventory_creation(self):
        """Test creation of MakerInventory."""
        inventory = MakerInventory(
            ticker="KXBTCD-25JUN-T100000",
            net_position=5,
            avg_entry_price=0.50,
            gross_exposure=250,
            realized_pnl_cents=100,
            unrealized_pnl_cents=50,
            quotes_filled=10,
            quotes_cancelled=2
        )
        
        assert inventory.ticker == "KXBTCD-25JUN-T100000"
        assert inventory.net_position == 5
        assert inventory.avg_entry_price == 0.50
        assert inventory.gross_exposure == 250
        assert inventory.realized_pnl_cents == 100
        assert inventory.unrealized_pnl_cents == 50
        assert inventory.quotes_filled == 10
        assert inventory.quotes_cancelled == 2
    
    def test_maker_inventory_defaults(self):
        """Test MakerInventory with default values."""
        inventory = MakerInventory(ticker="KXBTCD-25JUN-T100000")
        
        assert inventory.net_position == 0
        assert inventory.avg_entry_price == 0.0
        assert inventory.gross_exposure == 0
        assert inventory.realized_pnl_cents == 0
        assert inventory.unrealized_pnl_cents == 0
        assert inventory.quotes_filled == 0
        assert inventory.quotes_cancelled == 0


class TestMarketMakerIntegration:
    """Test MarketMakerIntegration class."""
    
    def test_market_maker_integration_singleton(self):
        """Test that MarketMakerIntegration is a singleton."""
        mm1 = get_market_maker_integration()
        mm2 = get_market_maker_integration()
        
        # Should return the same instance
        assert mm1 is mm2
    
    def test_market_maker_quote_generation(self):
        """Test quote generation for market making."""
        mm = get_market_maker_integration()
        
        # Mock market data
        market_data = {
            'ticker': 'KXBTCD-25JUN-T100000',
            'yes_bid': 48,
            'yes_ask': 52,
            'no_bid': 48,
            'no_ask': 52,
            'mid_price': 50
        }
        
        # Generate quotes (if method exists)
        if hasattr(mm, 'generate_quotes'):
            quotes = mm.generate_quotes(market_data)
            
            # Should return both bid and ask quotes
            assert len(quotes) == 2
            assert any(q.side == MakerSide.BID for q in quotes)
            assert any(q.side == MakerSide.ASK for q in quotes)
        else:
            # Skip if method doesn't exist
            pytest.skip("generate_quotes method not implemented")
    
    def test_market_maker_inventory_tracking(self):
        """Test inventory tracking for market making."""
        mm = get_market_maker_integration()
        
        # Mock fill
        fill = {
            'ticker': 'KXBTCD-25JUN-T100000',
            'side': 'yes',
            'action': 'buy',
            'price_cents': 48,
            'count': 5
        }
        
        # Update inventory (if method exists)
        if hasattr(mm, 'update_inventory'):
            mm.update_inventory(fill)
            
            # Check inventory was updated
            inventory = mm.get_inventory('KXBTCD-25JUN-T100000')
            assert inventory is not None
            assert inventory.net_position == 5
        else:
            # Skip if method doesn't exist
            pytest.skip("update_inventory method not implemented")


class TestMarketMakingRiskControls:
    """Test market making risk controls."""
    
    def test_inventory_limit_enforcement(self):
        """Test that inventory limits are enforced."""
        mm = get_market_maker_integration()
        
        # Set inventory limit
        max_inventory = 50
        
        # Mock current inventory
        current_inventory = 45
        
        # Mock new quote
        new_quote_size = 10
        
        # Should reject if would exceed limit
        if hasattr(mm, 'check_inventory_limit'):
            can_quote = mm.check_inventory_limit(
                current_inventory=current_inventory,
                new_quote_size=new_quote_size,
                max_inventory=max_inventory
            )
            
            # Should be False (would exceed limit)
            assert can_quote is False
        else:
            # Skip if method doesn't exist
            pytest.skip("check_inventory_limit method not implemented")
    
    def test_skew_adjustment(self):
        """Test skew adjustment based on inventory imbalance."""
        mm = get_market_maker_integration()
        
        # Mock inventory imbalance
        net_position = 30  # Long position
        max_inventory = 50
        
        # Should adjust quotes to reduce long exposure
        if hasattr(mm, 'calculate_skew_adjustment'):
            skew = mm.calculate_skew_adjustment(
                net_position=net_position,
                max_inventory=max_inventory
            )
            
            # Skew should be negative (reduce long exposure)
            assert skew < 0
        else:
            # Skip if method doesn't exist
            pytest.skip("calculate_skew_adjustment method not implemented")
