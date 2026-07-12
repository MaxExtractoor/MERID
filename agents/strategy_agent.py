from __future__ import annotations

# Stage 6 Strategy Agent: leverages validated memory + patterns to propose forward strategies.

from typing import Any, Dict, List, Optional

from agents.base_agent import BaseAgent
from memory.store import reality_memory
from social.social_aware_quant import get_social_aware_quant_engine

# CRITICAL FIX: Lazy import to break circular import chain
# core.social_strategy_router -> governance.multi_agent_risk_controls -> 
# core.strategy_versioning -> governance.meta_audit_runtime -> 
# agents.reflection_layer -> agents.strategy_agent (circular!)
def _get_evaluate_social_trade():
    from merid.core.social_strategy_router import evaluate_social_trade
    return evaluate_social_trade

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
            return await self._append_social_context(base_context)

        lines = [
            "Recent reality-confirmed strategies:",
        ]
        for item in recent:
            lines.append(
                f"- {item.get('payload', '')[:140]} | consensus {item.get('consensus', 0):.2f} "
                f"| validated {item.get('validated_at')}"
            )
        recap = "\n".join(lines)
        combined = f"{base_context}\n{recap}" if base_context else recap
        return await self._append_social_context(combined)

    async def _append_social_context(self, context: str) -> str:
        """Append latest social risk posture so LLM plans respect guardrails."""
        engine = get_social_aware_quant_engine()
        status = engine.get_social_risk_status()
        exposures = engine.get_top_asset_exposure()
        lines = [
            "Social risk snapshot:",
            f"- kill_switch_active: {status.get('kill_switch_active')}",
            f"- total_social_exposure: ${status.get('total_social_exposure', 0):,.2f}",
            f"- tracked_assets: {status.get('assets_tracked', 0)}",
        ]
        if exposures:
            lines.append("- top_social_assets:")
            for item in exposures:
                lines.append(
                    f"  • {item['asset']}: ${item['exposure']:,.2f} "
                    f"(confirmation {item['constraints'].get('confirmation_score', 0):.2f})"
                )
        social_context = "\n".join(lines)
        return f"{context}\n{social_context}" if context else social_context

    async def evaluate_social_trade(
        self,
        strategy_id: str,
        asset: str,
        portfolio_value: float,
        sentiment_score: float,
        *,
        version: Optional[str] = None,
        market_metrics: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Helper for downstream agents: run the social trade router with full guardrails.
        Ensures LLM-proposed trades can be programmatically vetted before execution.
        """
        # Use lazy import to avoid circular dependency
        evaluate_fn = _get_evaluate_social_trade()
        return evaluate_fn(
            strategy_id=strategy_id,
            asset=asset,
            portfolio_value=portfolio_value,
            risk_appetite=risk_appetite,
            social_sentiment=social_sentiment,
            version=version,
            market_metrics=market_metrics,
        )
