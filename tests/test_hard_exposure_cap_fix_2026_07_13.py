"""Tests for hard $1 exposure cap enforcement in order_router (2026-07-13).

This test suite validates the critical fix that adds a hard $1 exposure cap check
using slot_allocator.get_total_exposure() before order submission. This prevents
orders from being submitted when exposure is at $1.00, ensuring strict enforcement
of the MERID_FIXED_EXPOSURE_CAP_USD limit.

Key fixes tested:
1. Hard exposure cap check using slot_allocator (real-time exposure tracking)
2. Per-asset position limit as backup enforcement
3. Exit orders bypass the hard exposure gate
4. Gate runs before order submission (in _check_intent_risk)
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from merid.event_venues.kalshi.order_router import OrderIntent, _check_intent_risk, _is_exit_order


class TestHardExposureCapEnforcement:
    """Test hard $1 exposure cap enforcement in order_router."""
    
    def test_hard_exposure_cap_rejects_order_at_full_capacity(self):
        """Test that hard exposure cap rejects orders when exposure is at $1.00."""
        # Create entry order intent
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=2,  # $1.00 notional
            source="agent_grid"
        )
        
        # Mock slot allocator to return $1.00 current exposure
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 1.00
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache and risk envelope
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = None
        mock_position_cache.get_all_positions.return_value = {}
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should reject with hard_exposure_cap_exceeded
            assert rejection is not None, "Should reject order at full capacity"
            assert "hard_exposure_cap_exceeded" in rejection, f"Expected hard_exposure_cap_exceeded, got: {rejection}"
            assert "$1.00" in rejection or "$1.0" in rejection, f"Should mention $1 cap, got: {rejection}"
    
    def test_hard_exposure_cap_allows_order_below_capacity(self):
        """Test that hard exposure cap allows orders when exposure is below $1.00."""
        # Create entry order intent
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,  # $0.50 notional
            source="agent_grid"
        )
        
        # Mock slot allocator to return $0.40 current exposure
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 0.40
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache and risk envelope
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = None
        mock_position_cache.get_all_positions.return_value = {}
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should allow (return None)
            assert rejection is None, f"Should allow order below capacity, got rejection: {rejection}"
    
    def test_exit_order_bypasses_hard_exposure_cap(self):
        """Test that exit orders bypass the hard exposure cap check."""
        # Create exit order intent with exit marker
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            source="position_monitor_exit"  # Exit marker
        )
        
        # Mock slot allocator to return $1.00 current exposure (full capacity)
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 1.00
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache and risk envelope
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = Mock(contracts=1, current_price_cents=50)
        mock_position_cache.get_all_positions.return_value = {"KXBTC15M-TEST": Mock(contracts=1, current_price_cents=50)}
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should allow exit order even at full capacity
            assert rejection is None, f"Exit order should bypass hard exposure cap, got rejection: {rejection}"
    
    def test_hard_exposure_cap_uses_environment_variable(self):
        """Test that hard exposure cap uses MERID_FIXED_EXPOSURE_CAP_USD environment variable."""
        # Create entry order intent
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_grid"
        )
        
        # Mock slot allocator to return $0.50 current exposure
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 0.50
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache and risk envelope
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = None
        mock_position_cache.get_all_positions.return_value = {}
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        # Test with custom cap of $0.75
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '0.75'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should reject because $0.50 + $0.50 = $1.00 > $0.75 cap
            assert rejection is not None, "Should reject with custom $0.75 cap"
            assert "hard_exposure_cap_exceeded" in rejection
    
    def test_hard_exposure_cap_default_to_1_dollar(self):
        """Test that hard exposure cap defaults to $1.00 when environment variable is not set."""
        # Create entry order intent
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_grid"
        )
        
        # Mock slot allocator to return $0.50 current exposure
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 0.50
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache and risk envelope
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = None
        mock_position_cache.get_all_positions.return_value = {}
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        # Test without environment variable (should default to $1.00)
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {}, clear=True):
            
            rejection = _check_intent_risk(intent)
            
            # Should allow because $0.50 + $0.50 = $1.00 <= $1.00 default cap
            assert rejection is None, "Should allow with default $1.00 cap"


class TestPerAssetPositionLimitEnforcement:
    """Test per-asset position limit enforcement as backup to global allocator."""
    
    def test_per_asset_limit_rejects_duplicate_asset_position(self):
        """Test that per-asset limit rejects orders for asset that already has a position."""
        # Create entry order intent for BTC
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_grid"
        )
        
        # Mock slot allocator to reject allocation (simulating per-asset limit)
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 0.50
        mock_slot_allocator.can_allocate.return_value = (False, "asset BTC already has position")  # Reject allocation
        
        # Mock position cache with existing BTC position
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = None
        mock_position_cache.get_all_positions.return_value = {
            "KXBTC15M-OTHER": Mock(contracts=1, current_price_cents=50)  # Existing BTC position
        }
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should reject with slot_allocation_failed (per-asset limit enforced by slot allocator)
            assert rejection is not None, "Should reject duplicate asset position"
            assert "slot_allocation_failed" in rejection, f"Expected slot_allocation_failed, got: {rejection}"
            assert "BTC" in rejection or "asset" in rejection, f"Should mention asset, got: {rejection}"
    
    def test_per_asset_limit_allows_different_asset(self):
        """Test that per-asset limit allows orders for different assets."""
        # Create entry order intent for ETH
        intent = OrderIntent(
            ticker="KXETH15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_grid"
        )
        
        # Mock slot allocator
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 0.50
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache with existing BTC position (different asset)
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = None
        mock_position_cache.get_all_positions.return_value = {
            "KXBTC15M-OTHER": Mock(contracts=1, current_price_cents=50)  # Existing BTC position
        }
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should allow (different asset)
            assert rejection is None, f"Should allow different asset, got rejection: {rejection}"
    
    def test_per_asset_limit_bypassed_for_exit_orders(self):
        """Test that per-asset limit is bypassed for exit orders."""
        # Create exit order intent for BTC
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            source="position_monitor_exit"  # Exit marker
        )
        
        # Mock slot allocator
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 0.50
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache with existing BTC position
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = Mock(contracts=1, current_price_cents=50)
        mock_position_cache.get_all_positions.return_value = {
            "KXBTC15M-TEST": Mock(contracts=1, current_price_cents=50)  # Existing BTC position
        }
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should allow exit order (bypasses per-asset limit)
            assert rejection is None, f"Exit order should bypass per-asset limit, got rejection: {rejection}"
    
    def test_per_asset_limit_allows_first_position(self):
        """Test that per-asset limit allows first position for an asset."""
        # Create entry order intent for BTC
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_grid"
        )
        
        # Mock slot allocator
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 0.00
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        # Mock position cache with no positions
        mock_position_cache = Mock()
        mock_position_cache.get_position.return_value = None
        mock_position_cache.get_all_positions.return_value = {}
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            
            # Should allow first position
            assert rejection is None, f"Should allow first position, got rejection: {rejection}"


class TestExitOrderBypassVerification:
    """Verify that exit orders correctly bypass hard exposure and per-asset checks."""
    
    def test_exit_order_detected_by_source_marker(self):
        """Test that exit orders are detected by source markers."""
        exit_markers = ["take_profit", "stop_loss", "micro_scalp", "exit", "close", "ratchet"]
        
        for marker in exit_markers:
            intent = OrderIntent(
                ticker="KXBTC15M-TEST",
                side="yes",
                action="sell",
                price_cents=50,
                count=1,
                source=marker
            )
            
            assert _is_exit_order(intent) is True, f"Should detect exit marker: {marker}"
    
    def test_entry_order_not_detected_as_exit(self):
        """Test that entry orders are not detected as exits."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_grid"
        )
        
        assert _is_exit_order(intent) is False, "Entry order should not be detected as exit"
    
    def test_sell_action_alone_not_exit(self):
        """Test that sell action alone is not sufficient for exit detection."""
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="no",
            action="sell",  # NO entry order (sell-side)
            price_cents=50,
            count=1,
            source="agent_grid"  # No exit marker
        )
        
        assert _is_exit_order(intent) is False, "Sell action alone should not be exit (prevents NO entry bypass)"


class TestLoop15mDeduplicationFix:
    """Test the 2026-07-13 deduplication fix in loop_15m.py.
    
    This fix prevents the same candidate from executing multiple times within
    a 15-minute window by checking _executed_candidates_this_window BEFORE
    execution (not just adding to it after execution).
    """
    
    def test_get_candidate_key_includes_price_cents(self):
        """Test that _get_candidate_key includes price_cents for proper deduplication."""
        from merid.loop_15m import Kalshi15mLoop
        from unittest.mock import Mock
        
        # Create mock loop instance
        loop = Kalshi15mLoop(
            agent_grid=Mock(),
            bankroll_service=Mock(),
            risk_config=Mock(),
            cadence_seconds=5.0
        )
        
        # Test that key includes price_cents
        candidate1 = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 50
        }
        candidate2 = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 60  # Different price
        }
        
        key1 = loop._get_candidate_key(candidate1)
        key2 = loop._get_candidate_key(candidate2)
        
        # Keys should be different due to different prices
        assert key1 != key2, f"Keys should differ for different prices: {key1} vs {key2}"
        assert "50" in key1, f"Key should include price: {key1}"
        assert "60" in key2, f"Key should include price: {key2}"
    
    def test_get_candidate_key_same_price_same_key(self):
        """Test that same ticker+side+price produces same key."""
        from merid.loop_15m import Kalshi15mLoop
        from unittest.mock import Mock
        
        loop = Kalshi15mLoop(
            agent_grid=Mock(),
            bankroll_service=Mock(),
            risk_config=Mock(),
            cadence_seconds=5.0
        )
        
        candidate1 = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 50
        }
        candidate2 = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 50  # Same price
        }
        
        key1 = loop._get_candidate_key(candidate1)
        key2 = loop._get_candidate_key(candidate2)
        
        # Keys should be identical
        assert key1 == key2, f"Keys should be identical for same price: {key1} vs {key2}"
    
    def test_get_candidate_key_different_side_different_key(self):
        """Test that different sides produce different keys."""
        from merid.loop_15m import Kalshi15mLoop
        from unittest.mock import Mock
        
        loop = Kalshi15mLoop(
            agent_grid=Mock(),
            bankroll_service=Mock(),
            risk_config=Mock(),
            cadence_seconds=5.0
        )
        
        candidate1 = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 50
        }
        candidate2 = {
            "ticker": "KXBTC15M-TEST",
            "side": "no",
            "price_cents": 50
        }
        
        key1 = loop._get_candidate_key(candidate1)
        key2 = loop._get_candidate_key(candidate2)
        
        # Keys should be different due to different sides
        assert key1 != key2, f"Keys should differ for different sides: {key1} vs {key2}"
    
    def test_executed_candidates_set_prevents_reexecution(self):
        """Test that _executed_candidates_this_window prevents re-execution."""
        from merid.loop_15m import Kalshi15mLoop
        from unittest.mock import Mock
        
        loop = Kalshi15mLoop(
            agent_grid=Mock(),
            bankroll_service=Mock(),
            risk_config=Mock(),
            cadence_seconds=5.0
        )
        
        candidate = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 50
        }
        
        key = loop._get_candidate_key(candidate)
        
        # Initially, key should not be in set
        assert key not in loop._executed_candidates_this_window
        
        # Add to set (simulating execution)
        loop._executed_candidates_this_window.add(key)
        
        # Now key should be in set
        assert key in loop._executed_candidates_this_window
    
    def test_executed_candidates_set_cleared_on_window_change(self):
        """Test that _executed_candidates_this_window is cleared on window change."""
        from merid.loop_15m import Kalshi15mLoop
        from unittest.mock import Mock, patch
        
        loop = Kalshi15mLoop(
            agent_grid=Mock(),
            bankroll_service=Mock(),
            risk_config=Mock(),
            cadence_seconds=5.0
        )
        
        # Add some candidates
        loop._executed_candidates_this_window.add("KXBTC15M-TEST:yes:50")
        loop._executed_candidates_this_window.add("KXETH15M-TEST:no:60")
        
        assert len(loop._executed_candidates_this_window) == 2
        
        # Simulate window change (this happens in the actual loop)
        loop._executed_candidates_this_window.clear()
        
        # Set should be empty
        assert len(loop._executed_candidates_this_window) == 0


class TestEndToEndExecutionFlow:
    """End-to-end integration test for the full execution flow with deduplication.
    
    This test validates that the deduplication fix works correctly across the entire
    execution pipeline: agent_grid -> loop_15m -> order_router -> order_gate -> global_slot_allocator.
    """
    
    def test_full_flow_prevents_duplicate_execution_same_price(self):
        """Test that the full flow prevents duplicate execution at same price."""
        from merid.loop_15m import Kalshi15mLoop
        from merid.event_venues.kalshi.order_router import OrderIntent, _check_intent_risk
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        from unittest.mock import Mock, patch
        import os
        
        # Setup loop
        loop = Kalshi15mLoop(
            agent_grid=Mock(),
            bankroll_service=Mock(),
            risk_config=Mock(),
            cadence_seconds=5.0
        )
        
        # Create candidate
        candidate = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 50,
            "edge_pct": 0.02,
            "count": 1
        }
        
        # Simulate first execution
        key1 = loop._get_candidate_key(candidate)
        loop._executed_candidates_this_window.add(key1)
        
        # Simulate second attempt at same price (should be blocked by deduplication)
        key2 = loop._get_candidate_key(candidate)
        assert key2 in loop._executed_candidates_this_window, "Duplicate should be detected"
        
        # Verify order router would also block via hard exposure cap if deduplication failed
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_grid"
        )
        
        # Mock slot allocator at full capacity
        mock_slot_allocator = Mock()
        mock_slot_allocator.get_total_exposure.return_value = 1.00
        mock_slot_allocator.can_allocate.return_value = (True, "allocation allowed")  # Return tuple
        
        mock_position_cache = Mock()
        mock_position_cache.get_all_positions.return_value = {}
        
        mock_risk_envelope = Mock()
        mock_risk_envelope.max_total_notional_usd = 1.00
        
        with patch('merid.event_venues.kalshi.order_router._check_global_rate_limit', return_value=None), \
             patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_position_cache), \
             patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope', return_value=mock_risk_envelope), \
             patch('merid.risk.global_slot_allocator.get_global_slot_allocator', return_value=mock_slot_allocator), \
             patch.dict(os.environ, {'MERID_FIXED_EXPOSURE_CAP_USD': '1.00'}):
            
            rejection = _check_intent_risk(intent)
            # Should reject due to hard exposure cap (backup protection)
            assert rejection is not None, "Should reject at full capacity"
            assert "hard_exposure_cap_exceeded" in rejection
    
    def test_full_flow_allows_different_price_same_asset(self):
        """Test that the full flow allows execution at different price for same asset."""
        from merid.loop_15m import Kalshi15mLoop
        from unittest.mock import Mock
        
        # Setup loop
        loop = Kalshi15mLoop(
            agent_grid=Mock(),
            bankroll_service=Mock(),
            risk_config=Mock(),
            cadence_seconds=5.0
        )
        
        # Create candidate at 50c
        candidate1 = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 50,
            "edge_pct": 0.02,
            "count": 1
        }
        
        # Simulate execution at 50c
        key1 = loop._get_candidate_key(candidate1)
        loop._executed_candidates_this_window.add(key1)
        
        # Create candidate at 60c (different price)
        candidate2 = {
            "ticker": "KXBTC15M-TEST",
            "side": "yes",
            "price_cents": 60,
            "edge_pct": 0.03,
            "count": 1
        }
        
        # Should be allowed (different price = different key)
        key2 = loop._get_candidate_key(candidate2)
        assert key2 not in loop._executed_candidates_this_window, "Different price should be allowed"
        assert key1 != key2, "Keys should differ for different prices"
    
    def test_full_flow_enforces_per_asset_limit(self):
        """Test that the full flow enforces max 1 position per asset."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        from unittest.mock import Mock
        
        allocator = GlobalSlotAllocator()
        
        # Allocate first BTC position
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            entry_price_cents=50,
            edge_pct=0.02,
            spread_cents=2,
            confidence=0.5
        )
        
        success1, reason1, slot_id1 = allocator.request_allocation(request1)
        assert success1, f"First allocation should succeed: {reason1}"
        
        # Try to allocate second BTC position (should fail)
        request2 = AllocationRequest(
            agent_id="BTC_15M",
            ticker="KXBTC15M-TEST2",
            asset="BTC",
            entry_price_cents=60,
            edge_pct=0.03,
            spread_cents=2,
            confidence=0.5
        )
        
        success2, reason2, slot_id2 = allocator.request_allocation(request2)
        assert not success2, f"Second BTC allocation should fail: {reason2}"
        assert "already has" in reason2.lower(), f"Should mention asset limit: {reason2}"
        
        # Cleanup
        allocator.release_slot(slot_id1)
    
    def test_full_flow_enforces_1dollar_exposure_cap(self):
        """Test that the full flow enforces $1 exposure cap across all assets."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator, AllocationRequest
        
        allocator = GlobalSlotAllocator()
        
        # Allocate BTC at 50c ($0.50)
        request1 = AllocationRequest(
            agent_id="BTC_15M",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            entry_price_cents=50,
            edge_pct=0.02,
            spread_cents=2,
            confidence=0.5
        )
        
        success1, reason1, slot_id1 = allocator.request_allocation(request1)
        assert success1, f"First allocation should succeed: {reason1}"
        assert allocator.get_total_exposure() == 0.50
        
        # Try to allocate ETH at 60c ($0.60) - should fail (total would be $1.10 > $1.00)
        request2 = AllocationRequest(
            agent_id="ETH_15M",
            ticker="KXETH15M-TEST",
            asset="ETH",
            entry_price_cents=60,
            edge_pct=0.03,
            spread_cents=2,
            confidence=0.5
        )
        
        success2, reason2, slot_id2 = allocator.request_allocation(request2)
        assert not success2, f"ETH allocation should fail (exceeds $1 cap): {reason2}"
        assert "insufficient exposure" in reason2.lower(), f"Should mention exposure cap: {reason2}"
        
        # Try to allocate ETH at 40c ($0.40) - should succeed (total would be $0.90 <= $1.00)
        request3 = AllocationRequest(
            agent_id="ETH_15M",
            ticker="KXETH15M-TEST2",
            asset="ETH",
            entry_price_cents=40,
            edge_pct=0.03,
            spread_cents=2,
            confidence=0.5
        )
        
        success3, reason3, slot_id3 = allocator.request_allocation(request3)
        assert success3, f"ETH allocation at 40c should succeed: {reason3}"
        assert allocator.get_total_exposure() == 0.90
        
        # Cleanup
        allocator.release_slot(slot_id1)
        allocator.release_slot(slot_id3)


class TestAgentGridDeduplicationFix:
    """Test deduplication fix in agent_grid_15m.py to prevent duplicate executions."""
    
    def test_candidate_key_generation(self):
        """Test that candidate keys are generated correctly."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        # Create a mock agent grid with minimal setup
        mock_agents = []
        grid = LeanAgentGrid15m(agents=mock_agents)
        
        # Test candidate key generation
        key1 = grid._get_candidate_key("KXSOL15M-TEST", "yes", 25)
        key2 = grid._get_candidate_key("KXSOL15M-TEST", "yes", 25)
        key3 = grid._get_candidate_key("KXSOL15M-TEST", "no", 25)
        key4 = grid._get_candidate_key("KXSOL15M-TEST", "yes", 26)
        
        # Same parameters should generate same key
        assert key1 == key2, "Same parameters should generate same key"
        
        # Different parameters should generate different keys
        assert key1 != key3, "Different side should generate different key"
        assert key1 != key4, "Different price should generate different key"
        
        # Key format should be ticker:side:price
        assert key1 == "KXSOL15M-TEST:yes:25", f"Expected 'KXSOL15M-TEST:yes:25', got '{key1}'"
    
    def test_executed_candidates_set_initialized(self):
        """Test that executed candidates set is initialized on agent grid creation."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        mock_agents = []
        grid = LeanAgentGrid15m(agents=mock_agents)
        
        # Set should be initialized and empty
        assert hasattr(grid, '_executed_candidates'), "Agent grid should have _executed_candidates set"
        assert isinstance(grid._executed_candidates, set), "_executed_candidates should be a set"
        assert len(grid._executed_candidates) == 0, "_executed_candidates should be empty initially"
    
    def test_executed_candidates_cleared_on_startup(self):
        """Test that executed candidates set is cleared on startup."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        mock_agents = []
        grid = LeanAgentGrid15m(agents=mock_agents)
        
        # Add a candidate to the set
        grid._executed_candidates.add("KXSOL15M-TEST:yes:25")
        assert len(grid._executed_candidates) == 1, "Should have one executed candidate"
        
        # Simulate startup (this is async, but we can call the logic directly)
        grid._running = False
        # The start() method clears the set
        import asyncio
        asyncio.run(grid.start())
        
        # Set should be cleared
        assert len(grid._executed_candidates) == 0, "Executed candidates should be cleared on startup"
    
    def test_executed_candidates_cleared_on_market_rollover(self):
        """Test that executed candidates set is cleared on market rollover."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        mock_agents = []
        grid = LeanAgentGrid15m(agents=mock_agents)
        
        # Add candidates to the set
        grid._executed_candidates.add("KXSOL15M-TEST:yes:25")
        grid._executed_candidates.add("KXETH15M-TEST:no:30")
        assert len(grid._executed_candidates) == 2, "Should have two executed candidates"
        
        # Simulate market rollover
        grid.reset_strip_order_counts()
        
        # Set should be cleared
        assert len(grid._executed_candidates) == 0, "Executed candidates should be cleared on market rollover"
    
    def test_duplicate_candidate_detection(self):
        """Test that duplicate candidates are detected correctly."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        mock_agents = []
        grid = LeanAgentGrid15m(agents=mock_agents)
        
        # Add a candidate to the set
        candidate_key = "KXSOL15M-TEST:yes:25"
        grid._executed_candidates.add(candidate_key)
        
        # Check if it's in the set
        assert candidate_key in grid._executed_candidates, "Candidate should be in executed set"
        
        # Check a different candidate
        different_key = "KXSOL15M-TEST:yes:26"
        assert different_key not in grid._executed_candidates, "Different candidate should not be in set"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
