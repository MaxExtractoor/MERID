"""
Decentralized signing service network scaffolding.

Models multiple signer nodes that collectively authorize transactions using
threshold policies. Keeps audit logs of participation for slashing/governance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime
import hashlib


@dataclass
class SigningNode:
    node_id: str
    stake: float
    public_key: str
    active: bool = True
    last_participation: datetime = field(default_factory=datetime.utcnow)


class DecentralizedSigningService:
    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self._nodes: Dict[str, SigningNode] = {}
        self._signatures: List[Dict[str, object]] = []

    def register_node(self, node_id: str, stake: float, public_key: str) -> None:
        self._nodes[node_id] = SigningNode(node_id=node_id, stake=stake, public_key=public_key)

    def cosign(self, node_id: str, payload: str) -> str:
        node = self._nodes[node_id]
        node.last_participation = datetime.utcnow()
        signature = hashlib.sha256((payload + node.public_key).encode()).hexdigest()
        self._signatures.append({"node_id": node_id, "payload": payload, "signature": signature, "timestamp": node.last_participation.isoformat()})
        return signature

    def get_threshold(self) -> int:
        return self.threshold
