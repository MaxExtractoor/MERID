"""Tests for swarm.replicator."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from swarm import replicator as rep


class TestReplicatorAgent:
    def test_can_replicate_with_sufficient_energy(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=60.0,
        )
        agent.last_replication = 0  # Long time ago

        assert agent.can_replicate(min_energy=50.0, cooldown=0.0) is True

    def test_cannot_replicate_low_energy(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=30.0,
        )

        assert agent.can_replicate(min_energy=50.0) is False

    def test_cannot_replicate_max_replications_reached(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=100.0,
            replication_count=3,
            max_replications=3,
        )
        agent.last_replication = 0

        assert agent.can_replicate(cooldown=0.0) is False

    def test_replicate_creates_offspring(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=100.0,
        )
        agent.last_replication = 0

        with patch("random.uniform", return_value=0.0):
            offspring = agent.replicate()

        assert offspring is not None
        assert offspring.parent_id == "agent-1"
        assert offspring.generation == 1
        assert "child_1" in offspring.agent_id
        assert agent.energy == 70.0
        assert agent.replication_count == 1

    def test_replicate_fails_when_cannot_replicate(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=10.0,
        )

        offspring = agent.replicate()
        assert offspring is None

    def test_consume_energy(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=50.0,
        )

        agent.consume_energy(20.0)
        assert agent.energy == 30.0

        agent.consume_energy(100.0)
        assert agent.energy == 0.0

    def test_recharge_energy(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=50.0,
        )

        agent.recharge_energy(30.0)
        assert agent.energy == 80.0

        agent.recharge_energy(50.0)
        assert agent.energy == 100.0

    def test_is_alive(self):
        agent = rep.ReplicatorAgent(
            agent_id="agent-1",
            generation=0,
            parent_id=None,
            expertise=0.8,
            energy=10.0,
        )

        assert agent.is_alive() is True

        agent.energy = 0.0
        assert agent.is_alive() is False


class TestReplicatorSwarm:
    def test_initialization(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=5, max_population=20)

        assert len(swarm.agents) == 5
        assert swarm.max_population == 20
        assert swarm.generation_stats[0] == 5

    def test_step_consumes_energy(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=3)

        initial_energies = {aid: a.energy for aid, a in swarm.agents.items()}

        swarm.step(consensus_quality=0.5)

        for aid, agent in swarm.agents.items():
            assert agent.energy < initial_energies[aid]

    def test_step_recharges_on_high_consensus(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=3)

        for agent in swarm.agents.values():
            agent.energy = 50.0

        swarm.step(consensus_quality=0.9)

        for agent in swarm.agents.values():
            assert agent.energy == 54.0

    def test_step_removes_dead_agents(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=5, min_population=1)

        list(swarm.agents.values())[0].energy = 0.5

        stats = swarm.step(consensus_quality=0.5)

        assert stats["deaths"] >= 1

    def test_step_replicates_on_high_consensus(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(
                initial_population=3,
                max_population=10,
                replication_threshold=0.7,
            )

        for agent in swarm.agents.values():
            agent.last_replication = 0

        stats = swarm.step(consensus_quality=0.9)

        assert stats["replications"] > 0
        assert len(swarm.agents) > 3

    def test_step_emergency_replication_on_threat(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=3, max_population=10)

        for agent in swarm.agents.values():
            agent.last_replication = 0

        initial_pop = len(swarm.agents)
        stats = swarm.step(consensus_quality=0.5, threat_level=0.7)

        assert stats["population"] >= initial_pop

    def test_maintains_minimum_population(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=5, min_population=3)

        for agent in list(swarm.agents.values())[:4]:
            agent.energy = 0.0

        swarm.step(consensus_quality=0.5)

        assert len(swarm.agents) >= 3

    def test_get_metrics(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=3)

        metrics = swarm.get_metrics()

        assert metrics["population"] == 3
        assert "avg_energy" in metrics
        assert "avg_expertise" in metrics
        assert "generation_distribution" in metrics

    def test_get_active_agents(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=4)

        agents = swarm.get_active_agents()
        assert len(agents) == 4

    def test_inject_threat(self):
        with patch("random.uniform", return_value=0.8):
            swarm = rep.ReplicatorSwarm(initial_population=10)

        swarm.inject_threat(threat_level=0.5)

        dead_count = sum(1 for a in swarm.agents.values() if a.energy == 0.0)
        assert dead_count > 0


class TestBoidSwarm:
    def test_initialization(self):
        with patch("random.uniform", return_value=50.0):
            swarm = rep.BoidSwarm(num_boids=10)

        assert len(swarm.boids) == 10
        assert all("position" in b and "velocity" in b for b in swarm.boids)

    def test_step_updates_positions(self):
        with patch("random.uniform", return_value=50.0):
            swarm = rep.BoidSwarm(num_boids=5)

        initial_positions = [b["position"].copy() for b in swarm.boids]

        swarm.step()

        positions_changed = any(
            swarm.boids[i]["position"] != initial_positions[i]
            for i in range(len(swarm.boids))
        )
        assert positions_changed

    def test_get_snapshot(self):
        with patch("random.uniform", return_value=50.0):
            swarm = rep.BoidSwarm(num_boids=10)

        snapshot = swarm.get_snapshot()

        assert snapshot["num_boids"] == 10
        assert "boids" in snapshot
        assert "avg_speed" in snapshot
