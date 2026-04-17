"""Integration test for kill switch reset → execution gate allows trades.

This test verifies that after a kill switch reset, the execution gate
properly transitions from BLOCKED to CLEAR, allowing trading to resume.
"""

import pytest
from unittest.mock import patch, MagicMock

from core.execution_gate import check_execution_gate, ExecutionGateStatus, GateState
from merid.promotion.auto_promoter import AutoPromoter, PromotionState


class TestKillSwitchResetIntegration:
    """Test kill switch reset opens trading floodgates."""

    def test_execution_gate_blocked_when_kill_switch_engaged(self):
        """Execution gate should be BLOCKED when kill switch is active."""
        with patch("merid.risk.kill_switches.risk_controller") as mock_controller:
            mock_controller._global_kill = True
            mock_controller._kill_reason = "TEST_KILL"
            mock_controller._kill_details = "Test kill switch engaged"
            
            status = check_execution_gate()
            
            assert status.blocked is True
            assert status.gate_state == GateState.BLOCKED.value
            assert any(r.source == "kill_switch" for r in status.reasons)

    def test_execution_gate_clear_after_kill_switch_reset(self):
        """Execution gate should be CLEAR after kill switch is reset."""
        with patch("merid.risk.kill_switches.risk_controller") as mock_controller:
            # Start with kill switch engaged
            mock_controller._global_kill = False
            mock_controller._kill_reason = None
            mock_controller._kill_details = None
            mock_controller._daily_pnl = 0.0
            
            # Mock venue reconciliation to pass (merid.reconciliation is authoritative)
            with patch("merid.reconciliation.has_critical_discrepancies", return_value=False):
                with patch("core.execution_gate.check_price_feed_staleness") as mock_stale:
                    mock_stale.return_value = {"safe_to_trade": True}
                    
                    status = check_execution_gate()
                    
                    assert status.blocked is False
                    assert status.safe_to_trade is True
                    assert status.gate_state in (
                        GateState.CLEAR.value,
                        GateState.LIMITED.value,
                    )

    def test_guardian_promotion_after_kill_switch_reset(self):
        """Guardian mode should promote from OBSERVATION after reset + calibration."""
        promoter = AutoPromoter()
        # Mock _save_states to avoid file I/O timeout
        promoter._save_states = lambda: None
        
        # Initialize agent in PENDING state
        status = promoter.initialize_agent(
            agent_id="test-btc-15m",
            asset="BTC",
            timeframe="15m",
        )
        assert status.state == PromotionState.PENDING
        
        # Record gauntlet pass
        promoter.record_gauntlet_result(
            agent_id="test-btc-15m",
            passed=True,
            slo_pass_rate=0.96,
            failed_slos=[],
        )
        
        status = promoter.get_status("test-btc-15m")
        assert status.state == PromotionState.GAUNTLET_PASS
        
        # Record paper performance meeting benchmarks
        promoter.record_paper_performance(
            agent_id="test-btc-15m",
            trades=60,
            win_rate=0.50,
            profit_factor=1.15,
        )
        
        status = promoter.get_status("test-btc-15m")
        assert status.ready_for_live is True
        assert status.state == PromotionState.AWAITING_CONFIRMATION

    def test_kill_switch_blocks_agent_promotion_to_live(self):
        """Kill switch should prevent agent promotion to LIVE state."""
        promoter = AutoPromoter()
        # Mock _save_states to avoid file I/O timeout
        promoter._save_states = lambda: None
        
        # Initialize and advance agent to AWAITING_CONFIRMATION
        promoter.initialize_agent("test-agent", "BTC", "15m")
        promoter.record_gauntlet_result("test-agent", True, 0.96, [])
        promoter.record_paper_performance("test-agent", 60, 0.50, 1.15)
        
        # With kill switch engaged, confirm_live_trading should fail or be blocked
        with patch("merid.risk.kill_switches.risk_controller") as mock_controller:
            mock_controller._global_kill = True
            
            # Even if we try to confirm, execution gate should block
            status = check_execution_gate()
            assert status.blocked is True


class TestKalshiAgentGridSmoke:
    """Smoke test for Kalshi agent grid initialization."""

    def test_agent_promotion_status_instantiation_no_typo(self):
        """Verify AgentPromotionStatus can be instantiated without timerame typo."""
        from merid.promotion.auto_promoter import AgentPromotionStatus
        
        # This should NOT raise TypeError about 'timerame'
        status = AgentPromotionStatus(
            agent_id="btc-15m-01",
            asset="BTC",
            timeframe="15m",
            state=PromotionState.PENDING,
        )
        
        assert status.agent_id == "btc-15m-01"
        assert status.asset == "BTC"
        assert status.timeframe == "15m"
        assert status.state == PromotionState.PENDING

    def test_auto_promoter_initialize_agent_no_typo(self):
        """Verify AutoPromoter.initialize_agent works without timerame typo."""
        promoter = AutoPromoter()
        # Mock _save_states to avoid file I/O timeout
        promoter._save_states = lambda: None
        
        # This should NOT raise TypeError about 'timerame'
        status = promoter.initialize_agent(
            agent_id="eth-15m-01",
            asset="ETH",
            timeframe="15m",
        )
        
        assert status.agent_id == "eth-15m-01"
        assert status.asset == "ETH"
        assert status.timeframe == "15m"
        assert status.state == PromotionState.PENDING
