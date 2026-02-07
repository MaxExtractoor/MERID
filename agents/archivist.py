import json
from typing import Any, Dict

from agents.base_agent import BaseAgent
from db.neo4j import memory

role = """You are the Archivist — system historian. 
Query Neo4j memory for historical patterns matching current energy.
Compare novelty, past outcomes, agent accuracy on similar signals.
Be precise with sources from history."""

class Archivist(BaseAgent):
    def __init__(self, agent_id="archivist-01", model_name="gemma3:1b"):
        super().__init__(agent_id, model_name, role, tool_budget=0)

    async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
        # Query history for similar payloads
        try:
            history = memory.get_history(limit=10)
            payload_text = energy.get("payload", "")
            similar = [h for h in history if any(kw.lower() in h.get("payload", "").lower() for kw in payload_text.split()[:10])]
            context = f"Historical similar events ({len(similar)} found): {json.dumps(similar, indent=2)}" if similar else "No strong historical matches."
        except Exception as e:
            self.logger.warning(f"History query failed: {e}")
            context = "Historical context unavailable."
        
        # Use base class process with empty research (archivist doesn't do web research)
        result = await super().process(energy, phase)
        result["historical_context"] = context
        return result
