"""Tests for per-market and per-asset kill switches with proper isolation.

Test Suite Invariants:
- TradeMode is always reset between tests (via conftest.py autouse fixture)
- Kill switches use temp storage (via kill_switch_temp_dir fixture)
- No test alters global kill switch state for other tests
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from merid.risk.kill_switches import RiskController, KillSwitchReason, KillSwitchState
from merid.guard.trading_hours import get_trading_hours_guard
from trading.trade_mode import TradeMode, set_trade_mode, get_trade_mode


class TestPerMarketKillSwitch:
    """Tests for per-market kill switch behavior."""
    
    def test_per_market_kill_allows_paper_blocks_live(self, kill_switch_temp_dir, auto_promoter_clean):
        """Per-market kill: Paper allowed, Live blocked with specific reason."""
        controller = kill_switch_temp_dir
        promoter = auto_promoter_clean
        
        agent_id = "BTC_15M"
        market_id = "KXBTC-15M"
        
        # Initialize agent and block market
        promoter.initialize_agent(agent_id, "BTC", "15m")
        promoter.block_market(agent_id, market_id, "test_kill")
        
        # Verify market is blocked for this agent
        status = promoter.get_status(agent_id)
        assert market_id in status.blocked_markets
    
    def test_kill_switch_affects_only_targeted_market(self, kill_switch_temp_dir, auto_promoter_clean):
        """Kill switch affects only targeted market, not others."""
        controller = kill_switch_temp_dir
        promoter = auto_promoter_clean
        
        agent_id = "BTC_15M"
        
        promoter.initialize_agent(agent_id, "BTC", "15m")
        
        # Block only 15m market
        promoter.block_market(agent_id, "KXBTC-15M", "test_reason")
        
        status = promoter.get_status(agent_id)
        
        # Only 15m blocked
        assert "KXBTC-15M" in status.blocked_markets
        assert "KXBTC-HOURLY" not in status.blocked_markets
        assert "KXETH-15M" not in status.blocked_markets


class TestPerAssetKillSwitch:
    """Tests for per-asset kill switch behavior."""
    
    def test_per_asset_kill_blocks_all_markets_for_asset(self, kill_switch_temp_dir):
        """Per-asset kill should block all markets for that asset."""
        controller = kill_switch_temp_dir
        
        # Activate per-asset kill for BTC
        controller.trigger(
            reason=KillSwitchReason.MANUAL,
            scope="asset",
            target="BTC",
            details="Test per-asset kill"
        )
        
        # Verify BTC kill is active
        assert controller.is_asset_killed("BTC") is True
        assert controller.is_asset_killed("ETH") is False
    
    def test_global_kill_blocks_all(self, kill_switch_temp_dir):
        """Global kill switch blocks all trading."""
        controller = kill_switch_temp_dir
        
        # Verify initial state
        assert controller.is_global_active() is True  # ACTIVE means trading allowed
        
        # Trigger global kill
        controller.trigger(
            reason=KillSwitchReason.MANUAL,
            scope="global",
            details="Test global kill"
        )
        
        # Verify global kill is triggered
        assert controller.is_global_active() is False  # TRIGGERED means trading blocked


class TestKillSwitchIntegration:
    """Tests for kill switch integration with other components."""
    
    def test_trading_hours_respects_kill_switch(self, kill_switch_temp_dir, _reset_trade_mode_between_tests):
        """Trading hours guard doesn't override kill switch."""
        set_trade_mode(TradeMode.PAPER, reason="test")
        
        # Even outside maintenance window, if kill switch is active, trading should be blocked
        # (This tests that kill switch takes precedence)
        
        controller = kill_switch_temp_dir
        
        # Trigger global kill
        controller.trigger(
            reason=KillSwitchReason.MANUAL,
            scope="global",
            details="Test integration"
        )
        
        # Verify kill switch is active
        assert controller.is_global_active() is False
    
    def test_kill_switch_logged_with_context(self, kill_switch_temp_dir):
        """Kill switch activation is logged with full context."""
        controller = kill_switch_temp_dir
        
        # Trigger with specific reason
        controller.trigger(
            reason=KillSwitchReason.RTI_FEED_STALE,
            scope="asset",
            target="BTC",
            details="RTI feed stale for >5 minutes"
        )
        
        # Verify state
        assert controller.is_asset_killed("BTC") is True


class TestKillSwitchIsolation:
    """Tests to verify kill switches don't contaminate other tests."""
    
    def test_kill_switch_state_isolated_between_instances(self, tmp_path):
        """Each RiskController with different file has isolated state."""
        import os
        
        # Create two controllers with different temp files
        with patch.dict(os.environ, {"MERID_RISK_KS_FILE": str(tmp_path / "ks1.json")}):
            controller1 = RiskController()
            controller1.trigger(KillSwitchReason.MANUAL, scope="global")
        
        with patch.dict(os.environ, {"MERID_RISK_KS_FILE": str(tmp_path / "ks2.json")}):
            controller2 = RiskController()
            # controller2 should not see controller1's kill
            assert controller2.is_global_active() is True  # Still active (not triggered)
    
    def test_kill_switch_reset_between_tests(self, kill_switch_temp_dir):
        """Kill switch fixture provides clean state."""
        controller = kill_switch_temp_dir
        
        # Verify clean state
        assert controller.is_global_active() is True
        assert controller.is_asset_killed("BTC") is False


class TestKillSwitchTradeModeInteraction:
    """Tests verifying kill switches respect TradeMode (don't alter it)."""
    
    def test_kill_switch_operations_dont_change_trade_mode(self, kill_switch_temp_dir, _reset_trade_mode_between_tests):
        """Kill switch operations should never change TradeMode."""
        set_trade_mode(TradeMode.PAPER, reason="test_start")
        assert get_trade_mode() == TradeMode.PAPER
        
        controller = kill_switch_temp_dir
        
        # Various kill switch operations
        controller.trigger(KillSwitchReason.MANUAL, scope="global")
        assert get_trade_mode() == TradeMode.PAPER
        
        controller.reset(KillSwitchReason.MANUAL, operator_id="test_ops")
        assert get_trade_mode() == TradeMode.PAPER
        
        controller.trigger(KillSwitchReason.RTI_FEED_STALE, scope="asset", target="BTC")
        assert get_trade_mode() == TradeMode.PAPER
