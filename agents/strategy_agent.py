from __future__ import annotations

# Stage 6 Strategy Agent: leverages validated memory + patterns to propose forward strategies.

from typing import Any, Dict, List

from agents.base_agent import BaseAgent
from memory.store import reality_memory

ROLE_PROMPT = """
You are MERID's Autonomous Strategy Agent.
- Monitor validated realities and extract reusable structures (market, horizon, catalysts).
- Propose strategies with explicit entry/exit criteria and required validators.
- Reference only reality-confirmed evidence; never speculate.
- Default to abstain if no high-quality play exists.
""".strip()


class StrategyAgent(BaseAgent):
    def __init__(
        self,
        agent_id: str = "strategy-agent-01",
        model_name: str = "merid-strategist:latest",
    ) -> None:
        super().__init__(
            agent_id,
            model_name,
            ROLE_PROMPT,
            tool_budget=2,
            include_patterns=True,
            is_truth_layer=False,
        )

    def _custom_queries(self, energy: Dict[str, Any]) -> List[str]:
        payload = str(energy.get("payload", ""))[:160]
        return [
            f"market structure follow-through {payload}",
            "crypto rotation early signals liquidity flows",
            "derivatives positioning funding rates strategy",
        ]

    async def _additional_context(
        self,
        energy: Dict[str, Any],
        research: List[Dict[str, Any]],
    ) -> str:
        base_context = await super()._additional_context(energy, research)
        recent = reality_memory.recent(5)
        if not recent:
            return base_context

        lines = [
            "Recent reality-confirmed strategies:",
        ]
        for item in recent:
            lines.append(
                f"- {item.get('payload', '')[:140]} | consensus {item.get('consensus', 0):.2f} "
                f"| validated {item.get('validated_at')}"
            )
        recap = "\n".join(lines)
        if base_context:
            return f"{base_context}\n{recap}"
        return recap
