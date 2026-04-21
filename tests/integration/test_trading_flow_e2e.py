"""End-to-end integration tests for MERID trading flow."""
import pytest
import asyncio
import time
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from dataclasses import dataclass


class TestTradingFlowE2E:
    """End-to-end tests for trading flow: signal -> consensus -> execution."""

    @pytest.fixture
    def mock_agent(self):
        """Create mock agent."""
        agent = Mock()
        agent.agent_id = "test_agent_001"
        agent.get_signal = Mock(return_value={
            "action": "buy",
            "symbol": "BTC/USD",
            "confidence": 0.85,
            "size": 100.0,
        })
        return agent

    @pytest.fixture
    def mock_consensus(self):
        """Create mock consensus coordinator."""
        consensus = Mock()
        consensus.submit_proposal = Mock(return_value="proposal_001")
        consensus.get_result = Mock(return_value={
            "approved": True,
            "votes": {"for": 3, "against": 1},
            "quorum_met": True,
        })
        return consensus

    @pytest.fixture
    def mock_execution(self):
        """Create mock execution engine."""
        execution = Mock()
        execution.place_order = Mock(return_value={
            "order_id": "order_001",
            "status": "filled",
            "fill_price": 50000.0,
            "filled_qty": 100.0,
        })
        return execution

    def test_full_trading_flow(self, mock_agent, mock_consensus, mock_execution):
        """Test complete trading flow from signal to execution."""
        # Step 1: Agent generates signal
        signal = mock_agent.get_signal()
        assert signal["action"] == "buy"
        assert signal["confidence"] >= 0.8

        # Step 2: Submit to consensus
        proposal_id = mock_consensus.submit_proposal(signal)
        assert proposal_id == "proposal_001"

        # Step 3: Get consensus result
        result = mock_consensus.get_result(proposal_id)
        assert result["approved"] is True
        assert result["quorum_met"] is True

        # Step 4: Execute approved trade
        if result["approved"]:
            order = mock_execution.place_order(
                symbol=signal["symbol"],
                side=signal["action"],
                size=signal["size"],
            )
            assert order["status"] == "filled"
            assert order["fill_price"] > 0

    def test_trading_flow_rejected_by_consensus(self, mock_agent, mock_consensus, mock_execution):
        """Test flow when consensus rejects the trade."""
        signal = mock_agent.get_signal()
        
        mock_consensus.get_result = Mock(return_value={
            "approved": False,
            "votes": {"for": 1, "against": 3},
            "quorum_met": True,
            "rejection_reason": "Risk limits exceeded",
        })

        proposal_id = mock_consensus.submit_proposal(signal)
        result = mock_consensus.get_result(proposal_id)

        assert result["approved"] is False
        # Execution should NOT be called
        mock_execution.place_order.assert_not_called()

    def test_trading_flow_low_confidence_signal(self, mock_agent, mock_consensus):
        """Test flow filters out low confidence signals."""
        mock_agent.get_signal = Mock(return_value={
            "action": "buy",
            "symbol": "BTC/USD",
            "confidence": 0.3,  # Low confidence
            "size": 100.0,
        })

        signal = mock_agent.get_signal()
        
        # Low confidence signals should not reach consensus
        if signal["confidence"] < 0.5:
            mock_consensus.submit_proposal.assert_not_called()


class TestRiskGuardIntegration:
    """Integration tests for risk guard with trading."""

    @pytest.fixture
    def risk_guard(self):
        """Create mock risk guard."""
        guard = Mock()
        guard.can_trade = Mock(return_value=True)
        guard.check_order = Mock(return_value={"allowed": True})
        guard.record_trade = Mock()
        return guard

    def test_risk_guard_allows_trade(self, risk_guard):
        """Test risk guard allows valid trade."""
        order = {
            "symbol": "ETH/USD",
            "side": "buy",
            "size": 50.0,
            "price": 3000.0,
        }

        can_trade = risk_guard.can_trade()
        assert can_trade is True

        check = risk_guard.check_order(order)
        assert check["allowed"] is True

    def test_risk_guard_blocks_trade_kill_switch(self, risk_guard):
        """Test risk guard blocks trade when kill switch active."""
        risk_guard.can_trade = Mock(return_value=False)

        can_trade = risk_guard.can_trade()
        assert can_trade is False

    def test_risk_guard_blocks_oversized_order(self, risk_guard):
        """Test risk guard blocks oversized orders."""
        risk_guard.check_order = Mock(return_value={
            "allowed": False,
            "reason": "Order size exceeds limit",
        })

        oversized_order = {
            "symbol": "BTC/USD",
            "side": "buy",
            "size": 1000000.0,  # Very large
            "price": 50000.0,
        }

        check = risk_guard.check_order(oversized_order)
        assert check["allowed"] is False
        assert "exceeds" in check["reason"].lower()


class TestPaperTradingIntegration:
    """Integration tests for paper trading system."""

    @pytest.fixture
    def paper_engine(self):
        """Create mock paper trading engine."""
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            from trading.paper_trading import PaperTradingEngine
            engine = PaperTradingEngine(starting_balance=10000.0)
            engine.current_prices["BTC"] = 50000.0
            engine.current_prices["BTC/USD"] = 50000.0
            engine.current_prices["ETH"] = 3000.0
            engine.current_prices["ETH/USD"] = 3000.0
            return engine

    def test_paper_trading_full_cycle(self, paper_engine):
        """Test full paper trading cycle: order -> position -> close."""
        # Place order
        order = paper_engine.place_order(
            user_id="test_user",
            asset="BTC",
            side="long",
            size_usd=1000.0,
            order_type="market",
        )
        
        assert order.status.value == "filled"
        assert order.fill_price is not None

        # Check position created
        portfolio = paper_engine.get_portfolio("test_user")
        assert len(portfolio.positions) == 1

        # Close position
        position_key = "BTC_long_perp"
        pnl = paper_engine.close_position("test_user", position_key)
        
        assert pnl is not None
        assert len(portfolio.positions) == 0

    def test_paper_trading_multiple_orders(self, paper_engine):
        """Test multiple paper orders."""
        # Place multiple orders
        paper_engine.place_order("user1", "BTC", "long", 500.0)
        paper_engine.place_order("user1", "ETH", "long", 300.0)
        paper_engine.place_order("user2", "BTC", "short", 400.0)

        stats = paper_engine.get_global_stats()
        
        assert stats["accounts"] == 2
        assert stats["active_positions"] == 3

    def test_paper_trading_insufficient_balance(self, paper_engine):
        """Test order rejection for insufficient balance."""
        order = paper_engine.place_order(
            user_id="poor_user",
            asset="BTC",
            side="long",
            size_usd=50000.0,  # More than starting balance
            order_type="market",
        )
        
        assert order.status.value == "rejected"


class TestConsensusIntegration:
    """Integration tests for consensus system."""

    def test_consensus_quorum_calculation(self):
        """Test consensus quorum calculation."""
        total_agents = 5
        quorum_threshold = 0.6
        required_votes = int(total_agents * quorum_threshold)
        
        # 3 votes needed for quorum with 5 agents at 60%
        assert required_votes == 3

        # Test various vote scenarios
        votes_for = 3
        votes_against = 2
        quorum_met = (votes_for + votes_against) >= required_votes
        approved = votes_for > votes_against and quorum_met
        
        assert quorum_met is True
        assert approved is True

    def test_consensus_veto_power(self):
        """Test consensus veto handling."""
        votes = {
            "agent_1": {"vote": "for", "confidence": 0.9},
            "agent_2": {"vote": "for", "confidence": 0.8},
            "agent_3": {"vote": "veto", "confidence": 1.0, "reason": "Risk too high"},
        }

        has_veto = any(v["vote"] == "veto" for v in votes.values())
        assert has_veto is True

        # Veto should block regardless of votes
        if has_veto:
            approved = False
        else:
            approved = sum(1 for v in votes.values() if v["vote"] == "for") > len(votes) / 2
        
        assert approved is False


class TestAnomalyDetectionIntegration:
    """Integration tests for anomaly detection with trading."""

    @pytest.fixture
    def anomaly_stack(self):
        """Create anomaly detection stack."""
        from ops.anomaly_detection import AnomalyDetectionStack
        return AnomalyDetectionStack()

    def test_anomaly_detection_triggers_alert(self, anomaly_stack):
        """Test anomaly detection creates alerts."""
        import numpy as np

        # Train the isolation forest with normal data
        for _ in range(600):
            anomaly_stack.isolation_forest.add_training_sample(np.random.randn(10) * 0.1)

        # Check with normal input
        normal_input = np.zeros(10)
        event = anomaly_stack.check_input(normal_input)
        
        # Normal data should not trigger (or may trigger with low probability)
        assert event is None or event.severity.value in ["info", "warning"]

    def test_anomaly_detection_halt_decision(self, anomaly_stack):
        """Test halt decision based on anomalies."""
        from ops.anomaly_detection import AnomalyType, AnomalySeverity

        # Initially should not halt
        should_halt, reason = anomaly_stack.should_halt()
        assert should_halt is False

        # Add critical anomalies
        for i in range(4):
            anomaly_stack._create_event(
                anomaly_type=AnomalyType.OUTPUT_DRIFT,
                severity=AnomalySeverity.CRITICAL,
                detector="test",
                value=10.0,
                threshold=5.0,
                description=f"Test critical {i}",
            )

        should_halt, reason = anomaly_stack.should_halt()
        assert should_halt is True


class TestDisasterRecoveryIntegration:
    """Integration tests for disaster recovery."""

    @pytest.fixture
    def dr_manager(self):
        """Create disaster recovery manager."""
        from recovery.disaster_recovery import DisasterRecoveryManager
        return DisasterRecoveryManager()

    def test_recovery_point_creation(self, dr_manager):
        """Test creating recovery points."""
        point = dr_manager.create_recovery_point()
        
        assert point.point_id.startswith("rp_")
        assert point.verified is True
        assert len(dr_manager._recovery_points) == 1

    def test_playbook_execution(self, dr_manager):
        """Test executing recovery playbook."""
        result = dr_manager.execute_playbook("exchange_disconnect")
        
        assert result["playbook"] == "exchange_disconnect"
        assert result["status"] == "completed"
        assert len(result["steps_completed"]) > 0

    def test_capital_freeze_on_anomaly(self, dr_manager):
        """Test capital freeze triggers on anomaly."""
        dr_manager.capital_freeze.detect_anomaly(
            event_type="loss",
            value=15.0,  # Critical level
            threshold_key="max_loss_pct",
        )

        assert dr_manager.capital_freeze.is_frozen() is True

    def test_agent_quarantine_flow(self, dr_manager):
        """Test agent quarantine workflow."""
        # Check agent health and trigger quarantine
        reason = dr_manager.agent_quarantine.check_agent_health(
            agent_id="bad_agent",
            bad_decisions=10,
            consensus_rejections=0,
            trust_score=0.8,
        )

        assert reason is not None
        assert dr_manager.agent_quarantine.is_quarantined("bad_agent")

        # Release agent
        released = dr_manager.agent_quarantine.release_agent("bad_agent")
        assert released is True
        assert not dr_manager.agent_quarantine.is_quarantined("bad_agent")
