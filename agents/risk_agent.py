from __future__ import annotations

from merid.agents.base_agent import BaseAgent

ROLE_PROMPT = """
You are MERID’s chief risk officer.
- Focus exclusively on tail events, liquidity crunches, reflexivity cascades, counterparty failure.
- Reject if loss paths dominate. Abstain when data is insufficient.
- Demand scenario math: specify drawdowns, triggers, and mitigation.
""".strip()


class RiskAgent(BaseAgent):
    def __init__(self, agent_id: str = "risk-01", model_name: str = "merid-interface:latest") -> None:
        super().__init__(agent_id, model_name, ROLE_PROMPT, tool_budget=2)

    def _custom_queries(self, energy):
        payload = str(energy.get("payload", ""))
        return [
            f"{payload[:120]} downside risk crypto",
            "btc liquidation levels funding rates fear greed",
            "macro stress events usd liquidity crypto correlation",
        ]
