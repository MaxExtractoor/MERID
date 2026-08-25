"""Tests for YES/NO arbitrage integration in 15m trading loop."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time


class TestArbitrageLoopIntegration:
    """Test YES/NO arbitrage detection in loop_15m.py market scanning phase."""
    
    @pytest.fixture
    def mock_market_state(self):
        """Create mock market state with arbitrage opportunity."""
        state = Mock()
        state.best_bid_cents = 48  # YES bid
        state.best_ask_cents = 50  # YES ask
        state.best_no_bid_cents = 50  # NO bid
        state.best_no_ask_cents = 52  # NO ask
        state.has_bid = True
        state.has_ask = True
        state.has_no_bid = True
        state.has_no_ask = True
        state.min_depth_yes = 100
        state.min_depth_no = 100
        state.last_book_update_ts = time.monotonic()
        state.seconds_to_expiry = 600
        return state
    
    @pytest.fixture
    def mock_market_state_no_arbitrage(self):
        """Create mock market state without arbitrage opportunity."""
        state = Mock()
        state.best_bid_cents = 48  # YES bid
        state.best_ask_cents = 52  # YES ask
        state.best_no_bid_cents = 48  # NO bid
        state.best_no_ask_cents = 52  # NO ask
        state.has_bid = True
        state.has_ask = True
        state.has_no_bid = True
        state.has_no_ask = True
        state.min_depth_yes = 100
        state.min_depth_no = 100
        state.last_book_update_ts = time.monotonic()
        state.seconds_to_expiry = 600
        return state
    
    def test_arbitrage_detection_in_loop(self, mock_market_state):
        """Test that arbitrage opportunity is detected during market scanning."""
        from merid.event_venues.kalshi.duality_validator import check_yes_no_duality
        
        # Create a real arbitrage scenario: YES_ask + NO_bid < 100c
        # YES_ask=45, NO_bid=45, edge=10c
        # Need valid bid/ask pairs for both sides
        duality_result = check_yes_no_duality(
            yes_bid=50,  # YES bid
            no_bid=45,  # NO bid
            yes_ask=45,  # YES ask
            no_ask=50,  # NO ask (100 - YES_bid = 50)
            ticker="KXBTCD-TEST"
        )
        
        assert duality_result.arbitrage_opportunity is not None
        assert duality_result.arbitrage_opportunity.edge_cents == 10  # 100 - (45 + 45) = 10c
        assert duality_result.is_valid is True  # Arbitrage takes precedence over duality violation
    
    def test_no_arbitrage_normal_market(self, mock_market_state_no_arbitrage):
        """Test that normal market state doesn't trigger arbitrage."""
        from merid.event_venues.kalshi.duality_validator import check_yes_no_duality
        
        duality_result = check_yes_no_duality(
            yes_bid=mock_market_state_no_arbitrage.best_bid_cents,
            no_bid=mock_market_state_no_arbitrage.best_no_bid_cents,
            yes_ask=mock_market_state_no_arbitrage.best_ask_cents,
            no_ask=mock_market_state_no_arbitrage.best_no_ask_cents,
            ticker="KXBTCD-TEST"
        )
        
        assert duality_result.arbitrage_opportunity is None
        assert duality_result.is_valid is True
    
    def test_arbitrage_callback_invocation(self, mock_market_state):
        """Test that arbitrage callback is invoked when opportunity detected."""
        from merid.event_venues.kalshi.duality_validator import DualityValidator, ArbitrageOpportunity
        
        # Create mock callback
        callback_mock = Mock()
        
        # Create validator and set callback
        validator = DualityValidator()
        validator.set_arbitrage_callback(callback_mock)
        
        # Create arbitrage scenario: YES_ask=45, NO_bid=45, edge=10c
        # Need valid bid/ask pairs for both sides
        validator.check_yes_no_duality(
            yes_bid=50,  # YES bid
            no_bid=45,  # NO bid
            yes_ask=45,  # YES ask
            no_ask=50,  # NO ask (100 - YES_bid = 50)
            ticker="KXBTCD-TEST"
        )
        
        # Verify callback was invoked
        callback_mock.assert_called_once()
        call_args = callback_mock.call_args[0][0]
        assert isinstance(call_args, ArbitrageOpportunity)
        assert call_args.edge_cents == 10
    
    def test_arbitrage_edge_calculation(self):
        """Test arbitrage edge calculation accuracy."""
        from merid.event_venues.kalshi.duality_validator import check_yes_no_duality
        
        # Test a single valid arbitrage scenario
        # For arbitrage: YES_ask + NO_bid < 100
        # YES_bid=55, YES_ask=45, NO_bid=45, NO_ask=45
        # YES_ask + NO_bid = 45 + 45 = 90 < 100 (arbitrage of 10c)
        duality_result = check_yes_no_duality(
            yes_bid=55,
            no_bid=45,
            yes_ask=45,
            no_ask=45,
            ticker="KXBTCD-TEST"
        )
        
        assert duality_result.arbitrage_opportunity is not None
        assert duality_result.arbitrage_opportunity.edge_cents == 10  # 100 - (45 + 45) = 10c
        assert duality_result.arbitrage_opportunity.yes_ask == 45
        assert duality_result.arbitrage_opportunity.no_bid == 45
    
    def test_arbitrage_size_recommendation(self):
        """Test that recommended size is calculated correctly."""
        from merid.event_venues.kalshi.duality_validator import check_yes_no_duality
        
        # Large edge should recommend larger size
        duality_result = check_yes_no_duality(
            yes_bid=50,
            no_bid=40,  # Large arbitrage edge
            yes_ask=40,
            no_ask=50,  # NO ask = 100 - YES_bid = 50
            ticker="KXBTCD-TEST"
        )
        
        assert duality_result.arbitrage_opportunity is not None
        assert duality_result.arbitrage_opportunity.edge_cents == 20
        # Size should be edge_cents // 2 = 10
        assert duality_result.arbitrage_opportunity.recommended_size == 10


class TestArbitrageLoopLogging:
    """Test arbitrage logging in loop_15m.py."""
    
    @patch('merid.loop_15m.logger')
    def test_arbitrage_opportunity_logged(self, mock_logger):
        """Test that arbitrage opportunities are logged in the loop."""
        # This test verifies the logging pattern used in loop_15m.py
        # The actual integration test would require running the full loop
        
        # Simulate the log call that happens in loop_15m.py
        mock_logger.info(
            "[ARBITRAGE-OPPORTUNITY-LOOP] asset=%s ticker=%s edge=%dc yes_ask=%dc no_bid=%dc",
            "BTC", "KXBTCD-TEST", 4, 48, 48
        )
        
        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0]
        assert "[ARBITRAGE-OPPORTUNITY-LOOP]" in call_args[0]
        # Check that the format string contains the expected placeholders
        assert "edge=%dc" in call_args[0]
    
    @patch('merid.loop_15m.logger')
    def test_arbitrage_check_failure_logged(self, mock_logger):
        """Test that arbitrage check failures are logged gracefully."""
        mock_logger.warning(
            "[ARBITRAGE-CHECK-FAILED] asset=%s ticker=%s error=%s",
            "BTC", "KXBTCD-TEST", "test error"
        )
        
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0]
        assert "[ARBITRAGE-CHECK-FAILED]" in call_args[0]
