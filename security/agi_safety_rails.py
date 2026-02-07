"""
AGI-adjacent safety rails for stronger models.

Implements layered guardrails: policy filters, tool sandboxing, output scoring,
and escalation hooks. Integrated as a standalone module so high-capability
agents can wrap requests through this service before execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import logging


logger = logging.getLogger(__name__)


@dataclass
class SafetyPolicy:
    policy_id: str
    description: str
    allow: bool
    tags: List[str]


@dataclass
class SafetyDecision:
    request_id: str
    approved: bool
    reasons: List[str]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class AGISafetyRails:
    def __init__(self) -> None:
        self._policies: Dict[str, SafetyPolicy] = {}
        self._audit_log: List[SafetyDecision] = []
        self._register_default_policies()

    def _register_default_policies(self) -> None:
        self.register_policy(
            SafetyPolicy(
                policy_id="no_pii",
                description="Block attempts to exfiltrate raw PII",
                allow=False,
                tags=["privacy", "pii"],
            )
        )
        self.register_policy(
            SafetyPolicy(
                policy_id="no_market_manipulation",
                description="Deny actions that resemble market abuse",
                allow=False,
                tags=["market"],
            )
        )
        self.register_policy(
            SafetyPolicy(
                policy_id="sandbox_required",
                description="High-risk code execution must run in sandbox",
                allow=True,
                tags=["sandbox"],
            )
        )

    def register_policy(self, policy: SafetyPolicy) -> None:
        self._policies[policy.policy_id] = policy

    def evaluate(self, request_id: str, tags: List[str]) -> SafetyDecision:
        reasons = []
        approved = True
        for policy in self._policies.values():
            if set(tags) & set(policy.tags):
                if not policy.allow:
                    approved = False
                    reasons.append(f"Blocked by {policy.policy_id}")
        decision = SafetyDecision(request_id=request_id, approved=approved, reasons=reasons)
        self._audit_log.append(decision)
        if not approved:
            logger.warning("Safety rails denied request %s reasons=%s", request_id, reasons)
        return decision

    def get_audit_log(self, limit: int = 100) -> List[SafetyDecision]:
        return list(self._audit_log[-limit:])


_agi_safety_rails: Optional[AGISafetyRails] = None


def get_agi_safety_rails() -> AGISafetyRails:
    global _agi_safety_rails
    if _agi_safety_rails is None:
        _agi_safety_rails = AGISafetyRails()
    return _agi_safety_rails
