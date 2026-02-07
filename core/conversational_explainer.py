"""
Conversational Explainability Layer — LLM-backed follow-up queries.

Wraps the existing ExplainabilityService with a conversational interface
that supports multi-turn follow-up questions like:
- "Why did we take that trade?"
- "Tell me more about that rule"
- "What would have happened if we used a different model?"
- "Show me similar past decisions"

Falls back to structured plain-language explanations when no LLM is
configured, ensuring the system always provides useful answers.

Usage:
    from core.conversational_explainer import get_conversational_explainer
    explainer = get_conversational_explainer()
    answer = explainer.ask("Why did we buy BTC at 50K?")
    follow_up = explainer.ask("What rules were evaluated?", session_id=answer["session_id"])
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.conversational_explainer")


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationSession:
    """A multi-turn conversation session."""
    session_id: str
    decision_id: Optional[str] = None
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, role: str, content: str, **metadata: Any) -> None:
        self.turns.append(ConversationTurn(role=role, content=content, metadata=metadata))

    def get_history_text(self, max_turns: int = 10) -> str:
        recent = self.turns[-max_turns:]
        return "\n".join(f"{t.role}: {t.content}" for t in recent)


class ConversationalExplainer:
    """LLM-backed conversational explainability with structured fallback.

    Architecture:
    1. User asks a question (optionally referencing a decision_id)
    2. System retrieves relevant ExplanationRecords
    3. If LLM is available: builds prompt with context + history → LLM generates answer
    4. If no LLM: falls back to structured plain-language from ExplainabilityService
    5. Answer is stored in session for multi-turn follow-up
    """

    def __init__(self, llm_provider: Optional[str] = None, llm_model: Optional[str] = None):
        self._sessions: Dict[str, ConversationSession] = {}
        self._max_sessions = 100
        self._llm_provider = llm_provider or os.getenv("MERID_EXPLAIN_LLM_PROVIDER", "")
        self._llm_model = llm_model or os.getenv("MERID_EXPLAIN_LLM_MODEL", "")
        self._llm_available = bool(self._llm_provider)

    def ask(
        self,
        question: str,
        decision_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Ask a question about a trading decision.

        Args:
            question: Natural language question
            decision_id: Optional decision ID to focus on
            session_id: Optional session ID for follow-up questions

        Returns:
            Dict with answer, session_id, source, and metadata
        """
        # Get or create session
        session = self._get_or_create_session(session_id, decision_id)
        session.add_turn("user", question)

        # Resolve decision_id from session context if not provided
        effective_decision_id = decision_id or session.decision_id

        # Retrieve structured explanation context
        context = self._gather_context(effective_decision_id, question)
        session.context.update(context)

        # Generate answer
        if self._llm_available:
            answer = self._ask_llm(session, question, context)
            source = f"llm:{self._llm_provider}/{self._llm_model}"
        else:
            answer = self._structured_fallback(question, context, session)
            source = "structured_fallback"

        session.add_turn("assistant", answer)

        return {
            "answer": answer,
            "session_id": session.session_id,
            "decision_id": effective_decision_id,
            "source": source,
            "turn_count": len(session.turns),
            "timestamp": time.time(),
        }

    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        return self._sessions.get(session_id)

    def list_sessions(self, limit: int = 20) -> List[Dict[str, Any]]:
        sessions = sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)
        return [
            {
                "session_id": s.session_id,
                "decision_id": s.decision_id,
                "turns": len(s.turns),
                "created_at": s.created_at,
            }
            for s in sessions[:limit]
        ]

    # ── Internal methods ──────────────────────────────────────────

    def _get_or_create_session(
        self, session_id: Optional[str], decision_id: Optional[str]
    ) -> ConversationSession:
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            if decision_id:
                session.decision_id = decision_id
            return session

        new_id = session_id or f"conv-{uuid.uuid4().hex[:12]}"
        session = ConversationSession(session_id=new_id, decision_id=decision_id)
        self._sessions[new_id] = session

        # Evict oldest sessions if over limit
        if len(self._sessions) > self._max_sessions:
            oldest_key = min(self._sessions, key=lambda k: self._sessions[k].created_at)
            del self._sessions[oldest_key]

        return session

    def _gather_context(self, decision_id: Optional[str], question: str) -> Dict[str, Any]:
        """Retrieve structured explanation data for context."""
        context: Dict[str, Any] = {}

        try:
            from core.explainability import get_explainability_service
            svc = get_explainability_service()

            if decision_id:
                plain = svc.explain_plain_language(decision_id)
                if plain:
                    context["plain_explanation"] = plain["plain_text"]
                    context["explanation_type"] = plain.get("type")
                    context["agent_id"] = plain.get("agent_id")
                    context["domain"] = plain.get("domain")

                record = svc.find_by_decision_id(decision_id)
                if record:
                    context["record_summary"] = record.summary
                    if record.rationale:
                        context["rationale_reason"] = record.rationale.reason
                        if record.rationale.rules_fired:
                            context["rules"] = [
                                {
                                    "name": r.rule_name,
                                    "passed": r.passed,
                                    "observed": r.observed_value,
                                    "threshold": r.threshold,
                                }
                                for r in record.rationale.rules_fired
                            ]
                        if record.rationale.counterfactuals:
                            context["alternatives"] = [
                                {"summary": cf.summary, "rejected": cf.reason_rejected}
                                for cf in record.rationale.counterfactuals
                            ]

            # Also fetch recent decisions for broader context
            recent = svc.fetch_recent(limit=5)
            context["recent_decisions"] = [
                {"id": r.record_id, "type": r.explanation_type.value, "summary": r.summary}
                for r in recent
            ]
        except Exception as exc:
            logger.debug(f"Context gathering error: {exc}")
            context["error"] = str(exc)

        return context

    def _ask_llm(
        self, session: ConversationSession, question: str, context: Dict[str, Any]
    ) -> str:
        """Send question + context to LLM for conversational answer."""
        system_prompt = (
            "You are MERID's trading decision explainer. You help operators understand "
            "why the system made specific trading decisions. Be concise, factual, and "
            "reference specific rules, models, and agent reasoning when available. "
            "If you don't have enough information, say so clearly."
        )

        # Build context block
        context_block = ""
        if context.get("plain_explanation"):
            context_block += f"\n--- Decision Context ---\n{context['plain_explanation']}\n"
        if context.get("rules"):
            rules_text = "\n".join(
                f"  - {r['name']}: {'PASS' if r['passed'] else 'FAIL'} "
                f"(observed={r['observed']} vs threshold={r['threshold']})"
                for r in context["rules"]
            )
            context_block += f"\n--- Rules Evaluated ---\n{rules_text}\n"
        if context.get("alternatives"):
            alts_text = "\n".join(
                f"  - {a['summary']} → rejected: {a['rejected']}"
                for a in context["alternatives"]
            )
            context_block += f"\n--- Alternatives Considered ---\n{alts_text}\n"

        # Build messages
        messages = [{"role": "system", "content": system_prompt}]
        if context_block:
            messages.append({"role": "system", "content": context_block})

        # Add conversation history
        for turn in session.turns[-8:]:
            messages.append({"role": turn.role, "content": turn.content})

        # Try to call LLM
        try:
            if self._llm_provider == "openai":
                return self._call_openai(messages)
            elif self._llm_provider == "anthropic":
                return self._call_anthropic(messages)
            else:
                logger.warning(f"Unknown LLM provider: {self._llm_provider}, falling back")
                return self._structured_fallback(question, context, session)
        except Exception as exc:
            logger.warning(f"LLM call failed, falling back: {exc}")
            return self._structured_fallback(question, context, session)

    def _call_openai(self, messages: List[Dict[str, str]]) -> str:
        """Call OpenAI-compatible API."""
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model=self._llm_model or "gpt-4o-mini",
            messages=messages,
            max_tokens=500,
            temperature=0.3,
        )
        return response.choices[0].message.content or "No response generated."

    def _call_anthropic(self, messages: List[Dict[str, str]]) -> str:
        """Call Anthropic API."""
        import anthropic
        client = anthropic.Anthropic()
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        chat_msgs = [m for m in messages if m["role"] != "system"]
        response = client.messages.create(
            model=self._llm_model or "claude-3-5-haiku-20241022",
            system="\n\n".join(system_msgs),
            messages=chat_msgs,
            max_tokens=500,
        )
        return response.content[0].text

    def _structured_fallback(
        self, question: str, context: Dict[str, Any], session: ConversationSession
    ) -> str:
        """Generate a structured answer without LLM."""
        q_lower = question.lower()

        # Route to appropriate structured answer
        if context.get("plain_explanation"):
            base = context["plain_explanation"]
        else:
            base = "No specific decision context available."

        # Handle common follow-up patterns
        if any(kw in q_lower for kw in ["rule", "check", "constraint", "limit"]):
            if context.get("rules"):
                lines = ["Rules evaluated for this decision:"]
                for r in context["rules"]:
                    status = "✓ PASSED" if r["passed"] else "✗ FAILED"
                    lines.append(
                        f"  {status} {r['name']}: observed={r['observed']} "
                        f"(threshold={r['threshold']})"
                    )
                return "\n".join(lines)
            return "No rule evaluation data available for this decision."

        if any(kw in q_lower for kw in ["alternative", "other", "instead", "counterfactual"]):
            if context.get("alternatives"):
                lines = ["Alternatives that were considered:"]
                for a in context["alternatives"]:
                    lines.append(f"  - {a['summary']} → rejected because: {a['rejected']}")
                return "\n".join(lines)
            return "No alternative actions were recorded for this decision."

        if any(kw in q_lower for kw in ["recent", "history", "last", "previous"]):
            if context.get("recent_decisions"):
                lines = ["Recent decisions:"]
                for d in context["recent_decisions"]:
                    lines.append(f"  [{d['id']}] {d['type']}: {d['summary']}")
                return "\n".join(lines)
            return "No recent decision history available."

        if any(kw in q_lower for kw in ["why", "reason", "explain", "what"]):
            return base

        return f"Based on available context:\n{base}"


_explainer: Optional[ConversationalExplainer] = None


def get_conversational_explainer() -> ConversationalExplainer:
    """Get or create the singleton ConversationalExplainer."""
    global _explainer
    if _explainer is None:
        _explainer = ConversationalExplainer()
    return _explainer
