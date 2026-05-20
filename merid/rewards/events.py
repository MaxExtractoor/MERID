"""Reward Event schemas — typed events that flow into the RewardEngine.

Every rewarded behavior across MERID emits one of these events.  The engine
applies mechanisms to events and produces normalized reward records.

Event hierarchy:
  RewardEvent (base)
  ├── ForecastEvent      — prediction submitted / resolved
  ├── DebateEvent        — debate completed / resolved
  ├── CognitiveEvent     — hypothesis created / updated / retired
  ├── BettingEvent       — bet placed / settled / pool lifecycle
  ├── CodeQualityEvent   — tests added, alerts reduced, SLOs improved
  ├── DevForecastEvent   — engineer impact prediction on a change
  └── DevDebateEvent     — design-review / architecture debate
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EventCategory(str, Enum):
    """Top-level category for reward events."""
    FORECAST = "forecast"
    DEBATE = "debate"
    COGNITIVE = "cognitive"
    BETTING = "betting"
    CODE_QUALITY = "code_quality"
    DEV_FORECAST = "dev_forecast"
    DEV_DEBATE = "dev_debate"
    SPORTS_FORECAST = "sports_forecast"
    SPORTS_BET = "sports_bet"
    SPORTS_DEBATE = "sports_debate"


# ── Base event ────────────────────────────────────────────────────────

@dataclass
class RewardEvent:
    """Base reward event — all typed events inherit from this.

    Fields common to every event:
      id          — unique event identifier
      category    — EventCategory enum value
      agent_id    — who produced this event
      team_id     — optional team context
      venue       — where the event occurred (e.g. "kalshi", "infra", "research")
      timestamp   — when the event occurred (epoch seconds)
      metadata    — arbitrary key-value context
    """
    id: str = field(default_factory=lambda: f"evt-{uuid.uuid4().hex[:12]}")
    category: str = EventCategory.FORECAST.value
    agent_id: str = ""
    team_id: str = ""
    venue: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "agent_id": self.agent_id,
            "team_id": self.team_id,
            "venue": self.venue,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# ── Typed events ──────────────────────────────────────────────────────

@dataclass
class ForecastEvent(RewardEvent):
    """A prediction forecast was submitted or resolved."""
    category: str = EventCategory.FORECAST.value
    symbol: str = ""
    probability: float = 0.5
    confidence: float = 0.5
    outcome: Optional[int] = None        # 1=YES, 0=NO (set on resolution)
    brier_score: Optional[float] = None
    calibration_bucket: Optional[str] = None  # e.g. "0.6-0.7"
    prior_brier: Optional[float] = None  # agent's previous Brier on this symbol
    has_explanation: bool = False
    explanation_rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "symbol": self.symbol,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "outcome": self.outcome,
            "brier_score": round(self.brier_score, 6) if self.brier_score is not None else None,
            "prior_brier": round(self.prior_brier, 6) if self.prior_brier is not None else None,
            "has_explanation": self.has_explanation,
        })
        return d


@dataclass
class DebateEvent(RewardEvent):
    """A structured debate was completed or resolved."""
    category: str = EventCategory.DEBATE.value
    debate_id: str = ""
    symbol: str = ""
    role: str = ""                       # proposer, challenger, arbiter
    debate_lift: Optional[float] = None
    disagreement_width: float = 0.0
    pre_debate_prob: float = 0.5
    post_debate_prob: Optional[float] = None
    was_suppressed: bool = False
    has_explanation: bool = False
    explanation_rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "debate_id": self.debate_id,
            "symbol": self.symbol,
            "role": self.role,
            "debate_lift": round(self.debate_lift, 6) if self.debate_lift is not None else None,
            "disagreement_width": round(self.disagreement_width, 4),
            "was_suppressed": self.was_suppressed,
        })
        return d


@dataclass
class CognitiveEvent(RewardEvent):
    """A hypothesis or mental model was created, updated, or retired."""
    category: str = EventCategory.COGNITIVE.value
    action: str = "created"              # created, updated, retired
    hypothesis_id: str = ""
    regime_tag: str = ""                 # e.g. "fed_tightening", "crypto_winter"
    prior_confidence: Optional[float] = None
    new_confidence: Optional[float] = None
    evidence_count: int = 0              # how many data points support the update
    was_contradicted: bool = False       # did reality contradict the prior belief?

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "action": self.action,
            "hypothesis_id": self.hypothesis_id,
            "regime_tag": self.regime_tag,
            "prior_confidence": self.prior_confidence,
            "new_confidence": self.new_confidence,
            "evidence_count": self.evidence_count,
            "was_contradicted": self.was_contradicted,
        })
        return d


@dataclass
class BettingEvent(RewardEvent):
    """A bet was placed, settled, or a pool lifecycle event occurred."""
    category: str = EventCategory.BETTING.value
    action: str = "bet_placed"           # bet_placed, bet_settled, pool_created, pool_settled
    market_id: str = ""                  # universal market/instrument key
    bet_id: str = ""
    prediction: str = ""                 # outcome the agent bet on
    stake_amount: float = 0.0
    odds: float = 0.0
    payout: float = 0.0
    net_profit: float = 0.0
    won: Optional[bool] = None
    stated_probability: Optional[float] = None   # agent's opinion prob at bet time
    implied_probability: Optional[float] = None  # implied prob from bet odds
    coherence_score: Optional[float] = None      # |stated - implied| alignment
    role: str = ""                       # hedging, market_making, arb, directional

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "action": self.action,
            "market_id": self.market_id,
            "bet_id": self.bet_id,
            "prediction": self.prediction,
            "stake_amount": round(self.stake_amount, 2),
            "odds": round(self.odds, 4),
            "payout": round(self.payout, 2),
            "net_profit": round(self.net_profit, 2),
            "won": self.won,
            "stated_probability": round(self.stated_probability, 4) if self.stated_probability is not None else None,
            "implied_probability": round(self.implied_probability, 4) if self.implied_probability is not None else None,
            "coherence_score": round(self.coherence_score, 4) if self.coherence_score is not None else None,
            "role": self.role,
        })
        return d


@dataclass
class CodeQualityEvent(RewardEvent):
    """A system-improvement action: tests added, alerts reduced, SLOs tightened."""
    category: str = EventCategory.CODE_QUALITY.value
    action: str = ""                     # test_added, alert_reduced, slo_tightened, bug_fixed
    target: str = ""                     # what was improved (module, alert name, SLO name)
    impact_metric: str = ""              # metric name (e.g. "alert_count", "p95_latency")
    impact_before: Optional[float] = None
    impact_after: Optional[float] = None
    tests_added: int = 0
    alerts_reduced: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "action": self.action,
            "target": self.target,
            "impact_metric": self.impact_metric,
            "impact_before": self.impact_before,
            "impact_after": self.impact_after,
            "tests_added": self.tests_added,
            "alerts_reduced": self.alerts_reduced,
        })
        return d


@dataclass
class DevForecastEvent(RewardEvent):
    """An engineer's impact prediction about a change (scored like a forecast)."""
    category: str = EventCategory.DEV_FORECAST.value
    change_id: str = ""                  # PR, commit, or change identifier
    predicted_metric: str = ""           # e.g. "p95_latency", "error_rate"
    predicted_value: Optional[float] = None
    actual_value: Optional[float] = None
    predicted_direction: str = ""        # "improve", "degrade", "neutral"
    actual_direction: str = ""
    brier_score: Optional[float] = None  # computed after resolution

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "change_id": self.change_id,
            "predicted_metric": self.predicted_metric,
            "predicted_value": self.predicted_value,
            "actual_value": self.actual_value,
            "predicted_direction": self.predicted_direction,
            "actual_direction": self.actual_direction,
            "brier_score": round(self.brier_score, 6) if self.brier_score is not None else None,
        })
        return d


@dataclass
class DevDebateEvent(RewardEvent):
    """A design-review or architecture debate (scored like a prediction debate)."""
    category: str = EventCategory.DEV_DEBATE.value
    debate_id: str = ""
    change_id: str = ""                  # PR or design doc
    role: str = ""                       # proposer, reviewer, arbiter
    design_lift: Optional[float] = None  # did the debate improve the outcome?
    disagreement_width: float = 0.0
    outcome_metric: str = ""             # what was measured after merge
    outcome_before: Optional[float] = None
    outcome_after: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "debate_id": self.debate_id,
            "change_id": self.change_id,
            "role": self.role,
            "design_lift": round(self.design_lift, 6) if self.design_lift is not None else None,
            "disagreement_width": round(self.disagreement_width, 4),
            "outcome_metric": self.outcome_metric,
            "outcome_before": self.outcome_before,
            "outcome_after": self.outcome_after,
        })
        return d


@dataclass
class SportsForecastEvent(RewardEvent):
    """A sports prediction forecast was submitted or resolved."""
    category: str = EventCategory.SPORTS_FORECAST.value
    event_id: str = ""                   # sports event identifier
    outcome_label: str = ""              # e.g. "home", "over", "yes"
    sport: str = ""
    league: str = ""
    probability: float = 0.5
    confidence: float = 0.5
    edge: float = 0.0                    # agent_prob - external_prob
    external_prob: float = 0.5
    brier_score: Optional[float] = None
    is_live: bool = False
    signal_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "sport": self.sport,
            "league": self.league,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "edge": round(self.edge, 4),
            "external_prob": round(self.external_prob, 4),
            "brier_score": round(self.brier_score, 6) if self.brier_score is not None else None,
            "is_live": self.is_live,
            "signal_sources": self.signal_sources,
        })
        return d


@dataclass
class SportsBetEvent(RewardEvent):
    """A sports bet was placed or settled."""
    category: str = EventCategory.SPORTS_BET.value
    event_id: str = ""
    outcome_label: str = ""
    sport: str = ""
    stake: float = 0.0
    odds: float = 0.0
    pnl: Optional[float] = None
    is_settled: bool = False
    bet_latency_ms: float = 0.0          # how fast the bet was placed
    edge_at_placement: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "sport": self.sport,
            "stake": round(self.stake, 2),
            "odds": round(self.odds, 4),
            "pnl": round(self.pnl, 2) if self.pnl is not None else None,
            "is_settled": self.is_settled,
            "bet_latency_ms": round(self.bet_latency_ms, 1),
            "edge_at_placement": round(self.edge_at_placement, 4),
        })
        return d


@dataclass
class SportsDebateEvent(RewardEvent):
    """A sports debate was completed or resolved."""
    category: str = EventCategory.SPORTS_DEBATE.value
    debate_id: str = ""
    event_id: str = ""
    outcome_label: str = ""
    sport: str = ""
    role: str = ""                       # proposer, challenger, arbiter
    # LEGACY REMOVAL: debate_lift removed - debate module deleted
    pre_debate_prob: float = 0.5
    post_debate_prob: Optional[float] = None
    disagreement_width: float = 0.0
    rounds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "debate_id": self.debate_id,
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "sport": self.sport,
            "role": self.role,
            "debate_lift": round(self.debate_lift, 6) if self.debate_lift is not None else None,
            "pre_debate_prob": round(self.pre_debate_prob, 4),
            "post_debate_prob": round(self.post_debate_prob, 4) if self.post_debate_prob is not None else None,
            "disagreement_width": round(self.disagreement_width, 4),
            "rounds": self.rounds,
        })
        return d


# ── Event factory ─────────────────────────────────────────────────────

_EVENT_TYPE_MAP: Dict[str, type] = {
    EventCategory.FORECAST.value: ForecastEvent,
    EventCategory.DEBATE.value: DebateEvent,
    EventCategory.COGNITIVE.value: CognitiveEvent,
    EventCategory.BETTING.value: BettingEvent,
    EventCategory.CODE_QUALITY.value: CodeQualityEvent,
    EventCategory.DEV_FORECAST.value: DevForecastEvent,
    EventCategory.DEV_DEBATE.value: DevDebateEvent,
    EventCategory.SPORTS_FORECAST.value: SportsForecastEvent,
    EventCategory.SPORTS_BET.value: SportsBetEvent,
    EventCategory.SPORTS_DEBATE.value: SportsDebateEvent,
}


def event_from_dict(data: Dict[str, Any]) -> RewardEvent:
    """Reconstruct a typed RewardEvent from a dict (e.g. from JSON/DB)."""
    category = data.get("category", EventCategory.FORECAST.value)
    cls = _EVENT_TYPE_MAP.get(category, RewardEvent)
    # Filter to only fields the dataclass accepts
    import dataclasses
    valid_fields = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return cls(**filtered)
