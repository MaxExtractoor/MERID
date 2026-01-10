from agents.base_agent import BaseAgent

role = "You are an optimistic synthesizer. Find opportunities, confluence, catalysts. Balance the skeptic."

class Synthesizer(BaseAgent):
    def __init__(self, agent_id="synthesizer-01", model_name="merid-strategist:latest"):
        super().__init__(agent_id, model_name, role)
