"""
Tests for Exit Feedback Handler
"""

import pytest
from unittest.mock import Mock
from dataclasses import dataclass

from merid.position_management.exit_feedback_handler import (
    ExitFeedback,
    ExitReason,
    AgentExitFeedbackHandler,
)


@dataclass
class MockAgent:
    """Mock agent for testing."""
    agent_id: str = "test_agent"
    feedback_received: list = None
    
    def __post_init__(self):
        if self.feedback_received is None:
            self.feedback_received = []
    
    def on_exit_feedback(self, feedback: ExitFeedback) -> None:
        """Handle exit feedback."""
        self.feedback_received.append(feedback)


class TestExitFeedback:
    """Tests for ExitFeedback dataclass."""
    
    def test_exit_feedback_creation(self):
        """Test creating exit feedback."""
        feedback = ExitFeedback(
            position_id="test_position",
            agent_id="BTC_15M",
            exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60,
            realized_pnl_cents=10,
            hold_time_seconds=300,
            entry_edge_pct=0.05,
            exit_edge_pct=0.02,
            r_multiple_at_exit=1.0,
        )
        
        assert feedback.position_id == "test_position"
        assert feedback.agent_id == "BTC_15M"
        assert feedback.exit_reason == ExitReason.TAKE_PROFIT
        assert feedback.exit_price_cents == 60
        assert feedback.realized_pnl_cents == 10
        assert feedback.hold_time_seconds == 300
        assert feedback.entry_edge_pct == 0.05
        assert feedback.exit_edge_pct == 0.02
        assert feedback.r_multiple_at_exit == 1.0


class TestAgentExitFeedbackHandler:
    """Tests for AgentExitFeedbackHandler."""
    
    @pytest.fixture
    def handler(self):
        """Create a feedback handler."""
        return AgentExitFeedbackHandler(max_history=10)
    
    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent."""
        return MockAgent(agent_id="BTC_15M")
    
    def test_register_agent(self, handler, mock_agent):
        """Test registering an agent."""
        handler.register_agent("BTC_15M", mock_agent)
        
        assert "BTC_15M" in handler._agents
        assert handler._agents["BTC_15M"] == mock_agent
    
    def test_unregister_agent(self, handler, mock_agent):
        """Test unregistering an agent."""
        handler.register_agent("BTC_15M", mock_agent)
        handler.unregister_agent("BTC_15M")
        
        assert "BTC_15M" not in handler._agents
    
    def test_send_exit_feedback_success(self, handler, mock_agent):
        """Test sending exit feedback successfully."""
        handler.register_agent("BTC_15M", mock_agent)
        
        feedback = ExitFeedback(
            position_id="test_position",
            agent_id="BTC_15M",
            exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60,
            realized_pnl_cents=10,
            hold_time_seconds=300,
            entry_edge_pct=0.05,
        )
        
        handler.send_exit_feedback(feedback)
        
        assert len(mock_agent.feedback_received) == 1
        assert mock_agent.feedback_received[0] == feedback
        assert len(handler._feedback_history) == 1
    
    def test_send_exit_feedback_agent_not_registered(self, handler):
        """Test sending feedback to unregistered agent."""
        feedback = ExitFeedback(
            position_id="test_position",
            agent_id="UNREGISTERED",
            exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60,
            realized_pnl_cents=10,
            hold_time_seconds=300,
            entry_edge_pct=0.05,
        )
        
        handler.send_exit_feedback(feedback)
        
        # Should not crash, should still store in history
        assert len(handler._feedback_history) == 1
    
    def test_send_exit_feedback_agent_no_handler(self, handler):
        """Test sending feedback to agent without feedback handler."""
        mock_agent = Mock()  # No on_exit_feedback method
        handler.register_agent("BTC_15M", mock_agent)
        
        feedback = ExitFeedback(
            position_id="test_position",
            agent_id="BTC_15M",
            exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60,
            realized_pnl_cents=10,
            hold_time_seconds=300,
            entry_edge_pct=0.05,
        )
        
        handler.send_exit_feedback(feedback)
        
        # Should not crash, should still store in history
        assert len(handler._feedback_history) == 1
    
    def test_send_exit_feedback_agent_handler_fails(self, handler):
        """Test when agent feedback handler raises exception."""
        mock_agent = Mock()
        mock_agent.on_exit_feedback.side_effect = Exception("Handler failed")
        handler.register_agent("BTC_15M", mock_agent)
        
        feedback = ExitFeedback(
            position_id="test_position",
            agent_id="BTC_15M",
            exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60,
            realized_pnl_cents=10,
            hold_time_seconds=300,
            entry_edge_pct=0.05,
        )
        
        handler.send_exit_feedback(feedback)
        
        # Should not crash, should still store in history
        assert len(handler._feedback_history) == 1
    
    def test_get_feedback_history_all(self, handler):
        """Test getting all feedback history."""
        feedback1 = ExitFeedback(
            position_id="pos1", agent_id="A1", exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60, realized_pnl_cents=10, hold_time_seconds=300, entry_edge_pct=0.05
        )
        feedback2 = ExitFeedback(
            position_id="pos2", agent_id="A2", exit_reason=ExitReason.STOP_LOSS,
            exit_price_cents=40, realized_pnl_cents=-5, hold_time_seconds=200, entry_edge_pct=0.04
        )
        
        handler.send_exit_feedback(feedback1)
        handler.send_exit_feedback(feedback2)
        
        history = handler.get_feedback_history()
        assert len(history) == 2
    
    def test_get_feedback_history_filtered(self, handler):
        """Test getting feedback history filtered by agent."""
        feedback1 = ExitFeedback(
            position_id="pos1", agent_id="A1", exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60, realized_pnl_cents=10, hold_time_seconds=300, entry_edge_pct=0.05
        )
        feedback2 = ExitFeedback(
            position_id="pos2", agent_id="A2", exit_reason=ExitReason.STOP_LOSS,
            exit_price_cents=40, realized_pnl_cents=-5, hold_time_seconds=200, entry_edge_pct=0.04
        )
        
        handler.send_exit_feedback(feedback1)
        handler.send_exit_feedback(feedback2)
        
        history = handler.get_feedback_history(agent_id="A1")
        assert len(history) == 1
        assert history[0].agent_id == "A1"
    
    def test_history_trimming(self, handler):
        """Test that history is trimmed when exceeding max."""
        handler._max_history = 5
        
        for i in range(10):
            feedback = ExitFeedback(
                position_id=f"pos{i}", agent_id="A1", exit_reason=ExitReason.TAKE_PROFIT,
                exit_price_cents=60, realized_pnl_cents=10, hold_time_seconds=300, entry_edge_pct=0.05
            )
            handler.send_exit_feedback(feedback)
        
        history = handler.get_feedback_history()
        assert len(history) == 5
    
    def test_get_agent_performance_empty(self, handler):
        """Test getting performance for agent with no history."""
        perf = handler.get_agent_performance("A1")
        
        assert perf["agent_id"] == "A1"
        assert perf["total_exits"] == 0
        assert perf["total_pnl_cents"] == 0
        assert perf["avg_pnl_cents"] == 0.0
        assert perf["win_rate"] == 0.0
    
    def test_get_agent_performance_with_data(self, handler):
        """Test getting performance for agent with history."""
        feedback1 = ExitFeedback(
            position_id="pos1", agent_id="A1", exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60, realized_pnl_cents=10, hold_time_seconds=300, entry_edge_pct=0.05
        )
        feedback2 = ExitFeedback(
            position_id="pos2", agent_id="A1", exit_reason=ExitReason.STOP_LOSS,
            exit_price_cents=40, realized_pnl_cents=-5, hold_time_seconds=200, entry_edge_pct=0.04
        )
        
        handler.send_exit_feedback(feedback1)
        handler.send_exit_feedback(feedback2)
        
        perf = handler.get_agent_performance("A1")
        
        assert perf["agent_id"] == "A1"
        assert perf["total_exits"] == 2
        assert perf["total_pnl_cents"] == 5  # 10 + (-5)
        assert perf["avg_pnl_cents"] == 2.5
        assert perf["win_rate"] == 0.5  # 1 win out of 2
        assert perf["avg_hold_time_seconds"] == 250.0  # (300 + 200) / 2
    
    def test_get_exit_reason_distribution(self, handler):
        """Test getting exit reason distribution."""
        feedback1 = ExitFeedback(
            position_id="pos1", agent_id="A1", exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=60, realized_pnl_cents=10, hold_time_seconds=300, entry_edge_pct=0.05
        )
        feedback2 = ExitFeedback(
            position_id="pos2", agent_id="A1", exit_reason=ExitReason.STOP_LOSS,
            exit_price_cents=40, realized_pnl_cents=-5, hold_time_seconds=200, entry_edge_pct=0.04
        )
        feedback3 = ExitFeedback(
            position_id="pos3", agent_id="A1", exit_reason=ExitReason.TAKE_PROFIT,
            exit_price_cents=65, realized_pnl_cents=15, hold_time_seconds=250, entry_edge_pct=0.06
        )
        
        handler.send_exit_feedback(feedback1)
        handler.send_exit_feedback(feedback2)
        handler.send_exit_feedback(feedback3)
        
        dist = handler.get_exit_reason_distribution(agent_id="A1")
        
        assert dist["take_profit"] == 2
        assert dist["stop_loss"] == 1
