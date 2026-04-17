"""Tests for AutoPromoter with proper test isolation.

Test Suite Invariants:
- TradeMode is always reset between tests (via conftest.py autouse fixture)
- AutoPromoter uses temp storage (via auto_promoter_clean fixture)
- No test alters global mode for other tests
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from merid.promotion.auto_promoter import AutoPromoter, PromotionState, get_auto_promoter
from trading.trade_mode import TradeMode, set_trade_mode, get_trade_mode


class TestAutoPromoterLifecycle:
    """Tests for AutoPromoter promotion lifecycle with isolation."""
    
    def test_gauntlet_pass_produces_promotion_proposal(self, auto_promoter_clean):
        """GAUNTLET_PASS + sufficient paper performance produces promotion proposal, not auto-LIVE."""
        promoter = auto_promoter_clean
        agent_id = "BTC_15M"
        
        # Initialize agent
        promoter.initialize_agent(agent_id, "BTC", "15m")
        
        # Record gauntlet pass with high SLO rate
        promoter.record_gauntlet_result(
            agent_id=agent_id,
            passed=True,
            slo_pass_rate=0.98,
            failed_slos=[]
        )
        
        # Should be in GAUNTLET_PASS state
        status = promoter.get_status(agent_id)
        assert status.state == PromotionState.GAUNTLET_PASS
        assert status.gauntlet_passed is True
        assert status.ready_for_live is False  # Not ready yet - need paper performance
        
        # Record paper performance
        promoter.record_paper_performance(
            agent_id=agent_id,
            trades=60,
            win_rate=0.52,
            profit_factor=1.2
        )
        
        # Should now be AWAITING_CONFIRMATION (not automatically LIVE)
        status = promoter.get_status(agent_id)
        assert status.state == PromotionState.AWAITING_CONFIRMATION
        assert status.ready_for_live is True
    
    def test_gauntlet_fail_demotes_live_agent(self, auto_promoter_clean):
        """GAUNTLET_FAIL for a LIVE agent causes demotion + kill switch recommendation."""
        promoter = auto_promoter_clean
        agent_id = "ETH_15M"
        
        # Initialize and promote agent to LIVE
        promoter.initialize_agent(agent_id, "ETH", "15m")
        
        # Simulate full promotion path
        promoter.record_gauntlet_result(agent_id, True, 0.98, [])
        promoter.record_paper_performance(agent_id, 60, 0.52, 1.2)
        
        # Confirm live (simulating operator approval)
        promoter.confirm_live_trading(agent_id, operator_id="test_operator")
        
        status = promoter.get_status(agent_id)
        assert status.state == PromotionState.LIVE
        
        # Now simulate gauntlet failure (e.g., periodic re-check)
        promoter.record_gauntlet_result(
            agent_id=agent_id,
            passed=False,
            slo_pass_rate=0.75,
            failed_slos=["latency_p95", "fill_quality"]
        )
        
        # Should be demoted
        status = promoter.get_status(agent_id)
        assert status.state == PromotionState.DEMOTED
        assert "gauntlet failed" in status.demotion_reason.lower()
        
        # Markets should be blocked
        assert len(status.blocked_markets) > 0
    
    def test_operator_confirmation_required_for_live(self, auto_promoter_clean):
        """Operator confirmation is required - no silent transition to LIVE."""
        promoter = auto_promoter_clean
        agent_id = "SOL_15M"
        
        promoter.initialize_agent(agent_id, "SOL", "15m")
        promoter.record_gauntlet_result(agent_id, True, 0.98, [])
        promoter.record_paper_performance(agent_id, 60, 0.52, 1.2)
        
        # Should be awaiting confirmation
        status = promoter.get_status(agent_id)
        assert status.state == PromotionState.AWAITING_CONFIRMATION
        
        # Without confirmation, cannot go LIVE
        # (The state machine prevents this, but verify no silent transition)
        status2 = promoter.get_status(agent_id)
        assert status2.state != PromotionState.LIVE
    
    def test_promote_from_wrong_state_fails(self, auto_promoter_clean):
        """Cannot confirm live trading from wrong state."""
        promoter = auto_promoter_clean
        agent_id = "XRP_15M"
        
        # Initialize but don't complete gauntlet/paper
        promoter.initialize_agent(agent_id, "XRP", "15m")
        
        # Try to confirm live without meeting criteria
        result = promoter.confirm_live_trading(agent_id, operator_id="test_operator")
        
        # Should fail
        assert result is False
        
        status = promoter.get_status(agent_id)
        assert status.state != PromotionState.LIVE


class TestAutoPromoterKillSwitchIntegration:
    """Tests for AutoPromoter + per-market kill switch integration."""
    
    def test_per_market_kill_blocks_specific_ticker(self, auto_promoter_clean):
        """Block a specific market and verify it doesn't affect others."""
        promoter = auto_promoter_clean
        agent_id = "BTC_15M"
        
        promoter.initialize_agent(agent_id, "BTC", "15m")
        
        # Block only the 15m market
        promoter.block_market(agent_id, "KXBTC-15M", "test_reason")
        
        # Other markets should not be blocked
        status = promoter.get_status(agent_id)
        assert "KXBTC-15M" in status.blocked_markets
        assert "KXBTC-HOURLY" not in status.blocked_markets
        assert "KXETH-15M" not in status.blocked_markets
    
    def test_unblock_market_requires_operator(self, auto_promoter_clean):
        """Unblocking a market requires explicit operator action."""
        promoter = auto_promoter_clean
        agent_id = "DOGE_15M"
        
        promoter.initialize_agent(agent_id, "DOGE", "15m")
        promoter.block_market(agent_id, "KXDOGE-15M", "test_reason")
        
        status = promoter.get_status(agent_id)
        assert "KXDOGE-15M" in status.blocked_markets
        
        # Unblock with operator
        promoter.unblock_market(agent_id, "KXDOGE-15M", operator_id="test_ops")
        
        status = promoter.get_status(agent_id)
        assert "KXDOGE-15M" not in status.blocked_markets


class TestAutoPromoterIsolation:
    """Tests to verify AutoPromoter doesn't contaminate other tests."""
    
    def test_auto_promoter_state_isolated(self, tmp_path):
        """Each AutoPromoter instance has isolated state."""
        promoter1 = AutoPromoter()
        promoter1._state_file = tmp_path / "promoter1.json"
        promoter1._statuses = {}
        
        promoter2 = AutoPromoter()
        promoter2._state_file = tmp_path / "promoter2.json"
        promoter2._statuses = {}
        
        # Modify promoter1
        promoter1.initialize_agent("BTC_15M", "BTC", "15m")
        
        # Promoter2 should not see the agent
        assert promoter2.get_status("BTC_15M") is None
    
    def test_get_auto_promoter_singleton(self):
        """get_auto_promoter returns the same singleton instance."""
        p1 = get_auto_promoter()
        p2 = get_auto_promoter()
        
        assert p1 is p2


class TestAutoPromoterTradeModeInteraction:
    """Tests verifying AutoPromoter respects TradeMode (doesn't alter it)."""
    
    def test_promoter_operations_dont_change_trade_mode(self, auto_promoter_clean, _reset_trade_mode_between_tests):
        """AutoPromoter operations should never change TradeMode."""
        # Start in PAPER
        set_trade_mode(TradeMode.PAPER, reason="test_start")
        assert get_trade_mode() == TradeMode.PAPER
        
        promoter = auto_promoter_clean
        
        # Various promoter operations
        promoter.initialize_agent("BTC_15M", "BTC", "15m")
        assert get_trade_mode() == TradeMode.PAPER
        
        promoter.record_gauntlet_result("BTC_15M", True, 0.98, [])
        assert get_trade_mode() == TradeMode.PAPER
        
        promoter.record_paper_performance("BTC_15M", 60, 0.52, 1.2)
        assert get_trade_mode() == TradeMode.PAPER
        
        promoter.confirm_live_trading("BTC_15M", operator_id="test_ops")
        assert get_trade_mode() == TradeMode.PAPER  # Still PAPER (promoter doesn't change mode)
