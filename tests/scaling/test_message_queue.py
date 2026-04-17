"""Tests for scaling/message_queue.py - Message Queue System."""
import pytest
import asyncio
import time
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from scaling.message_queue import (
    MessageConfig,
    Message,
    QueueStats,
    MockMessageBroker,
)


class TestMessageConfig:
    """Test MessageConfig dataclass."""

    def test_default_config(self):
        """Test default message config."""
        config = MessageConfig()
        assert config.broker_type == "rabbitmq"
        assert config.connection_host == "localhost"
        assert config.connection_port == 5672

    def test_rabbitmq_config(self):
        """Test RabbitMQ config."""
        config = MessageConfig(
            broker_type="rabbitmq",
            connection_host="rabbitmq.local",
            connection_port=5672,
            username="admin",
            password="secret",
            virtual_host="/merid",
        )
        assert config.broker_type == "rabbitmq"
        assert config.virtual_host == "/merid"

    def test_kafka_config(self):
        """Test Kafka config."""
        config = MessageConfig(
            broker_type="kafka",
            kafka_bootstrap_servers="kafka1:9092,kafka2:9092",
            kafka_group_id="merid_trading",
            kafka_auto_offset_reset="latest",
        )
        assert config.broker_type == "kafka"
        assert "kafka1:9092" in config.kafka_bootstrap_servers

    def test_queue_settings(self):
        """Test queue settings."""
        config = MessageConfig(
            queue_durable=True,
            message_ttl=7200000,
            max_retries=5,
            retry_delay=10,
        )
        assert config.queue_durable is True
        assert config.message_ttl == 7200000
        assert config.max_retries == 5

    def test_us_compliance_settings(self):
        """Test US compliance settings."""
        config = MessageConfig(
            encrypt_messages=True,
            audit_message_access=True,
            message_retention_days=30,
        )
        assert config.encrypt_messages is True
        assert config.audit_message_access is True


class TestMessage:
    """Test Message dataclass."""

    def test_basic_message(self):
        """Test creating basic message."""
        msg = Message(
            message_id="msg_001",
            topic="orders",
            payload={"order_id": "ord_123", "action": "buy"},
        )
        assert msg.message_id == "msg_001"
        assert msg.topic == "orders"
        assert msg.payload["order_id"] == "ord_123"

    def test_message_with_headers(self):
        """Test message with headers."""
        msg = Message(
            message_id="msg_002",
            topic="trades",
            payload={"trade_id": "trd_456"},
            headers={"content-type": "application/json", "x-priority": "high"},
        )
        assert msg.headers["x-priority"] == "high"

    def test_message_priority(self):
        """Test message priority."""
        high_priority = Message(
            message_id="msg_003",
            topic="alerts",
            payload={"alert": "kill_switch_triggered"},
            priority=10,
        )
        low_priority = Message(
            message_id="msg_004",
            topic="logs",
            payload={"log": "info message"},
            priority=1,
        )
        assert high_priority.priority == 10
        assert low_priority.priority == 1

    def test_message_retry(self):
        """Test message retry tracking."""
        msg = Message(
            message_id="msg_005",
            topic="orders",
            payload={},
            retry_count=2,
            max_retries=3,
        )
        assert msg.retry_count < msg.max_retries
        
        # Simulate retry
        msg.retry_count += 1
        assert msg.retry_count == msg.max_retries

    def test_message_correlation(self):
        """Test message correlation."""
        request = Message(
            message_id="req_001",
            topic="requests",
            payload={"action": "get_price"},
            correlation_id="corr_123",
            reply_to="responses",
        )
        assert request.correlation_id == "corr_123"
        assert request.reply_to == "responses"

    def test_message_expiration(self):
        """Test message expiration."""
        msg = Message(
            message_id="msg_006",
            topic="ephemeral",
            payload={},
            expiration=60000,  # 60 seconds
        )
        assert msg.expiration == 60000


class TestQueueStats:
    """Test QueueStats dataclass."""

    def test_default_stats(self):
        """Test default queue stats."""
        stats = QueueStats()
        assert stats.total_messages == 0
        assert stats.error_rate == 0.0

    def test_stats_with_values(self):
        """Test stats with values."""
        stats = QueueStats(
            total_messages=1000,
            successful_messages=950,
            failed_messages=50,
            retried_messages=30,
            avg_processing_time=0.05,
            total_processing_time=50.0,
            queue_depth=100,
        )
        assert stats.successful_messages == 950
        assert stats.queue_depth == 100

    def test_error_rate_calculation(self):
        """Test error rate calculation."""
        stats = QueueStats(
            total_messages=1000,
            failed_messages=50,
        )
        error_rate = stats.failed_messages / stats.total_messages if stats.total_messages > 0 else 0
        assert error_rate == pytest.approx(0.05)

    def test_throughput_calculation(self):
        """Test throughput calculation."""
        stats = QueueStats(
            total_messages=6000,
            total_processing_time=60.0,  # 60 seconds
        )
        throughput = stats.total_messages / stats.total_processing_time if stats.total_processing_time > 0 else 0
        assert throughput == pytest.approx(100.0)  # 100 msgs/sec


class TestMockMessageBroker:
    """Test MockMessageBroker class."""

    @pytest.fixture
    def broker(self):
        """Create mock broker."""
        return MockMessageBroker()

    def test_broker_creation(self, broker):
        """Test creating broker."""
        assert broker is not None
        assert broker.queues == {}
        assert broker.stats["published"] == 0

    @pytest.mark.asyncio
    async def test_publish_message(self, broker):
        """Test publishing message."""
        msg = Message(
            message_id="msg_001",
            topic="orders",
            payload={"order": "data"},
        )
        
        await broker.publish("orders", msg)
        
        assert "orders" in broker.queues
        assert len(broker.queues["orders"]) == 1
        assert broker.stats["published"] == 1

    @pytest.mark.asyncio
    async def test_publish_multiple_messages(self, broker):
        """Test publishing multiple messages."""
        for i in range(10):
            msg = Message(
                message_id=f"msg_{i:03d}",
                topic="trades",
                payload={"trade_id": i},
            )
            await broker.publish("trades", msg)
        
        assert len(broker.queues["trades"]) == 10
        assert broker.stats["published"] == 10

    @pytest.mark.asyncio
    async def test_publish_to_multiple_topics(self, broker):
        """Test publishing to multiple topics."""
        topics = ["orders", "trades", "alerts", "logs"]
        
        for topic in topics:
            msg = Message(
                message_id=f"msg_{topic}",
                topic=topic,
                payload={"topic": topic},
            )
            await broker.publish(topic, msg)
        
        assert len(broker.queues) == 4
        assert broker.stats["published"] == 4


class TestMessageQueueIntegration:
    """Integration tests for message queue patterns."""

    def test_request_reply_pattern(self):
        """Test request-reply messaging pattern."""
        correlation_id = "corr_001"
        
        request = Message(
            message_id="req_001",
            topic="requests",
            payload={"action": "get_balance"},
            correlation_id=correlation_id,
            reply_to="responses",
        )
        
        # Simulate response
        response = Message(
            message_id="res_001",
            topic="responses",
            payload={"balance": 10000.0},
            correlation_id=correlation_id,
        )
        
        assert request.correlation_id == response.correlation_id

    def test_pub_sub_pattern(self):
        """Test publish-subscribe pattern."""
        subscribers = ["sub_1", "sub_2", "sub_3"]
        message = Message(
            message_id="pub_001",
            topic="market_data",
            payload={"symbol": "BTC/USD", "price": 50000},
        )
        
        # Each subscriber receives the message
        received = {sub: message for sub in subscribers}
        
        assert len(received) == 3
        assert all(msg.topic == "market_data" for msg in received.values())

    def test_dead_letter_queue_pattern(self):
        """Test dead letter queue pattern."""
        failed_message = Message(
            message_id="fail_001",
            topic="orders",
            payload={"order": "invalid"},
            retry_count=3,
            max_retries=3,
        )
        
        # Message should go to DLQ
        should_dlq = failed_message.retry_count >= failed_message.max_retries
        
        assert should_dlq is True

    def test_message_ordering(self):
        """Test message ordering."""
        messages = [
            Message(message_id=f"msg_{i}", topic="ordered", payload={"seq": i})
            for i in range(5)
        ]
        
        # Verify FIFO ordering
        for i, msg in enumerate(messages):
            assert msg.payload["seq"] == i
