"""Stage 6 consensus math with source-aware weighted voting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger("core.consensus")


@dataclass
class Vote:
    """A single agent vote with trust and confidence."""

    agent_id: str
    vote: int  # +1 or -1
    trust: float  # Agent trust [0.5, 2.0]
    confidence: float  # Energy confidence_final [0, 1]
    source: str  # Source name
    source_srw: float  # Source reliability weight at vote time


@dataclass
class ConsensusResult:
    """Outcome of consensus computation."""

    consensus_score: float  # Weighted consensus [-1, 1]
    approved: bool  # Whether consensus threshold met
    vote_count: int
    avg_source_srw: float
    fallback_ratio: float
    total_weight: float

    def to_dict(self) -> dict:
        """Serialize for storage."""
        return {
            "consensus_score": round(self.consensus_score, 4),
            "approved": self.approved,
            "vote_count": self.vote_count,
            "avg_source_srw": round(self.avg_source_srw, 4),
            "fallback_ratio": round(self.fallback_ratio, 4),
            "total_weight": round(self.total_weight, 4),
        }


def compute_consensus(
    votes: List[Vote],
    threshold: float = 0.6,
) -> ConsensusResult:
    """
    Compute weighted consensus using Stage 6 formula:
    
    weighted_vote_i = vote_i × trust_i × confidence_i
    consensus_score = sum(weighted_vote_i) / sum(|weighted_vote_i|)
    approved = consensus_score ≥ threshold
    """
    if not votes:
        return ConsensusResult(
            consensus_score=0.0,
            approved=False,
            vote_count=0,
            avg_source_srw=0.0,
            fallback_ratio=0.0,
            total_weight=0.0,
        )

    weighted_votes = []
    abs_weights = []
    srw_sum = 0.0
    fallback_count = 0

    for v in votes:
        # Weighted vote
        weighted = v.vote * v.trust * v.confidence
        weighted_votes.append(weighted)
        abs_weights.append(abs(weighted))
        srw_sum += v.source_srw

        # Track fallback usage (approximated by low SRW)
        if v.source_srw < 0.7:
            fallback_count += 1

    total_weight = sum(abs_weights)
    consensus_score = sum(weighted_votes) / total_weight if total_weight > 0 else 0.0
    approved = consensus_score >= threshold

    avg_source_srw = srw_sum / len(votes)
    fallback_ratio = fallback_count / len(votes)

    logger.debug(
        "Consensus computed: score=%.3f, approved=%s, votes=%d, avg_srw=%.3f",
        consensus_score,
        approved,
        len(votes),
        avg_source_srw,
    )

    return ConsensusResult(
        consensus_score=consensus_score,
        approved=approved,
        vote_count=len(votes),
        avg_source_srw=avg_source_srw,
        fallback_ratio=fallback_ratio,
        total_weight=total_weight,
    )
