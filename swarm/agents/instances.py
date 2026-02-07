from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from .charters import AgentCharter


@dataclass
class AgentInstance:
    """Runtime representation of an agent spawned from a charter."""

    charter: AgentCharter
    parent_id: Optional[str] = None
    instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    current_score: float = 1.0
    last_active: float = field(default_factory=lambda: time.time())
    lineage: List[str] = field(default_factory=list)
    active: bool = True

    def __post_init__(self) -> None:
        if not self.lineage:
            self.lineage = [self.instance_id]

    @property
    def role(self) -> str:
        return self.charter.role.value

    def inherit_from_parent(self, parent: "AgentInstance") -> None:
        self.parent_id = parent.instance_id
        self.current_score = max(0.1, parent.current_score * 0.8)
        self.lineage = parent.lineage + [self.instance_id]

    def record_activity(self, reward: float = 0.05) -> None:
        self.last_active = time.time()
        self.current_score = min(1.5, self.current_score + reward)
        self.active = True

    def apply_decay(self, current_time: Optional[float] = None) -> None:
        if current_time is None:
            current_time = time.time()
        inactive_time = max(0.0, current_time - self.last_active)
        if inactive_time <= 0:
            return
        hours = inactive_time / 3600.0
        decay_rate = self.charter.decay_rate or 0.02
        self.current_score *= math.exp(-decay_rate * hours)
        if self.current_score < 0.3:
            self.active = False

    def to_dict(self) -> dict:
        return {
            "instance_id": self.instance_id,
            "parent_id": self.parent_id,
            "role": self.role,
            "charter": self.charter.to_dict(),
            "current_score": round(self.current_score, 4),
            "last_active": self.last_active,
            "active": self.active,
            "lineage": list(self.lineage),
        }
