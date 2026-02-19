"""Guardrails for LLM tool usage and RAG sanitization."""
from __future__ import annotations

import re
from typing import Dict, Iterable, Optional, Tuple

from merid.llm.governance import LLMRole


DEFAULT_TOOL_ALLOWLIST: Dict[LLMRole, Iterable[str]] = {
    LLMRole.DEV_SWARM: {
        "rag_dev",
        "list_pending_approvals",
        "create_dev_proposal",
        "annotate_proposal",
    },
    LLMRole.COGNITIVE: {
        "rag_cognitive",
        "get_hypotheses",
        "get_reality_debug_snapshot",
        "get_team_diversity",
    },
    LLMRole.SPORTS: {
        "rag_sports",
        "get_sports_events",
        "get_opticodds_edges",
    },
    LLMRole.OPS: {
        "rag_dev",
        "rag_cognitive",
        "get_slo_status",
        "list_pending_approvals",
    },
    LLMRole.RESEARCH: {
        "rag_dev",
        "rag_cognitive",
        "rag_sports",
        "get_brier_history",
    },
    LLMRole.TRADING: {
        "get_market_calibration",
        "get_odds_movement",
        "rag_dev",
    },
}


_INJECTION_PATTERNS = [
    r"ignore\s+(previous|earlier)\s+instructions",
    r"disregard\s+all\s+instructions",
    r"act\s+as\s+.*",
    r"you\s+are\s+now\s+.*",
    r"override\s+system",
    r"jailbreak",
    r"DAN\s+mode",
]


def check_tool_allowed(
    role: LLMRole,
    tool_name: str,
    params: Optional[Dict[str, object]] = None,
) -> Tuple[bool, Optional[str]]:
    """Return whether a tool is allowed for the role."""
    _ = params
    allowed = DEFAULT_TOOL_ALLOWLIST.get(role, set())
    if tool_name in allowed:
        return True, None
    return False, f"Tool '{tool_name}' not allowed for role '{role.value}'."


def sanitize_rag_chunk(text: str) -> str:
    """Remove common prompt injection patterns from RAG text."""
    sanitized = text
    for pattern in _INJECTION_PATTERNS:
        sanitized = re.sub(pattern, "[redacted]", sanitized, flags=re.IGNORECASE)
    return sanitized
