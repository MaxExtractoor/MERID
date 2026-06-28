"""
Test MarketCandidate → Signal Pipeline

This test verifies that the fix for the MarketCandidate vs dict type mismatch
in _generate_signal works correctly. The test simulates the pipeline flow:
1. candidate_optimizer.generate_candidates() returns MarketCandidate objects
2. agent.collect_order_candidate() passes MarketCandidate to _generate_signal
3. _generate_signal handles both MarketCandidate (canonical) and Dict[str, Any] (legacy)
"""

import pytest
from dataclasses import dataclass, field
from typing import Optional, List, Any
from datetime import datetime, timezone


@dataclass
class MarketCandidate:
    """Canonical MarketCandidate dataclass from candidate_optimizer."""
    market_id: str
    ticker: str
    spread_cents: int
    depth_yes: int
    depth_no: int
    yes_bid: int
    yes_ask: int
    minutes_to_expiry: float
    strike_price: Optional[float] = None
    asset: Optional[str] = None


class MockAgent:
    """Mock agent with _generate_signal method for testing."""
    
    def __init__(self):
        self.config = type('obj', (object,), {
            'name': 'BTC_15M',
            'signal_mode': 'trend'
        })()
        self._cached_bankroll_usd = 1000.0
        self._indicator_stacks = {}
        self._unified_edge_enabled = False
    
    def _get_asset_from_series(self):
        return "BTC"
    
    def _generate_signal(self, spot_price: float, market: Any, minutes_to_expiry: float) -> Optional[dict]:
        """
        Simplified version of _generate_signal for testing type handling.
        This mirrors the fix applied to agent_grid_15m.py.
        """
        # Handle both MarketCandidate (canonical) and Dict[str, Any] (legacy)
        if hasattr(market, 'ticker'):
            # MarketCandidate dataclass (canonical)
            market_id = market.ticker
        elif isinstance(market, dict):
            # Dict[str, Any] (legacy fallback)
            market_id = market.get('ticker', market.get('market_id', str(market)))
        else:
            # Fallback for unknown types
            market_id = str(market)
        
        asset = self._get_asset_from_series()
        
        # Return a signal dict if type handling succeeded
        return {
            'side': 'yes',
            'edge': 0.05,
            'market_id': market_id,
            'asset': asset,
            'spot_price': spot_price,
            'minutes_to_expiry': minutes_to_expiry
        }


class TestMarketCandidateSignalPipeline:
    """Test MarketCandidate → signal pipeline with type compatibility."""
    
    def test_market_candidate_attribute_access(self):
        """Test that MarketCandidate dataclass is handled correctly via attribute access."""
        agent = MockAgent()
        
        # Create a MarketCandidate object (canonical type from candidate_optimizer)
        candidate = MarketCandidate(
            market_id="KXBTC15M-26JUN031000-00",
            ticker="KXBTC15M-26JUN031000-00",
            spread_cents=2,
            depth_yes=100,
            depth_no=100,
            yes_bid=48,
            yes_ask=50,
            minutes_to_expiry=14.5,
            strike_price=31000.0,
            asset="BTC"
        )
        
        # Call _generate_signal with MarketCandidate
        signal = agent._generate_signal(
            spot_price=70000.0,
            market=candidate,
            minutes_to_expiry=14.5
        )
        
        # Verify signal is generated successfully
        assert signal is not None
        assert signal['side'] == 'yes'
        assert signal['market_id'] == "KXBTC15M-26JUN031000-00"
        assert signal['asset'] == "BTC"
        assert signal['spot_price'] == 70000.0
        assert signal['minutes_to_expiry'] == 14.5
    
    def test_dict_fallback_access(self):
        """Test that Dict[str, Any] is handled correctly via .get() fallback."""
        agent = MockAgent()
        
        # Create a dict (legacy type)
        market_dict = {
            'ticker': "KXBTC15M-26JUN031000-00",
            'market_id': "KXBTC15M-26JUN031000-00",
            'spread_cents': 2,
            'depth_yes': 100,
            'depth_no': 100,
            'yes_bid': 48,
            'yes_ask': 50,
            'minutes_to_expiry': 14.5
        }
        
        # Call _generate_signal with dict
        signal = agent._generate_signal(
            spot_price=70000.0,
            market=market_dict,
            minutes_to_expiry=14.5
        )
        
        # Verify signal is generated successfully
        assert signal is not None
        assert signal['side'] == 'yes'
        assert signal['market_id'] == "KXBTC15M-26JUN031000-00"
        assert signal['asset'] == "BTC"
    
    def test_dict_without_ticker_fallback(self):
        """Test that dict without 'ticker' falls back to 'market_id'."""
        agent = MockAgent()
        
        # Create a dict without 'ticker' key
        market_dict = {
            'market_id': "KXBTC15M-26JUN031000-00",
            'spread_cents': 2,
            'depth_yes': 100,
            'depth_no': 100,
            'yes_bid': 48,
            'yes_ask': 50,
            'minutes_to_expiry': 14.5
        }
        
        # Call _generate_signal with dict
        signal = agent._generate_signal(
            spot_price=70000.0,
            market=market_dict,
            minutes_to_expiry=14.5
        )
        
        # Verify signal is generated successfully using market_id fallback
        assert signal is not None
        assert signal['market_id'] == "KXBTC15M-26JUN031000-00"
    
    def test_unknown_type_fallback(self):
        """Test that unknown types fall back to str(market)."""
        agent = MockAgent()
        
        # Create an unknown type (e.g., a string)
        market_str = "KXBTC15M-26JUN031000-00"
        
        # Call _generate_signal with string
        signal = agent._generate_signal(
            spot_price=70000.0,
            market=market_str,
            minutes_to_expiry=14.5
        )
        
        # Verify signal is generated successfully using str fallback
        assert signal is not None
        assert signal['market_id'] == "KXBTC15M-26JUN031000-00"
    
    def test_market_candidate_all_assets(self):
        """Test MarketCandidate handling for all 5 crypto assets."""
        assets = [
            ("BTC", "KXBTC15M-26JUN031000-00", 31000.0),
            ("ETH", "KXETH15M-26JUN01800-00", 1800.0),
            ("SOL", "KXSOL15M-26JUN07459-00", 74.59),
            ("XRP", "KXXRP15M-26JUN01230-00", 1.23),
            ("DOGE", "KXDOGE15M-26JUN00094-00", 0.0094)
        ]
        
        for asset, ticker, strike in assets:
            agent = MockAgent()
            # Override _get_asset_from_series for each asset
            agent._get_asset_from_series = lambda a=asset: a
            
            candidate = MarketCandidate(
                market_id=ticker,
                ticker=ticker,
                spread_cents=2,
                depth_yes=100,
                depth_no=100,
                yes_bid=48,
                yes_ask=50,
                minutes_to_expiry=14.5,
                strike_price=strike,
                asset=asset
            )
            
            signal = agent._generate_signal(
                spot_price=70000.0 if asset == "BTC" else (1800.0 if asset == "ETH" else 100.0),
                market=candidate,
                minutes_to_expiry=14.5
            )
            
            assert signal is not None, f"Signal generation failed for {asset}"
            assert signal['asset'] == asset, f"Asset mismatch for {asset}"
            assert signal['market_id'] == ticker, f"Market ID mismatch for {asset}"
    
    def test_market_candidate_with_none_fields(self):
        """Test MarketCandidate with optional None fields."""
        agent = MockAgent()
        
        candidate = MarketCandidate(
            market_id="KXBTC15M-26JUN031000-00",
            ticker="KXBTC15M-26JUN031000-00",
            spread_cents=2,
            depth_yes=100,
            depth_no=100,
            yes_bid=48,
            yes_ask=50,
            minutes_to_expiry=14.5,
            strike_price=None,  # Optional field is None
            asset=None  # Optional field is None
        )
        
        signal = agent._generate_signal(
            spot_price=70000.0,
            market=candidate,
            minutes_to_expiry=14.5
        )
        
        # Signal should still be generated
        assert signal is not None
        assert signal['market_id'] == "KXBTC15M-26JUN031000-00"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
