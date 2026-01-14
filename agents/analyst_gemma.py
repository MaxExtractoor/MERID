from __future__ import annotations

from agents.base_agent import BaseAgent

ROLE_PROMPT = """
You are the fast-twitch MERID interface analyst.
- Prioritize intraday momentum, tape speed, funding imbalances.
- Surface concrete catalysts and data points, not vibes.
- Flag uncertainty explicitly and abstain when signal is weak.
""".strip()


class AnalystGemma(BaseAgent):
    def __init__(self, agent_id: str = "analyst-gemma-01", model_name: str = "merid-interface:latest") -> None:
        super().__init__(agent_id, model_name, ROLE_PROMPT, tool_budget=1)
