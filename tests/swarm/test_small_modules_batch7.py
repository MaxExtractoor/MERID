"""Tests for RLlib/SB3 env wrappers and structural weakness analyzer."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pytest

from swarm.rllib_wrapper import MERIDRLlibEnv
from swarm.sb3_wrapper import MERIDMultiAgentEnv
from swarm.structural_weaknesses_analysis import (
    StructuralWeaknessAnalyzer,
    WeaknessType,
    WorkflowNode,
)



class TestMERIDRLlibEnv:
    def test_reset_and_step_cycle(self):
        env = MERIDRLlibEnv(
            {
                "num_agents": 3,
                "obs_size": 20,
                "action_size": 2,
                "max_steps": 5,
                "agent_id": 7,
            }
        )

        obs, info = env.reset(seed=123)
        assert obs.shape == (20,)
        assert obs.dtype == np.float32
        assert info == {}

        done = False
        steps = 0
        while not done:
            obs, reward, done, truncated, step_info = env.step(env.action_space.sample())
            assert obs.shape == (20,)
            assert 0.0 <= reward <= 1.0
            assert truncated is False
            assert step_info["agent_id"] == 7
            steps += 1

        assert steps == env.max_steps


class TestMERIDMultiAgentEnv:
    def test_multi_agent_step_returns_rewards_and_infos(self):
        env = MERIDMultiAgentEnv(num_agents=4, obs_size=20, action_size=3, max_steps=3)
        observations, info = env.reset(seed=42)

        assert set(observations.keys()) == set(env.agents)
        assert info["step"] == 0

        actions: Dict[str, int] = {agent: env.action_space.sample() for agent in env.agents}
        next_obs, rewards, terminations, truncations, infos = env.step(actions)

        for agent in env.agents:
            assert next_obs[agent].shape == (20,)
            assert agent in rewards and isinstance(rewards[agent], float)
            assert agent in terminations and agent in truncations
            assert "consensus_quality" in infos[agent]
        assert set(terminations.keys()) == set(env.agents)


class TestStructuralWeaknessAnalyzer:
    def test_analyze_workflow_detects_multiple_weaknesses(self):
        analyzer = StructuralWeaknessAnalyzer()

        nodes: Dict[str, WorkflowNode] = {}

        # Create long chain to trigger over-chained detection
        nodes["stage_1"] = WorkflowNode(
            node_id="stage_1",
            node_type="agent",
            role="worker",
            dependencies=set(),
            optimization_metric="pnl",
        )
        setattr(nodes["stage_1"], "metadata", {"external_dependencies": ["market_data"]})
        for i in range(2, 8):  # chain length 7 (> default 5)
            nodes[f"stage_{i}"] = WorkflowNode(
                node_id=f"stage_{i}",
                node_type="agent",
                role="worker",
                dependencies={f"stage_{i-1}"},
                optimization_metric="pnl",
            )
            setattr(
                nodes[f"stage_{i}"],
                "metadata",
                {"external_dependencies": ["market_data"]},
            )

        # Circular dependency pair
        nodes["cycle_a"] = WorkflowNode(
            node_id="cycle_a",
            node_type="agent",
            role="risk",
            dependencies={"cycle_b"},
            optimization_metric="risk",
        )
        setattr(nodes["cycle_a"], "metadata", {})
        nodes["cycle_b"] = WorkflowNode(
            node_id="cycle_b",
            node_type="agent",
            role="risk",
            dependencies={"cycle_a"},
            optimization_metric="return",
        )
        setattr(nodes["cycle_b"], "metadata", {})

        # Orchestrator without fallback to trigger missing fallback
        nodes["planner"] = WorkflowNode(
            node_id="planner",
            node_type="orchestrator",
            role="planner",
            dependencies={"stage_7"},
            fallback_node=None,
        )
        setattr(nodes["planner"], "metadata", {})

        # Agent with self-dependency and no retries to trigger recursion
        nodes["loop"] = WorkflowNode(
            node_id="loop",
            node_type="agent",
            role="monitor",
            dependencies={"loop"},
            max_retries=None,
        )
        setattr(nodes["loop"], "metadata", {})

        workflow = analyzer.register_workflow(
            workflow_id="wf-1",
            name="Deep Workflow",
            description="Test workflow for weakness detection",
            nodes=nodes,
            entry_points=["stage_1"],
            exit_points=["planner"],
            global_objective="stability",
        )

        weaknesses = analyzer.analyze_workflow(workflow.workflow_id)
        types = {weakness.weakness_type for weakness in weaknesses}

        assert WeaknessType.OVER_CHAINED in types
        assert WeaknessType.CIRCULAR_DEPENDENCY in types
        assert WeaknessType.UNBOUNDED_RECURSION in types
        assert WeaknessType.MISSING_FALLBACK in types
        assert WeaknessType.UNCLEAR_INCENTIVES in types

        mitigated = analyzer.mitigate_weakness(weaknesses[0].weakness_id, "handled")
        assert mitigated.mitigated is True
