"""Tests for core/agent.py."""
import pytest
import asyncio
from core.agent import MeridAgent


class TestMeridAgent:
    """Test MeridAgent class."""

    def test_initialization(self):
        """Test agent initialization."""
        agent = MeridAgent("TestAgent", "gpt-4")
        assert agent.name == "TestAgent"
        assert agent.model == "gpt-4"

    @pytest.mark.asyncio
    async def test_reason(self):
        """Test agent reason method."""
        agent = MeridAgent("TestAgent", "gpt-4")
        result = await agent.reason({"test": "data"})
        
        assert "vote" in result
        assert "confidence" in result
        assert "analysis" in result
        assert result["vote"] == "accept"
        assert result["confidence"] == 0.85
        assert "TestAgent" in result["analysis"]

    @pytest.mark.asyncio
    async def test_reason_different_agents(self):
        """Test different agents return different analyses."""
        agent1 = MeridAgent("Agent1", "gpt-4")
        agent2 = MeridAgent("Agent2", "gpt-4")
        
        result1 = await agent1.reason({})
        result2 = await agent2.reason({})
        
        assert "Agent1" in result1["analysis"]
        assert "Agent2" in result2["analysis"]
