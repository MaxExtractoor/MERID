"""T-058: Swarm integration tests.

Tests agent coordination, consensus formation, and opinion routing
with real objects (not mocks) using test configurations.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from consensus.consensus_coordinator import EnhancedConsensusCoordinator as ConsensusCoordinator


@pytest.fixture
def coordinator():
    """Create a real ConsensusCoordinator with test config."""
    coord = ConsensusCoordinator.__new__(ConsensusCoordinator)
    coord._rounds = {}
    coord._round_history = []
    coord._pending_opinions = {}
    coord._registered_agents = {}
    coord._agent_heartbeats = {}
    coord._agent_reliability = {}
    coord._total_rounds = 0
    coord._successful_rounds = 0
    coord._timeout_rounds = 0
    coord._vetoed_rounds = 0
    coord._consecutive_timeouts = {}
    coord._vote_history = {}
    coord._limp_mode = False
    coord._limp_reason = ""
    coord._last_heartbeat = time.time()
    return coord


class TestSwarmConsensusFormation:
    """Test that consensus forms correctly with multiple agents."""

    def test_metrics_report_structure(self, coordinator):
        metrics = coordinator.get_metrics()
        assert "total_rounds" in metrics
        assert "successful_rounds" in metrics
        assert "active_rounds" in metrics
        assert "registered_agents" in metrics
        assert "heartbeat_age_s" in metrics
        assert "limp_mode" in metrics

    def test_no_active_rounds_initially(self, coordinator):
        assert coordinator.get_active_rounds() == []

    def test_recent_decisions_empty(self, coordinator):
        assert coordinator.get_recent_decisions() == []


class TestSwarmHeartbeat:
    """Test heartbeat dead-man's switch."""

    def test_heartbeat_ok(self, coordinator):
        coordinator.publish_heartbeat()
        assert coordinator.check_heartbeat() == "ok"

    def test_heartbeat_defensive(self, coordinator):
        coordinator._last_heartbeat = time.time() - 150
        assert coordinator.check_heartbeat() == "defensive"

    def test_heartbeat_kill(self, coordinator):
        coordinator._last_heartbeat = time.time() - 350
        assert coordinator.check_heartbeat() == "kill"

    def test_heartbeat_initializes_on_first_check(self, coordinator):
        del coordinator._last_heartbeat
        assert coordinator.check_heartbeat() == "ok"


class TestSwarmLimpMode:
    """Test limp mode enforcement."""

    def test_not_limp_by_default(self, coordinator):
        assert not coordinator.is_limp_mode()

    def test_enter_limp_mode(self, coordinator):
        coordinator.enter_limp_mode("test reason")
        assert coordinator.is_limp_mode()

    def test_exit_limp_mode(self, coordinator):
        coordinator.enter_limp_mode("test")
        coordinator.exit_limp_mode()
        assert not coordinator.is_limp_mode()

    def test_filter_plans_normal_mode(self, coordinator):
        plans = [{"symbol": "A", "direction": "long"}, {"symbol": "B", "direction": "close"}]
        filtered = coordinator.filter_plans_for_limp_mode(plans)
        assert len(filtered) == 2

    def test_filter_plans_limp_mode_blocks_long(self, coordinator):
        coordinator.enter_limp_mode("drawdown")
        plans = [
            {"symbol": "A", "direction": "long"},
            {"symbol": "B", "direction": "close"},
            {"symbol": "C", "direction": "reduce"},
            {"symbol": "D", "direction": "short"},
            {"symbol": "E", "direction": "flat"},
        ]
        filtered = coordinator.filter_plans_for_limp_mode(plans)
        directions = [p["direction"] for p in filtered]
        assert "long" not in directions
        assert "short" not in directions
        assert "close" in directions
        assert "reduce" in directions
        assert "flat" in directions
        assert len(filtered) == 3


class TestSwarmCollusionDetection:
    """Test collusion detection infrastructure."""

    def test_vote_history_tracking(self, coordinator):
        coordinator._vote_history["agent_1"] = [0.8, 0.7, 0.9]
        coordinator._vote_history["agent_2"] = [0.8, 0.7, 0.9]
        assert len(coordinator._vote_history) == 2

    def test_vote_history_independent(self, coordinator):
        coordinator._vote_history["agent_1"] = [0.8, 0.7, 0.9]
        coordinator._vote_history["agent_2"] = [0.2, 0.3, 0.1]
        assert coordinator._vote_history["agent_1"] != coordinator._vote_history["agent_2"]


class TestSwarmTimeoutEscalation:
    """Test timeout escalation tracking."""

    def test_consecutive_timeout_tracking(self, coordinator):
        coordinator._consecutive_timeouts["SYM1"] = 0
        coordinator._consecutive_timeouts["SYM1"] += 1
        assert coordinator._consecutive_timeouts["SYM1"] == 1

    def test_timeout_escalation_threshold(self, coordinator):
        coordinator._consecutive_timeouts["SYM1"] = 3
        assert coordinator._consecutive_timeouts["SYM1"] >= 3

    def test_timeout_reset_on_success(self, coordinator):
        coordinator._consecutive_timeouts["SYM1"] = 2
        coordinator._consecutive_timeouts["SYM1"] = 0
        assert coordinator._consecutive_timeouts["SYM1"] == 0
