"""
Community-run indexing infrastructure scaffolding.

Models independent indexer nodes that replicate on-chain/state data and expose
GraphQL-like APIs. Tracks uptime and reward credits to ensure decentralization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class IndexerNode:
    node_id: str
    operator: str
    uptime_percent: float = 100.0
    last_sync: datetime = field(default_factory=datetime.utcnow)
    reward_credits: float = 0.0


class CommunityIndexingInfrastructure:
    def __init__(self) -> None:
        self._nodes: Dict[str, IndexerNode] = {}
        self._api_endpoints: Dict[str, str] = {}

    def register_node(self, node_id: str, operator: str, endpoint: str) -> None:
        self._nodes[node_id] = IndexerNode(node_id=node_id, operator=operator)
        self._api_endpoints[node_id] = endpoint

    def record_sync(self, node_id: str, uptime_percent: float) -> None:
        node = self._nodes[node_id]
        node.last_sync = datetime.utcnow()
        node.uptime_percent = uptime_percent
        node.reward_credits += uptime_percent / 100
