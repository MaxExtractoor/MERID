"""
Cross-network agent discovery service.

Indexes external registries (AgentConnect, ANP, custom DIDs) and syncs metadata
into the collaborative swarm registry with trust filters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class ExternalAgentRecord:
    source: str
    did: str
    capabilities: List[str]
    trust_score: float
    last_seen: datetime


class CrossNetworkDiscovery:
    def __init__(self, min_trust: float = 0.4) -> None:
        self.min_trust = min_trust
        self._external_agents: Dict[str, ExternalAgentRecord] = {}

    def ingest(self, record: ExternalAgentRecord) -> None:
        if record.trust_score < self.min_trust:
            return
        key = f"{record.source}:{record.did}"
        self._external_agents[key] = record

    def list_agents(self, capability_filter: List[str] | None = None) -> List[ExternalAgentRecord]:
        agents = list(self._external_agents.values())
        if capability_filter:
            agents = [agent for agent in agents if set(capability_filter).issubset(set(agent.capabilities))]
        return sorted(agents, key=lambda rec: rec.trust_score, reverse=True)
