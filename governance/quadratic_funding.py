"""Quadratic funding primitives for MERID governance."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("governance.quadratic_funding")


class ProposalStatus(Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    FUNDED = "funded"
    DEFUNDED = "defunded"


class RoundStatus(Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    FINALIZED = "finalized"


@dataclass
class Proposal:
    proposal_id: str
    title: str
    description: str
    requested_budget_usd: float
    target_swarm: str
    tags: List[str] = field(default_factory=list)
    owner: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: ProposalStatus = ProposalStatus.DRAFT
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Contribution:
    contributor_id: str
    amount_usd: float
    contributed_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QuadraticFundingRound:
    round_id: str
    matching_pool_usd: float
    proposal_ids: List[str]
    status: RoundStatus = RoundStatus.PLANNED
    created_at: datetime = field(default_factory=datetime.utcnow)
    contributions: Dict[str, List[Contribution]] = field(default_factory=dict)
    finalized_results: Dict[str, Dict[str, float]] = field(default_factory=dict)
    governance_notes: List[str] = field(default_factory=list)

    def add_contribution(
        self,
        proposal_id: str,
        contribution: Contribution,
    ) -> None:
        if proposal_id not in self.proposal_ids:
            raise ValueError(f"Proposal {proposal_id} not part of round {self.round_id}")
        if contribution.amount_usd <= 0:
            raise ValueError("Contribution amount must be positive")
        self.contributions.setdefault(proposal_id, []).append(contribution)


class QuadraticFundingProgram:
    """Coordinator for quadratic funding proposals and rounds."""

    def __init__(self) -> None:
        self._proposals: Dict[str, Proposal] = {}
        self._rounds: Dict[str, QuadraticFundingRound] = {}
        self._next_proposal_id = 1
        self._next_round_id = 1

    # ------------------------------------------------------------------
    # Proposal management
    # ------------------------------------------------------------------

    def register_proposal(
        self,
        title: str,
        description: str,
        requested_budget_usd: float,
        target_swarm: str,
        tags: Optional[List[str]] = None,
        owner: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Proposal:
        proposal_id = f"prop_{self._next_proposal_id}"
        self._next_proposal_id += 1
        proposal = Proposal(
            proposal_id=proposal_id,
            title=title,
            description=description,
            requested_budget_usd=requested_budget_usd,
            target_swarm=target_swarm,
            tags=tags or [],
            owner=owner,
            metadata=metadata or {},
            status=ProposalStatus.ACTIVE,
        )
        self._proposals[proposal_id] = proposal
        logger.info("Registered proposal %s for swarm %s", proposal_id, target_swarm)
        return proposal

    def list_proposals(
        self,
        status: Optional[ProposalStatus] = None,
    ) -> List[Proposal]:
        proposals = list(self._proposals.values())
        if status is not None:
            proposals = [p for p in proposals if p.status == status]
        return proposals

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        return self._proposals.get(proposal_id)

    # ------------------------------------------------------------------
    # Round management
    # ------------------------------------------------------------------

    def start_round(
        self,
        matching_pool_usd: float,
        proposal_ids: Optional[List[str]] = None,
    ) -> QuadraticFundingRound:
        if matching_pool_usd <= 0:
            raise ValueError("Matching pool must be positive")
        proposal_ids = proposal_ids or [p.proposal_id for p in self.list_proposals(ProposalStatus.ACTIVE)]
        for proposal_id in proposal_ids:
            if proposal_id not in self._proposals:
                raise ValueError(f"Unknown proposal {proposal_id}")
        round_id = f"round_{self._next_round_id}"
        self._next_round_id += 1
        round_obj = QuadraticFundingRound(
            round_id=round_id,
            matching_pool_usd=matching_pool_usd,
            proposal_ids=proposal_ids,
            status=RoundStatus.ACTIVE,
        )
        self._rounds[round_id] = round_obj
        logger.info("Started quadratic funding round %s with pool %.2f", round_id, matching_pool_usd)
        return round_obj

    def list_rounds(self, status: Optional[RoundStatus] = None) -> List[QuadraticFundingRound]:
        rounds = list(self._rounds.values())
        if status is not None:
            rounds = [r for r in rounds if r.status == status]
        rounds.sort(key=lambda r: r.created_at, reverse=True)
        return rounds

    def get_round(self, round_id: str) -> Optional[QuadraticFundingRound]:
        return self._rounds.get(round_id)

    def record_contribution(
        self,
        round_id: str,
        proposal_id: str,
        contributor_id: str,
        amount_usd: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Contribution:
        round_obj = self._require_round(round_id)
        if round_obj.status != RoundStatus.ACTIVE:
            raise ValueError(f"Round {round_id} is not active")
        contribution = Contribution(
            contributor_id=contributor_id,
            amount_usd=amount_usd,
            metadata=metadata or {},
        )
        round_obj.add_contribution(proposal_id, contribution)
        logger.info(
            "Recorded contribution %.2f for proposal %s in round %s",
            amount_usd,
            proposal_id,
            round_id,
        )
        return contribution

    def finalize_round(
        self,
        round_id: str,
        governance_notes: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, float]]:
        round_obj = self._require_round(round_id)
        if round_obj.status == RoundStatus.FINALIZED:
            return round_obj.finalized_results
        raw_matches: Dict[str, float] = {}
        total_weight = 0.0
        for proposal_id in round_obj.proposal_ids:
            contributions = round_obj.contributions.get(proposal_id, [])
            match_value = self._quadratic_match(contributions)
            raw_matches[proposal_id] = match_value
            total_weight += match_value
        payouts: Dict[str, Dict[str, float]] = {}
        for proposal_id in round_obj.proposal_ids:
            contributions = round_obj.contributions.get(proposal_id, [])
            direct = sum(c.amount_usd for c in contributions)
            if total_weight > 0:
                match_share = raw_matches[proposal_id] / total_weight
                matched = match_share * round_obj.matching_pool_usd
            else:
                matched = 0.0
            allocated = direct + matched
            payouts[proposal_id] = {
                "direct_usd": round(direct, 2),
                "matched_usd": round(matched, 2),
                "total_usd": round(allocated, 2),
                "supporters": len(contributions),
            }
            if matched > 0 and direct > 0:
                self._proposals[proposal_id].status = ProposalStatus.FUNDED
        round_obj.finalized_results = payouts
        round_obj.status = RoundStatus.FINALIZED
        if governance_notes:
            round_obj.governance_notes.extend(governance_notes)

        summary = self._summarize_round(round_obj)
        self._record_board_summary(summary)

        logger.info("Finalized round %s with %d funded proposals", round_id, len(payouts))
        return payouts

    def summarize_rounds(
        self,
        status: Optional[RoundStatus] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        rounds = self.list_rounds(status=status)
        if limit is not None:
            rounds = rounds[:limit]
        return [self._summarize_round(round_obj) for round_obj in rounds]

    def summary_for_round(self, round_id: str) -> Dict[str, Any]:
        round_obj = self._require_round(round_id)
        return self._summarize_round(round_obj)

    def proposal_support(self, proposal_id: str) -> Dict[str, Any]:
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Unknown proposal {proposal_id}")
        supporter_counts = []
        direct_total = 0.0
        for round_obj in self._rounds.values():
            contributions = round_obj.contributions.get(proposal_id, [])
            if not contributions:
                continue
            direct = sum(c.amount_usd for c in contributions)
            direct_total += direct
            supporter_counts.append(len(contributions))
        return {
            "proposal_id": proposal_id,
            "title": proposal.title,
            "target_swarm": proposal.target_swarm,
            "total_direct_usd": round(direct_total, 2),
            "total_supporters": sum(supporter_counts),
            "status": proposal.status.value,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _quadratic_match(contributions: List[Contribution]) -> float:
        if not contributions:
            return 0.0
        sum_sqrt = sum(c.amount_usd ** 0.5 for c in contributions)
        raw = sum_sqrt ** 2
        direct = sum(c.amount_usd for c in contributions)
        match = raw - direct
        return max(match, 0.0)

    def _require_round(self, round_id: str) -> QuadraticFundingRound:
        round_obj = self._rounds.get(round_id)
        if not round_obj:
            raise ValueError(f"Unknown round {round_id}")
        return round_obj

    def _summarize_round(self, round_obj: QuadraticFundingRound) -> Dict[str, Any]:
        breakdown: List[Dict[str, Any]] = []
        total_direct = 0.0
        total_matched = 0.0
        if round_obj.status == RoundStatus.FINALIZED and round_obj.finalized_results:
            for proposal_id in round_obj.proposal_ids:
                contributions = round_obj.contributions.get(proposal_id, [])
                direct = sum(c.amount_usd for c in contributions)
                result = round_obj.finalized_results.get(proposal_id, {})
                matched = result.get("matched_usd", 0.0)
                total = result.get("total_usd", direct + matched)
                breakdown.append(
                    {
                        "proposal_id": proposal_id,
                        "direct_usd": round(direct, 2),
                        "matched_usd": round(matched, 2),
                        "total_usd": round(total, 2),
                        "supporters": len(contributions),
                    }
                )
                total_direct += direct
                total_matched += matched
        else:
            raw_matches: Dict[str, float] = {}
            for proposal_id in round_obj.proposal_ids:
                contributions = round_obj.contributions.get(proposal_id, [])
                raw_matches[proposal_id] = self._quadratic_match(contributions)
            total_weight = sum(raw_matches.values())
            for proposal_id in round_obj.proposal_ids:
                contributions = round_obj.contributions.get(proposal_id, [])
                direct = sum(c.amount_usd for c in contributions)
                projected_match = (
                    round_obj.matching_pool_usd * (raw_matches[proposal_id] / total_weight)
                    if total_weight > 0 else 0.0
                )
                breakdown.append(
                    {
                        "proposal_id": proposal_id,
                        "direct_usd": round(direct, 2),
                        "matched_usd": round(projected_match, 2),
                        "total_usd": round(direct + projected_match, 2),
                        "supporters": len(contributions),
                        "projected": True,
                    }
                )
                total_direct += direct
                total_matched += projected_match
        return {
            "round_id": round_obj.round_id,
            "status": round_obj.status.value,
            "matching_pool_usd": round(round_obj.matching_pool_usd, 2),
            "total_direct_usd": round(total_direct, 2),
            "total_matched_usd": round(total_matched, 2),
            "total_allocated_usd": round(total_direct + total_matched, 2),
            "proposal_breakdown": breakdown,
            "governance_notes": list(round_obj.governance_notes),
            "created_at": round_obj.created_at.isoformat(),
        }

    @staticmethod
    def _record_board_summary(summary: Dict[str, Any]) -> None:
        try:
            from governance.board_reporting import get_board_reporting_framework

            framework = get_board_reporting_framework()
            framework.record_public_goods_round(summary)
        except Exception:
            logger.exception("Failed to record board summary for round %s", summary.get("round_id"))


_program: Optional[QuadraticFundingProgram] = None


def get_quadratic_funding_program() -> QuadraticFundingProgram:
    global _program
    if _program is None:
        _program = QuadraticFundingProgram()
    return _program


def reset_quadratic_funding_program() -> QuadraticFundingProgram:
    """Reset the global quadratic funding program (primarily for tests)."""
    global _program
    _program = QuadraticFundingProgram()
    return _program
