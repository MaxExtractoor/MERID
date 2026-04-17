import json
from typing import Any, Dict, List

from agents.base_agent import BaseAgent
from db.neo4j import memory

role = """You are the Archivist — system historian.
Query Neo4j memory for historical patterns matching current energy.
Compare novelty, past outcomes, agent accuracy on similar signals.
Be precise with sources from history."""

class Archivist(BaseAgent):
    def __init__(self, agent_id="archivist-01", model_name="gemma3:1b"):
        super().__init__(agent_id, model_name, role, tool_budget=0)
        # Cache the historical context so _additional_context can access it
        self._historical_context: str = ""

    async def _additional_context(
        self, energy: Dict[str, Any], research: List[Dict[str, Any]]
    ) -> str:
        """Inject Neo4j historical context into the LLM prompt."""
        try:
            if memory is None:
                raise AttributeError("Neo4j memory unavailable")
            history = memory.get_history(limit=10)
            payload_text = str(energy.get("payload", ""))
            similar = [
                h for h in history
                if any(kw.lower() in h.get("payload", "").lower() for kw in payload_text.split()[:10])
            ]
            context = (
                f"Historical similar events ({len(similar)} found):\n"
                f"{json.dumps(similar, indent=2, default=str)}"
                if similar else "No strong historical matches."
            )
        except Exception as e:
            self.logger.warning(f"History query failed: {e}")
            context = "Historical context unavailable."

        self._historical_context = context
        return context

    async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
        result = await super().process(energy, phase)
        # Expose the context that was already injected into the prompt
        result["historical_context"] = self._historical_context
        return result
