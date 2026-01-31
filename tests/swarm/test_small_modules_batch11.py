"""Tests for secure_agent_communication, pso_optimizer, and spawner modules."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import pytest

from swarm.pso_optimizer import (
    MARLHyperparams,
    PSOConfig,
    PSOOptimizer,
    PSOMarLTuner,
)
from swarm.secure_agent_communication import (
    MessagePriority,
    MessageType,
    SecureAgentCommunication,
)
from swarm.spawner import SwarmSpawner


@pytest.fixture(autouse=True)
def _seed_randomness() -> None:
    random.seed(42)
    np.random.seed(42)


@pytest.fixture()
def comm() -> SecureAgentCommunication:
    comm = SecureAgentCommunication()
    comm.register_agent(
        agent_id="agent_a",
        role="exec",
        public_key="pub-a",
        authorized_topics={"trading", "alerts"},
        authorized_message_types={MessageType.INTENT, MessageType.ALERT},
    )
    comm.register_agent(
        agent_id="agent_b",
        role="ops",
        public_key="pub-b",
        authorized_topics={"trading"},
        authorized_message_types={MessageType.INTENT, MessageType.ALERT},
    )
    return comm


class TestSecureAgentCommunication:
    def test_send_receive_updates_metrics(self, comm: SecureAgentCommunication):
        payload = {"action": "buy", "asset": "ETH", "side": "bid", "size": 1.2}
        message = comm.send_message(
            sender_id="agent_a",
            message_type=MessageType.INTENT,
            topic="trading",
            payload=payload,
            recipient_id="agent_b",
            priority=MessagePriority.HIGH,
        )
        assert message is not None and message.signature

        received = comm.receive_messages("agent_b", topic="trading")
        assert received and received[0].payload == payload

        metrics = comm.get_communication_metrics(topic="trading", message_type=MessageType.INTENT)[0]
        assert metrics.total_sent == 1
        assert metrics.total_received == 1
        assert metrics.avg_latency_ms >= 0

    def test_authorization_and_circuit_breaker(self, comm: SecureAgentCommunication):
        comm.register_agent(
            agent_id="agent_c",
            role="observer",
            public_key="pub-c",
            authorized_topics={"alerts"},
            authorized_message_types={MessageType.ALERT},
        )

        # Unauthorized topic should fail
        rejected = comm.send_message(
            sender_id="agent_c",
            message_type=MessageType.ALERT,
            topic="trading",
            payload={"alert_type": "risk", "severity": "MED", "description": "test"},
        )
        assert rejected is None

        # Open circuit breaker prevents sends
        comm._circuit_breakers["alerts"] = {"open": True}
        dropped = comm.send_message(
            sender_id="agent_a",
            message_type=MessageType.ALERT,
            topic="alerts",
            payload={"alert_type": "latency", "severity": "HIGH", "description": "spike"},
        )
        assert dropped is None

        summary = comm.get_communication_summary()
        assert summary["total_errors"] >= 1
        assert summary["total_dropped"] >= 1


class TestPSOOptimizer:
    def test_optimize_converges_on_simple_function(self):
        config = PSOConfig(
            num_particles=6,
            max_iterations=8,
            bounds=[(-1.0, 1.0), (-1.0, 1.0)],
            adaptive_inertia=False,
            w=0.6,
        )
        optimizer = PSOOptimizer(config)

        def fitness(position: np.ndarray) -> float:
            # Maximum at origin
            return -float(np.sum(position ** 2))

        best_position, best_fitness = optimizer.optimize(fitness)

        assert best_fitness <= 0
        assert np.linalg.norm(best_position) < 0.5
        metrics = optimizer.get_metrics()
        assert metrics["iteration"] == config.max_iterations - 1
        assert len(metrics["fitness_history"]) == config.max_iterations

    def test_ring_topology_uses_neighbor_best(self):
        config = PSOConfig(
            num_particles=4,
            max_iterations=1,
            bounds=[(-1.0, 1.0)],
            topology="ring",
        )
        optimizer = PSOOptimizer(config)
        for idx, particle in enumerate(optimizer.particles):
            particle.best_fitness = float(idx)
            particle.best_position = np.array([idx], dtype=float)
        best = optimizer._get_neighborhood_best(0)
        assert np.isclose(best[0], 3.0)


class _StubEnv:
    def __init__(self) -> None:
        self.calls: List[MARLHyperparams] = []

    def run_episode(self, hyperparams: MARLHyperparams) -> float:
        self.calls.append(hyperparams)
        return float(hyperparams.hidden_size) / 512.0


class TestPSOMarLTuner:
    def test_tuner_uses_optimizer_output(self, monkeypatch):
        tuner = PSOMarLTuner(lambda: _StubEnv(), num_particles=2, max_iterations=1)

        def fake_optimize(self, fitness_fn):  # type: ignore[override]
            position = np.array([0.001, 0.95, 0.995, 64, 2000, 256], dtype=float)
            self.global_best_position = position
            self.global_best_fitness = 10.0
            return position, 10.0

        monkeypatch.setattr(PSOOptimizer, "optimize", fake_optimize)
        best = tuner.tune()
        assert pytest.approx(best.learning_rate, rel=1e-6) == 0.001
        metrics = tuner.get_metrics()
        assert metrics["pso_metrics"]["global_best_fitness"] == 10.0


@dataclass
class _StubAgent:
    agent_id: str
    model_name: str = "alpha"
    trust: float = 1.0
    tool_budget: int = 2


class _StubLedger:
    def __init__(self, rows: List[Dict[str, Any]], parent: Optional[Dict[str, Any]]):
        self._rows = rows
        self._parent = parent

    def leaderboard(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._rows[:limit]

    def best_parent(self, min_score: float, min_votes: int) -> Optional[Dict[str, Any]]:
        if self._parent and self._parent["score"] >= min_score and self._parent["votes"] >= min_votes:
            return self._parent
        return None


@pytest.fixture()
def fixed_time(monkeypatch):
    monkeypatch.setattr("swarm.spawner.current_time", lambda: {"utc_iso": "2026-01-19T00:00:00Z"})


class TestSwarmSpawner:
    def test_bootstrap_records_lineage(self, fixed_time):
        ledger = _StubLedger([], None)
        spawner = SwarmSpawner(ledger)
        agents = [_StubAgent("agent#0001"), _StubAgent("agent#0002")]
        spawner.bootstrap(agents)

        lineage = {record.agent_id: record for record in spawner.lineage()}
        assert lineage["agent#0001"].parent_id is None
        assert lineage["agent#0002"].notes == "bootstrap"
        assert set(a.agent_id for a in spawner.get_active_agents()) == {"agent#0001", "agent#0002"}

    def test_refresh_handles_retire_and_spawn(self, monkeypatch, fixed_time):
        rows = [
            {"agent_id": "agent#0001", "votes": 6, "score": 0.2},
            {"agent_id": "agent#0002", "votes": 8, "score": 0.95},
        ]
        parent_stats = {"agent_id": "agent#0002", "votes": 8, "score": 0.95}
        ledger = _StubLedger(rows, parent_stats)

        spawner = SwarmSpawner(ledger, max_population=3, stale_score=0.3, spawn_threshold=0.6)
        agents = [_StubAgent("agent#0001"), _StubAgent("agent#0002")]
        spawner.bootstrap(agents)
        # Mark agent#0001 as generation > 0 to allow retirement
        spawner._lineage["agent#0001"].generation = 1

        monkeypatch.setattr("random.shuffle", lambda seq: None)
        refreshed = spawner.refresh_population()

        assert any(agent.agent_id != "agent#0002" and agent.agent_id.startswith("agent") for agent in refreshed)
        lineage = spawner.lineage()
        assert any(record.parent_id == "agent#0002" for record in lineage)
        assert spawner.get_replication_count() >= 0  # accessors remain usable
