"""
Dynamic network policy adjustment engine.

Observes agent traffic, compliance flags, and risk levels to automatically
tighten or relax network policies (e.g., allowed proxy tiers, latency caps).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict
from datetime import datetime


@dataclass
class NetworkPolicyState:
    agent_id: str
    sensitivity: str
    max_latency_ms: int
    allowed_proxy_types: list[str]
    last_updated: datetime = field(default_factory=datetime.utcnow)


class DynamicNetworkPolicyEngine:
    def __init__(self) -> None:
        self._policies: Dict[str, NetworkPolicyState] = {}

    def record_event(self, agent_id: str, latency_ms: float, violations: int) -> NetworkPolicyState:
        policy = self._policies.setdefault(
            agent_id,
            NetworkPolicyState(agent_id=agent_id, sensitivity="PUBLIC", max_latency_ms=1000, allowed_proxy_types=["http", "https", "vpn"]),
        )
        if latency_ms > policy.max_latency_ms:
            policy.max_latency_ms = int(latency_ms * 1.1)
        if violations > 0:
            policy.sensitivity = "CRITICAL"
            policy.allowed_proxy_types = ["direct"]
        policy.last_updated = datetime.utcnow()
        return policy

    def get_policy(self, agent_id: str) -> NetworkPolicyState | None:
        return self._policies.get(agent_id)
