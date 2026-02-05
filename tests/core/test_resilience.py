"""Tests for core/resilience.py."""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from core.resilience import (
    ResilienceConfig, ResilientAPIClient, FallbackManager,
    resilient_client, fallback_manager, resilient_call
)


class TestResilienceConfig:
    """Test ResilienceConfig dataclass."""

    def test_default_values(self):
        """Test default config values."""
        config = ResilienceConfig()
        assert config.max_retries == 3
        assert config.retry_delay == 1.0
        assert config.retry_multiplier == 2.0
        assert config.retry_max_delay == 60.0
        assert config.circuit_breaker_threshold == 5
        assert config.circuit_breaker_timeout == 30
        assert config.timeout == 30.0

    def test_custom_values(self):
        """Test custom config values."""
        config = ResilienceConfig(
            max_retries=5,
            retry_delay=2.0,
            timeout=60.0
        )
        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.timeout == 60.0


class TestResilientAPIClient:
    """Test ResilientAPIClient class."""

    def test_initialization(self):
        """Test client initialization."""
        client = ResilientAPIClient()
        assert client.config is not None
        assert client.circuit_breaker is not None

    def test_custom_config(self):
        """Test client with custom config."""
        config = ResilienceConfig(max_retries=5)
        client = ResilientAPIClient(config)
        assert client.config.max_retries == 5


class TestFallbackManager:
    """Test FallbackManager class."""

    def test_initialization(self):
        """Test manager initialization."""
        manager = FallbackManager()
        assert manager.fallback_strategies == {}

    def test_register_fallback(self):
        """Test registering fallback strategy."""
        manager = FallbackManager()
        fallback_func = Mock()
        manager.register_fallback("service1", fallback_func)
        assert "service1" in manager.fallback_strategies
        assert manager.fallback_strategies["service1"] == fallback_func

    @pytest.mark.asyncio
    async def test_execute_primary_success(self):
        """Test execute when primary succeeds."""
        manager = FallbackManager()
        primary = AsyncMock(return_value="success")
        result = await manager.execute_with_fallback("service", primary)
        assert result == "success"
        primary.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_fallback_on_failure(self):
        """Test fallback executed when primary fails."""
        manager = FallbackManager()
        primary = AsyncMock(side_effect=ConnectionError("Failed"))
        fallback = AsyncMock(return_value="fallback_result")
        manager.register_fallback("service", fallback)
        
        result = await manager.execute_with_fallback("service", primary)
        assert result == "fallback_result"
        fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_raises_without_fallback(self):
        """Test raises when no fallback available."""
        manager = FallbackManager()
        primary = AsyncMock(side_effect=ConnectionError("Failed"))
        
        with pytest.raises(ConnectionError):
            await manager.execute_with_fallback("service", primary)


class TestResilientCallDecorator:
    """Test resilient_call decorator."""

    @pytest.mark.asyncio
    async def test_decorator_creation(self):
        """Test decorator creates wrapper."""
        @resilient_call(max_retries=2, timeout=5.0)
        async def test_func():
            return "result"
        
        # Should have created a wrapper
        assert hasattr(test_func, '__wrapped__')


class TestGlobalInstances:
    """Test global resilience instances."""

    def test_resilient_client_exists(self):
        """Test global resilient_client exists."""
        assert resilient_client is not None
        assert isinstance(resilient_client, ResilientAPIClient)

    def test_fallback_manager_exists(self):
        """Test global fallback_manager exists."""
        assert fallback_manager is not None
        assert isinstance(fallback_manager, FallbackManager)

    def test_fallbacks_registered(self):
        """Test default fallbacks are registered."""
        assert "market_data" in fallback_manager.fallback_strategies
        assert "order_submission" in fallback_manager.fallback_strategies
