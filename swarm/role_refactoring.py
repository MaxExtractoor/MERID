"""
Automatic role refactoring and consolidation utilities.

Analyzes overlapping responsibilities, performance metrics, and capability
scores to propose merges/splits for swarm agent roles. Designed to ensure the
agent graph stays lean while MERID scales.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import logging
import statistics


logger = logging.getLogger(__name__)


@dataclass
class RoleSnapshot:
    """Current view of a role."""

    role_id: str
    name: str
    responsibilities: List[str]
    reliability: float
    load_factor: float
    duplicate_of: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)


@dataclass
class RefactorProposal:
    """Suggested merge/split operation."""

    proposal_id: str
    created_at: datetime
    action: str  # merge, split, retire
    roles_involved: List[str]
    justification: str
    projected_savings: float
    risk_score: float


class RoleRefactoringEngine:
    """Generate and track refactor proposals."""

    def __init__(self) -> None:
        self._roles: Dict[str, RoleSnapshot] = {}
        self._proposals: List[RefactorProposal] = []

    def register_role(self, snapshot: RoleSnapshot) -> None:
        self._roles[snapshot.role_id] = snapshot
        logger.info("Registered role snapshot %s (%s)", snapshot.role_id, snapshot.name)

    def propose_refactors(self, reliability_floor: float = 0.6) -> List[RefactorProposal]:
        """Analyze roles and create proposals for duplicates or underperformers."""
        self._proposals.clear()
        roles = list(self._roles.values())
        for i, role_a in enumerate(roles):
            for role_b in roles[i + 1 :]:
                overlap = self._responsibility_overlap(role_a, role_b)
                if overlap >= 0.7:
                    justification = (
                        f"{role_a.name} and {role_b.name} overlap {overlap:.0%} "
                        "and share similar metrics."
                    )
                    proposal = RefactorProposal(
                        proposal_id=f"merge_{role_a.role_id}_{role_b.role_id}",
                        created_at=datetime.utcnow(),
                        action="merge",
                        roles_involved=[role_a.role_id, role_b.role_id],
                        justification=justification,
                        projected_savings=self._project_savings(role_a, role_b),
                        risk_score=self._risk_score([role_a, role_b]),
                    )
                    self._proposals.append(proposal)

        # Identify underperforming roles to retire or split
        for role in roles:
            if role.reliability < reliability_floor:
                action = "split" if role.load_factor > 0.8 else "retire"
                justification = (
                    f"{role.name} reliability {role.reliability:.2f} below floor {reliability_floor}"
                )
                proposal = RefactorProposal(
                    proposal_id=f"{action}_{role.role_id}",
                    created_at=datetime.utcnow(),
                    action=action,
                    roles_involved=[role.role_id],
                    justification=justification,
                    projected_savings=max(0.1, 1.0 - role.reliability),
                    risk_score=0.2,
                )
                self._proposals.append(proposal)
        logger.info("Generated %d role refactor proposals", len(self._proposals))
        return self._proposals

    def get_proposals(self) -> List[RefactorProposal]:
        return list(self._proposals)

    def _responsibility_overlap(self, role_a: RoleSnapshot, role_b: RoleSnapshot) -> float:
        set_a = set(role_a.responsibilities)
        set_b = set(role_b.responsibilities)
        if not set_a and not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def _project_savings(self, role_a: RoleSnapshot, role_b: RoleSnapshot) -> float:
        return (role_a.load_factor + role_b.load_factor) / 2

    def _risk_score(self, roles: List[RoleSnapshot]) -> float:
        reliability = [role.reliability for role in roles]
        variance = statistics.pvariance(reliability) if len(reliability) > 1 else 0.0
        return min(1.0, 0.3 + variance)


_role_refactoring_engine: Optional[RoleRefactoringEngine] = None


def get_role_refactoring_engine() -> RoleRefactoringEngine:
    global _role_refactoring_engine
    if _role_refactoring_engine is None:
        _role_refactoring_engine = RoleRefactoringEngine()
    return _role_refactoring_engine
