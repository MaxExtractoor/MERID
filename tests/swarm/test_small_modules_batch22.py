"""Batch 22 tests: secure communication metrics and RLlib fallbacks."""

from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from swarm.secure_agent_communication import (
    MessagePriority,
    MessageType,
    SecureAgentCommunication,
)
from swarm import rllib_wrapper


class TestSecureAgentCommunicationMetrics:
    def test_metrics_filters_and_summary(self) -> None:
        comms = SecureAgentCommunication()
        topic = "ops"

        for agent_id in ("alpha", "beta"):
            comms.register_agent(
                agent_id=agent_id,
                role="ops",
                public_key=f"pub-{agent_id}",
                authorized_topics={topic},
                authorized_message_types={MessageType.INTENT},
            )

        payload = {"action": "rebalance", "asset": "ETH", "side": "buy", "size": 1.0}
        message = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic=topic,
            payload=payload,
            recipient_id="beta",
            priority=MessagePriority.HIGH,
            encrypt=True,
        )
        assert message is not None

        received = comms.receive_messages("beta", topic, message_type=MessageType.INTENT)
        assert len(received) == 1
        assert received[0].signature == message.signature

        metrics = comms.get_communication_metrics(topic=topic, message_type=MessageType.INTENT)
        assert metrics and metrics[0].total_sent == 1 and metrics[0].total_received == 1
        assert metrics[0].avg_latency_ms >= 0.0

        summary = comms.get_communication_summary()
        assert summary["total_sent"] == 1
        assert summary["total_received"] == 1
        assert summary["registered_agents"] == 2
        assert summary["active_topics"] >= 1
        assert summary["queued_messages"] == 0


class TestRLlibWrapperFallbacks:
    def test_train_rllib_returns_none_when_ray_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_import(name, *args, **kwargs):
            if name.startswith("ray"):
                raise ImportError("ray not available")
            return original_import(name, *args, **kwargs)

        original_import = builtins.__import__
        monkeypatch.setattr(builtins, "__import__", fake_import)

        algo = rllib_wrapper.train_rllib_marl(algorithm="PPO", training_iterations=1)
        assert algo is None

    def test_distributed_training_handles_failed_algo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(rllib_wrapper, "train_rllib_marl", lambda **_: None)
        result = rllib_wrapper.distributed_marl_training(num_agents=2, num_workers=1, num_gpus=0)
        assert result["status"] == "error"
        assert "detail" in result
