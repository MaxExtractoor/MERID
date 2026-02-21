"""
Task Auction — market-style bidding for agent task priority.

When multiple agents compete for limited execution slots, each agent
submits a bid (credits + confidence). The auction allocates tasks to
the highest-value bidders, enforcing budget constraints.

Usage:
    from core.task_auction import TaskAuction, TaskBid
    auction = TaskAuction(max_concurrent=3)
    auction.submit_bid(TaskBid(agent_id="researcher", task_id="t1", credits=10, confidence=0.9))
    auction.submit_bid(TaskBid(agent_id="coder", task_id="t1", credits=8, confidence=0.85))
    winners = auction.resolve()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.task_auction")


@dataclass
class TaskBid:
    """A bid from an agent for a task slot."""
    agent_id: str
    task_id: str
    credits: float          # credits the agent is willing to spend
    confidence: float       # agent's self-assessed confidence [0, 1]
    priority_boost: float = 0.0  # optional external priority boost
    timestamp: float = field(default_factory=time.time)

    @property
    def score(self) -> float:
        """Composite bid score: credits × confidence + priority boost."""
        return self.credits * self.confidence + self.priority_boost


@dataclass
class AuctionResult:
    """Result of a resolved auction round."""
    round_id: str
    winners: List[TaskBid]
    losers: List[TaskBid]
    total_bids: int
    slots_available: int
    resolved_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_id": self.round_id,
            "winners": [
                {"agent_id": b.agent_id, "task_id": b.task_id,
                 "score": round(b.score, 3), "credits": b.credits}
                for b in self.winners
            ],
            "losers": [
                {"agent_id": b.agent_id, "task_id": b.task_id,
                 "score": round(b.score, 3)}
                for b in self.losers
            ],
            "total_bids": self.total_bids,
            "slots_available": self.slots_available,
            "resolved_at": self.resolved_at,
        }


class TaskAuction:
    """Market-style auction for agent task allocation.

    Each round:
    1. Agents submit bids (credits + confidence)
    2. Bids are ranked by composite score
    3. Top N bids win execution slots
    4. Winners' credits are deducted (pay-as-bid)
    5. Losers' bids are refunded (no cost)
    """

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._pending_bids: List[TaskBid] = []
        self._history: List[AuctionResult] = []
        self._round_counter = 0

    def submit_bid(self, bid: TaskBid) -> None:
        """Submit a bid for a task slot."""
        if bid.credits <= 0:
            raise ValueError("Bid credits must be positive")
        if not 0 <= bid.confidence <= 1:
            raise ValueError("Confidence must be in [0, 1]")
        self._pending_bids.append(bid)
        logger.debug(
            f"Bid received: agent={bid.agent_id} task={bid.task_id} "
            f"score={bid.score:.3f}"
        )

    def resolve(self) -> AuctionResult:
        """Resolve the current auction round.

        Returns the AuctionResult with winners and losers.
        Winners are selected by highest composite score.
        """
        self._round_counter += 1
        round_id = f"auction-{self._round_counter}"

        # Rank by score descending, then by timestamp ascending (earlier = tiebreak)
        ranked = sorted(
            self._pending_bids,
            key=lambda b: (-b.score, b.timestamp),
        )

        winners = ranked[:self.max_concurrent]
        losers = ranked[self.max_concurrent:]

        # Deduct credits from winners via ledger (if available)
        for bid in winners:
            try:
                from core.agent_credit_ledger import get_credit_ledger
                ledger = get_credit_ledger()
                ledger.deduct(bid.agent_id, bid.credits, reason=f"auction:{round_id}")
            except Exception:
                pass  # ledger not available or agent not registered

        result = AuctionResult(
            round_id=round_id,
            winners=winners,
            losers=losers,
            total_bids=len(self._pending_bids),
            slots_available=self.max_concurrent,
        )

        self._history.append(result)
        self._pending_bids.clear()

        logger.info(
            f"Auction {round_id} resolved: "
            f"{len(winners)} winners / {len(losers)} losers "
            f"from {result.total_bids} bids"
        )
        return result

    def get_pending_count(self) -> int:
        return len(self._pending_bids)

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history[-limit:]]

    def get_summary(self) -> Dict[str, Any]:
        total_rounds = len(self._history)
        total_bids = sum(r.total_bids for r in self._history)
        return {
            "total_rounds": total_rounds,
            "total_bids": total_bids,
            "max_concurrent": self.max_concurrent,
            "pending_bids": len(self._pending_bids),
            "avg_bids_per_round": total_bids / total_rounds if total_rounds else 0,
        }


_auction: Optional[TaskAuction] = None


def get_task_auction(max_concurrent: int = 3) -> TaskAuction:
    """Get or create the singleton TaskAuction."""
    global _auction
    if _auction is None:
        _auction = TaskAuction(max_concurrent=max_concurrent)
    return _auction
