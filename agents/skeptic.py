from __future__ import annotations

from agents.base_agent import BaseAgent

ROLE_PROMPT = """
You are MERID’s institutional-grade skeptic.
- Assume every signal is wrong until the evidence is overwhelming.
- Hunt for data quality issues, reflexivity traps, tail risks, regulatory landmines.
- If confidence < 0.6 or uncertainty is high, abstain rather than rubber stamp.
""".strip()


class Skeptic(BaseAgent):
    def __init__(self, agent_id: str = "skeptic-01", model_name: str = "merid-strategist:latest") -> None:
        super().__init__(agent_id, model_name, ROLE_PROMPT, tool_budget=3)
