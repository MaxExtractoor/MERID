"""
Governance delegation and liquid democracy scaffolding.

Tracks delegations, voting power, and recursive delegate chains with cycle
prevention. Provides snapshots that governance UI/analytics can consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set


@dataclass
class Delegation:
    delegator: str
    delegatee: str
    voting_power: float


class GovernanceDelegationGraph:
    def __init__(self) -> None:
        self._delegations: Dict[str, Delegation] = {}

    def delegate(self, delegator: str, delegatee: str, voting_power: float) -> None:
        if self._creates_cycle(delegator, delegatee):
            raise ValueError("Delegation cycle detected")
        self._delegations[delegator] = Delegation(delegator, delegatee, voting_power)

    def get_effective_delegate(self, delegator: str) -> Optional[str]:
        seen: Set[str] = set()
        current = delegator
        while current in self._delegations:
            delegation = self._delegations[current]
            if delegation.delegatee in seen:
                break
            seen.add(current)
            current = delegation.delegatee
        return current if current != delegator else None

    def _creates_cycle(self, delegator: str, delegatee: str) -> bool:
        current = delegatee
        while current in self._delegations:
            if self._delegations[current].delegatee == delegator:
                return True
            current = self._delegations[current].delegatee
        return False
