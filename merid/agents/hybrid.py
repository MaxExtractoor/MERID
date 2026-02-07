"""§2 Hybrid Agent Bridge — Connect CanonicalAgent to BaseAgent LLM pipeline.

Allows any CanonicalAgent to optionally invoke the LLM reasoning pipeline
(BaseAgent.process) for qualitative analysis, then merge the LLM output
with the agent's structured typed output.

Pattern:
    CanonicalAgent._execute() produces structured data (theses, signals, etc.)
    → HybridBridge.enhance() sends a summary to the LLM for reasoning
    → LLM returns vote/confidence/reasoning
    → Merged into AgentOutput.payload["llm_reasoning"]
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentOutput, CanonicalAgent

from utils.logger import get_logger

logger = get_logger("merid.agents.hybrid")


@dataclass
class LLMEnhancement:
    """Result of LLM reasoning applied to structured agent output."""
    vote: str = "abstain"          # accept, reject, abstain
    confidence: float = 0.5
    reasoning: str = ""
    simulation: str = ""
    model_name: str = ""
    latency_ms: float = 0.0
    success: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "vote": self.vote,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "simulation": self.simulation,
            "model_name": self.model_name,
            "latency_ms": round(self.latency_ms, 2),
            "success": self.success,
            "error": self.error,
        }


class HybridBridge:
    """Bridge between CanonicalAgent (typed) and BaseAgent (LLM).

    Usage::

        bridge = HybridBridge()
        # After canonical agent produces output:
        enhanced = await bridge.enhance(agent_output, context="Crypto arb scan")
        agent_output.payload["llm_reasoning"] = enhanced.to_dict()
    """

    def __init__(
        self,
        model_name: str = "gemma3:4b",
        role_prompt: str = "You are a MERID trading analyst. Evaluate the following data and provide reasoning.",
        timeout_seconds: float = 30.0,
    ):
        self.model_name = model_name
        self.role_prompt = role_prompt
        self.timeout_seconds = timeout_seconds
        self._base_agent = None

    def _get_base_agent(self):
        """Lazy-init BaseAgent for LLM calls."""
        if self._base_agent is None:
            try:
                from agents.base_agent import BaseAgent
                self._base_agent = BaseAgent(
                    agent_id="hybrid-bridge",
                    model_name=self.model_name,
                    role_prompt=self.role_prompt,
                    tool_budget=0,  # No web search in bridge mode
                )
            except Exception as exc:
                logger.warning(f"BaseAgent unavailable for hybrid bridge: {exc}")
        return self._base_agent

    async def enhance(
        self,
        output: AgentOutput,
        context: str = "",
        max_payload_chars: int = 2000,
    ) -> LLMEnhancement:
        """Send structured output to LLM for qualitative reasoning.

        Args:
            output: The structured AgentOutput from a canonical agent.
            context: Additional context string for the LLM.
            max_payload_chars: Max chars of payload to send to LLM.

        Returns:
            LLMEnhancement with vote, confidence, and reasoning.
        """
        agent = self._get_base_agent()
        if not agent:
            return LLMEnhancement(error="BaseAgent unavailable")

        # Build energy packet from AgentOutput
        payload_str = json.dumps(output.payload, default=str)[:max_payload_chars]
        energy = {
            "energy_id": f"hybrid-{output.run_id}",
            "source": f"canonical:{output.agent_id}",
            "payload": f"{context}\n\nAgent: {output.agent_id} ({output.category})\n"
                       f"Type: {output.output_type}\n"
                       f"Confidence: {output.confidence}\n"
                       f"Data: {payload_str}",
        }

        import time
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                agent.process(energy, phase="hybrid_reasoning"),
                timeout=self.timeout_seconds,
            )
            latency = (time.perf_counter() - start) * 1000

            return LLMEnhancement(
                vote=result.get("vote", "abstain"),
                confidence=result.get("confidence", 0.5),
                reasoning=result.get("reasoning", ""),
                simulation=result.get("simulation", ""),
                model_name=self.model_name,
                latency_ms=latency,
                success=True,
            )
        except asyncio.TimeoutError:
            return LLMEnhancement(
                error="LLM timeout",
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return LLMEnhancement(
                error=str(exc),
                latency_ms=(time.perf_counter() - start) * 1000,
            )

    async def enhance_output(
        self,
        output: AgentOutput,
        context: str = "",
    ) -> AgentOutput:
        """Enhance an AgentOutput in-place with LLM reasoning.

        Adds llm_reasoning to the payload and adjusts confidence
        based on LLM agreement.
        """
        enhancement = await self.enhance(output, context)
        output.payload["llm_reasoning"] = enhancement.to_dict()

        if enhancement.success:
            # Blend confidence: 70% structured + 30% LLM
            blended = output.confidence * 0.7 + enhancement.confidence * 0.3
            output.confidence = round(blended, 4)

        return output


# ── Hybrid-aware CanonicalAgent mixin ────────────────────────────────

class HybridCanonicalAgent(CanonicalAgent):
    """CanonicalAgent with optional LLM enhancement.

    Subclasses implement _execute() as usual. If llm_enabled is True,
    the output is automatically enhanced via HybridBridge.
    """

    def __init__(self, agent_id, category, *, llm_enabled: bool = False, bridge: Optional[HybridBridge] = None):
        super().__init__(agent_id, category)
        self.llm_enabled = llm_enabled
        self._bridge = bridge

    @property
    def bridge(self) -> HybridBridge:
        if self._bridge is None:
            self._bridge = HybridBridge()
        return self._bridge

    async def run(self, context: Dict[str, Any] = None) -> AgentOutput:
        output = await super().run(context)

        if self.llm_enabled and output.output_type not in ("skipped", "error"):
            try:
                output = await self.bridge.enhance_output(output)
            except Exception as exc:
                logger.warning(f"LLM enhancement failed for {self.agent_id}: {exc}")

        return output
