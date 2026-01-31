"""Batch 16 tests for PSO optimizer and secure agent communication."""

from __future__ import annotations

import random
from typing import Callable

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


class TestPSOOptimizer:
    def test_optimizer_metrics_and_history(self) -> None:
        random.seed(0)
        np.random.seed(0)
        config = PSOConfig(
            num_particles=6,
            max_iterations=6,
            bounds=[(-1.0, 1.0), (-1.0, 1.0)],
            adaptive_inertia=False,
            w=0.5,
        )
        optimizer = PSOOptimizer(config)
        target = np.array([0.25, -0.75])

        def fitness_fn(position: np.ndarray) -> float:
            return -float(np.linalg.norm(position - target) ** 2)

        best_position, best_fitness = optimizer.optimize(fitness_fn)
        metrics = optimizer.get_metrics()

        assert best_position is not None
        assert metrics["iteration"] == config.max_iterations - 1
        assert metrics["global_best_fitness"] == pytest.approx(best_fitness)
        assert metrics["global_best_position"] == pytest.approx(best_position.tolist())
        assert len(metrics["fitness_history"]) == config.max_iterations
        assert len(metrics["diversity_history"]) == config.max_iterations


class DummyMarlEnv:
    def __init__(self) -> None:
        self.calls = 0

    def run_episode(self, hyperparams: MARLHyperparams) -> float:
        self.calls += 1
        return (
            100.0
            - abs(hyperparams.learning_rate - 0.005) * 5000
            - abs(hyperparams.gamma - 0.97) * 1000
            - abs(hyperparams.batch_size - 64) * 0.2
        )


class TestPSOMarLTuner:
    def test_tuner_returns_best_hyperparams_and_metrics(self) -> None:
        random.seed(1)
        np.random.seed(1)
        tuner = PSOMarLTuner(lambda: DummyMarlEnv(), num_particles=4, max_iterations=4)

        best_hyperparams = tuner.tune()
        metrics = tuner.get_metrics()

        assert isinstance(best_hyperparams, MARLHyperparams)
        assert metrics["best_hyperparams"]["learning_rate"] == pytest.approx(
            best_hyperparams.learning_rate
        )
        assert metrics["pso_metrics"]["global_best_fitness"] >= 0
        assert metrics["pso_metrics"]["num_particles"] == 4


class TestSecureAgentCommunication:
    def _register_agent(self, comm: SecureAgentCommunication, agent_id: str, topics: set[str]) -> None:
        comm.register_agent(
            agent_id=agent_id,
            role="secops",
            public_key=f"key-{agent_id}",
            authorized_topics=topics,
            authorized_message_types={MessageType.ALERT},
        )

    def _alert_payload(self) -> dict:
        return {
            "alert_type": "incident",
            "severity": "high",
            "description": "test alert",
        }

    def test_authorization_failure_records_error(self) -> None:
        comm = SecureAgentCommunication()
        self._register_agent(comm, "agent-alpha", {"alerts"})

        result = comm.send_message(
            sender_id="agent-alpha",
            message_type=MessageType.ALERT,
            topic="governance",
            payload=self._alert_payload(),
            priority=MessagePriority.HIGH,
        )

        assert result is None
        metrics = comm.get_communication_metrics(topic="governance")
        assert metrics and metrics[0].total_errors == 1

    def test_circuit_breaker_drops_messages(self) -> None:
        comm = SecureAgentCommunication()
        self._register_agent(comm, "agent-beta", {"alerts"})

        comm._circuit_breakers["alerts"] = {"open": True}
        result = comm.send_message(
            sender_id="agent-beta",
            message_type=MessageType.ALERT,
            topic="alerts",
            payload=self._alert_payload(),
        )

        assert result is None
        metrics = comm.get_communication_metrics(topic="alerts")
        assert metrics and metrics[0].total_dropped == 1

    def test_signature_verification_failure_in_receive(self) -> None:
        comm = SecureAgentCommunication()
        self._register_agent(comm, "agent-sender", {"alerts"})
        self._register_agent(comm, "agent-recipient", {"alerts"})

        message = comm.send_message(
            sender_id="agent-sender",
            message_type=MessageType.ALERT,
            topic="alerts",
            payload=self._alert_payload(),
        )
        assert message is not None

        queued = comm._message_queue["alerts"][0]
        queued.signature = "tampered"

        received = comm.receive_messages(
            recipient_id="agent-recipient",
            topic="alerts",
            message_type=MessageType.ALERT,
        )

        assert received == []
        metrics = comm.get_communication_metrics(topic="alerts")
        error_metrics = [m for m in metrics if m.total_errors > 0]
        assert error_metrics and error_metrics[0].total_errors >= 1
        summary = comm.get_communication_summary()
        assert summary["total_sent"] == 1
        assert summary["total_received"] == 0
