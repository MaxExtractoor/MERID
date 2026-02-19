"""Sports debate protocol — wires sports markets into the debate system.

Extends the DebateCoordinatorAgent pattern for sports-specific debates:
  1. SportsDebateSession: A debate on a sports event outcome, with
     proposer/challenger/arbiter roles drawn from sports-aware agents.
  2. SportsDebateCoordinator: Orchestrates sports debates, triggers them
     when agent opinions diverge on a live/pre-game event.
  3. SportsDebateLiftTracker: Measures whether debates improve prediction
     accuracy for sports events (Brier lift).
  4. SportsExplanationBuilder: Produces sports-specific explanations
     (team form, injuries, weather, sharp-book signals, etc.).

Integration points:
  - SportsForecastEngine provides agent forecasts.
  - LiveOddsEngine provides external odds context.
  - DebateStore persists debate sessions and arguments.
  - RewardEngine receives SportsDebateEvents on resolution.
"""

from __future__ import annotations

import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.betting.sports_debate")


# ═══════════════════════════════════════════════════════════════════════
# 1. Sports Debate Session
# ═══════════════════════════════════════════════════════════════════════

SPORTS_DEBATE_STATUSES = ("open", "closed", "resolved")
SPORTS_DEBATE_ROLES = ("proposer", "challenger", "arbiter")


@dataclass
class SportsDebateArgument:
    """A single argument in a sports debate."""
    id: str = field(default_factory=lambda: f"sdarg-{uuid.uuid4().hex[:8]}")
    debate_id: str = ""
    agent_id: str = ""
    role: str = "proposer"
    probability: float = 0.5
    confidence: float = 0.5
    reasoning: str = ""
    signal_sources: List[str] = field(default_factory=list)
    explanation: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "debate_id": self.debate_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "signal_sources": self.signal_sources,
            "created_at": self.created_at,
        }
        if self.explanation:
            d["explanation"] = self.explanation
        return d


@dataclass
class SportsDebateSession:
    """A structured debate on a sports event outcome."""
    id: str = field(default_factory=lambda: f"sdeb-{uuid.uuid4().hex[:8]}")
    event_id: str = ""
    outcome_label: str = ""
    sport: str = ""
    league: str = ""
    status: str = "open"
    pre_debate_prob: float = 0.5
    post_debate_prob: Optional[float] = None
    external_prob: float = 0.5       # sportsbook consensus at debate time
    outcome: Optional[int] = None    # 1=correct, 0=incorrect (set on resolution)
    debate_lift: Optional[float] = None
    arguments: List[SportsDebateArgument] = field(default_factory=list)
    rounds: int = 0
    trigger_reason: str = ""         # why the debate was triggered
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "sport": self.sport,
            "league": self.league,
            "status": self.status,
            "pre_debate_prob": round(self.pre_debate_prob, 4),
            "external_prob": round(self.external_prob, 4),
            "rounds": self.rounds,
            "trigger_reason": self.trigger_reason,
            "arguments": [a.to_dict() for a in self.arguments],
            "created_at": self.created_at,
        }
        if self.post_debate_prob is not None:
            d["post_debate_prob"] = round(self.post_debate_prob, 4)
        if self.debate_lift is not None:
            d["debate_lift"] = round(self.debate_lift, 4)
        if self.outcome is not None:
            d["outcome"] = self.outcome
        if self.closed_at is not None:
            d["closed_at"] = self.closed_at
        return d


# ═══════════════════════════════════════════════════════════════════════
# 2. Sports Explanation Builder
# ═══════════════════════════════════════════════════════════════════════

class SportsExplanationBuilder:
    """Builds structured explanations for sports debate arguments.

    Produces explanations that reference:
      - Sharp-book vs consensus divergence
      - Home/away advantage context
      - Live game state (score, period, momentum)
      - Historical matchup data (placeholder)
      - Agent model signals
    """

    @staticmethod
    def build(
        event_id: str,
        outcome_label: str,
        agent_prob: float,
        external_prob: float,
        sport: str = "",
        is_live: bool = False,
        score_home: Optional[int] = None,
        score_away: Optional[int] = None,
        period: str = "",
        sharp_prob: Optional[float] = None,
        signal_sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build a sports-specific explanation dict."""
        edge = agent_prob - external_prob
        sharp_edge = (agent_prob - sharp_prob) if sharp_prob is not None else None

        factors = []
        if abs(edge) > 0.05:
            direction = "higher" if edge > 0 else "lower"
            factors.append(f"Agent estimates {direction} probability than consensus by {abs(edge):.1%}")
        if sharp_prob is not None and abs(agent_prob - sharp_prob) > 0.03:
            factors.append(f"Diverges from sharp books by {abs(agent_prob - sharp_prob):.1%}")
        if is_live:
            score_str = f"{score_home}-{score_away}" if score_home is not None else "unknown"
            factors.append(f"Live game context: score {score_str}, period {period or 'unknown'}")
        if sport:
            factors.append(f"Sport-specific model for {sport}")

        return {
            "type": "sports_debate_explanation",
            "event_id": event_id,
            "outcome_label": outcome_label,
            "edge_vs_consensus": round(edge, 4),
            "edge_vs_sharp": round(sharp_edge, 4) if sharp_edge is not None else None,
            "is_live": is_live,
            "factors": factors,
            "signal_sources": signal_sources or [],
            "sport": sport,
        }


# ═══════════════════════════════════════════════════════════════════════
# 3. Sports Debate Lift Tracker
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class LiftRecord:
    """Records the Brier lift from a single sports debate."""
    debate_id: str = ""
    event_id: str = ""
    outcome_label: str = ""
    pre_brier: float = 0.0
    post_brier: float = 0.0
    lift: float = 0.0                # pre_brier - post_brier (positive = improvement)
    outcome: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "pre_brier": round(self.pre_brier, 4),
            "post_brier": round(self.post_brier, 4),
            "lift": round(self.lift, 4),
            "outcome": self.outcome,
        }


class SportsDebateLiftTracker:
    """Tracks whether sports debates improve prediction accuracy."""

    def __init__(self):
        self._lock = threading.RLock()
        self._records: List[LiftRecord] = []

    def record_lift(
        self,
        debate: SportsDebateSession,
        outcome: int,
    ) -> LiftRecord:
        """Compute and record debate lift for a resolved debate."""
        pre_brier = (debate.pre_debate_prob - outcome) ** 2
        post_prob = debate.post_debate_prob if debate.post_debate_prob is not None else debate.pre_debate_prob
        post_brier = (post_prob - outcome) ** 2
        lift = pre_brier - post_brier  # positive = debate improved accuracy

        record = LiftRecord(
            debate_id=debate.id,
            event_id=debate.event_id,
            outcome_label=debate.outcome_label,
            pre_brier=pre_brier,
            post_brier=post_brier,
            lift=lift,
            outcome=outcome,
        )

        with self._lock:
            self._records.append(record)
        return record

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate lift statistics."""
        with self._lock:
            records = list(self._records)
        if not records:
            return {"total_debates": 0, "avg_lift": None, "positive_lift_rate": None}

        lifts = [r.lift for r in records]
        positive = sum(1 for l in lifts if l > 0)
        return {
            "total_debates": len(records),
            "avg_lift": round(statistics.mean(lifts), 4),
            "median_lift": round(statistics.median(lifts), 4),
            "positive_lift_rate": round(positive / len(records), 4),
            "max_lift": round(max(lifts), 4),
            "min_lift": round(min(lifts), 4),
            "total_brier_saved": round(sum(l for l in lifts if l > 0), 4),
        }

    def get_records(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._records[-limit:]]


# ═══════════════════════════════════════════════════════════════════════
# 4. Sports Debate Coordinator
# ═══════════════════════════════════════════════════════════════════════

class SportsDebateCoordinator:
    """Orchestrates sports debates when agent opinions diverge.

    Trigger conditions:
      - Agent forecast diverges from external odds by > divergence_threshold
      - Multiple agents disagree on an outcome by > disagreement_threshold
      - Explicit trigger via API

    Debate flow:
      1. Proposer submits initial argument (highest-edge agent).
      2. Challenger responds (agent with most opposing view).
      3. Arbiter synthesizes (confidence-weighted blend).
      4. Post-debate probability is the arbiter's output.
    """

    def __init__(
        self,
        divergence_threshold: float = 0.05,
        disagreement_threshold: float = 0.08,
        min_arguments: int = 2,
        max_arguments: int = 5,
    ):
        self._lock = threading.RLock()
        self._sessions: Dict[str, SportsDebateSession] = {}
        self._lift_tracker = SportsDebateLiftTracker()
        self.divergence_threshold = divergence_threshold
        self.disagreement_threshold = disagreement_threshold
        self.min_arguments = min_arguments
        self.max_arguments = max_arguments

    @property
    def lift_tracker(self) -> SportsDebateLiftTracker:
        return self._lift_tracker

    def create_debate(
        self,
        event_id: str,
        outcome_label: str,
        pre_debate_prob: float,
        external_prob: float = 0.5,
        sport: str = "",
        league: str = "",
        trigger_reason: str = "divergence",
    ) -> SportsDebateSession:
        """Create a new sports debate session."""
        session = SportsDebateSession(
            event_id=event_id,
            outcome_label=outcome_label,
            sport=sport,
            league=league,
            pre_debate_prob=pre_debate_prob,
            external_prob=external_prob,
            trigger_reason=trigger_reason,
        )
        with self._lock:
            self._sessions[session.id] = session
        logger.info("Sports debate created: %s for %s:%s", session.id, event_id, outcome_label)
        return session

    def add_argument(
        self,
        debate_id: str,
        agent_id: str,
        role: str,
        probability: float,
        confidence: float = 0.5,
        reasoning: str = "",
        signal_sources: Optional[List[str]] = None,
        explanation: Optional[Dict[str, Any]] = None,
    ) -> Optional[SportsDebateArgument]:
        """Add an argument to a sports debate."""
        with self._lock:
            session = self._sessions.get(debate_id)
            if not session or session.status != "open":
                return None
            if session.rounds >= self.max_arguments:
                return None

            arg = SportsDebateArgument(
                debate_id=debate_id,
                agent_id=agent_id,
                role=role,
                probability=probability,
                confidence=confidence,
                reasoning=reasoning,
                signal_sources=signal_sources or [],
                explanation=explanation,
            )
            session.arguments.append(arg)
            session.rounds += 1

        return arg

    def close_debate(self, debate_id: str) -> Optional[SportsDebateSession]:
        """Close a debate and compute post-debate probability."""
        with self._lock:
            session = self._sessions.get(debate_id)
            if not session or session.status != "open":
                return None

            if not session.arguments:
                return None

            # Compute post-debate prob: confidence-weighted average of all arguments
            total_conf = sum(a.confidence for a in session.arguments)
            if total_conf > 0:
                post_prob = sum(
                    a.probability * a.confidence for a in session.arguments
                ) / total_conf
            else:
                post_prob = statistics.mean([a.probability for a in session.arguments])

            session.post_debate_prob = max(0.01, min(0.99, post_prob))
            session.status = "closed"
            session.closed_at = time.time()

        return session

    def resolve_debate(self, debate_id: str, outcome: int) -> Optional[SportsDebateSession]:
        """Resolve a debate with the actual outcome and compute lift."""
        with self._lock:
            session = self._sessions.get(debate_id)
            if not session:
                return None

            session.outcome = outcome
            session.status = "resolved"

            # Compute lift
            lift_record = self._lift_tracker.record_lift(session, outcome)
            session.debate_lift = lift_record.lift

        return session

    def check_divergence(
        self,
        event_id: str,
        outcome_label: str,
        agent_forecasts: List[Dict[str, Any]],
        external_prob: float,
    ) -> Optional[str]:
        """Check if a debate should be triggered. Returns trigger reason or None."""
        if not agent_forecasts:
            return None

        probs = [f.get("probability", 0.5) for f in agent_forecasts]

        # Check agent vs external divergence
        avg_agent = statistics.mean(probs)
        if abs(avg_agent - external_prob) > self.divergence_threshold:
            return f"agent_external_divergence_{abs(avg_agent - external_prob):.1%}"

        # Check inter-agent disagreement
        if len(probs) >= 2:
            spread = max(probs) - min(probs)
            if spread > self.disagreement_threshold:
                return f"agent_disagreement_{spread:.1%}"

        return None

    def get_debate(self, debate_id: str) -> Optional[SportsDebateSession]:
        with self._lock:
            return self._sessions.get(debate_id)

    def list_debates(
        self,
        event_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[SportsDebateSession]:
        with self._lock:
            sessions = list(self._sessions.values())
        if event_id:
            sessions = [s for s in sessions if s.event_id == event_id]
        if status:
            sessions = [s for s in sessions if s.status == status]
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions[:limit]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            sessions = list(self._sessions.values())
        return {
            "total_debates": len(sessions),
            "open": sum(1 for s in sessions if s.status == "open"),
            "closed": sum(1 for s in sessions if s.status == "closed"),
            "resolved": sum(1 for s in sessions if s.status == "resolved"),
            "lift_stats": self._lift_tracker.get_stats(),
        }


# ═══════════════════════════════════════════════════════════════════════
# 5. Singleton
# ═══════════════════════════════════════════════════════════════════════

_coordinator: Optional[SportsDebateCoordinator] = None


def get_sports_debate_coordinator() -> SportsDebateCoordinator:
    """Get or create the singleton SportsDebateCoordinator."""
    global _coordinator
    if _coordinator is None:
        _coordinator = SportsDebateCoordinator()
    return _coordinator
