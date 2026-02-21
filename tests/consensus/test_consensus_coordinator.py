"""
Tests for EnhancedConsensusCoordinator.

Covers:
- Agent registration and health tracking
- Voting and quorum logic
- Veto handling
- Timeouts and retries
- Metrics and decision history
- Minimum viable swarm checks
"""

import pytest

# Quarantined: async event loop hangs on Windows IOCP in select/poll
pytestmark = pytest.mark.windows_flaky_async

import asyncio
import time
from unittest.mock import MagicMock

from consensus.consensus_coordinator import (
    EnhancedConsensusCoordinator,
    ConsensusConfig,
    ConsensusState,
    SafeDefaultAction,
    check_minimum_viable_swarm,
    get_limp_mode_policy,
)


@pytest.fixture
def coordinator():
    """Create a coordinator with short timeouts for testing."""
    EnhancedConsensusCoordinator._instance = None
    config = ConsensusConfig(
        min_agents_for_quorum=2,
        quorum_percentage=0.5,
        opinion_window_seconds=0.05,
        voting_timeout_seconds=0.05,
        round_timeout_seconds=0.05,
        max_retries=0,
    )
    return EnhancedConsensusCoordinator(config)


@pytest.fixture
def coordinator_single_quorum():
    """Create a coordinator that reaches quorum with one vote."""
    EnhancedConsensusCoordinator._instance = None
    config = ConsensusConfig(
        min_agents_for_quorum=1,
        quorum_percentage=0.5,
        opinion_window_seconds=0.05,
        voting_timeout_seconds=0.05,
        round_timeout_seconds=0.05,
        max_retries=0,
    )
    return EnhancedConsensusCoordinator(config)


class TestAgentManagement:
    def test_register_and_unregister_agent(self, coordinator):
        coordinator.register_agent("agent_1", "analyst")

        assert "agent_1" in coordinator._registered_agents
        assert "agent_1" in coordinator._agent_heartbeats
        assert coordinator._agent_reliability["agent_1"] == 1.0

        coordinator.unregister_agent("agent_1")
        assert "agent_1" not in coordinator._registered_agents
        assert "agent_1" not in coordinator._agent_heartbeats

    def test_record_heartbeat_resets_state(self, coordinator):
        coordinator.register_agent("agent_1", "analyst")
        hb = coordinator._agent_heartbeats["agent_1"]
        hb.is_healthy = False
        hb.consecutive_misses = 2

        coordinator.record_heartbeat("agent_1")

        hb = coordinator._agent_heartbeats["agent_1"]
        assert hb.is_healthy is True
        assert hb.consecutive_misses == 0

    def test_check_agent_health_marks_unhealthy(self, coordinator):
        coordinator.register_agent("agent_1", "analyst")
        hb = coordinator._agent_heartbeats["agent_1"]
        hb.last_heartbeat = time.time() - 120

        unhealthy = coordinator.check_agent_health(timeout_seconds=1)

        assert "agent_1" in unhealthy
        assert coordinator._agent_heartbeats["agent_1"].is_healthy is False
        assert coordinator._agent_heartbeats["agent_1"].consecutive_misses == 1
        assert coordinator._agent_reliability["agent_1"] < 1.0

    def test_agent_weight_risk_boost_and_confidence_penalty(self, coordinator):
        coordinator.register_agent("risk_agent", "risk_manager")
        coordinator.register_agent("analyst", "analyst")

        risk_weight = coordinator._get_agent_weight("risk_agent", "risk_manager", 0.9)
        analyst_weight = coordinator._get_agent_weight("analyst", "analyst", 0.9)
        low_conf_weight = coordinator._get_agent_weight("analyst", "analyst", 0.3)

        assert risk_weight > analyst_weight
        assert low_conf_weight < analyst_weight


class TestConsensusRounds:
    @pytest.mark.asyncio
    async def test_start_round_and_quorum_decision(self, coordinator_single_quorum):
        coordinator_single_quorum.register_agent("agent_1", "analyst")
        await coordinator_single_quorum.start_round("BTC", "paper")

        success = await coordinator_single_quorum.submit_vote(
            symbol="BTC",
            agent_id="agent_1",
            vote="approve",
            score=0.8,
            confidence=0.9,
            reasoning="Bullish signal",
        )

        assert success is True
        assert coordinator_single_quorum.get_round_status("BTC") is None

        decisions = coordinator_single_quorum.get_recent_decisions(limit=1)
        assert len(decisions) == 1
        assert decisions[0]["state"] == ConsensusState.DECIDED.value
        assert decisions[0]["direction"] == "long"

    @pytest.mark.asyncio
    async def test_veto_vote_short_circuits_round(self, coordinator):
        coordinator.register_agent("risk_agent", "risk_manager")
        await coordinator.start_round("ETH", "paper")

        success = await coordinator.submit_vote(
            symbol="ETH",
            agent_id="risk_agent",
            vote="veto",
            score=-1.0,
            confidence=1.0,
            reasoning="Risk veto",
        )

        assert success is True
        assert coordinator.get_round_status("ETH") is None

        decisions = coordinator.get_recent_decisions(limit=1)
        assert decisions[0]["state"] == ConsensusState.VETOED.value
        assert decisions[0]["direction"] == "flat"

    @pytest.mark.asyncio
    async def test_quorum_requires_min_agents(self, coordinator):
        coordinator.register_agent("agent_1", "analyst")
        coordinator.register_agent("agent_2", "analyst")
        await coordinator.start_round("SOL", "paper")

        success = await coordinator.submit_vote(
            symbol="SOL",
            agent_id="agent_1",
            vote="approve",
            score=0.7,
            confidence=0.8,
            reasoning="Signal",
        )

        assert success is True
        assert coordinator.get_round_status("SOL") is not None

        await coordinator.submit_vote(
            symbol="SOL",
            agent_id="agent_2",
            vote="approve",
            score=0.6,
            confidence=0.8,
            reasoning="Signal",
        )

        assert coordinator.get_round_status("SOL") is None

    @pytest.mark.asyncio
    async def test_round_timeout_marks_timeout(self, coordinator):
        coordinator.register_agent("agent_1", "analyst")
        await coordinator.start_round("XRP", "paper")

        await asyncio.sleep(0.1)

        decisions = coordinator.get_recent_decisions(limit=1)
        assert len(decisions) == 1
        assert decisions[0]["state"] == ConsensusState.TIMEOUT.value


class TestMetricsAndHistory:
    @pytest.mark.asyncio
    async def test_metrics_counts_rounds(self, coordinator_single_quorum):
        coordinator_single_quorum.register_agent("agent_1", "analyst")
        await coordinator_single_quorum.start_round("BTC", "paper")
        await coordinator_single_quorum.submit_vote(
            symbol="BTC",
            agent_id="agent_1",
            vote="approve",
            score=0.8,
            confidence=0.9,
            reasoning="Bullish",
        )

        metrics = coordinator_single_quorum.get_metrics()
        assert metrics["total_rounds"] == 1
        assert metrics["successful_rounds"] == 1
        assert metrics["active_rounds"] == 0

    @pytest.mark.asyncio
    async def test_recent_decisions_limit(self, coordinator_single_quorum):
        coordinator_single_quorum.register_agent("agent_1", "analyst")
        for symbol in ["BTC", "ETH", "SOL"]:
            await coordinator_single_quorum.start_round(symbol, "paper")
            await coordinator_single_quorum.submit_vote(
                symbol=symbol,
                agent_id="agent_1",
                vote="approve",
                score=0.8,
                confidence=0.9,
                reasoning="Signal",
            )

        decisions = coordinator_single_quorum.get_recent_decisions(limit=2)
        assert len(decisions) == 2


class TestMinimumViableSwarm:
    def test_minimum_viable_swarm_true(self, coordinator):
        coordinator.register_agent("agent_risk", "risk_manager")
        coordinator.register_agent("agent_exec", "execution_agent")

        assert check_minimum_viable_swarm(coordinator) is True

    def test_minimum_viable_swarm_false(self, coordinator):
        coordinator.register_agent("agent_risk", "risk_manager")

        assert check_minimum_viable_swarm(coordinator) is False

    def test_limp_mode_policy(self):
        policy = get_limp_mode_policy()

        assert "allowed_actions" in policy
        assert "blocked_actions" in policy
        assert "max_new_position_usd" in policy
        assert "require_risk_approval" in policy
