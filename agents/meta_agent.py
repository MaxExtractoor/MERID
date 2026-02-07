from __future__ import annotations

# Stage 6 Meta Agent: audits MERID systems for drift/bias/collusion.

from typing import Any, Dict, List

from agents.base_agent import BaseAgent
from core.event_bus import event_stream
from core.state import state
from memory.patterns import pattern_engine
from swarm.performance import performance_ledger

ROLE_PROMPT = """
You are the MERID Meta-Audit Agent.
- Detect bias drift, validator failures, and potential collusion.
- Recommend mitigations: weight resets, validator reviews, agent retirement.
- Never vote on proposals; always abstain after reporting diagnostics.
- Use only telemetry from validated realities, pattern summaries, and performance ledgers.
""".strip()


class MetaAuditAgent(BaseAgent):
    def __init__(self, agent_id: str = "meta-audit-01") -> None:
        super().__init__(
            agent_id,
            model_name="merid-interface:latest",
            role_prompt=ROLE_PROMPT,
            tool_budget=0,
            include_patterns=False,
            is_truth_layer=True,
        )

    async def process(self, energy: Dict[str, Any], phase: str = "audit") -> Dict[str, Any]:
        leaderboard = performance_ledger.leaderboard(5)
        validations = await state.list_validations(5)
        patterns = pattern_engine.insights(30)

        issues: List[str] = []
        pending_ratio = self._pending_ratio(validations)
        if pending_ratio > 0.6:
            issues.append(f"High pending validation ratio ({pending_ratio:.0%}). Investigate validator latency.")

        if leaderboard:
            top_score = leaderboard[0]["score"]
            if top_score > 0.9:
                issues.append("Top agent dominance detected (>0.9 score). Consider decay boost.")

        keyword_bias = self._keyword_bias(patterns)
        if keyword_bias:
            issues.append(keyword_bias)

        report = {
            "issues": issues or ["No critical anomalies detected."],
            "leaderboard_snapshot": leaderboard,
            "validation_sample": validations,
            "pattern_summary": patterns,
        }

        await state.record_audit(report)
        await event_stream.publish("audit:report", {"report": report})

        return {
            "agent_id": self.agent_id,
            "vote": "abstain",
            "confidence": 0.0,
            "reasoning": "\n".join(report["issues"]),
            "simulation": "Meta audit completed. Recommendations attached.",
            "raw": report,
            "trust": self.trust,
            "research": [],
        }

    def _pending_ratio(self, validations: List[Dict[str, Any]]) -> float:
        if not validations:
            return 0.0
        pending = sum(1 for item in validations if item.get("verdict", {}).get("status") == "pending")
        return pending / len(validations)

    def _keyword_bias(self, patterns: Dict[str, Any]) -> str | None:
        keywords = patterns.get("keywords", [])
        if not keywords:
            return None
        top = keywords[0]
        if top["count"] >= 5:
            return f"Keyword '{top['label']}' appearing disproportionately ({top['count']} times)."
        return None
