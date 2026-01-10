from __future__ import annotations

from agents.base_agent import BaseAgent

ROLE_PROMPT = """
You are the deep-cycle strategic analyst.
- Evaluate macro, liquidity, positioning, and regulatory catalysts.
- Identify second and third-order impacts before recommending acceptance.
- Require explicit causal chains and evidence prior to approving.
""".strip()


class AnalystLlama(BaseAgent):
    def __init__(
        self,
        agent_id: str = "analyst-llama-01",
        model_name: str = "merid-strategist:latest",
    ) -> None:
        super().__init__(agent_id, model_name, ROLE_PROMPT, tool_budget=3)

    def _custom_queries(self, energy):
        payload = str(energy.get("payload", ""))
        return [
            f"macro implications {payload[:120]} crypto",
            "btc eth liquidity flows cme futures positioning",
            "regulatory news bitcoin etf approval timeline",
            "btc eth correlation with gold and usd",
        ]

    async def process(self, energy, phase="reasoning"):
        # Real research first
        search_results = self.research(f"{energy['payload']} site:coindesk.com OR site:theblock.co OR site:bloomberg.com")
        context = f"Web research results:\\n{search_results}"
        
        prompt = self._build_prompt(energy, phase) + f"\\nResearch Context:\\n{context}"
        # ... rest of ollama call
