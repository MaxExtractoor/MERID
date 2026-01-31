"""Batch 21 tests: protocol maintenance agents and RLlib env helpers."""

from __future__ import annotations

import numpy as np

from swarm.protocol_maintenance import (
    HealthMetricType,
    ParameterTunerAgent,
    ProtocolHealthMonitor,
    SecurityMaintenanceAgent,
    UpgradeCoordinator,
)
from swarm.rllib_wrapper import MERIDRLlibEnv, evaluate_rllib_model


class DummyAlgo:
    def __init__(self):
        self._deterministic = 0

    def compute_single_action(self, obs, explore: bool = False):
        self._deterministic = (self._deterministic + 1) % 4
        return self._deterministic


class TestProtocolHealthMonitor:
    def test_metric_updates_and_health_report(self) -> None:
        monitor = ProtocolHealthMonitor()
        volume_metric = monitor.update_metric(HealthMetricType.VOLUME_24H, 200000.0)
        assert volume_metric.status.value in {"healthy", "degraded"}

        error_metric = monitor.update_metric(HealthMetricType.ERROR_RATE, 0.2)
        assert error_metric.status.value == "critical"
        report = monitor.get_health_report()
        assert report["overall_status"] in {"critical", "degraded"}
        assert HealthMetricType.ERROR_RATE.value in report["metrics"]
        assert report["metrics"][HealthMetricType.ERROR_RATE.value]["status"] == "critical"

    def test_parameter_tuner_flow(self) -> None:
        tuner = ParameterTunerAgent()
        proposal = tuner.propose_parameter_change(
            parameter_type=HealthMetricType.VOLUME_24H,
            parameter_name="maker_fee",
            current_value=0.001,
            proposed_value=0.0008,
            reason="Increase maker participation",
            expected_impact="+5% liquidity",
            within_governance_caps=False,
        )
        assert proposal.requires_approval is True
        tuner.approve_proposal(proposal.proposal_id)
        assert tuner.apply_proposal(proposal.proposal_id) is True

        experiment = tuner.start_experiment("exp_fee", "maker_fee", [0.0008, 0.0006], duration_hours=1)
        assert experiment["experiment_id"] == "exp_fee"
        tuner.record_experiment_result("exp_fee", 0.0008, True)
        tuner.record_experiment_result("exp_fee", 0.0008, False)
        tuner.record_experiment_result("exp_fee", 0.0006, True)
        assert tuner.get_experiment_winner("exp_fee") in {0.0008, 0.0006}

    def test_upgrade_and_security_agents(self) -> None:
        coordinator = UpgradeCoordinator()
        plan = coordinator.create_upgrade_plan(
            upgrade_type=HealthMetricType.SLIPPAGE,
            description="Router upgrade",
            affected_contracts=["router_v1"],
            estimated_downtime_minutes=5,
            requires_liquidity_migration=True,
        )
        results = coordinator.simulate_upgrade(plan.plan_id, {"stress": "high"})
        assert results["success" ] is True
        proposal_id = coordinator.prepare_governance_proposal(plan.plan_id)
        assert proposal_id.startswith("gov_proposal_")
        assert coordinator.execute_upgrade(plan.plan_id, governance_approved=True) is True

        security = SecurityMaintenanceAgent()
        update = security.create_security_update(
            update_type="exploit",
            description="New MEV detection",
            new_patterns=["sandwich_v2"],
        )
        assert security.get_pending_updates()
        assert security.apply_security_update(update.update_id) is True
        assert security.get_pending_updates() == []


class TestRLlibEnvAndEvaluation:
    def test_env_reset_and_step_shapes(self) -> None:
        env = MERIDRLlibEnv({"num_agents": 2, "obs_size": 20, "action_size": 3, "max_steps": 5})
        obs, _ = env.reset()
        assert obs.shape == (20,)
        obs2, reward, done, truncated, info = env.step(env.action_space.sample())
        assert obs2.shape == (20,)
        assert isinstance(reward, float)
        assert info["agent_id"] == env.agent_id
        assert done in {True, False}
        assert truncated is False

    def test_evaluate_rllib_model_with_dummy_algo(self) -> None:
        metrics = evaluate_rllib_model(DummyAlgo(), num_episodes=2)
        assert metrics["num_episodes"] == 2
        assert metrics["mean_reward"] >= 0.0
        assert metrics["mean_episode_length"] > 0
