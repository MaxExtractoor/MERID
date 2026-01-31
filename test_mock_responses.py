"""Unit test for mock response structural consistency."""

import pytest
import json
from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent
from agents.base_agent import BaseAgent

def test_mock_response_structure():
    """Test that mock responses have the same structure as live LLM responses."""
    
    # Create agent instance
    agent = PredictionArbitrageAnalystAgent()
    
    # Test arbitrage-specific mock response
    mock_response = agent._generate_mock_response("arbitrage opportunities analysis")
    parsed = json.loads(mock_response)
    
    # Verify required fields for arbitrage analysis
    assert "summary" in parsed
    assert "top_opportunities" in parsed
    assert "filters_used" in parsed
    assert "total_opportunities_analyzed" in parsed
    assert "analysis_timestamp" in parsed
    
    # Verify opportunity structure
    if parsed["top_opportunities"]:
        opp = parsed["top_opportunities"][0]
        required_opp_fields = [
            "canonical_question", "spread_probability", "best_venue",
            "best_probability", "worst_venue", "worst_probability",
            "days_to_resolution", "total_liquidity", "risk_note"
        ]
        for field in required_opp_fields:
            assert field in opp, f"Missing required field: {field}"
    
    # Test generic mock response
    generic_response = agent._generate_mock_response("simple test prompt")
    parsed_generic = json.loads(generic_response)
    
    # Verify generic response structure
    assert "reasoning" in parsed_generic
    assert "confidence" in parsed_generic
    assert "vote" in parsed_generic
    assert "simulation" in parsed_generic

def test_mock_response_deterministic():
    """Test that mock responses are deterministic."""
    
    agent = PredictionArbitrageAnalystAgent()
    
    # Same prompt should produce same response
    prompt = "arbitrage opportunities analysis"
    response1 = agent._generate_mock_response(prompt)
    response2 = agent._generate_mock_response(prompt)
    
    assert response1 == response2, "Mock responses should be deterministic"

def test_llm_mode_logging():
    """Test that llm_mode and llm_status are properly logged."""
    
    from core.settings import AGENT_LLM_MODE
    
    # Test mock mode
    original_mode = AGENT_LLM_MODE
    try:
        # Mock mode should set llm_mode to "mock" and llm_status to "skipped"
        agent = PredictionArbitrageAnalystAgent()
        
        # Create a mock run log
        from agents.prediction_arbitrage_analyst import AgentRunLog
        run_log = AgentRunLog(
            run_id="test-123",
            timestamp=1234567890.0,
            agent_id="test-agent",
            agent_version="test-model",
            run_type="test"
        )
        
        # Set reference
        agent._current_run_log = run_log
        
        # Call mock mode (this should set the fields)
        response = agent._generate_mock_response("test")
        
        # Verify fields were set
        assert run_log.llm_mode == "mock"
        assert run_log.llm_status == "skipped"
        
    finally:
        # Restore original mode
        import os
        os.environ["AGENT_LLM_MODE"] = original_mode

if __name__ == "__main__":
    test_mock_response_structure()
    test_mock_response_deterministic()
    test_llm_mode_logging()
    print("✅ All mock response tests passed")
