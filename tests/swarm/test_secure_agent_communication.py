"""Tests for SecureAgentCommunication."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm import secure_agent_communication as sac


def _build_system() -> sac.SecureAgentCommunication:
    system = sac.SecureAgentCommunication()
    system._schemas.clear()
    system._identities.clear()
    system._message_queue.clear()
    system._sent_messages.clear()
    system._received_messages.clear()
    system._metrics.clear()
    system._latency_samples.clear()
    system._circuit_breakers.clear()
    system._sequence_numbers.clear()
    system._initialize_schemas()
    return system


def _register_basic_agents(system: sac.SecureAgentCommunication) -> None:
    allowed_types = {sac.MessageType.INTENT, sac.MessageType.ALERT}
    system.register_agent(
        agent_id="agent-alpha",
        role="planner",
        public_key="pk-alpha",
        authorized_topics={"trading", "alerts"},
        authorized_message_types=allowed_types,
    )
    system.register_agent(
        agent_id="agent-beta",
        role="executor",
        public_key="pk-beta",
        authorized_topics={"trading"},
        authorized_message_types=allowed_types,
    )


@pytest.fixture()
def system():
    return _build_system()


@pytest.fixture()
def registered_system(system):
    _register_basic_agents(system)
    return system


def test_send_fails_when_schema_missing_required_field(registered_system):
    registered_system.register_schema(
        message_type=sac.MessageType.COORDINATION,
        version="1.0",
        required_fields={"step"},
        optional_fields=set(),
        field_types={"step": int},
    )

    registered_system.register_agent(
        agent_id="agent-gamma",
        role="coord",
        public_key="pk-gamma",
        authorized_topics={"coord"},
        authorized_message_types={sac.MessageType.COORDINATION},
    )

    msg = registered_system.send_message(
        sender_id="agent-gamma",
        message_type=sac.MessageType.COORDINATION,
        topic="coord",
        payload={},
    )

    assert msg is None
    metrics = registered_system._metrics["coord_coordination"]
    assert metrics.total_errors == 1


def test_authorization_blocks_unallowed_topic(registered_system):
    message = registered_system.send_message(
        sender_id="agent-beta",
        message_type=sac.MessageType.INTENT,
        topic="alerts",
        payload={"action": "buy", "asset": "ETH", "side": "buy", "size": 1.0},
    )
    assert message is None


def test_send_and_receive_flow_updates_metrics(monkeypatch, registered_system):
    payload = {"action": "rebalance", "asset": "BTC", "side": "sell", "size": 0.5}

    message = registered_system.send_message(
        sender_id="agent-alpha",
        message_type=sac.MessageType.INTENT,
        topic="trading",
        payload=payload,
        recipient_id="agent-beta",
        correlation_id="corr-1",
        sign=True,
    )
    assert message is not None
    assert message.sequence_number == 1

    received = registered_system.receive_messages(
        recipient_id="agent-beta",
        topic="trading",
        max_messages=5,
    )
    assert len(received) == 1
    assert received[0].correlation_id == "corr-1"

    metrics = registered_system._metrics["trading_intent"]
    assert metrics.total_sent == 1
    assert metrics.total_received == 1
    assert metrics.avg_latency_ms >= 0


def test_circuit_breaker_drop_records_metrics(monkeypatch, registered_system):
    registered_system._circuit_breakers["alerts"] = {"open": True}

    message = registered_system.send_message(
        sender_id="agent-alpha",
        message_type=sac.MessageType.ALERT,
        topic="alerts",
        payload={"alert_type": "risk", "severity": "high", "description": "test"},
    )
    assert message is None

    metrics = registered_system._metrics["alerts_alert"]
    assert metrics.total_dropped == 1


def test_sequence_numbers_increment_per_agent(registered_system):
    payload = {"action": "hedge", "asset": "ETH", "side": "buy", "size": 1.0}

    first = registered_system.send_message(
        sender_id="agent-alpha",
        message_type=sac.MessageType.INTENT,
        topic="trading",
        payload=payload,
    )
    second = registered_system.send_message(
        sender_id="agent-alpha",
        message_type=sac.MessageType.INTENT,
        topic="trading",
        payload=payload,
    )

    assert first.sequence_number == 1
    assert second.sequence_number == 2
