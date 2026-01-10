from agents.base_agent import BaseAgent
from db.neo4j import memory

role = """You are the Archivist — system historian. 
Query Neo4j memory for historical patterns matching current energy.
Compare novelty, past outcomes, agent accuracy on similar signals.
Be precise with sources from history."""

class Archivist(BaseAgent):
    def __init__(self, agent_id="archivist-01", model_name="gemma3:1b"):
        super().__init__(agent_id, model_name, role)

    async def process(self, energy, phase="reasoning"):
        # Query history for similar payloads
        history = memory.get_history(limit=10)
        similar = [h for h in history if any(kw.lower() in h["payload"].lower() for kw in energy["payload"].split()[:10])]
        
        context = f"Historical similar events ({len(similar)} found): {json.dumps(similar, indent=2)}" if similar else "No strong historical matches."
        
        prompt = self._build_prompt(energy, phase) + f"\nHistorical Context:\n{context}"
        
        # Rest same as base
        stream = ollama.generate(model=self.model_name, prompt=prompt, stream=True)
        # ... (keep streaming logic)
