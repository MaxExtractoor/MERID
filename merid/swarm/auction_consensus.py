"""Auction-Style Consensus — Sprint R.

When the standard weighted-vote consensus is CONFLICTED (high disagreement),
this module runs a second-pass auction where agents can raise their "stakes"
by committing confidence capital. Agents with stronger conviction and better
track records can escalate their influence.

Mechanism:
1. Each conflicted proposal gets an auction round
2. Agents submit "bids" — higher bid = more conviction
3. Bids are weighted by agent's calibration score (Brier weight)
4. Winner(s) set the consensus direction, but only if total bid
   exceeds a minimum threshold (prevents weak resolution)
5. If no resolution → consensus stays CONFLICTED (no forced decision)

Usage::

    resolver = get_auction_resolver()
    result = resolver.resolve_conflict(
        proposals=[p1, p2, p3],
        asset="BTC", timeframe="15m",
    )
    if result.resolved:
        # Use result.winning_direction, result.winning_probability
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.swarm.auction_consensus")


@dataclass
class AuctionBid:
    """A single agent's bid in the auction round."""
    agent_id: str
    direction: str          # "yes" or "no"
    conviction: float       # 0.0–1.0 (how much confidence they stake)
    probability: float      # Their predicted probability
    edge_estimate: float    # Their edge estimate
    calibration_weight: float = 1.0  # From Brier/calibration store

    @property
    def effective_bid(self) -> float:
        """Bid strength = conviction × calibration_weight."""
        return self.conviction * self.calibration_weight


@dataclass
class AuctionResult:
    """Outcome of the auction consensus round."""
    resolved: bool
    winning_direction: str        # "yes", "no", or "neutral" if unresolved
    winning_probability: float
    winning_confidence: float
    total_yes_bid: float
    total_no_bid: float
    num_bidders: int
    rounds: int
    reason: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved": self.resolved,
            "winning_direction": self.winning_direction,
            "winning_probability": round(self.winning_probability, 4),
            "winning_confidence": round(self.winning_confidence, 3),
            "total_yes_bid": round(self.total_yes_bid, 3),
            "total_no_bid": round(self.total_no_bid, 3),
            "num_bidders": self.num_bidders,
            "rounds": self.rounds,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# Thresholds
_MIN_TOTAL_BID = 1.5         # Minimum combined bid strength to resolve
_MIN_MARGIN = 0.20           # Winning side must have 20% margin over losing
_MAX_ROUNDS = 3              # Maximum escalation rounds


class AuctionConsensusResolver:
    """Resolves conflicted consensus via auction mechanism.

    When ``SwarmConsensusAggregator`` produces a CONFLICTED status,
    this resolver can be invoked to run an auction round that gives
    higher-conviction, better-calibrated agents more influence.
    """

    def __init__(self):
        self._history: List[AuctionResult] = []
        self._max_history = 200
        self._resolved_count = 0
        self._unresolved_count = 0

    def resolve_conflict(
        self,
        proposals: list,
        asset: str,
        timeframe: str,
    ) -> AuctionResult:
        """Run auction consensus on conflicted proposals.

        Args:
            proposals: List of AgentProposal objects from the aggregator
            asset: Asset identifier
            timeframe: Timeframe identifier

        Returns:
            AuctionResult with resolution outcome
        """
        if not proposals:
            result = AuctionResult(
                resolved=False,
                winning_direction="neutral",
                winning_probability=0.5,
                winning_confidence=0.0,
                total_yes_bid=0.0,
                total_no_bid=0.0,
                num_bidders=0,
                rounds=0,
                reason="No proposals to resolve",
            )
            self._record(result)
            return result

        # Convert proposals to auction bids
        bids = self._proposals_to_bids(proposals)

        # Run escalation rounds
        for round_num in range(1, _MAX_ROUNDS + 1):
            yes_bids = [b for b in bids if b.direction == "yes"]
            no_bids = [b for b in bids if b.direction == "no"]

            total_yes = sum(b.effective_bid for b in yes_bids)
            total_no = sum(b.effective_bid for b in no_bids)
            total = total_yes + total_no

            if total < _MIN_TOTAL_BID:
                # Not enough conviction on either side
                continue

            # Check if one side has decisive margin
            if total > 0:
                yes_share = total_yes / total
                no_share = total_no / total

                if yes_share - no_share >= _MIN_MARGIN:
                    # YES wins
                    prob = self._weighted_probability(yes_bids)
                    confidence = min(0.9, yes_share * 0.9)
                    result = AuctionResult(
                        resolved=True,
                        winning_direction="yes",
                        winning_probability=prob,
                        winning_confidence=confidence,
                        total_yes_bid=total_yes,
                        total_no_bid=total_no,
                        num_bidders=len(bids),
                        rounds=round_num,
                        reason=f"YES won auction ({yes_share:.0%} vs {no_share:.0%}), "
                               f"margin={yes_share - no_share:.0%}",
                    )
                    self._record(result)
                    return result

                elif no_share - yes_share >= _MIN_MARGIN:
                    # NO wins
                    prob = self._weighted_probability(no_bids)
                    confidence = min(0.9, no_share * 0.9)
                    result = AuctionResult(
                        resolved=True,
                        winning_direction="no",
                        winning_probability=prob,
                        winning_confidence=confidence,
                        total_yes_bid=total_yes,
                        total_no_bid=total_no,
                        num_bidders=len(bids),
                        rounds=round_num,
                        reason=f"NO won auction ({no_share:.0%} vs {yes_share:.0%}), "
                               f"margin={no_share - yes_share:.0%}",
                    )
                    self._record(result)
                    return result

            # Escalation: increase conviction of agents with better calibration
            if round_num < _MAX_ROUNDS:
                for bid in bids:
                    if bid.calibration_weight > 1.0:
                        bid.conviction = min(1.0, bid.conviction * 1.2)

        # No resolution after max rounds
        total_yes = sum(b.effective_bid for b in bids if b.direction == "yes")
        total_no = sum(b.effective_bid for b in bids if b.direction == "no")
        result = AuctionResult(
            resolved=False,
            winning_direction="neutral",
            winning_probability=0.5,
            winning_confidence=0.0,
            total_yes_bid=total_yes,
            total_no_bid=total_no,
            num_bidders=len(bids),
            rounds=_MAX_ROUNDS,
            reason=f"Auction unresolved after {_MAX_ROUNDS} rounds "
                   f"(yes={total_yes:.2f}, no={total_no:.2f})",
        )
        self._record(result)
        return result

    def _proposals_to_bids(self, proposals: list) -> List[AuctionBid]:
        """Convert AgentProposals to AuctionBids with calibration weights."""
        bids = []
        for p in proposals:
            # Get calibration weight
            cal_weight = 1.0
            try:
                from merid.metrics.calibration import get_calibration_store
                cal = get_calibration_store()
                bucket = (getattr(p, "asset", None) or "unknown").lower()
                cal_weight = cal.get_weight(
                    getattr(p, "agent_id", "unknown"), bucket
                )
            except Exception:
                pass

            direction = getattr(p, "direction", "neutral")
            if direction == "neutral":
                continue  # Neutral agents don't bid

            bids.append(AuctionBid(
                agent_id=getattr(p, "agent_id", "unknown"),
                direction=direction,
                conviction=getattr(p, "confidence", 0.5),
                probability=getattr(p, "probability", 0.5),
                edge_estimate=getattr(p, "edge_estimate", 0.0),
                calibration_weight=cal_weight,
            ))

        return bids

    def _weighted_probability(self, bids: List[AuctionBid]) -> float:
        """Compute bid-weighted average probability."""
        if not bids:
            return 0.5
        total_weight = sum(b.effective_bid for b in bids)
        if total_weight <= 0:
            return 0.5
        weighted = sum(b.probability * b.effective_bid for b in bids) / total_weight
        return max(0.02, min(0.98, weighted))

    def _record(self, result: AuctionResult) -> None:
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        if result.resolved:
            self._resolved_count += 1
        else:
            self._unresolved_count += 1

    @property
    def stats(self) -> Dict[str, Any]:
        total = self._resolved_count + self._unresolved_count
        return {
            "total_auctions": total,
            "resolved": self._resolved_count,
            "unresolved": self._unresolved_count,
            "resolution_rate": round(
                self._resolved_count / total, 3
            ) if total > 0 else 0.0,
        }

    @property
    def history(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history[-50:]]


# ── Singleton ────────────────────────────────────────────────────────────

_resolver: Optional[AuctionConsensusResolver] = None


def get_auction_resolver() -> AuctionConsensusResolver:
    """Get or create the singleton AuctionConsensusResolver."""
    global _resolver
    if _resolver is None:
        _resolver = AuctionConsensusResolver()
    return _resolver
