"""Tests for core/events.py."""
import pytest
import time
import json
from core.events import (
    EventType, EventPriority, EventMetadata, EventEnvelope,
    create_market_event, create_agent_output_event, create_consensus_event, create_audit_event
)


class TestEventType:
    """Test EventType enum."""

    def test_event_type_values(self):
        """Test EventType enum values."""
        assert EventType.MARKET_DATA.value == "market_data"
        assert EventType.NEWS.value == "news"
        assert EventType.AGENT_OUTPUT.value == "agent_output"
        assert EventType.CONSENSUS.value == "consensus"
        assert EventType.EXECUTION.value == "execution"


class TestEventPriority:
    """Test EventPriority enum."""

    def test_priority_values(self):
        """Test EventPriority enum values."""
        assert EventPriority.CRITICAL.value == 0
        assert EventPriority.HIGH.value == 1
        assert EventPriority.NORMAL.value == 2
        assert EventPriority.LOW.value == 3
        assert EventPriority.BACKGROUND.value == 4


class TestEventMetadata:
    """Test EventMetadata dataclass."""

    def test_default_values(self):
        """Test default metadata values."""
        meta = EventMetadata()
        assert meta.schema_version == "1.0"
        assert meta.producer_id == ""
        assert meta.retry_count == 0
        assert meta.max_retries == 3

    def test_to_dict(self):
        """Test metadata to_dict."""
        meta = EventMetadata(producer_id="test")
        d = meta.to_dict()
        assert d["producer_id"] == "test"
        assert d["schema_version"] == "1.0"

    def test_from_dict(self):
        """Test metadata from_dict."""
        data = {"producer_id": "test", "retry_count": 5}
        meta = EventMetadata.from_dict(data)
        assert meta.producer_id == "test"
        assert meta.retry_count == 5


class TestEventEnvelope:
    """Test EventEnvelope dataclass."""

    def test_creation(self):
        """Test envelope creation."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test_source",
            payload={"key": "value"}
        )
        assert envelope.event_type == EventType.MARKET_DATA
        assert envelope.source == "test_source"
        assert envelope.payload == {"key": "value"}
        assert envelope.event_id is not None
        assert envelope.timestamp > 0

    def test_creation_empty_source_raises(self):
        """Test empty source raises ValueError."""
        with pytest.raises(ValueError, match="source cannot be empty"):
            EventEnvelope(
                event_type=EventType.MARKET_DATA,
                source="",
                payload={}
            )

    def test_creation_invalid_event_type_raises(self):
        """Test invalid event type raises TypeError."""
        with pytest.raises(TypeError, match="event_type must be EventType"):
            EventEnvelope(
                event_type="invalid",
                source="test",
                payload={}
            )

    def test_validate_success(self):
        """Test successful validation."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={}
        )
        assert envelope.validate() is True

    def test_validate_empty_event_id(self):
        """Test validation fails with empty event_id."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={},
            event_id=""
        )
        assert envelope.validate() is False

    def test_is_expired(self):
        """Test expiration check."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={},
            metadata=EventMetadata(ttl_seconds=1)
        )
        assert envelope.is_expired() is False
        time.sleep(1.1)
        assert envelope.is_expired() is True

    def test_is_expired_no_ttl(self):
        """Test expiration check with no TTL."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={}
        )
        assert envelope.is_expired() is False

    def test_can_retry(self):
        """Test retry check."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={},
            metadata=EventMetadata(retry_count=1, max_retries=3)
        )
        assert envelope.can_retry() is True

    def test_can_retry_max_reached(self):
        """Test retry check at max."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={},
            metadata=EventMetadata(retry_count=3, max_retries=3)
        )
        assert envelope.can_retry() is False

    def test_increment_retry(self):
        """Test retry increment."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={},
            metadata=EventMetadata(retry_count=1)
        )
        new_envelope = envelope.increment_retry()
        assert new_envelope.metadata.retry_count == 2

    def test_with_causation(self):
        """Test with_causation method."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={}
        )
        child = envelope.with_causation(envelope.event_id)
        assert child.causation_id == envelope.event_id
        assert child.correlation_id == envelope.event_id
        assert child.event_id != envelope.event_id

    def test_compute_hash(self):
        """Test hash computation."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={"price": 100.0}
        )
        hash1 = envelope.compute_hash()
        hash2 = envelope.compute_hash()
        assert hash1 == hash2  # Deterministic
        assert len(hash1) == 64  # SHA-256 hex

    def test_sign_and_verify(self):
        """Test signing and verification."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={}
        )
        secret = "my_secret_key"
        signature = envelope.sign(secret)
        assert signature is not None
        assert envelope.verify_signature(secret) is True
        assert envelope.verify_signature("wrong_key") is False

    def test_to_dict(self):
        """Test serialization to dict."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={"key": "value"}
        )
        d = envelope.to_dict()
        assert d["event_type"] == "market_data"
        assert d["source"] == "test"
        assert d["payload"] == {"key": "value"}

    def test_to_json(self):
        """Test serialization to JSON."""
        envelope = EventEnvelope(
            event_type=EventType.MARKET_DATA,
            source="test",
            payload={}
        )
        json_str = envelope.to_json()
        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert data["event_type"] == "market_data"

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "event_type": "market_data",
            "source": "test",
            "payload": {"price": 100.0},
            "timestamp": 1234567890.0
        }
        envelope = EventEnvelope.from_dict(data)
        assert envelope.event_type == EventType.MARKET_DATA
        assert envelope.source == "test"
        assert envelope.payload["price"] == 100.0

    def test_from_json(self):
        """Test deserialization from JSON."""
        json_str = '{"event_type":"market_data","source":"test","payload":{}}'
        envelope = EventEnvelope.from_json(json_str)
        assert envelope.event_type == EventType.MARKET_DATA


class TestFactoryFunctions:
    """Test event factory functions."""

    def test_create_market_event(self):
        """Test create_market_event."""
        event = create_market_event("coinbase", "BTC/USDT", 50000.0, 100.0)
        assert event.event_type == EventType.MARKET_DATA
        assert event.source == "coinbase"
        assert event.payload["symbol"] == "BTC/USDT"
        assert event.payload["price"] == 50000.0
        assert event.priority == EventPriority.HIGH

    def test_create_agent_output_event(self):
        """Test create_agent_output_event."""
        event = create_agent_output_event("agent1", "analysis", {"result": "bullish"})
        assert event.event_type == EventType.AGENT_OUTPUT
        assert event.source == "agent1"
        assert event.payload["output_type"] == "analysis"
        assert event.priority == EventPriority.NORMAL

    def test_create_consensus_event(self):
        """Test create_consensus_event."""
        event = create_consensus_event("round1", "voting", {"agent1": "yes"}, "accepted")
        assert event.event_type == EventType.CONSENSUS
        assert event.payload["round_id"] == "round1"
        assert event.priority == EventPriority.HIGH

    def test_create_audit_event(self):
        """Test create_audit_event."""
        event = create_audit_event("login", "user1", {"ip": "1.2.3.4"}, "info")
        assert event.event_type == EventType.AUDIT
        assert event.payload["action"] == "login"
        assert event.payload["severity"] == "info"
        assert event.priority == EventPriority.LOW
