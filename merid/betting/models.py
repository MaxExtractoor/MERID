"""Betting domain models — events, odds, consensus, plans, settlements.

Key objects:
  - BettingEvent: a sports/event market (NFL game, election, etc.)
  - BettingOutcome: one side of an event (Team A, Team B, Over, Under, etc.)
  - BookOdds: odds from a single sportsbook for one outcome
  - OddsSnapshot: point-in-time snapshot of all book odds for an event
  - BettingEventConsensus: merged view — sportsbook + prediction market + swarm
  - LiveBetPlan: edge-gated betting plan with latency/risk guards
  - SettledBet: resolved bet with PnL
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────

class EventState(str, Enum):
    PRE = "pre"
    LIVE = "live"
    FINAL = "final"
    CANCELLED = "cancelled"


class MarketType(str, Enum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    PROP = "prop"
    FUTURES = "futures"
    YES_NO = "yes_no"


class BetStatus(str, Enum):
    PENDING = "pending"
    PLACED = "placed"
    WON = "won"
    LOST = "lost"
    PUSH = "push"
    CANCELLED = "cancelled"


class BettingStance(str, Enum):
    STRONG_YES = "strong_yes"
    WEAK_YES = "weak_yes"
    NEUTRAL = "neutral"
    WEAK_NO = "weak_no"
    STRONG_NO = "strong_no"


# ── Core domain objects ───────────────────────────────────────────────

@dataclass
class BettingOutcome:
    """One side of an event — e.g. 'Chiefs ML', 'Over 45.5', 'Yes'."""
    id: str = ""
    name: str = ""
    market_type: str = "moneyline"

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "market_type": self.market_type}


@dataclass
class BookOdds:
    """Odds from a single sportsbook for one outcome."""
    book: str = ""               # e.g. "draftkings", "fanduel", "consensus"
    outcome_id: str = ""
    american_odds: int = 0       # e.g. -110, +150
    decimal_odds: float = 0.0    # e.g. 1.91, 2.50
    implied_prob: float = 0.0    # after vig removal (0-1)
    raw_implied_prob: float = 0.0  # before vig removal
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()
        if self.decimal_odds > 0 and self.raw_implied_prob == 0:
            self.raw_implied_prob = 1.0 / self.decimal_odds
        if self.american_odds != 0 and self.decimal_odds == 0:
            self.decimal_odds = american_to_decimal(self.american_odds)
            self.raw_implied_prob = 1.0 / self.decimal_odds if self.decimal_odds > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "book": self.book, "outcome_id": self.outcome_id,
            "american_odds": self.american_odds, "decimal_odds": round(self.decimal_odds, 4),
            "implied_prob": round(self.implied_prob, 4),
            "raw_implied_prob": round(self.raw_implied_prob, 4),
            "timestamp": self.timestamp,
        }


@dataclass
class BettingEvent:
    """A sports or event market — e.g. 'Chiefs vs 49ers', 'BTC > 100K'."""
    id: str = ""
    sport: str = ""               # e.g. "nfl", "nba", "mlb", "politics", "crypto"
    league: str = ""              # e.g. "NFL", "NBA", "Premier League"
    title: str = ""               # human-readable title
    description: str = ""
    home_team: str = ""
    away_team: str = ""
    start_time: float = 0.0       # unix epoch
    state: str = "pre"            # pre / live / final / cancelled
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    period: str = ""              # "Q2", "3rd", "Half", etc.
    clock: str = ""               # "5:23", "45:00", etc.
    outcomes: List[BettingOutcome] = field(default_factory=list)
    market_types: List[str] = field(default_factory=lambda: ["moneyline"])
    kalshi_event_id: Optional[str] = None   # matching Kalshi event if any
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:12]
        now = time.time()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "sport": self.sport, "league": self.league,
            "title": self.title, "description": self.description,
            "home_team": self.home_team, "away_team": self.away_team,
            "start_time": self.start_time, "state": self.state,
            "score_home": self.score_home, "score_away": self.score_away,
            "period": self.period, "clock": self.clock,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "market_types": self.market_types,
            "kalshi_event_id": self.kalshi_event_id,
        }


@dataclass
class OddsSnapshot:
    """Point-in-time snapshot: all book odds for one event + one market type."""
    event_id: str = ""
    market_type: str = "moneyline"
    book_odds: List[BookOdds] = field(default_factory=list)
    consensus_prob: Dict[str, float] = field(default_factory=dict)  # outcome_id → prob
    sharp_prob: Dict[str, float] = field(default_factory=dict)      # from "sharp" books
    best_odds: Dict[str, BookOdds] = field(default_factory=dict)    # outcome_id → best book
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id, "market_type": self.market_type,
            "consensus_prob": {k: round(v, 4) for k, v in self.consensus_prob.items()},
            "sharp_prob": {k: round(v, 4) for k, v in self.sharp_prob.items()},
            "best_odds": {k: v.to_dict() for k, v in self.best_odds.items()},
            "book_count": len(set(o.book for o in self.book_odds)),
            "timestamp": self.timestamp,
        }


@dataclass
class BettingEventConsensus:
    """Merged consensus for one event: sportsbooks + prediction markets + swarm.

    This is THE object the betting page reads — one per event per market type.
    """
    event_id: str = ""
    event: Optional[BettingEvent] = None

    # Sportsbook layer
    sportsbook_consensus_prob: Dict[str, float] = field(default_factory=dict)  # outcome_id → prob
    sharp_book_prob: Dict[str, float] = field(default_factory=dict)
    best_book_odds: Dict[str, BookOdds] = field(default_factory=dict)
    book_count: int = 0

    # Prediction market layer (Kalshi etc.)
    prediction_market_prob: Dict[str, float] = field(default_factory=dict)  # outcome_id → prob
    prediction_market_source: str = ""  # "kalshi", "polymarket", etc.

    # Swarm layer
    swarm_prob: Dict[str, float] = field(default_factory=dict)  # outcome_id → prob
    swarm_confidence: float = 0.0
    swarm_supporting_agents: int = 0
    swarm_opposing_agents: int = 0
    swarm_opinion_count: int = 0

    # Derived edges (per primary outcome)
    edge_vs_books: Dict[str, float] = field(default_factory=dict)
    edge_vs_prediction: Dict[str, float] = field(default_factory=dict)
    stance: str = "neutral"
    max_edge: float = 0.0

    # Plan tracking
    active_plans: Dict[str, int] = field(default_factory=lambda: {"proposed": 0, "approved": 0, "executing": 0})

    # Meta
    state: str = "pre"
    last_update_ts: float = 0.0
    arbitrage_flag: bool = False

    def __post_init__(self):
        if not self.last_update_ts:
            self.last_update_ts = time.time()

    def compute_edges(self) -> None:
        """Recompute edge_vs_books, edge_vs_prediction, stance, max_edge."""
        self.edge_vs_books = {}
        self.edge_vs_prediction = {}
        max_abs = 0.0

        for oid in self.swarm_prob:
            sp = self.swarm_prob.get(oid, 0.5)
            bp = self.sportsbook_consensus_prob.get(oid, 0.5)
            pp = self.prediction_market_prob.get(oid, bp)

            self.edge_vs_books[oid] = round(sp - bp, 4)
            self.edge_vs_prediction[oid] = round(sp - pp, 4)

            if abs(sp - bp) > max_abs:
                max_abs = abs(sp - bp)

        self.max_edge = round(max_abs, 4)
        self.stance = classify_betting_stance(self.max_edge, self.swarm_prob, self.sportsbook_consensus_prob)

        # Arb flag: check if any combo of best odds across outcomes > 1
        if self.best_book_odds:
            total_implied = sum(
                bo.implied_prob for bo in self.best_book_odds.values()
            )
            self.arbitrage_flag = total_implied < 0.98  # sub-100% = arb opportunity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event": self.event.to_dict() if self.event else None,
            "sportsbook_consensus_prob": {k: round(v, 4) for k, v in self.sportsbook_consensus_prob.items()},
            "sharp_book_prob": {k: round(v, 4) for k, v in self.sharp_book_prob.items()},
            "best_book_odds": {k: v.to_dict() for k, v in self.best_book_odds.items()},
            "book_count": self.book_count,
            "prediction_market_prob": {k: round(v, 4) for k, v in self.prediction_market_prob.items()},
            "prediction_market_source": self.prediction_market_source,
            "swarm_prob": {k: round(v, 4) for k, v in self.swarm_prob.items()},
            "swarm_confidence": round(self.swarm_confidence, 4),
            "swarm_supporting_agents": self.swarm_supporting_agents,
            "swarm_opposing_agents": self.swarm_opposing_agents,
            "swarm_opinion_count": self.swarm_opinion_count,
            "edge_vs_books": self.edge_vs_books,
            "edge_vs_prediction": self.edge_vs_prediction,
            "stance": self.stance,
            "max_edge": self.max_edge,
            "active_plans": self.active_plans,
            "state": self.state,
            "last_update_ts": self.last_update_ts,
            "arbitrage_flag": self.arbitrage_flag,
        }


@dataclass
class LiveBetPlan:
    """Edge-gated betting plan — similar to PredictionPlan but for straight bets."""
    id: str = ""
    event_id: str = ""
    outcome_id: str = ""
    outcome_name: str = ""
    market_type: str = "moneyline"
    direction: str = "back"       # "back" or "lay"
    stake_usd: float = 100.0
    min_edge_vs_books: float = 0.03
    min_edge_vs_prediction: float = 0.0
    max_odds_age_seconds: float = 30.0    # for live: odds must be fresh
    max_line_move_tolerance: float = 0.03  # reject if line moved > 3%
    confidence: float = 0.5
    supporting_agents: List[str] = field(default_factory=list)
    status: str = "proposed"       # proposed / approved / placed / settled / cancelled
    placed_odds: float = 0.0       # decimal odds at placement
    placed_at: float = 0.0
    settled_at: float = 0.0
    pnl_usd: float = 0.0
    created_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = f"bet-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "event_id": self.event_id,
            "outcome_id": self.outcome_id, "outcome_name": self.outcome_name,
            "market_type": self.market_type, "direction": self.direction,
            "stake_usd": self.stake_usd,
            "min_edge_vs_books": self.min_edge_vs_books,
            "min_edge_vs_prediction": self.min_edge_vs_prediction,
            "max_odds_age_seconds": self.max_odds_age_seconds,
            "confidence": round(self.confidence, 4),
            "supporting_agents": self.supporting_agents,
            "status": self.status,
            "placed_odds": self.placed_odds,
            "placed_at": self.placed_at, "settled_at": self.settled_at,
            "pnl_usd": round(self.pnl_usd, 2),
            "created_at": self.created_at,
        }


@dataclass
class SettledBet:
    """Resolved bet — outcome known, PnL computed."""
    bet_id: str = ""
    event_id: str = ""
    outcome_id: str = ""
    stake_usd: float = 0.0
    placed_odds: float = 0.0
    result: str = "pending"   # won / lost / push
    pnl_usd: float = 0.0
    settled_at: float = 0.0

    def __post_init__(self):
        if not self.settled_at:
            self.settled_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bet_id": self.bet_id, "event_id": self.event_id,
            "outcome_id": self.outcome_id, "stake_usd": self.stake_usd,
            "placed_odds": self.placed_odds, "result": self.result,
            "pnl_usd": round(self.pnl_usd, 2), "settled_at": self.settled_at,
        }


# ── Helpers ───────────────────────────────────────────────────────────

def american_to_decimal(american: int) -> float:
    """Convert American odds to decimal odds."""
    if american > 0:
        return 1.0 + american / 100.0
    elif american < 0:
        return 1.0 + 100.0 / abs(american)
    return 1.0


def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability (includes vig)."""
    if decimal_odds <= 0:
        return 0.0
    return 1.0 / decimal_odds


def remove_vig(raw_probs: List[float]) -> List[float]:
    """Remove vig (overround) from a set of raw implied probabilities.

    Proportional method: scale each probability so they sum to 1.0.
    """
    total = sum(raw_probs)
    if total <= 0:
        return [1.0 / len(raw_probs)] * len(raw_probs) if raw_probs else []
    return [p / total for p in raw_probs]


def classify_betting_stance(
    max_edge: float,
    swarm_prob: Dict[str, float],
    book_prob: Dict[str, float],
) -> str:
    """Classify overall stance based on max edge magnitude."""
    if max_edge >= 0.10:
        # Check direction: is swarm higher on any outcome?
        for oid in swarm_prob:
            diff = swarm_prob.get(oid, 0.5) - book_prob.get(oid, 0.5)
            if abs(diff) >= 0.10:
                return "strong_yes" if diff > 0 else "strong_no"
        return "strong_yes"
    elif max_edge >= 0.03:
        for oid in swarm_prob:
            diff = swarm_prob.get(oid, 0.5) - book_prob.get(oid, 0.5)
            if abs(diff) >= 0.03:
                return "weak_yes" if diff > 0 else "weak_no"
        return "weak_yes"
    return "neutral"
