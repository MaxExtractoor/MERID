"""
Decentralized AI node network with staking + slashing primitives.

This module supervises community-operated AI nodes, enforces stake-backed
participation, and records infra metrics that can drive sovereign deployment
decisions. It simulates the control plane for a future on-chain slashing
contract by providing deterministic accounting hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import logging


logger = logging.getLogger(__name__)


@dataclass
class AINode:
    node_id: str
    operator: str
    stake_amount: float
    status: str = "active"  # active|slashed|offline
    reputation: float = 1.0
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    total_tasks: int = 0
    failed_tasks: int = 0


class DecentralizedAINetwork:
    """Manage AI nodes, stakes, and slashing events."""

    def __init__(self, min_stake: float = 1_000.0, slash_ratio: float = 0.25) -> None:
        self.min_stake = min_stake
        self.slash_ratio = slash_ratio
        self._nodes: Dict[str, AINode] = {}
        self._slashing_events: List[Dict[str, object]] = []

    def register_node(self, node_id: str, operator: str, stake_amount: float) -> AINode:
        if stake_amount < self.min_stake:
            raise ValueError("Insufficient stake for registration")
        node = AINode(node_id=node_id, operator=operator, stake_amount=stake_amount)
        self._nodes[node_id] = node
        logger.info("Registered AI node %s with stake %.2f", node_id, stake_amount)
        return node

    def record_task_result(self, node_id: str, success: bool) -> None:
        node = self._nodes[node_id]
        node.total_tasks += 1
        node.last_heartbeat = datetime.utcnow()
        if not success:
            node.failed_tasks += 1
            failure_rate = node.failed_tasks / node.total_tasks
            if failure_rate > 0.15:
                self._slash(node, reason="excessive_failures")
        else:
            node.reputation = min(1.0, node.reputation + 0.01)

    def get_network_state(self) -> Dict[str, object]:
        return {
            "nodes": list(self._nodes.values()),
            "active_nodes": len([n for n in self._nodes.values() if n.status == "active"]),
            "slashing_events": self._slashing_events[-10:],
        }

    def _slash(self, node: AINode, reason: str) -> None:
        penalty = node.stake_amount * self.slash_ratio
        node.stake_amount -= penalty
        node.status = "slashed"
        event = {
            "node_id": node.node_id,
            "operator": node.operator,
            "penalty": penalty,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._slashing_events.append(event)
        logger.warning("Slashed node %s for %s penalty %.2f", node.node_id, reason, penalty)


_decentralized_ai_network: Optional[DecentralizedAINetwork] = None


def get_decentralized_ai_network() -> DecentralizedAINetwork:
    global _decentralized_ai_network
    if _decentralized_ai_network is None:
        _decentralized_ai_network = DecentralizedAINetwork()
    return _decentralized_ai_network
