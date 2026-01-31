"""Integration tests for LLM health endpoints."""

import pytest
from unittest.mock import patch, AsyncMock
import httpx

from web.api.health import test_ollama_health as ollama_health_func


class TestLLMHealthEndpoints:
    """Integration tests for LLM health endpoints."""

    @pytest.mark.asyncio
    async def test_ollama_health_success(self):
        """Test successful Ollama health check."""
        mock_response_data = {
            "response": '{"status": "ok"}',
            "model": "test-model",
            "done": True
        }
        
        # Mock httpx.AsyncClient to return successful response
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_request = AsyncMock()
            mock_response = httpx.Response(
                status_code=200,
                json=mock_response_data,
                request=mock_request
            )
            mock_response._request = mock_request  # Set internal request
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            
            result = await ollama_health_func()
            
            assert result["status"] == "ok"
            assert result["model"] == "merid-interface:latest"  # From settings
            assert result["latency_ms"] >= 0  # Can be 0 in tests
            assert result["error"] is None
            assert "response" in result

    @pytest.mark.asyncio
    async def test_ollama_health_timeout(self):
        """Test Ollama health check with timeout."""
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ReadTimeout("Read timeout", request=None)
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            
            result = await ollama_health_func()
            
            assert result["status"] == "error"
            assert "timeout" in result["error"].lower()
            assert result["model"] == "merid-interface:latest"  # From settings
            assert result["response"] is None

    @pytest.mark.asyncio
    async def test_ollama_health_connection_error(self):
        """Test Ollama health check with connection error."""
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectTimeout("Connection timeout", request=None)
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            
            result = await ollama_health_func()
            
            assert result["status"] == "error"
            assert "connection timeout" in result["error"].lower()
            assert result["model"] == "merid-interface:latest"  # From settings
            assert result["response"] is None

    # Agent self-test tests require more complex mocking due to real agent loading
    # These can be added later when the agent registry is better isolated for testing


if __name__ == "__main__":
    pytest.main([__file__])
