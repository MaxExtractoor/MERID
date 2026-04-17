"""Simple test agent to debug LLM integration issues."""

from agents.base_agent import BaseAgent
from utils.logger import get_logger

class SimpleTestAgent(BaseAgent):
    """Minimal agent for testing LLM integration."""
    
    def __init__(self, agent_id: str = "simple-test-agent", model_name: str = "gemma3:1b"):
        role_prompt = "You are a helpful assistant. Respond briefly and clearly."
        super().__init__(agent_id, model_name, role_prompt, tool_budget=0)
        self.logger = get_logger(f"agents.{agent_id}")
    
    async def _additional_context(self, energy: dict, research_findings: str) -> str:
        """Simple context for testing."""
        return f"Test input: {energy.get('test_input', 'hello')}"
    
    def _parse_response(self, raw: str) -> dict:
        """Simple response parsing."""
        return {
            "vote": "test",
            "confidence": 0.8,
            "reasoning": raw[:200],  # Truncate to avoid issues
            "simulation": {},
            "raw": raw
        }

# Create a simple test endpoint
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/test", tags=["test"])

class TestRequest(BaseModel):
    test_input: str = "hello"

@router.post("/simple-agent")
async def test_simple_agent(request: TestRequest):
    """Test simple agent integration."""
    try:
        agent = SimpleTestAgent()
        energy = {
            "energy_id": "test-123",
            "test_input": request.test_input
        }
        
        result = await agent.process(energy)
        return {
            "status": "success",
            "result": result
        }
    except Exception as e:
        return {
            "status": "error", 
            "error": str(e)
        }
