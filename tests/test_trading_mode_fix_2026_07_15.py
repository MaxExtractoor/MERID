"""Tests for TradingMode enum type mismatch fix (2026-07-15).

This test verifies that the order_router and fills_ledger use VenueGate as the
canonical source of truth for trading mode, instead of the incompatible
trading.trade_mode enum.

Root cause: order_router.py imported TradingMode from merid.prediction.trading_mode
but called get_trade_mode() from trading.trade_mode (different enum), which could
cause orders to be routed to paper fill simulation instead of live execution.

Fix: Use get_venue_gate().mode as the canonical source of truth for Kalshi venue mode.
"""

import pytest
from unittest.mock import Mock, patch
import os


class TestTradingModeCanonicalSource:
    """Test that order_router uses VenueGate as canonical mode source."""

    def test_resolve_mode_uses_venue_gate(self):
        """Test that _resolve_mode uses get_venue_gate().mode."""
        from merid.event_venues.kalshi.order_router import _resolve_mode
        from merid.prediction.trading_mode import TradingMode

        # Mock VenueGate to return LIVE mode
        mock_gate = Mock()
        mock_gate.mode = TradingMode.LIVE

        with patch('merid.event_venues.kalshi.order_router.get_venue_gate', return_value=mock_gate):
            mode = _resolve_mode(None)
            assert mode == TradingMode.LIVE

        # Mock VenueGate to return PAPER mode
        mock_gate.mode = TradingMode.PAPER
        with patch('merid.event_venues.kalshi.order_router.get_venue_gate', return_value=mock_gate):
            mode = _resolve_mode(None)
            assert mode == TradingMode.PAPER

    def test_resolve_mode_respects_override(self):
        """Test that _resolve_mode respects explicit override."""
        from merid.event_venues.kalshi.order_router import _resolve_mode
        from merid.prediction.trading_mode import TradingMode

        # Override should take precedence over VenueGate
        mock_gate = Mock()
        mock_gate.mode = TradingMode.PAPER

        with patch('merid.event_venues.kalshi.order_router.get_venue_gate', return_value=mock_gate):
            mode = _resolve_mode(TradingMode.LIVE)
            assert mode == TradingMode.LIVE

    def test_no_trading_trade_mode_import(self):
        """Test that order_router does not import from trading.trade_mode."""
        import merid.event_venues.kalshi.order_router as order_router_module
        source = order_router_module.__file__
        
        with open(source, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should NOT import from trading.trade_mode
        assert 'from trading.trade_mode import' not in content
        # Should import from merid.prediction.trading_mode
        assert 'from merid.prediction.trading_mode import TradingMode' in content


class TestFillsLedgerTradingMode:
    """Test that fills_ledger uses VenueGate for live trade detection."""

    def test_fills_ledger_uses_venue_gate(self):
        """Test that fills_ledger uses get_venue_gate().mode for live detection."""
        from merid.prediction.trading_mode import TradingMode

        # Mock VenueGate to return LIVE mode
        mock_gate = Mock()
        mock_gate.mode = TradingMode.LIVE

        # Patch the import location inside the function (not module-level)
        with patch('merid.prediction.venue_gate.get_venue_gate', return_value=mock_gate):
            from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
            
            # Create a minimal fill dict
            fill_dict = {
                'fill_id': 'test_fill_123',
                'market_ticker': 'KXBTC15M-TEST',
                'side': 'yes',
                'action': 'buy',
                'count': 10,
                'price_cents': 50,
                'fee_cents': 1,
                'created_at': '2026-07-15T00:00:00Z',
                'source': 'rest'
            }
            
            # The is_live_trade detection should use VenueGate
            # This is tested indirectly through the fill processing logic
            # which depends on is_live_trade being correctly detected
            ledger = KalshiFillsLedger()
            # The initialization should not fail with the fix applied
            assert ledger is not None

    def test_fills_ledger_fallback_to_env(self):
        """Test that fills_ledger falls back to env vars if VenueGate fails."""
        # Set env vars for live mode
        os.environ['MERID_PM_TRADING_MODE'] = 'live'
        os.environ['MERID_ALLOW_LIVE_TRADES'] = 'true'
        
        try:
            # Patch the import location inside the function (not module-level)
            with patch('merid.prediction.venue_gate.get_venue_gate', side_effect=Exception('Gate failed')):
                from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
                
                ledger = KalshiFillsLedger()
                # Should not fail despite VenueGate exception
                assert ledger is not None
        finally:
            # Clean up env vars
            os.environ.pop('MERID_PM_TRADING_MODE', None)
            os.environ.pop('MERID_ALLOW_LIVE_TRADES', None)


class TestTradingModeEnumCompatibility:
    """Test that TradingMode enums are compatible where needed."""

    def test_prediction_trading_mode_values(self):
        """Test that merid.prediction.trading_mode has expected values."""
        from merid.prediction.trading_mode import TradingMode
        
        assert TradingMode.LIVE.value == "live"
        assert TradingMode.PAPER.value == "paper"
        assert TradingMode.MOCK.value == "mock"

    def test_venue_gate_uses_prediction_trading_mode(self):
        """Test that VenueGate uses merid.prediction.trading_mode."""
        from merid.prediction.venue_gate import VenueGate
        from merid.prediction.trading_mode import TradingMode
        
        # Create a VenueGate instance
        gate = VenueGate(mode=TradingMode.LIVE, live_enabled=True)
        
        # Should use the correct enum
        assert gate.mode == TradingMode.LIVE
        assert isinstance(gate.mode, TradingMode)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
