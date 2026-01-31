"""Tests for BaseAgent error handling and LLM invocation robustness."""

import json
import pytest
from unittest.mock import AsyncMock, Mock, patch
import httpx

from agents.base_agent import BaseAgent, AgentErrorResponse, AgentErrorType


class TestBaseAgentErrorHandling:
    """Test suite for BaseAgent error handling scenarios."""

    @pytest.fixture
    def test_agent(self):
        """Create a test agent for testing."""
        return BaseAgent(
            agent_id="test-agent-01",
            model_name="test-model:latest",
            role_prompt="You are a test agent. Respond with JSON.",
        )

    @pytest.fixture
    def sample_energy(self):
        """Sample energy packet for testing."""
        return {
            "energy_id": "test-energy-123",
            "source": "test",
            "payload": "Test payload for agent processing",
        }

    @pytest.mark.asyncio
    async def test_successful_llm_call(self, test_agent, sample_energy):
        """Test successful LLM invocation and response parsing."""
        mock_response_data = {
            "response": json.dumps({
                "reasoning": "Test reasoning",
                "vote": "accept",
                "confidence": 0.8,
                "simulation": "Test simulation"
            })
        }
        
        # Mock the httpx.AsyncClient context manager properly
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            # Use regular Mock for response to avoid making json() async
            from unittest.mock import Mock
            mock_response = Mock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_client.post.return_value = mock_response
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            
            result = await test_agent.process(sample_energy)
            
            assert result["agent_id"] == "test-agent-01"
            assert result["vote"] == "accept"
            assert result["confidence"] == 0.8
            assert result["reasoning"] == "Test reasoning"
            assert result["simulation"] == "Test simulation"

    @pytest.mark.asyncio
    async def test_read_timeout_error(self, test_agent, sample_energy):
        """Test handling of httpx.ReadTimeout during LLM invocation."""
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ReadTimeout("Read timeout", request=None)
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            
            with pytest.raises(AgentErrorResponse) as exc_info:
                await test_agent.process(sample_energy)
            
            error_response = exc_info.value
            assert error_response.error_type == AgentErrorType.TIMEOUT
            assert "Read timeout" in error_response.message
            assert error_response.details['agent_id'] == "test-agent-01"
            assert error_response.details['model_name'] == "test-model:latest"

    @pytest.mark.asyncio
    async def test_connect_timeout_error(self, test_agent, sample_energy):
        """Test handling of httpx.ConnectTimeout during LLM invocation."""
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectTimeout("Connection timeout", request=None)
            mock_client_class.return_value.__aenter__.return_value = mock_client
            mock_client_class.return_value.__aexit__.return_value = None
            
            with pytest.raises(AgentErrorResponse) as exc_info:
                await test_agent.process(sample_energy)
            
            error_response = exc_info.value
            assert error_response.error_type == AgentErrorType.CONNECTION
            assert "Connection timeout" in error_response.message
            assert error_response.details['agent_id'] == "test-agent-01"

    @pytest.mark.asyncio
    async def test_http_status_error(self, test_agent, sample_energy):
        """Test handling of HTTP status errors during LLM invocation."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("500 Server Error", request=Mock(), response=mock_response)
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            with pytest.raises(AgentErrorResponse) as exc_info:
                await test_agent.process(sample_energy)
            
            error_response = exc_info.value
            assert error_response.error_type == AgentErrorType.HTTP_ERROR
            assert "HTTP error 500" in error_response.message
            assert error_response.details['raw_response'] == "Internal Server Error"

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, test_agent, sample_energy):
        """Test handling of invalid JSON response from LLM."""
        mock_response_data = {
            "response": "This is not valid JSON { invalid syntax"
        }
        
        mock_response = Mock()
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status.return_value = None
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            
            with pytest.raises(AgentErrorResponse) as exc_info:
                await test_agent.process(sample_energy)
            
            error_response = exc_info.value
            assert error_response.error_type == AgentErrorType.INVALID_JSON
            assert "JSON parsing failed" in error_response.message
            assert error_response.details['raw_response'] == "This is not valid JSON { invalid syntax"

    # Validation with fallbacks is working correctly, no error raised needed

    @pytest.mark.asyncio
    async def test_orchestrator_handles_agent_error(self, test_agent, sample_energy):
        """Test that orchestrator properly handles AgentErrorResponse."""
        from core.orchestrator import MeridCore
        
        # Mock the agent to raise AgentErrorResponse
        with patch.object(test_agent, 'process') as mock_process:
            mock_process.side_effect = AgentErrorResponse(
                error_type=AgentErrorType.TIMEOUT,
                message="Test timeout error",
                details={'agent_id': "test-agent-01"}
            )
            
            core = MeridCore()
            # Replace one agent with our test agent
            core.agents = [test_agent]
            
            result = await core._execute_agent(test_agent, sample_energy)
            
            assert result["agent_id"] == "test-agent-01"
            assert result["vote"] == "abstain"
            assert result["confidence"] == 0.0
            assert result["error_type"] == "timeout"
            assert "timeout error" in result["reasoning"]

    def test_vote_normalization(self, test_agent):
        """Test vote normalization with various inputs."""
        test_cases = [
            ("accept", "accept"),
            ("yes", "accept"),
            ("APPROVE", "accept"),
            ("+1", "accept"),
            ("reject", "reject"),
            ("no", "reject"),
            ("DENY", "reject"),
            ("-1", "reject"),
            ("abstain", "abstain"),
            ("hold", "abstain"),
            ("0", "abstain"),
            ("invalid", "abstain"),
            ("", "abstain"),
            (None, "abstain"),
        ]
        
        for input_vote, expected in test_cases:
            result = test_agent._normalize_vote(input_vote)
            assert result == expected, f"Failed for input: {input_vote}"

    @pytest.mark.asyncio
    async def test_confidence_clamping(self, test_agent, sample_energy):
        """Test confidence values are properly clamped to [0, 1] range."""
        test_cases = [
            (1.5, 1.0),
            (2.0, 1.0),
            (-0.5, 0.0),
            (-1.0, 0.0),
            (0.5, 0.5),
            (0.0, 0.0),
            (1.0, 1.0),
        ]
        
        for confidence_input, expected in test_cases:
            mock_response_data = {
                "response": json.dumps({
                    "reasoning": "Test reasoning",
                    "vote": "accept",
                    "confidence": confidence_input,
                    "simulation": "Test simulation"
                })
            }
            
            mock_response = Mock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            
            with patch('httpx.AsyncClient') as mock_client:
                mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
                
                result = await test_agent.process(sample_energy)
                
                assert result["confidence"] == expected, f"Failed for confidence: {confidence_input}"
