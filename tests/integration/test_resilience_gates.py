"""
Integration Tests for MERID Resilience Gates
Gate 3: Service Reliability - Evidence Artifact
Date: 2026-01-26

Tests circuit breakers, retries, and distributed tracing
to ensure service reliability under failure conditions.
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch
from typing import Dict, Any

from core.resilience import ResilientAPIClient, ResilienceConfig, resilient_call
from core.tracing import TracingManager, TraceContext
from core.resilience import fallback_manager


class TestResilientAPIClient:
    """Test the ResilientAPIClient implementation."""
    
    @pytest.fixture
    def client(self):
        config = ResilienceConfig(
            max_retries=2,
            retry_delay=0.1,
            circuit_breaker_threshold=2,
            timeout=1.0
        )
        return ResilientAPIClient(config)
    
    @pytest.mark.asyncio
    async def test_successful_call(self, client):
        """Test successful API call goes through without retries."""
        call_count = 0
        
        async def mock_func():
            nonlocal call_count
            call_count += 1
            return {"status": "success"}
        
        result = await client.call_api(mock_func)
        assert result["status"] == "success"
        assert call_count == 1  # No retries needed
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self, client):
        """Test that retries work on temporary failures."""
        call_count = 0
        
        async def mock_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Temporary failure")
            return {"status": "success"}
        
        result = await client.call_api(mock_func)
        assert result["status"] == "success"
        assert call_count == 3  # Initial call + 2 retries
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens(self, client):
        """Test that circuit breaker opens after threshold failures."""
        call_count = 0
        
        async def mock_func():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Persistent failure")
        
        # First 2 calls should trigger circuit breaker opening
        with pytest.raises(ConnectionError):
            await client.call_api(mock_func)
        with pytest.raises(ConnectionError):
            await client.call_api(mock_func)
        
        # Third call should be blocked by circuit breaker
        with pytest.raises(Exception):  # CircuitBreakerError
            await client.call_api(mock_func)
        
        assert call_count == 2  # Should stop after threshold
    
    @pytest.mark.asyncio
    async def test_timeout_protection(self, client):
        """Test that timeout protection works."""
        
        async def slow_func():
            await asyncio.sleep(2.0)  # Longer than timeout
            return {"status": "success"}
        
        with pytest.raises(asyncio.TimeoutError):
            await client.call_api(slow_func)


class TestFallbackManager:
    """Test the FallbackManager implementation."""
    
    @pytest.fixture
    def manager(self):
        return FallbackManager()
    
    @pytest.mark.asyncio
    async def test_primary_success(self, manager):
        """Test that primary function works when no fallback needed."""
        
        async def primary_func():
            return {"status": "primary_success"}
        
        result = await manager.execute_with_fallback("test_service", primary_func)
        assert result["status"] == "primary_success"
    
    @pytest.mark.asyncio
    async def test_fallback_execution(self, manager):
        """Test that fallback executes when primary fails."""
        
        async def primary_func():
            raise Exception("Primary service failed")
        
        async def fallback_func():
            return {"status": "fallback_success"}
        
        manager.register_fallback("test_service", fallback_func)
        
        result = await manager.execute_with_fallback("test_service", primary_func)
        assert result["status"] == "fallback_success"
    
    @pytest.mark.asyncio
    async def test_no_fallback_available(self, manager):
        """Test that failure propagates when no fallback exists."""
        
        async def primary_func():
            raise Exception("Primary service failed")
        
        with pytest.raises(Exception):
            await manager.execute_with_fallback("no_fallback_service", primary_func)


class TestDistributedTracing:
    """Test the distributed tracing implementation."""
    
    @pytest.fixture
    def tracing_manager(self):
        return TracingManager("test-service")
    
    def test_trace_context_creation(self):
        """Test TraceContext creation and serialization."""
        context = TraceContext()
        
        assert context.trace_id
        assert context.span_id
        assert context.correlation_id
        assert context.parent_span_id is None
        
        headers = context.to_dict()
        assert "x-trace-id" in headers
        assert "x-span-id" in headers
        assert "x-correlation-id" in headers
    
    def test_context_extraction(self, tracing_manager):
        """Test context extraction from headers."""
        headers = {
            "x-trace-id": "test-trace-id",
            "x-span-id": "test-span-id",
            "x-correlation-id": "test-correlation-id",
            "x-parent-span-id": "test-parent-span-id"
        }
        
        context = tracing_manager.extract_context_from_headers(headers)
        
        assert context.trace_id == "test-trace-id"
        assert context.span_id == "test-span-id"
        assert context.correlation_id == "test-correlation-id"
        assert context.parent_span_id == "test-parent-span-id"
    
    def test_context_injection(self, tracing_manager):
        """Test context injection into headers."""
        context = TraceContext(
            trace_id="inject-trace-id",
            span_id="inject-span-id",
            correlation_id="inject-correlation-id"
        )
        
        headers = tracing_manager.inject_context_into_headers(context)
        
        assert headers["x-trace-id"] == "inject-trace-id"
        assert headers["x-span-id"] == "inject-span-id"
        assert headers["x-correlation-id"] == "inject-correlation-id"
    
    @pytest.mark.asyncio
    async def test_tracing_operation(self, tracing_manager):
        """Test tracing operation context manager."""
        
        with tracing_manager.trace_operation("test_operation") as span:
            span.set_attribute("test.attribute", "test_value")
            assert span.is_recording()
        
        # Span should be ended after context exit
        assert not span.is_recording()
    
    @pytest.mark.asyncio
    async def test_async_tracing_decorator(self):
        """Test the async tracing decorator."""
        
        @trace_async("decorated_function")
        async def decorated_function():
            await asyncio.sleep(0.1)
            return {"result": "success"}
        
        result = await decorated_function()
        assert result["result"] == "success"


class TestResilienceIntegration:
    """Integration tests combining resilience patterns."""
    
    @pytest.mark.asyncio
    async def test_resilient_api_with_tracing(self):
        """Test that resilient API calls are properly traced."""
        
        tracing_manager = TracingManager("integration-test")
        config = ResilienceConfig(max_retries=2, timeout=1.0)
        client = ResilientAPIClient(config)
        
        call_count = 0
        
        async def mock_api_call():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("First call fails")
            return {"status": "success"}
        
        with tracing_manager.trace_operation("resilient_api_call") as span:
            span.set_attribute("api.endpoint", "test-endpoint")
            result = await client.call_api(mock_api_call)
        
        assert result["status"] == "success"
        assert call_count == 2  # One failure + one success
    
    @pytest.mark.asyncio
    async def test_fallback_with_tracing(self):
        """Test that fallback execution is properly traced."""
        
        tracing_manager = TracingManager("fallback-test")
        
        async def primary_func():
            raise Exception("Primary service failed")
        
        async def fallback_func():
            return {"status": "fallback_success"}
        
        fallback_manager.register_fallback("test_service", fallback_func)
        
        with tracing_manager.trace_operation("fallback_execution") as span:
            span.set_attribute("service.name", "test_service")
            result = await fallback_manager.execute_with_fallback("test_service", primary_func)
        
        assert result["status"] == "fallback_success"


class TestResiliencePerformance:
    """Performance tests for resilience patterns."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after timeout."""
        config = ResilienceConfig(
            circuit_breaker_threshold=2,
            circuit_breaker_timeout=1,  # 1 second timeout
            timeout=0.5
        )
        client = ResilientAPIClient(config)
        
        # Trigger circuit breaker opening
        async def failing_func():
            raise ConnectionError("Persistent failure")
        
        # Open circuit breaker
        for _ in range(3):
            try:
                await client.call_api(failing_func)
            except Exception:
                pass
        
        # Wait for circuit breaker to recover
        await asyncio.sleep(1.5)
        
        # Should work again after recovery
        async def working_func():
            return {"status": "recovered"}
        
        result = await client.call_api(working_func)
        assert result["status"] == "recovered"
    
    @pytest.mark.asyncio
    async def test_concurrent_resilient_calls(self):
        """Test concurrent resilient API calls."""
        config = ResilienceConfig(max_retries=2, timeout=1.0)
        client = ResilientAPIClient(config)
        
        async def mock_func(id: int):
            await asyncio.sleep(0.1)
            return {"id": id, "status": "success"}
        
        # Run multiple concurrent calls
        tasks = [client.call_api(mock_func, i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should succeed
        for result in results:
            assert isinstance(result, dict)
            assert result["status"] == "success"


if __name__ == "__main__":
    pytest.main([__file__])
