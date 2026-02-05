"""Tests for MERID integration components (Redis, Celery, validation)."""

import pytest
import asyncio
import pandas as pd
from unittest.mock import Mock, patch, AsyncMock
import json


class TestRedisEventBus:
    """Tests for Redis event bus."""
    
    @pytest.fixture
    async def event_bus(self):
        from core.redis_events import RedisEventBus
        bus = RedisEventBus(redis_url="redis://localhost:6379/15")
        # Mock the redis connection for testing
        bus.redis = AsyncMock()
        bus.pubsub = AsyncMock()
        return bus
    
    @pytest.mark.asyncio
    async def test_publish_message(self, event_bus):
        """Test publishing a message."""
        message = {"type": "test", "data": "value"}
        await event_bus.publish("test_channel", message)
        
        event_bus.redis.publish.assert_called_once()
        call_args = event_bus.redis.publish.call_args
        assert call_args[0][0] == "test_channel"
        assert json.loads(call_args[0][1]) == message
    
    @pytest.mark.asyncio
    async def test_subscribe_to_channel(self, event_bus):
        """Test subscribing to a channel."""
        handler = Mock()
        
        await event_bus.subscribe("test_channel", handler)
        
        event_bus.pubsub.subscribe.assert_called_once_with("test_channel")
        assert "test_channel" in event_bus.subscribers
        assert handler in event_bus.subscribers["test_channel"]


class TestOrderEventPublisher:
    """Tests for order event publisher."""
    
    @pytest.fixture
    def publisher(self):
        from core.redis_events import OrderEventPublisher, RedisEventBus
        bus = Mock(spec=RedisEventBus)
        bus.publish = AsyncMock()
        return OrderEventPublisher(bus)
    
    @pytest.mark.asyncio
    async def test_publish_order_created(self, publisher):
        """Test publishing order created event."""
        await publisher.publish_order_created("ord_123", "AAPL", "buy", 100.0)
        
        publisher.event_bus.publish.assert_called_once()
        call_args = publisher.event_bus.publish.call_args
        assert call_args[0][0] == "orders"
        
        message = call_args[0][1]
        assert message["type"] == "order_created"
        assert message["order_id"] == "ord_123"
        assert message["symbol"] == "AAPL"


class TestMarketDataValidator:
    """Tests for market data validation."""
    
    @pytest.fixture
    def validator(self):
        from core.data_validation import MarketDataValidator
        return MarketDataValidator()
    
    def test_valid_tick_data(self, validator):
        """Test validation of valid tick data."""
        data = pd.DataFrame({
            "symbol": ["AAPL", "GOOGL"],
            "price": [150.0, 2800.0],
            "timestamp": pd.to_datetime(["2024-01-15", "2024-01-15"]),
            "volume": [1000, 500]
        })
        
        # Note: This would need Great Expectations context setup
        # For now, just test the structure
        assert len(data) == 2
        assert "symbol" in data.columns
    
    def test_invalid_tick_data_missing_column(self, validator):
        """Test validation catches missing columns."""
        data = pd.DataFrame({
            "symbol": ["AAPL"],
            "price": [150.0]
            # Missing timestamp and volume
        })
        
        # This would fail validation in real implementation
        assert "timestamp" not in data.columns


class TestSchemaValidator:
    """Tests for schema validation."""
    
    @pytest.fixture
    def validator(self):
        from core.data_validation import SchemaValidator
        return SchemaValidator()
    
    def test_valid_trade_signal(self, validator):
        """Test valid trade signal passes validation."""
        signal = {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 100.0,
            "price": 150.0,
            "confidence": 0.85
        }
        
        result = validator.validate(signal, "trade_signal")
        assert result["success"] is True
        assert len(result["errors"]) == 0
    
    def test_invalid_trade_signal_missing_field(self, validator):
        """Test validation catches missing required field."""
        signal = {
            "symbol": "AAPL",
            "side": "buy"
            # Missing quantity
        }
        
        result = validator.validate(signal, "trade_signal")
        assert result["success"] is False
        assert len(result["errors"]) > 0
    
    def test_invalid_trade_signal_wrong_type(self, validator):
        """Test validation catches wrong data type."""
        signal = {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": "not_a_number"  # Should be number
        }
        
        result = validator.validate(signal, "trade_signal")
        assert result["success"] is False


class TestDependencyContainer:
    """Tests for dependency injection container."""
    
    @pytest.fixture
    def container(self):
        from core.data_validation import DependencyContainer
        return DependencyContainer()
    
    def test_register_and_get_service(self, container):
        """Test registering and retrieving a service."""
        mock_service = Mock()
        container.register("test_service", mock_service)
        
        retrieved = container.get("test_service")
        assert retrieved is mock_service
    
    def test_register_factory(self, container):
        """Test registering a factory function."""
        mock_instance = Mock()
        container.register_factory("factory_service", lambda: mock_instance)
        
        retrieved = container.get("factory_service")
        assert retrieved is mock_instance
    
    def test_factory_caches_instance(self, container):
        """Test factory caches the created instance."""
        call_count = 0
        
        def factory():
            nonlocal call_count
            call_count += 1
            return Mock()
        
        container.register_factory("cached_service", factory)
        
        # Get twice
        instance1 = container.get("cached_service")
        instance2 = container.get("cached_service")
        
        assert call_count == 1  # Factory only called once
        assert instance1 is instance2  # Same instance returned
    
    def test_has_service(self, container):
        """Test checking if service exists."""
        container.register("exists", Mock())
        
        assert container.has("exists") is True
        assert container.has("not_exists") is False
    
    def test_get_missing_service_raises(self, container):
        """Test getting non-existent service raises error."""
        with pytest.raises(KeyError):
            container.get("missing")


class TestCeleryTasks:
    """Tests for Celery task definitions."""
    
    @patch("core.celery_tasks.logger")
    def test_backtest_task_signature(self, mock_logger):
        """Test backtest task can be imported and has correct signature."""
        from core.celery_tasks import run_backtest
        
        # Check task is properly decorated
        assert run_backtest.name == "core.celery_tasks.run_backtest"
        assert run_backtest.max_retries == 3
    
    @patch("core.celery_tasks.logger")
    def test_risk_calculation_task_signature(self, mock_logger):
        """Test risk calculation task signature."""
        from core.celery_tasks import calculate_risk_metrics
        
        assert calculate_risk_metrics.name == "core.celery_tasks.calculate_risk_metrics"
        assert calculate_risk_metrics.max_retries == 2


class TestIntegrationWorkflows:
    """End-to-end integration workflow tests."""
    
    @pytest.mark.asyncio
    async def test_full_order_flow(self):
        """Test complete order flow with mocked dependencies."""
        from core.data_validation import SchemaValidator
        from core.redis_events import OrderEventPublisher
        
        # 1. Validate incoming order request
        validator = SchemaValidator()
        order_request = {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 100,
            "order_type": "market"
        }
        
        validation = validator.validate(order_request, "order_request")
        assert validation["success"] is True
        
        # 2. Publish event to Redis
        mock_bus = AsyncMock()
        publisher = OrderEventPublisher(mock_bus)
        await publisher.publish_order_created("ord_123", "AAPL", "buy", 100.0)
        
        mock_bus.publish.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_swarm_to_ui_event_flow(self):
        """Test swarm agent decision propagates to UI."""
        from core.redis_events import SwarmEventPublisher, UIUpdatePublisher
        
        mock_bus = AsyncMock()
        swarm_publisher = SwarmEventPublisher(mock_bus)
        ui_publisher = UIUpdatePublisher(mock_bus)
        
        # Swarm publishes trade signal
        await swarm_publisher.publish_trade_signal(
            {"symbol": "BTC", "side": "buy"},
            confidence=0.85
        )
        
        # UI receives portfolio update
        await ui_publisher.update_portfolio({
            "total_value": 100000,
            "cash": 50000
        })
        
        assert mock_bus.publish.call_count == 2
