"""
Structured Negotiation Protocol for conflicting agent risk views.

Implements a propose → counter → accept/reject cycle so agents can
resolve disagreements iteratively instead of relying solely on VETO
or majority vote.

Readiness Impact: S1-03 (1→2) — agent-to-agent negotiation and conflict resolution.

Usage:
    from core.negotiation_protocol import NegotiationSession, Proposal
    session = NegotiationSession(
        topic="BTC long entry",
        initiator="strategy-agent",
        respondent="risk-agent",
    )
    session.propose(Proposal(agent_id="strategy-agent", action="EXECUTE_LONG", confidence=0.85))
    session.counter(Proposal(agent_id="risk-agent", action="REDUCE_SIZE_50PCT", confidence=0.70))
    session.accept("strategy-agent")
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.negotiation_protocol")


class NegotiationState(str, Enum):
    """States of a negotiation session."""
    OPEN = "open"
    PROPOSED = "proposed"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEADLOCKED = "deadlocked"
    EXPIRED = "expired"


@dataclass
class Proposal:
    """A proposal or counter-proposal from an agent."""
    agent_id: str
    action: str
    confidence: float
    rationale: str = ""
    constraints: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "agent_id": self.agent_id,
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "constraints": self.constraints,
            "timestamp": self.timestamp,
        }


@dataclass
class NegotiationSession:
    """A structured negotiation between two agents.

    Lifecycle:
        OPEN → propose() → PROPOSED → counter() → COUNTERED
        → accept() → ACCEPTED  or  reject() → REJECTED
        Counter rounds repeat up to ``max_rounds``.
        If max_rounds exceeded → DEADLOCKED.
        If timeout exceeded → EXPIRED.
    """

    topic: str
    initiator: str
    respondent: str
    max_rounds: int = 3
    timeout_seconds: float = 60.0
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: NegotiationState = NegotiationState.OPEN
    created_at: float = field(default_factory=time.time)

    proposals: List[Proposal] = field(default_factory=list)
    resolution: Optional[Proposal] = None
    resolved_by: Optional[str] = None
    _round: int = 0
    _callbacks: List[Callable] = field(default_factory=list)

    def on_resolved(self, callback: Callable) -> None:
        """Register a callback for when the session resolves."""
        self._callbacks.append(callback)

    @property
    def current_round(self) -> int:
        return self._round

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            NegotiationState.ACCEPTED,
            NegotiationState.REJECTED,
            NegotiationState.DEADLOCKED,
            NegotiationState.EXPIRED,
        )

    def propose(self, proposal: Proposal) -> None:
        """Submit the initial proposal (or a new proposal after counter)."""
        self._check_expired()
        if self.is_terminal:
            raise NegotiationError(f"Session {self.session_id} is already {self.state.value}")

        if self.state not in (NegotiationState.OPEN, NegotiationState.COUNTERED):
            raise NegotiationError(
                f"Cannot propose in state {self.state.value}; expected OPEN or COUNTERED"
            )

        self.proposals.append(proposal)
        self.state = NegotiationState.PROPOSED
        self._round += 1
        logger.info(
            f"Negotiation {self.session_id}: {proposal.agent_id} proposes "
            f"'{proposal.action}' (round {self._round})"
        )

    def counter(self, proposal: Proposal) -> None:
        """Submit a counter-proposal."""
        self._check_expired()
        if self.is_terminal:
            raise NegotiationError(f"Session {self.session_id} is already {self.state.value}")

        if self.state != NegotiationState.PROPOSED:
            raise NegotiationError(
                f"Cannot counter in state {self.state.value}; expected PROPOSED"
            )

        if self._round >= self.max_rounds:
            self.state = NegotiationState.DEADLOCKED
            logger.warning(
                f"Negotiation {self.session_id}: deadlocked after {self._round} rounds"
            )
            self._fire_callbacks()
            return

        self.proposals.append(proposal)
        self.state = NegotiationState.COUNTERED
        logger.info(
            f"Negotiation {self.session_id}: {proposal.agent_id} counters "
            f"with '{proposal.action}' (round {self._round})"
        )

    def accept(self, agent_id: str) -> None:
        """Accept the latest proposal."""
        self._check_expired()
        if self.is_terminal:
            raise NegotiationError(f"Session {self.session_id} is already {self.state.value}")

        if not self.proposals:
            raise NegotiationError("No proposal to accept")

        self.resolution = self.proposals[-1]
        self.resolved_by = agent_id
        self.state = NegotiationState.ACCEPTED
        logger.info(
            f"Negotiation {self.session_id}: {agent_id} accepts "
            f"'{self.resolution.action}'"
        )
        self._fire_callbacks()

    def reject(self, agent_id: str, reason: str = "") -> None:
        """Reject the negotiation entirely."""
        self._check_expired()
        if self.is_terminal:
            raise NegotiationError(f"Session {self.session_id} is already {self.state.value}")

        self.resolved_by = agent_id
        self.state = NegotiationState.REJECTED
        logger.info(
            f"Negotiation {self.session_id}: {agent_id} rejects "
            f"(reason: {reason or 'none'})"
        )
        self._fire_callbacks()

    def _check_expired(self) -> None:
        if not self.is_terminal and (time.time() - self.created_at) > self.timeout_seconds:
            self.state = NegotiationState.EXPIRED
            logger.warning(f"Negotiation {self.session_id}: expired")
            self._fire_callbacks()

    def _fire_callbacks(self) -> None:
        for cb in self._callbacks:
            try:
                cb(self)
            except Exception as exc:
                logger.error(f"Negotiation callback error: {exc}")

    def get_history(self) -> List[Dict[str, Any]]:
        """Return the full proposal history."""
        return [p.to_dict() for p in self.proposals]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "initiator": self.initiator,
            "respondent": self.respondent,
            "state": self.state.value,
            "round": self._round,
            "max_rounds": self.max_rounds,
            "resolution": self.resolution.to_dict() if self.resolution else None,
            "resolved_by": self.resolved_by,
            "proposals": self.get_history(),
            "created_at": self.created_at,
        }


class NegotiationError(Exception):
    """Raised when a negotiation protocol violation occurs."""
    pass


class NegotiationMediator:
    """Manages multiple negotiation sessions and provides resolution strategies.

    Strategies:
    - ``highest_confidence``: accept the proposal with the highest confidence
    - ``last_proposal``: accept the most recent proposal
    - ``initiator_wins``: accept the initiator's latest proposal
    """

    def __init__(self):
        self._sessions: Dict[str, NegotiationSession] = {}
        self._resolved: List[NegotiationSession] = []

    def create_session(
        self,
        topic: str,
        initiator: str,
        respondent: str,
        max_rounds: int = 3,
        timeout_seconds: float = 60.0,
    ) -> NegotiationSession:
        session = NegotiationSession(
            topic=topic,
            initiator=initiator,
            respondent=respondent,
            max_rounds=max_rounds,
            timeout_seconds=timeout_seconds,
        )
        self._sessions[session.session_id] = session
        session.on_resolved(lambda s: self._on_resolved(s))
        return session

    def _on_resolved(self, session: NegotiationSession) -> None:
        self._resolved.append(session)

    def get_session(self, session_id: str) -> Optional[NegotiationSession]:
        return self._sessions.get(session_id)

    def get_active_sessions(self) -> List[NegotiationSession]:
        return [s for s in self._sessions.values() if not s.is_terminal]

    def get_resolved_sessions(self) -> List[NegotiationSession]:
        return list(self._resolved)

    def auto_resolve_deadlock(
        self, session: NegotiationSession, strategy: str = "highest_confidence"
    ) -> Optional[Proposal]:
        """Auto-resolve a deadlocked session using a strategy."""
        if session.state != NegotiationState.DEADLOCKED:
            return None

        if not session.proposals:
            return None

        if strategy == "highest_confidence":
            best = max(session.proposals, key=lambda p: p.confidence)
        elif strategy == "last_proposal":
            best = session.proposals[-1]
        elif strategy == "initiator_wins":
            initiator_proposals = [
                p for p in session.proposals if p.agent_id == session.initiator
            ]
            best = initiator_proposals[-1] if initiator_proposals else session.proposals[-1]
        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        session.resolution = best
        session.resolved_by = f"mediator:{strategy}"
        session.state = NegotiationState.ACCEPTED
        logger.info(
            f"Mediator resolved {session.session_id} via {strategy}: "
            f"'{best.action}' by {best.agent_id}"
        )
        return best

    def get_summary(self) -> Dict[str, Any]:
        return {
            "active_sessions": len(self.get_active_sessions()),
            "resolved_sessions": len(self._resolved),
            "total_sessions": len(self._sessions),
        }
