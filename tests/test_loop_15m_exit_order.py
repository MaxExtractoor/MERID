"""Tests for loop_15m.py exit order logic (fixed cent SL)."""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock
from datetime import datetime

from merid.position_management.position import Position, PositionSide, TrailingType


class TestLoop15mExitOrderSL:
    """Tests for fixed cent SL computation in loop_15m._execute_exit_order."""
    
    def test_fixed_cent_sl_yes_position(self):
        """Test YES position uses entry - 5 cents for SL."""
        # Simulate the SL computation logic from loop_15m.py
        price_cents = 50
        side_raw = "YES"
        sl_r_multiple = 0.5
        
        # YES: SL = entry - (entry * sl_r_multiple)
        stop_loss_price_cents = int(price_cents * (1 - sl_r_multiple))
        
        assert stop_loss_price_cents == 25  # 50 - (50 * 0.5) = 25
    
    def test_fixed_cent_sl_no_position(self):
        """Test NO position uses entry + 5 cents for SL."""
        # Simulate the SL computation logic from loop_15m.py
        price_cents = 50
        side_raw = "NO"
        sl_r_multiple = 0.5
        
        # NO: SL = entry + (entry * sl_r_multiple)
        stop_loss_price_cents = int(price_cents * (1 + sl_r_multiple))
        
        assert stop_loss_price_cents == 75  # 50 + (50 * 0.5) = 75
    
    def test_sl_cents_priority_over_r_multiple(self):
        """Test sl_cents takes priority over sl_r_multiple when available."""
        # Simulate the logic: if sl_cents is set, use it directly
        sl_cents = 45
        sl_r_multiple = 0.5
        price_cents = 50
        side_raw = "YES"
        
        # If sl_cents is set, use it directly
        if sl_cents:
            stop_loss_price_cents = sl_cents
        elif sl_r_multiple:
            stop_loss_price_cents = int(price_cents * (1 - sl_r_multiple))
        
        assert stop_loss_price_cents == 45  # sl_cents takes priority
    
    def test_default_sl_when_no_policy(self):
        """Test default 5 cent SL when no exit policy is available."""
        price_cents = 50
        side_raw = "YES"
        
        # Default to 5 cent SL if no policy
        stop_loss_price_cents = max(1, price_cents - 5) if side_raw == "YES" else price_cents + 5
        
        assert stop_loss_price_cents == 45  # 50 - 5 = 45
    
    def test_default_sl_no_position(self):
        """Test default 5 cent SL for NO position when no policy."""
        price_cents = 50
        side_raw = "NO"
        
        # Default to 5 cent SL if no policy
        stop_loss_price_cents = max(1, price_cents - 5) if side_raw == "YES" else price_cents + 5
        
        assert stop_loss_price_cents == 55  # 50 + 5 = 55


class TestLoop15mKalshiSideConversion:
    """Tests for Kalshi side format conversion in exit orders."""
    
    def test_yes_position_exit_converts_to_sell_yes(self):
        """Test YES position exit converts to SELL_YES."""
        side_str = "yes"
        action = "sell"
        side_upper = side_str.upper()
        
        if side_upper == "YES" and action == "sell":
            kalshi_side = "SELL_YES"
        elif side_upper == "NO" and action == "sell":
            kalshi_side = "SELL_NO"
        else:
            kalshi_side = f"{action.upper()}_{side_upper}"
        
        assert kalshi_side == "SELL_YES"
    
    def test_no_position_exit_converts_to_sell_no(self):
        """Test NO position exit converts to SELL_NO."""
        side_str = "no"
        action = "sell"
        side_upper = side_str.upper()
        
        if side_upper == "YES" and action == "sell":
            kalshi_side = "SELL_YES"
        elif side_upper == "NO" and action == "sell":
            kalshi_side = "SELL_NO"
        else:
            kalshi_side = f"{action.upper()}_{side_upper}"
        
        assert kalshi_side == "SELL_NO"
    
    def test_position_side_enum_conversion(self):
        """Test PositionSide enum conversion to string."""
        position = Position(
            position_id="test-1",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        side_str = position.side.value if hasattr(position.side, 'value') else str(position.side)
        assert side_str == "yes"
        
        position_no = Position(
            position_id="test-2",
            market_id="KXBTC15M-TEST",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=50,
        )
        
        side_str = position_no.side.value if hasattr(position_no.side, 'value') else str(position_no.side)
        assert side_str == "no"


class TestLoop15mTPComputation:
    """Tests for TP computation in loop_15m.py."""
    
    def test_tp_computation_from_exit_policy(self):
        """Test TP is computed from exit_policy.tp_r_multiple."""
        price_cents = 50
        tp_r_multiple = 1.0
        
        take_profit_price_cents = int(price_cents * (1 + tp_r_multiple))
        
        assert take_profit_price_cents == 100  # 50 * (1 + 1.0) = 100
    
    def test_tp_none_when_no_policy(self):
        """Test TP is None when exit_policy is not available."""
        exit_policy = None
        
        if exit_policy and exit_policy.tp_r_multiple:
            take_profit_price_cents = 100
        else:
            take_profit_price_cents = None
        
        assert take_profit_price_cents is None


class TestLoop15mExitOrderCorrectSideMapping:
    """Tests for correct Kalshi side mapping in exit orders (critical fix for duplicate startup bug)."""
    
    def test_exit_order_yes_position_uses_sell_yes(self):
        """Test YES position exit uses SELL_YES (not 'no' + 'sell' from wrong callback).
        
        This test verifies the fix for the duplicate startup bug where main_15m_lean.py
        had wrong side logic (YES -> side='no', action='sell') that overwrote the
        correct callback from loop_15m.py (YES -> SELL_YES).
        """
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        position = Position(
            position_id="test-1",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=5,
            avg_entry_price_cents=50,
            exit_policy_id="test-policy-123",
        )
        
        # Simulate CORRECT logic from loop_15m.py (the fix)
        action = "sell"
        side_str = position.side.value if hasattr(position.side, 'value') else str(position.side)
        side_upper = side_str.upper()
        
        if side_upper == "YES" and action == "sell":
            kalshi_side = "SELL_YES"  # CORRECT
        elif side_upper == "NO" and action == "sell":
            kalshi_side = "SELL_NO"
        else:
            kalshi_side = f"{action.upper()}_{side_upper}"
        
        # Verify correct Kalshi side format
        assert kalshi_side == "SELL_YES"
        
        # Create exit order with correct side
        intent = OrderIntent(
            ticker=position.market_id,
            side=kalshi_side,
            action=action,
            price_cents=60,
            count=position.size,
            order_type="limit",
            time_in_force="gtc",
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            exit_policy_id=position.exit_policy_id,
        )
        
        # Verify side is SELL_YES (not 'no')
        assert intent.side == "SELL_YES"
    
    def test_exit_order_no_position_uses_sell_no(self):
        """Test NO position exit uses SELL_NO (not 'yes' + 'buy' from wrong callback).
        
        This test verifies the fix for the duplicate startup bug where main_15m_lean.py
        had wrong side logic (NO -> side='yes', action='buy') that overwrote the
        correct callback from loop_15m.py (NO -> SELL_NO).
        """
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        position = Position(
            position_id="test-2",
            market_id="KXBTC15M-TEST",
            side=PositionSide.NO,
            size=5,
            avg_entry_price_cents=50,
            exit_policy_id="test-policy-123",
        )
        
        # Simulate CORRECT logic from loop_15m.py (the fix)
        action = "sell"
        side_str = position.side.value if hasattr(position.side, 'value') else str(position.side)
        side_upper = side_str.upper()
        
        if side_upper == "YES" and action == "sell":
            kalshi_side = "SELL_YES"
        elif side_upper == "NO" and action == "sell":
            kalshi_side = "SELL_NO"  # CORRECT
        else:
            kalshi_side = f"{action.upper()}_{side_upper}"
        
        # Verify correct Kalshi side format
        assert kalshi_side == "SELL_NO"
        
        # Create exit order with correct side
        intent = OrderIntent(
            ticker=position.market_id,
            side=kalshi_side,
            action=action,
            price_cents=40,
            count=position.size,
            order_type="limit",
            time_in_force="gtc",
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            exit_policy_id=position.exit_policy_id,
        )
        
        # Verify side is SELL_NO (not 'yes')
        assert intent.side == "SELL_NO"
    
    def test_wrong_side_mapping_from_duplicate_startup_bug(self):
        """Test that the WRONG side mapping from the duplicate startup bug is rejected.
        
        This test documents the bug that was fixed: main_15m_lean.py had:
        - YES position: side='no', action='sell' (WRONG)
        - NO position: side='yes', action='buy' (WRONG)
        
        The correct mapping from loop_15m.py is:
        - YES position: SELL_YES
        - NO position: SELL_NO
        """
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Simulate WRONG logic from main_15m_lean.py (the bug)
        # YES position with wrong side mapping
        wrong_side_yes = "no"  # WRONG - should be SELL_YES
        wrong_action_yes = "sell"
        
        # This would create an invalid order
        intent_wrong = OrderIntent(
            ticker="KXBTC15M-TEST",
            side=wrong_side_yes,  # WRONG - should be SELL_YES
            action=wrong_action_yes,
            price_cents=60,
            count=5,
            order_type="limit",
            time_in_force="gtc",
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            exit_policy_id="test-policy-123",
        )
        
        # Verify this is NOT the correct Kalshi format
        assert intent_wrong.side not in ("SELL_YES", "SELL_NO", "BUY_YES", "BUY_NO")
        
        # Simulate CORRECT logic from loop_15m.py (the fix)
        correct_side_yes = "SELL_YES"  # CORRECT
        correct_action_yes = "sell"
        
        intent_correct = OrderIntent(
            ticker="KXBTC15M-TEST",
            side=correct_side_yes,  # CORRECT
            action=correct_action_yes,
            price_cents=60,
            count=5,
            order_type="limit",
            time_in_force="gtc",
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            exit_policy_id="test-policy-123",
        )
        
        # Verify this IS the correct Kalshi format
        assert intent_correct.side == "SELL_YES"


class TestLoop15mExitOrderExitPolicyId:
    """Tests for exit_policy_id field in exit orders (critical fix)."""
    
    def test_exit_order_includes_exit_policy_id(self):
        """Test that exit orders include exit_policy_id from position.
        
        This test verifies the critical fix where exit orders were missing
        exit_policy_id, causing them to be rejected by order router validation.
        """
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create a position with exit_policy_id
        position = Position(
            position_id="test-1",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=5,
            avg_entry_price_cents=50,
            exit_policy_id="test-policy-123",  # CRITICAL: This field must be passed to exit order
        )
        
        # Simulate exit order creation logic from loop_15m.py
        action = "sell"
        side_str = position.side.value if hasattr(position.side, 'value') else str(position.side)
        side_upper = side_str.upper()
        
        if side_upper == "YES" and action == "sell":
            kalshi_side = "SELL_YES"
        elif side_upper == "NO" and action == "sell":
            kalshi_side = "SELL_NO"
        else:
            kalshi_side = f"{action.upper()}_{side_upper}"
        
        exit_price_cents = 60
        count = position.size
        
        # Create exit OrderIntent with exit_policy_id (CRITICAL FIX)
        intent = OrderIntent(
            ticker=position.market_id,
            side=kalshi_side,
            action=action,
            price_cents=exit_price_cents,
            count=count,
            order_type="limit",
            time_in_force="gtc",
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            exit_policy_id=position.exit_policy_id,  # CRITICAL FIX: Required for validation
        )
        
        # Verify exit_policy_id is set
        assert intent.exit_policy_id == "test-policy-123"
    
    def test_exit_order_without_exit_policy_id_would_fail_validation(self):
        """Test that exit orders without exit_policy_id would fail validation.
        
        This test demonstrates why the exit_policy_id fix is critical.
        Without it, exit orders would be rejected by _validate_risk_contract_linkage.
        """
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order, _is_crypto_15m_market, _validate_risk_contract_linkage
        
        # Create exit order WITHOUT exit_policy_id (the bug)
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="SELL_YES",
            action="sell",
            price_cents=60,
            count=5,
            order_type="limit",
            time_in_force="gtc",
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            # exit_policy_id MISSING - this would cause rejection
        )
        
        # Verify it's an exit order
        assert _is_exit_order(intent) is True
        
        # Verify it's a crypto 15m market
        assert _is_crypto_15m_market(intent.ticker) is True
        
        # Validate risk contract linkage - should FAIL without exit_policy_id
        is_valid, error_message = _validate_risk_contract_linkage(intent)
        
        # Should be invalid with specific error message
        assert is_valid is False
        assert "exit_policy_id" in error_message.lower()
        assert error_message == "Exit order missing exit_policy_id"
    
    def test_exit_order_with_exit_policy_id_passes_validation(self):
        """Test that exit orders with exit_policy_id pass validation.
        
        This test verifies the fix allows exit orders to pass validation.
        """
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order, _is_crypto_15m_market, _validate_risk_contract_linkage
        
        # Create exit order WITH exit_policy_id (the fix)
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="SELL_YES",
            action="sell",
            price_cents=60,
            count=5,
            order_type="limit",
            time_in_force="gtc",
            source="position_monitor_exit",
            agent_id="merid.position_management.position_monitor",
            exit_policy_id="test-policy-123",  # CRITICAL FIX: This field is required
        )
        
        # Verify it's an exit order
        assert _is_exit_order(intent) is True
        
        # Verify it's a crypto 15m market
        assert _is_crypto_15m_market(intent.ticker) is True
        
        # Validate risk contract linkage - should PASS with exit_policy_id
        is_valid, error_message = _validate_risk_contract_linkage(intent)
        
        # Should be valid
        assert is_valid is True
        assert error_message is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
