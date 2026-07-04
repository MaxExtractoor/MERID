"""
Tests for ExitPolicy and ExitPolicyResolver.

Tests TIME_STOP, EDGE_DECAY, and RISK policies.
"""

import pytest
from datetime import datetime, timedelta
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy import (
    ExitPolicy,
    ExitAction,
    ExitReason,
)
from merid.position_management.exit_policy_resolver import (
    ExitPolicyResolver,
    get_exit_policy_resolver,
)


class TestExitPolicy:
    """Test ExitPolicy evaluation logic."""
    
    def test_evaluate_risk_kill_switch(self):
        """Test risk kill switch triggers exit."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=10.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            risk_kill_switch=True,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.RISK
    
    def test_evaluate_time_stop_losing(self):
        """Test time stop triggers on losing position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=45,
            unrealized_pnl_cents=-50,
            r_multiple=-5.0,
            time_since_entry_seconds=900.0,  # At max hold
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.TIME_STOP
    
    def test_evaluate_time_stop_no_progress(self):
        """Test time stop triggers on no progress (0-0.5R)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=52,
            unrealized_pnl_cents=20,
            r_multiple=0.2,  # No meaningful progress
            time_since_entry_seconds=900.0,
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.TIME_STOP
    
    def test_evaluate_time_stop_profitable(self):
        """Test time stop does NOT trigger on profitable position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=100,
            r_multiple=10.0,  # Profitable
            time_since_entry_seconds=900.0,
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_evaluate_time_stop_before_max_hold(self):
        """Test time stop does NOT trigger before max hold."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
            stop_loss_price_cents=40,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=45,
            unrealized_pnl_cents=-50,
            r_multiple=-5.0,
            time_since_entry_seconds=500.0,  # Before max hold
            time_to_expiry_seconds=600.0,
            max_hold_seconds=900.0,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_evaluate_edge_decay(self):
        """Test edge decay triggers exit."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,  # 3% minimum edge
        )
        
        policy.evaluate(current_edge_pct=0.02)  # Below threshold
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.EDGE_DECAY
    
    def test_evaluate_edge_decay_sufficient(self):
        """Test edge decay does NOT trigger when edge sufficient."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            min_edge_threshold=0.03,
        )
        
        policy.evaluate(current_edge_pct=0.05)  # Above threshold
        
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_evaluate_loss_cap_triggers(self):
        """Test loss cap triggers at 80% loss (2026 FIX)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,  # Entry at 50c
        )
        
        # 80% loss: current price = 10c (50c * 0.20)
        # Unrealized PnL = -40c per contract = -400c total
        # Max loss = 50c * 10 = 500c
        # Loss percentage = 400 / 500 = 80%
        policy = ExitPolicy(
            position=position,
            current_price_cents=10,
            unrealized_pnl_cents=-400,  # Directly set to 80% loss
            r_multiple=-8.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.EXIT_MARKET
        assert policy.reason == ExitReason.LOSS_CAP
    
    def test_evaluate_loss_cap_no_trigger_below_threshold(self):
        """Test loss cap does NOT trigger below 80% loss."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,  # Entry at 50c
        )
        
        # Update position runtime state to calculate unrealized PnL
        position.update_runtime_state(current_price_cents=20)
        
        # 60% loss: current price = 20c (50c * 0.40)
        # Unrealized PnL = -30c per contract = -300c total
        policy = ExitPolicy(
            position=position,
            current_price_cents=20,
            unrealized_pnl_cents=position.unrealized_pnl_cents,
            r_multiple=position.r_multiple,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_evaluate_loss_cap_no_trigger_profitable(self):
        """Test loss cap does NOT trigger on profitable position."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # Update position runtime state to calculate unrealized PnL
        position.update_runtime_state(current_price_cents=60)
        
        policy = ExitPolicy(
            position=position,
            current_price_cents=60,
            unrealized_pnl_cents=position.unrealized_pnl_cents,
            r_multiple=position.r_multiple,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
        )
        
        policy.evaluate()
        
        assert policy.action == ExitAction.HOLD
        assert policy.reason is None
    
    def test_get_effective_max_hold_volatility_adjustment(self):
        """Test volatility-adjusted max hold time."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # HIGH volatility: 50% of base
        policy_high = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            max_hold_seconds=900.0,
            volatility_regime="HIGH",
        )
        
        assert policy_high.get_effective_max_hold() == 450.0  # 900 * 0.5
        
        # LOW volatility: 100% of base
        policy_low = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            max_hold_seconds=900.0,
            volatility_regime="LOW",
        )
        
        assert policy_low.get_effective_max_hold() == 900.0  # 900 * 1.0
        
        # No volatility regime: use base
        policy_none = ExitPolicy(
            position=position,
            current_price_cents=50,
            unrealized_pnl_cents=0,
            r_multiple=0.0,
            time_since_entry_seconds=100.0,
            time_to_expiry_seconds=800.0,
            max_hold_seconds=900.0,
            volatility_regime=None,
        )
        
        assert policy_none.get_effective_max_hold() == 900.0


class TestExitPolicyResolver:
    """Test ExitPolicyResolver singleton and resolution."""
    
    def test_get_exit_policy_resolver_singleton(self):
        """Test singleton pattern."""
        resolver1 = get_exit_policy_resolver()
        resolver2 = get_exit_policy_resolver()
        
        assert resolver1 is resolver2
    
    def test_resolve_basic(self):
        """Test basic policy resolution."""
        resolver = ExitPolicyResolver(max_hold_seconds=900.0)
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        policy = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        
        assert policy.position is position
        assert policy.current_price_cents == 50
        assert policy.max_hold_seconds == 900.0
        assert policy.action == ExitAction.HOLD
    
    def test_set_risk_kill_switch(self):
        """Test risk kill switch setting."""
        resolver = ExitPolicyResolver()
        
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        # Kill switch off
        policy1 = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        assert policy1.action == ExitAction.HOLD
        
        # Enable kill switch
        resolver.set_risk_kill_switch(True)
        
        policy2 = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        assert policy2.action == ExitAction.EXIT_MARKET
        assert policy2.reason == ExitReason.RISK
        
        # Disable kill switch
        resolver.set_risk_kill_switch(False)
        
        policy3 = resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        assert policy3.action == ExitAction.HOLD
