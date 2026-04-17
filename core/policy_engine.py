"""Policy engine providing guardrail evaluations for MERID dev swarm."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Tuple, Optional

import yaml

_GUARDRAIL_CONFIG_PATH = "policy/guardrails.yml"


def _load_guardrails() -> Dict[str, Dict[str, Any]]:
    with open(_GUARDRAIL_CONFIG_PATH, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    guardrails = {}
    for entry in data.get("guardrails", []):
        guardrails[entry["id"]] = entry
    return guardrails


_GUARDRAILS = _load_guardrails()


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass
class GuardrailContext:
    surface: str
    action: str
    metadata: Dict[str, Any]
    agent_id: str
    intent_id: str


def evaluate_guardrail(context: GuardrailContext) -> Tuple[PolicyDecision, str, Optional[str]]:
    """Evaluate guardrail decision for a proposed action."""

    for guardrail_id, cfg in _GUARDRAILS.items():
        if cfg.get("surface") != context.surface:
            continue
        prohibited = cfg.get("prohibited_actions", [])
        if context.action in prohibited:
            decision = PolicyDecision(cfg.get("default_decision", PolicyDecision.DENY))
            rationale = f"Guardrail {guardrail_id}: {cfg.get('rationale')}"
            return decision, rationale, guardrail_id
    return PolicyDecision.ALLOW, "No guardrail matched", None
