from __future__ import annotations

# Stage 2 Agents: async reasoning pipeline, research tools, and structured outputs.

import asyncio
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

from core.event_bus import event_stream
from core.settings import MAX_TOOL_RESULTS, OLLAMA_BASE_URL, OLLAMA_GENERATE_ENDPOINT
from core.time_authority import current_time
from tools import web_search
from utils.logger import get_logger
from agents.reflection.integration import get_reflection_system
from agents.explainability import (
    get_explainability_tracker, create_reasoning_builder, DecisionType
)

_OLLAMA_URL = f"{OLLAMA_BASE_URL.rstrip('/')}{OLLAMA_GENERATE_ENDPOINT}"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_MODEL_SEMAPHORE = asyncio.Semaphore(1)  # serialize Ollama calls so HTTP stays responsive

class AgentErrorType(str, Enum):
    """Categorized error types for agent operations."""
    NETWORK = "network"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    VALIDATION = "validation"
    MODEL_ERROR = "model_error"
    UNKNOWN = "unknown"


@dataclass
class AgentErrorResponse:
    """Structured error response from an agent operation."""
    error_type: AgentErrorType
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": True,
            "error_type": self.error_type.value,
            "message": self.message,
            "details": self.details,
        }


def _model_stub_enabled() -> bool:
    return os.getenv("MERID_AGENT_MODEL_STUB", "false").strip().lower() in _TRUE_VALUES


def _build_stub_response(prompt: str, agent_id: str = "unknown") -> str:
    """Deterministic stub output when no LLM is available."""
    summary = prompt.strip().splitlines()
    summary = " ".join(line.strip() for line in summary if line.strip())[:320]
    
    # Generate varied votes based on agent_id hash for testing
    # This prevents all-abstain deadlock when Ollama is down
    agent_hash = hash(agent_id) % 3
    if agent_hash == 0:
        vote = "accept"
        confidence = 0.35
    elif agent_hash == 1:
        vote = "reject"
        confidence = 0.30
    else:
        vote = "abstain"
        confidence = 0.25
    
    return json.dumps({
        "reasoning": f"[stub] Ollama unreachable; using fallback response for {agent_id}",
        "vote": vote,
        "confidence": confidence,
        "simulation": f"Model offline. Agent {agent_id} using deterministic stub (vote={vote}).",
    })


class BaseAgent:
    """Shared async agent primitive for all MERID roles."""

    def __init__(
        self,
        agent_id: str,
        model_name: str,
        role_prompt: str,
        *,
        tool_budget: int = 2,
        is_truth_layer: bool = False,
        include_patterns: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.model_name = model_name
        self.role_prompt = role_prompt.strip()
        self.tool_budget = max(0, tool_budget)
        self.is_truth_layer = is_truth_layer
        self.include_patterns = include_patterns
        self.trust: float = 1.0
        self.logger = get_logger(f"agents.{agent_id}")

    async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
        """Execute the agent reasoning pipeline for a single energy packet."""
        await event_stream.publish(
            "agent:start",
            {"agent": self.agent_id, "energy_id": energy["energy_id"], "phase": phase},
        )
        self.logger.info("Processing energy %s", energy["energy_id"])

        research_findings = await self._gather_research(energy)
        extra_context = await self._additional_context(energy, research_findings)

        # Add reflection context for self-learning
        reflection_system = get_reflection_system()
        reflection_context = reflection_system.get_agent_context(
            self.agent_id,
            include_metrics=True,
            include_insights=True
        )
        if reflection_context:
            extra_context = f"{extra_context}\n\nReflection Context:\n{reflection_context}"

        prompt = self._build_prompt(energy, phase, research_findings, extra_context)

        raw_response = await self._invoke_model(prompt)
        parsed = self._parse_response(raw_response)

        result = {
            "agent_id": self.agent_id,
            "vote": parsed["vote"],
            "confidence": parsed["confidence"],
            "reasoning": parsed["reasoning"],
            "simulation": parsed["simulation"],
            "raw": parsed["raw"],
            "trust": self.trust,
            "research": research_findings,
        }

        # CONSTITUTIONAL: Record explainable decision reasoning
        try:
            reasoning_builder = create_reasoning_builder(
                agent_id=self.agent_id,
                decision_type=DecisionType.VOTE
            )

            reasoning_builder.set_decision(
                decision=parsed["vote"],
                confidence=parsed["confidence"]
            ).set_primary_reason(
                parsed["reasoning"]
            )

            # Add research findings as data sources
            for finding in research_findings:
                reasoning_builder.add_data_source(finding.get("source", "unknown"))

            # Add market context from energy
            reasoning_builder.set_market_context({
                "energy_id": energy["energy_id"],
                "source": energy.get("source", "unknown"),
                "payload": str(energy.get("payload", ""))[:200]
            })

            # Build and record reasoning
            decision_reasoning = reasoning_builder.build()
            explainability_tracker = get_explainability_tracker()
            explainability_tracker.record_decision(decision_reasoning)

            # Add reasoning to result
            result["explainable_reasoning"] = decision_reasoning.to_dict()

        except Exception as e:
            self.logger.error(f"Failed to record explainable reasoning: {e}")

        # Record decision for reflection and learning
        reflection_system.record_decision(
            agent_id=self.agent_id,
            energy_id=energy["energy_id"],
            decision=parsed["vote"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
            market_context={
                "source": energy.get("source"),
                "payload": str(energy.get("payload", ""))[:200]
            }
        )

        await event_stream.publish(
            "agent:result",
            {"agent": self.agent_id, "energy_id": energy["energy_id"], "result": result},
        )
        return result

    async def _gather_research(self, energy: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Run lightweight research bursts via the shared toolchain."""
        if self.tool_budget <= 0:
            return []

        payload = str(energy.get("payload", "")).strip()
        source = energy.get("source", "user")

        queries = [
            payload[:160],
            f"{source} signal context {payload[:120]}",
            "crypto macro trend latest catalysts",
        ]
        queries.extend(self._custom_queries(energy))

        seen: List[str] = []
        findings: List[Dict[str, Any]] = []
        for query in queries:
            normalized = query.strip()
            if not normalized or normalized.lower() in seen:
                continue
            seen.append(normalized.lower())
            if len(findings) >= self.tool_budget:
                break
            result = await asyncio.to_thread(web_search, normalized, MAX_TOOL_RESULTS)
            findings.append({"query": normalized, "results": result.get("results", [])})
        return findings

    def _build_prompt(
        self,
        energy: Dict[str, Any],
        phase: str,
        research: List[Dict[str, Any]],
        extra_context: str = "",
    ) -> str:
        research_section = ""
        if research:
            snippets: List[str] = []
            for chunk in research:
                summary = "; ".join(
                    f"{item.get('title', '')}: {item.get('snippet', '')[:180]}"
                    for item in chunk.get("results", [])[:2]
                )
                if summary:
                    snippets.append(f"- {chunk['query']}: {summary}")
            if snippets:
                research_section = "\nResearch Findings:\n" + "\n".join(snippets)

        context_block = ""
        if extra_context:
            context_block = f"\nAdditional Context:\n{extra_context.strip()}\n"

        return f"""
{self.role_prompt}

Timestamp: {current_time()["utc_iso"]}
Energy Source: {energy.get("source")}
Payload: {energy.get("payload")}
Phase: {phase}
Agent ID: {self.agent_id}
Model: {self.model_name}

Instructions:
- Think step-by-step with evidence.
- Reference provided research when relevant.
- Be explicit about uncertainty and assumptions.
- Respond strictly in JSON with keys reasoning, vote, confidence, simulation.
{context_block}
{research_section}
"""

    async def _invoke_model(self, prompt: str) -> str:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "temperature": 0.35,
            "stream": False,
        }

        if _model_stub_enabled():
            self.logger.warning(" Model stub mode enabled - bypassing Ollama for %s", self.agent_id)
            return _build_stub_response(prompt, self.agent_id)

        try:
            async with _MODEL_SEMAPHORE:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                    response = await client.post(_OLLAMA_URL, json=payload)
                    response.raise_for_status()
                    data = response.json()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:  
            self.logger.warning(" Ollama unreachable at %s (using stub fallback): %s", _OLLAMA_URL, exc)
            return _build_stub_response(prompt, self.agent_id)
        except Exception as exc:  
            self.logger.error(" Model invocation failed for %s: %s", self.agent_id, exc)
            return _build_stub_response(prompt, self.agent_id)

        return data.get("response") or data.get("output") or json.dumps(data)

    def _parse_response(self, raw: str) -> Dict[str, Any]:
        fallback = {
            "reasoning": raw[:400],
            "vote": "abstain",
            "confidence": 0.45,
            "simulation": "Insufficient structured response",
            "raw": raw,
        }

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            self.logger.warning("[%s] JSON parsing failed.", self.agent_id)
            return fallback

        reasoning = str(parsed.get("reasoning", "")).strip() or fallback["reasoning"]
        simulation = str(parsed.get("simulation", "")).strip() or fallback["simulation"]
        confidence = float(parsed.get("confidence", fallback["confidence"]) or fallback["confidence"])
        vote = self._normalize_vote(parsed.get("vote", "abstain"))

        return {
            "reasoning": reasoning,
            "vote": vote,
            "confidence": max(0.0, min(confidence, 1.0)),
            "simulation": simulation,
            "raw": raw,
        }

    def _normalize_vote(self, value: Any) -> str:
        mapping = {
            "accept": "accept",
            "+1": "accept",
            "approve": "accept",
            "yes": "accept",
            "reject": "reject",
            "-1": "reject",
            "no": "reject",
            "deny": "reject",
            "abstain": "abstain",
            "0": "abstain",
            "hold": "abstain",
        }
        normalized = str(value).strip().lower()
        return mapping.get(normalized, "abstain")

    def update_trust(self, value: float) -> None:
        """Allow external systems (Neo4j) to sync trust values."""
        self.trust = value

    def _custom_queries(self, energy: Dict[str, Any]) -> List[str]:
        """Agents can override to add tailored research queries."""
        return []

    async def _additional_context(
        self, energy: Dict[str, Any], research: List[Dict[str, Any]]
    ) -> str:
        """Agents may contribute extra prompt context (e.g., history)."""
        if not self.include_patterns:
            return ""

        from memory.patterns import pattern_engine  # Local import to avoid cycles

        insights = pattern_engine.insights(20)
        parts = []
        if insights["keywords"]:
            keyword_summary = ", ".join(f"{item['label']} ({item['count']})" for item in insights["keywords"])
            parts.append(f"Top keywords: {keyword_summary}")
        if insights["sources"]:
            source_summary = ", ".join(f"{item['label']} ({item['count']})" for item in insights["sources"])
            parts.append(f"Source distribution: {source_summary}")
        if insights["validation_status"]:
            status_summary = ", ".join(f"{item['label']} ({item['count']})" for item in insights["validation_status"])
            parts.append(f"Validation states: {status_summary}")

        return "\n".join(parts)