"""Tests for agents/base_agent.py."""
import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from agents.base_agent import (
    AgentErrorType, AgentErrorResponse, BaseAgent, _OLLAMA_URL
)


class TestAgentErrorType:
    """Test AgentErrorType enum."""

    def test_error_type_values(self):
        """Test error type enum values."""
        assert AgentErrorType.NETWORK.value == "network"
        assert AgentErrorType.TIMEOUT.value == "timeout"
        assert AgentErrorType.RATE_LIMIT.value == "rate_limit"
        assert AgentErrorType.VALIDATION.value == "validation"
        assert AgentErrorType.MODEL_ERROR.value == "model_error"
        assert AgentErrorType.UNKNOWN.value == "unknown"


class TestAgentErrorResponse:
    """Test AgentErrorResponse class."""

    def test_creation(self):
        """Test error response creation."""
        error = AgentErrorResponse(
            error_type=AgentErrorType.NETWORK,
            message="Connection failed",
            details={"host": "api.example.com"}
        )
        assert error.error_type == AgentErrorType.NETWORK
        assert error.message == "Connection failed"
        assert error.details == {"host": "api.example.com"}

    def test_to_dict(self):
        """Test error response to_dict."""
        error = AgentErrorResponse(
            error_type=AgentErrorType.VALIDATION,
            message="Invalid input",
            details={"field": "amount"}
        )
        d = error.to_dict()
        assert d["error"] is True
        assert d["error_type"] == "validation"
        assert d["message"] == "Invalid input"
        assert d["details"] == {"field": "amount"}

    def test_default_details(self):
        """Test error response with default details."""
        error = AgentErrorResponse(
            error_type=AgentErrorType.UNKNOWN,
            message="Unknown error"
        )
        assert error.details == {}


class TestBaseAgentInitialization:
    """Test BaseAgent initialization."""

    def test_default_initialization(self):
        """Test default agent initialization."""
        agent = BaseAgent(
            agent_id="test_agent",
            model_name="llama2",
            role_prompt="You are a test agent."
        )
        assert agent.agent_id == "test_agent"
        assert agent.model_name == "llama2"
        assert agent.role_prompt == "You are a test agent."
        assert agent.tool_budget == 2
        assert agent.is_truth_layer is False
        assert agent.include_patterns is False
        assert agent.trust == 1.0

    def test_custom_initialization(self):
        """Test custom agent initialization."""
        agent = BaseAgent(
            agent_id="custom_agent",
            model_name="gemma",
            role_prompt="Custom role.",
            tool_budget=5,
            is_truth_layer=True,
            include_patterns=True
        )
        assert agent.tool_budget == 5
        assert agent.is_truth_layer is True
        assert agent.include_patterns is True

    def test_tool_budget_clamping(self):
        """Test tool budget is clamped to non-negative."""
        agent = BaseAgent(
            agent_id="test",
            model_name="llama2",
            role_prompt="Test.",
            tool_budget=-5
        )
        assert agent.tool_budget == 0


class TestBaseAgentNormalizeVote:
    """Test BaseAgent _normalize_vote method."""

    def test_normalize_accept_variants(self):
        """Test normalize vote accept variants."""
        agent = BaseAgent("test", "llama2", "Test.")
        assert agent._normalize_vote("accept") == "accept"
        assert agent._normalize_vote("+1") == "accept"
        assert agent._normalize_vote("approve") == "accept"
        assert agent._normalize_vote("yes") == "accept"

    def test_normalize_reject_variants(self):
        """Test normalize vote reject variants."""
        agent = BaseAgent("test", "llama2", "Test.")
        assert agent._normalize_vote("reject") == "reject"
        assert agent._normalize_vote("-1") == "reject"
        assert agent._normalize_vote("no") == "reject"
        assert agent._normalize_vote("deny") == "reject"

    def test_normalize_abstain_variants(self):
        """Test normalize vote abstain variants."""
        agent = BaseAgent("test", "llama2", "Test.")
        assert agent._normalize_vote("abstain") == "abstain"
        assert agent._normalize_vote("0") == "abstain"
        assert agent._normalize_vote("hold") == "abstain"

    def test_normalize_unknown_defaults_to_abstain(self):
        """Test unknown vote values default to abstain."""
        agent = BaseAgent("test", "llama2", "Test.")
        assert agent._normalize_vote("unknown") == "abstain"
        assert agent._normalize_vote("maybe") == "abstain"


class TestBaseAgentParseResponse:
    """Test BaseAgent _parse_response method."""

    def test_parse_valid_json(self):
        """Test parsing valid JSON response."""
        agent = BaseAgent("test", "llama2", "Test.")
        raw = json.dumps({
            "reasoning": "Good signal",
            "vote": "accept",
            "confidence": 0.85,
            "simulation": "Would profit"
        })
        
        parsed = agent._parse_response(raw)
        
        assert parsed["reasoning"] == "Good signal"
        assert parsed["vote"] == "accept"
        assert parsed["confidence"] == 0.85
        assert parsed["simulation"] == "Would profit"

    def test_parse_invalid_json_uses_fallback(self):
        """Test parsing invalid JSON uses fallback."""
        agent = BaseAgent("test", "llama2", "Test.")
        raw = "This is not JSON"
        
        parsed = agent._parse_response(raw)
        
        assert parsed["vote"] == "abstain"
        assert parsed["confidence"] == 0.45

    def test_parse_confidence_clamping(self):
        """Test confidence is clamped between 0 and 1."""
        agent = BaseAgent("test", "llama2", "Test.")
        
        raw = json.dumps({"confidence": 1.5})
        parsed = agent._parse_response(raw)
        assert parsed["confidence"] == 1.0
        
        raw = json.dumps({"confidence": -0.5})
        parsed = agent._parse_response(raw)
        assert parsed["confidence"] == 0.0


class TestBaseAgentUpdateTrust:
    """Test BaseAgent update_trust method."""

    def test_update_trust(self):
        """Test updating trust value."""
        agent = BaseAgent("test", "llama2", "Test.")
        assert agent.trust == 1.0
        
        agent.update_trust(0.75)
        assert agent.trust == 0.75
