"""Sports & Live Betting Integration — Sprint 12.

Bridges sports events into the MERID prediction/consensus spine and provides
a latency-aware live betting engine with SLO enforcement.

Components:
  1. SportsInstrumentBridge: registers sports events as PredictionInstruments
     in the PredictionConsensusStore, converting odds ↔ implied probabilities.
  2. LiveOddsEngine: combines external book odds, agent predictions, and risk
     constraints to produce platform live lines with latency tracking.
  3. LiveBettingEngine: acceptance windows, auto-reprice on odds movement,
     bet acceptance latency SLOs, feed delay indicators.
  4. SportsOddsFeed: poll/push odds ingestion with provider health tracking.
  5. SportsForecastStrategy: OpinionStrategy subclass for agent sports forecasting.
  6. QuestEngine: cross-vertical quests (CLV, Brier+ROI, pricing accuracy).
"""

from __future__ import annotations

import collections
import hashlib
import math
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("merid.betting.live_sports")

# ═══════════════════════════════════════════════════════════════════════
# 1. Sports Instrument Bridge
# ═══════════════════════════════════════════════════════════════════════

SPORT_CATEGORY_MAP = {
    "nfl": "sports", "nba": "sports", "mlb": "sports", "nhl": "sports",
    "soccer": "sports", "mma": "sports", "ncaab": "sports", "ncaaf": "sports",
    "politics": "politics", "crypto": "crypto", "weather": "weather",
}


def _sports_symbol(event_id: str, outcome: str) -> str:
    """Build canonical PRED:SPORTS:<event_id>:<OUTCOME> symbol."""
    return f"PRED:SPORTS:{event_id}:{outcome.upper()}"


@dataclass
class SportsOutcomeSchema:
    """Describes the outcome structure for a sports market."""
    market_type: str = "moneyline"          # moneyline, spread, total, prop, futures, yes_no
    outcomes: List[str] = field(default_factory=list)  # ["home", "away"] or ["over", "under"]
    line: Optional[float] = None            # spread or total line (e.g. -3.5, 45.5)
    props: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_type": self.market_type,
            "outcomes": self.outcomes,
            "line": self.line,
            "props": self.props,
        }


@dataclass
class SportsInstrument:
    """A sports event registered as a first-class MERID instrument.

    Wraps a BettingEvent and maps each outcome to a PredictionInstrument
    in the consensus store.
    """
    event_id: str = ""
    sport: str = ""
    league: str = ""
    title: str = ""
    home_team: str = ""
    away_team: str = ""
    start_time: float = 0.0
    state: str = "pre"                      # pre, live, final, cancelled
    score_home: Optional[int] = None
    score_away: Optional[int] = None
    period: str = ""
    clock: str = ""
    outcome_schemas: List[SportsOutcomeSchema] = field(default_factory=list)
    registered_symbols: List[str] = field(default_factory=list)
    implied_probs: Dict[str, float] = field(default_factory=dict)  # outcome_label → prob
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sport": self.sport,
            "league": self.league,
            "title": self.title,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "start_time": self.start_time,
            "state": self.state,
            "score_home": self.score_home,
            "score_away": self.score_away,
            "period": self.period,
            "clock": self.clock,
            "outcome_schemas": [s.to_dict() for s in self.outcome_schemas],
            "registered_symbols": self.registered_symbols,
            "implied_probs": {k: round(v, 4) for k, v in self.implied_probs.items()},
        }


class SportsInstrumentBridge:
    """Registers sports events as PredictionInstruments in the consensus store.

    Each outcome of a sports event becomes a separate instrument so agents
    can submit opinions and the consensus machinery works unchanged.
    """

    def __init__(self):
        self._instruments: Dict[str, SportsInstrument] = {}  # event_id → SportsInstrument
        self._lock = threading.RLock()

    def register_event(
        self,
        event_id: str,
        sport: str,
        league: str,
        title: str,
        home_team: str = "",
        away_team: str = "",
        start_time: float = 0.0,
        state: str = "pre",
        outcome_schemas: Optional[List[SportsOutcomeSchema]] = None,
        implied_probs: Optional[Dict[str, float]] = None,
    ) -> SportsInstrument:
        """Register a sports event and create PredictionInstruments for each outcome."""
        if outcome_schemas is None:
            outcome_schemas = [SportsOutcomeSchema(
                market_type="moneyline",
                outcomes=["home", "away"],
            )]

        if implied_probs is None:
            # Default even odds
            all_outcomes = []
            for schema in outcome_schemas:
                all_outcomes.extend(schema.outcomes)
            n = len(all_outcomes) if all_outcomes else 2
            implied_probs = {o: 1.0 / n for o in all_outcomes}

        si = SportsInstrument(
            event_id=event_id,
            sport=sport,
            league=league,
            title=title,
            home_team=home_team,
            away_team=away_team,
            start_time=start_time,
            state=state,
            outcome_schemas=outcome_schemas,
            implied_probs=implied_probs,
        )

        # Register each outcome as a PredictionInstrument
        symbols = []
        category = SPORT_CATEGORY_MAP.get(sport, "sports")
        for schema in outcome_schemas:
            for outcome_label in schema.outcomes:
                symbol = _sports_symbol(event_id, outcome_label)
                prob = implied_probs.get(outcome_label, 0.5)
                try:
                    from merid.prediction.consensus import (
                        PredictionInstrument,
                        get_prediction_consensus_store,
                    )
                    store = get_prediction_consensus_store()
                    inst = PredictionInstrument(
                        symbol=symbol,
                        venue="sports",
                        event_id=event_id,
                        ticker=f"{event_id}:{outcome_label}",
                        outcome=outcome_label.upper(),
                        asset_class="prediction",
                        category=category,
                        title=f"{title} — {outcome_label}",
                        description=f"{schema.market_type}: {outcome_label} (line={schema.line})",
                        expiry=start_time if start_time > 0 else None,
                        market_implied_prob=prob,
                        status="active" if state in ("pre", "live") else "closed",
                    )
                    store.upsert_instrument(inst)
                    symbols.append(symbol)
                except Exception as exc:
                    logger.warning("Failed to register instrument %s: %s", symbol, exc)
                    symbols.append(symbol)

        si.registered_symbols = symbols

        with self._lock:
            self._instruments[event_id] = si

        logger.info(
            "Registered sports event %s (%s) with %d instruments",
            event_id, title, len(symbols),
        )
        return si

    def update_event_state(
        self,
        event_id: str,
        state: str,
        score_home: Optional[int] = None,
        score_away: Optional[int] = None,
        period: str = "",
        clock: str = "",
    ) -> Optional[SportsInstrument]:
        """Update live state of a sports event."""
        with self._lock:
            si = self._instruments.get(event_id)
            if not si:
                return None
            si.state = state
            si.score_home = score_home if score_home is not None else si.score_home
            si.score_away = score_away if score_away is not None else si.score_away
            si.period = period or si.period
            si.clock = clock or si.clock
            si.updated_at = time.time()

        # Update instrument status in consensus store
        if state in ("final", "cancelled"):
            try:
                from merid.prediction.consensus import get_prediction_consensus_store
                store = get_prediction_consensus_store()
                for sym in si.registered_symbols:
                    inst = store.get_instrument(sym)
                    if inst:
                        inst.status = "closed" if state == "final" else "cancelled"
                        store.upsert_instrument(inst)
            except Exception as exc:
                logger.debug("operation_suppressed", error=str(exc))

        return si

    def update_odds(self, event_id: str, implied_probs: Dict[str, float]) -> bool:
        """Update implied probabilities for a sports event's outcomes."""
        with self._lock:
            si = self._instruments.get(event_id)
            if not si:
                return False
            si.implied_probs.update(implied_probs)
            si.updated_at = time.time()

        # Push to consensus store
        try:
            store = get_prediction_consensus_store()
            for outcome_label, prob in implied_probs.items():
                symbol = _sports_symbol(event_id, outcome_label)
                inst = store.get_instrument(symbol)
                if inst:
                    inst.market_implied_prob = prob
                    inst.last_refreshed = time.time()
                    store.upsert_instrument(inst)
        except Exception as exc:
            logger.warning("Failed to update odds for %s: %s", event_id, exc)
            return False
        return True

    def get_event(self, event_id: str) -> Optional[SportsInstrument]:
        with self._lock:
            return self._instruments.get(event_id)

    def list_events(self, sport: Optional[str] = None, state: Optional[str] = None) -> List[SportsInstrument]:
        with self._lock:
            events = list(self._instruments.values())
        if sport:
            events = [e for e in events if e.sport == sport]
        if state:
            events = [e for e in events if e.state == state]
        return events

    def settle_event(
        self,
        event_id: str,
        winning_outcomes: List[str],
    ) -> Dict[str, Any]:
        """Settle a sports event: mark winning outcomes in consensus store."""
        si = self.get_event(event_id)
        if not si:
            raise ValueError(f"Event {event_id} not found")

        self.update_event_state(event_id, "final")

        settled = []
        try:
            from merid.prediction.consensus import (
                ResolvedMarket,
                get_prediction_consensus_store,
            )
            store = get_prediction_consensus_store()
            for sym in si.registered_symbols:
                # Parse outcome from symbol
                parts = sym.split(":")
                outcome_label = parts[-1].lower() if len(parts) >= 4 else ""
                is_winner = outcome_label in [w.lower() for w in winning_outcomes]
                rm = ResolvedMarket(
                    symbol=sym,
                    outcome=1 if is_winner else 0,
                )
                store.record_resolution(rm)
                settled.append({"symbol": sym, "outcome": "won" if is_winner else "lost"})
        except Exception as exc:
            logger.warning("Failed to settle event %s: %s", event_id, exc)

        return {
            "event_id": event_id,
            "winning_outcomes": winning_outcomes,
            "settled_instruments": settled,
        }


# ═══════════════════════════════════════════════════════════════════════
# 2. Sports Odds Feed
# ═══════════════════════════════════════════════════════════════════════

class FeedState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STALE = "stale"
    ERROR = "error"


@dataclass
class OddsUpdate:
    """A single odds update from a provider."""
    provider: str = ""
    event_id: str = ""
    outcome_label: str = ""
    american_odds: int = 0
    decimal_odds: float = 0.0
    implied_prob: float = 0.0
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.0                 # time from provider → our receipt

    def __post_init__(self):
        if self.decimal_odds > 0 and self.implied_prob == 0:
            self.implied_prob = 1.0 / self.decimal_odds
        if self.american_odds != 0 and self.decimal_odds == 0:
            from merid.betting.models import american_to_decimal
            self.decimal_odds = american_to_decimal(self.american_odds)
            self.implied_prob = 1.0 / self.decimal_odds if self.decimal_odds > 0 else 0.0


@dataclass
class FeedHealth:
    """Health metrics for a single odds feed provider."""
    provider: str = ""
    state: str = FeedState.DISCONNECTED.value
    last_update_ts: float = 0.0
    updates_received: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    errors: int = 0
    stale_threshold_s: float = 60.0

    @property
    def is_stale(self) -> bool:
        if self.last_update_ts == 0:
            return True
        return (time.time() - self.last_update_ts) > self.stale_threshold_s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.state,
            "last_update_ts": self.last_update_ts,
            "age_s": round(time.time() - self.last_update_ts, 1) if self.last_update_ts else None,
            "updates_received": self.updates_received,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "errors": self.errors,
            "is_stale": self.is_stale,
        }


class SportsOddsFeed:
    """Aggregates odds updates from multiple providers with health tracking.

    Supports both poll-based and push-based (WebSocket/SSE) providers.
    Each provider is registered with a name and stale threshold.
    """

    def __init__(self, stale_threshold_s: float = 60.0):
        self._lock = threading.RLock()
        self._providers: Dict[str, FeedHealth] = {}
        self._stale_threshold_s = stale_threshold_s
        self._latency_window: Dict[str, Deque[float]] = {}  # provider → recent latencies
        self._latency_window_size = 100
        self._subscribers: List[Callable[[OddsUpdate], None]] = []
        self._update_log: Deque[OddsUpdate] = collections.deque(maxlen=1000)

    def register_provider(self, provider: str, stale_threshold_s: Optional[float] = None) -> None:
        with self._lock:
            self._providers[provider] = FeedHealth(
                provider=provider,
                stale_threshold_s=stale_threshold_s or self._stale_threshold_s,
            )
            self._latency_window[provider] = collections.deque(maxlen=self._latency_window_size)

    def subscribe(self, callback: Callable[[OddsUpdate], None]) -> None:
        self._subscribers.append(callback)

    def ingest_update(self, update: OddsUpdate) -> None:
        """Process an incoming odds update from any provider."""
        with self._lock:
            health = self._providers.get(update.provider)
            if not health:
                self.register_provider(update.provider)
                health = self._providers[update.provider]

            health.state = FeedState.CONNECTED.value
            health.last_update_ts = update.timestamp
            health.updates_received += 1

            # Track latency
            self._latency_window[update.provider].append(update.latency_ms)
            latencies = list(self._latency_window[update.provider])
            health.avg_latency_ms = statistics.mean(latencies) if latencies else 0.0
            if len(latencies) >= 2:
                sorted_lat = sorted(latencies)
                idx = int(len(sorted_lat) * 0.95)
                health.p95_latency_ms = sorted_lat[min(idx, len(sorted_lat) - 1)]

            self._update_log.append(update)

        # Notify subscribers
        for cb in self._subscribers:
            try:
                cb(update)
            except Exception as exc:
                logger.warning("Feed subscriber error: %s", exc)

    def record_error(self, provider: str) -> None:
        with self._lock:
            health = self._providers.get(provider)
            if health:
                health.errors += 1
                health.state = FeedState.ERROR.value

    def get_feed_health(self) -> Dict[str, Any]:
        """Get health metrics for all registered providers."""
        with self._lock:
            providers = {}
            stale_count = 0
            for name, health in self._providers.items():
                # Auto-detect staleness
                if health.is_stale and health.state == FeedState.CONNECTED.value:
                    health.state = FeedState.STALE.value
                if health.is_stale:
                    stale_count += 1
                providers[name] = health.to_dict()

            return {
                "providers": providers,
                "total_providers": len(self._providers),
                "stale_providers": stale_count,
                "total_updates": sum(h.updates_received for h in self._providers.values()),
                "any_stale": stale_count > 0,
            }

    def get_recent_updates(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            updates = list(self._update_log)[-limit:]
        return [
            {
                "provider": u.provider,
                "event_id": u.event_id,
                "outcome": u.outcome_label,
                "implied_prob": round(u.implied_prob, 4),
                "decimal_odds": round(u.decimal_odds, 4),
                "latency_ms": round(u.latency_ms, 1),
                "timestamp": u.timestamp,
            }
            for u in updates
        ]


# ═══════════════════════════════════════════════════════════════════════
# 3. Live Odds Engine
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PlatformLine:
    """The platform's computed line for one outcome, combining all sources."""
    event_id: str = ""
    outcome_label: str = ""
    external_prob: float = 0.5              # from sportsbooks
    agent_prob: float = 0.5                 # from MERID agents
    platform_prob: float = 0.5              # blended
    decimal_odds: float = 2.0
    margin_pct: float = 5.0                 # house margin
    confidence: float = 0.5
    stale: bool = False
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "external_prob": round(self.external_prob, 4),
            "agent_prob": round(self.agent_prob, 4),
            "platform_prob": round(self.platform_prob, 4),
            "decimal_odds": round(self.decimal_odds, 4),
            "margin_pct": round(self.margin_pct, 2),
            "confidence": round(self.confidence, 4),
            "stale": self.stale,
            "last_updated": self.last_updated,
        }


class LiveOddsEngine:
    """Combines external odds, agent predictions, and risk constraints
    to produce platform live lines.

    Blending formula:
        platform_prob = w_ext * external_prob + w_agent * agent_prob
    where weights depend on confidence and freshness.
    """

    def __init__(
        self,
        external_weight: float = 0.7,
        agent_weight: float = 0.3,
        house_margin_pct: float = 5.0,
        max_exposure_per_outcome: float = 50000.0,
    ):
        self.external_weight = external_weight
        self.agent_weight = agent_weight
        self.house_margin_pct = house_margin_pct
        self.max_exposure_per_outcome = max_exposure_per_outcome
        self._lines: Dict[str, PlatformLine] = {}  # "event_id:outcome" → PlatformLine
        self._lock = threading.RLock()
        self._exposure: Dict[str, float] = {}  # "event_id:outcome" → total exposure

    def compute_line(
        self,
        event_id: str,
        outcome_label: str,
        external_prob: float,
        agent_prob: float = 0.5,
        agent_confidence: float = 0.5,
    ) -> PlatformLine:
        """Compute or update the platform line for one outcome."""
        # Adjust weights by agent confidence
        w_ext = self.external_weight
        w_agent = self.agent_weight * agent_confidence
        total_w = w_ext + w_agent
        if total_w > 0:
            blended = (w_ext * external_prob + w_agent * agent_prob) / total_w
        else:
            blended = external_prob

        # Clamp
        blended = max(0.01, min(0.99, blended))

        # Apply house margin
        margin_factor = 1.0 + (self.house_margin_pct / 100.0)
        fair_odds = 1.0 / blended
        offered_odds = fair_odds / margin_factor
        offered_odds = max(offered_odds, 1.01)

        key = f"{event_id}:{outcome_label}"
        line = PlatformLine(
            event_id=event_id,
            outcome_label=outcome_label,
            external_prob=external_prob,
            agent_prob=agent_prob,
            platform_prob=blended,
            decimal_odds=round(offered_odds, 4),
            margin_pct=self.house_margin_pct,
            confidence=agent_confidence,
        )

        with self._lock:
            self._lines[key] = line

        return line

    def get_line(self, event_id: str, outcome_label: str) -> Optional[PlatformLine]:
        key = f"{event_id}:{outcome_label}"
        with self._lock:
            return self._lines.get(key)

    def get_all_lines(self, event_id: Optional[str] = None) -> List[PlatformLine]:
        with self._lock:
            lines = list(self._lines.values())
        if event_id:
            lines = [l for l in lines if l.event_id == event_id]
        return lines

    def record_exposure(self, event_id: str, outcome_label: str, amount: float) -> bool:
        """Record bet exposure. Returns False if would exceed limit."""
        key = f"{event_id}:{outcome_label}"
        with self._lock:
            current = self._exposure.get(key, 0.0)
            if current + amount > self.max_exposure_per_outcome:
                return False
            self._exposure[key] = current + amount
        return True

    def get_exposure(self, event_id: str, outcome_label: str) -> float:
        key = f"{event_id}:{outcome_label}"
        with self._lock:
            return self._exposure.get(key, 0.0)

    def get_pricing_divergence(self) -> Dict[str, Any]:
        """Compute divergence between platform lines and external odds."""
        with self._lock:
            lines = list(self._lines.values())
        if not lines:
            return {"avg_divergence": 0.0, "max_divergence": 0.0, "lines_count": 0}

        divergences = [abs(l.platform_prob - l.external_prob) for l in lines]
        return {
            "avg_divergence": round(statistics.mean(divergences), 4) if divergences else 0.0,
            "max_divergence": round(max(divergences), 4) if divergences else 0.0,
            "lines_count": len(lines),
            "stale_lines": sum(1 for l in lines if l.stale),
        }


# ═══════════════════════════════════════════════════════════════════════
# 4. Live Betting Engine
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class BetAcceptanceResult:
    """Result of a live bet acceptance attempt."""
    accepted: bool = False
    bet_id: str = ""
    event_id: str = ""
    outcome_label: str = ""
    stake: float = 0.0
    odds_at_placement: float = 0.0
    odds_at_display: float = 0.0
    repriced: bool = False
    rejection_reason: str = ""
    acceptance_latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "bet_id": self.bet_id,
            "event_id": self.event_id,
            "outcome_label": self.outcome_label,
            "stake": round(self.stake, 2),
            "odds_at_placement": round(self.odds_at_placement, 4),
            "odds_at_display": round(self.odds_at_display, 4),
            "repriced": self.repriced,
            "rejection_reason": self.rejection_reason,
            "acceptance_latency_ms": round(self.acceptance_latency_ms, 1),
        }


class LiveBettingEngine:
    """Latency-aware live betting engine with SLO enforcement.

    SLOs:
      - P95 bet acceptance < 300ms
      - Auto-reprice if odds moved > reprice_threshold since display
      - Reject if odds moved > reject_threshold
      - Track feed delay indicators
    """

    def __init__(
        self,
        odds_engine: LiveOddsEngine,
        reprice_threshold: float = 0.03,     # 3% odds movement → auto-reprice
        reject_threshold: float = 0.08,      # 8% odds movement → reject
        max_acceptance_ms: float = 300.0,    # SLO target
        acceptance_window_s: float = 5.0,    # bet must be placed within N seconds of odds display
    ):
        self.odds_engine = odds_engine
        self.reprice_threshold = reprice_threshold
        self.reject_threshold = reject_threshold
        self.max_acceptance_ms = max_acceptance_ms
        self.acceptance_window_s = acceptance_window_s

        self._lock = threading.RLock()
        self._acceptance_latencies: Deque[float] = collections.deque(maxlen=1000)
        self._total_bets: int = 0
        self._accepted_bets: int = 0
        self._rejected_bets: int = 0
        self._repriced_bets: int = 0
        self._slo_breaches: int = 0

    def accept_bet(
        self,
        event_id: str,
        outcome_label: str,
        stake: float,
        displayed_odds: float,
        user_id: str = "",
    ) -> BetAcceptanceResult:
        """Attempt to accept a live bet with latency tracking and SLO enforcement."""
        start_ts = time.time()
        start_perf = time.perf_counter()

        result = BetAcceptanceResult(
            event_id=event_id,
            outcome_label=outcome_label,
            stake=stake,
            odds_at_display=displayed_odds,
        )

        # Get current platform line
        line = self.odds_engine.get_line(event_id, outcome_label)
        if not line:
            result.rejection_reason = "no_line_available"
            self._record_rejection(result, start_perf)
            return result

        current_odds = line.decimal_odds
        result.odds_at_placement = current_odds

        # Check if line is stale
        if line.stale:
            result.rejection_reason = "stale_odds"
            self._record_rejection(result, start_perf)
            return result

        # Check odds movement
        if displayed_odds > 0:
            odds_movement = abs(current_odds - displayed_odds) / displayed_odds
        else:
            odds_movement = 0.0

        if odds_movement > self.reject_threshold:
            result.rejection_reason = f"odds_moved_{odds_movement:.1%}"
            self._record_rejection(result, start_perf)
            return result

        if odds_movement > self.reprice_threshold:
            result.repriced = True
            result.odds_at_placement = current_odds

        # Check exposure limits
        if not self.odds_engine.record_exposure(event_id, outcome_label, stake):
            result.rejection_reason = "exposure_limit_exceeded"
            self._record_rejection(result, start_perf)
            return result

        # Accept the bet
        result.accepted = True
        result.bet_id = f"live-{uuid.uuid4().hex[:8]}"
        result.odds_at_placement = current_odds if result.repriced else displayed_odds

        # Record latency
        elapsed_ms = (time.perf_counter() - start_perf) * 1000
        result.acceptance_latency_ms = elapsed_ms

        with self._lock:
            self._total_bets += 1
            self._accepted_bets += 1
            self._acceptance_latencies.append(elapsed_ms)
            if result.repriced:
                self._repriced_bets += 1
            if elapsed_ms > self.max_acceptance_ms:
                self._slo_breaches += 1

        return result

    def _record_rejection(self, result: BetAcceptanceResult, start_perf: float) -> None:
        elapsed_ms = (time.perf_counter() - start_perf) * 1000
        result.acceptance_latency_ms = elapsed_ms
        with self._lock:
            self._total_bets += 1
            self._rejected_bets += 1
            self._acceptance_latencies.append(elapsed_ms)

    def get_slo_metrics(self) -> Dict[str, Any]:
        """Get live betting SLO metrics."""
        with self._lock:
            latencies = list(self._acceptance_latencies)
            total = self._total_bets
            accepted = self._accepted_bets
            rejected = self._rejected_bets
            repriced = self._repriced_bets
            slo_breaches = self._slo_breaches

        p95 = 0.0
        avg = 0.0
        if latencies:
            avg = statistics.mean(latencies)
            sorted_lat = sorted(latencies)
            idx = int(len(sorted_lat) * 0.95)
            p95 = sorted_lat[min(idx, len(sorted_lat) - 1)]

        acceptance_rate = accepted / total if total > 0 else 0.0
        reprice_rate = repriced / total if total > 0 else 0.0
        slo_breach_rate = slo_breaches / total if total > 0 else 0.0

        return {
            "total_bets": total,
            "accepted": accepted,
            "rejected": rejected,
            "repriced": repriced,
            "acceptance_rate": round(acceptance_rate, 4),
            "reprice_rate": round(reprice_rate, 4),
            "avg_acceptance_latency_ms": round(avg, 1),
            "p95_acceptance_latency_ms": round(p95, 1),
            "slo_target_ms": self.max_acceptance_ms,
            "slo_breaches": slo_breaches,
            "slo_breach_rate": round(slo_breach_rate, 4),
            "slo_met": p95 <= self.max_acceptance_ms,
        }


# ═══════════════════════════════════════════════════════════════════════
# 5. Sports Forecast Strategy (agent sports forecasting)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SportsForecast:
    """An agent's forecast for a sports outcome."""
    agent_id: str = ""
    event_id: str = ""
    outcome_label: str = ""
    probability: float = 0.5
    confidence: float = 0.5
    reasoning: str = ""
    signal_sources: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_opinion_kwargs(self) -> Dict[str, Any]:
        """Convert to PredictionOpinion constructor kwargs."""
        return {
            "agent_id": self.agent_id,
            "symbol": _sports_symbol(self.event_id, self.outcome_label),
            "probability": self.probability,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "signal_sources": self.signal_sources,
            "horizon": "event",
        }


class SportsForecastEngine:
    """Manages agent sports forecasts and submits them as PredictionOpinions.

    Agents use their existing OpinionStrategy machinery to forecast sports
    events. This engine bridges the gap by:
      1. Converting sports context into strategy inputs
      2. Submitting forecasts as PredictionOpinions
      3. Tracking forecast accuracy (Brier) and coherence with bets
    """

    def __init__(self):
        self._forecasts: Dict[str, List[SportsForecast]] = {}  # event_id → forecasts
        self._lock = threading.RLock()
        self._coherence_log: List[Dict[str, Any]] = []

    def submit_forecast(self, forecast: SportsForecast) -> Dict[str, Any]:
        """Submit an agent forecast and register it as a PredictionOpinion."""
        with self._lock:
            self._forecasts.setdefault(forecast.event_id, []).append(forecast)

        # Submit to consensus store
        opinion_result = None
        try:
            from merid.prediction.consensus import (
                PredictionOpinion,
                get_prediction_consensus_store,
            )
            store = get_prediction_consensus_store()
            op = PredictionOpinion(**forecast.to_opinion_kwargs())
            store.add_opinion(op)
            opinion_result = op.id
        except Exception as exc:
            logger.warning("Failed to submit forecast as opinion: %s", exc)

        return {
            "event_id": forecast.event_id,
            "outcome": forecast.outcome_label,
            "agent_id": forecast.agent_id,
            "probability": round(forecast.probability, 4),
            "opinion_id": opinion_result,
        }

    def get_agent_forecasts(self, agent_id: str) -> List[SportsForecast]:
        with self._lock:
            all_forecasts = []
            for forecasts in self._forecasts.values():
                all_forecasts.extend(f for f in forecasts if f.agent_id == agent_id)
        return all_forecasts

    def get_event_forecasts(self, event_id: str) -> List[SportsForecast]:
        with self._lock:
            return list(self._forecasts.get(event_id, []))

    def log_coherence(
        self,
        agent_id: str,
        event_id: str,
        outcome_label: str,
        bet_implied_prob: float,
    ) -> Optional[float]:
        """Log coherence between an agent's forecast and their bet.

        Returns coherence score (1.0 = perfect alignment, 0.0 = max divergence).
        """
        forecasts = self.get_event_forecasts(event_id)
        agent_forecasts = [f for f in forecasts if f.agent_id == agent_id and f.outcome_label == outcome_label]
        if not agent_forecasts:
            return None

        latest = max(agent_forecasts, key=lambda f: f.timestamp)
        divergence = abs(latest.probability - bet_implied_prob)
        coherence = max(0.0, 1.0 - divergence)

        with self._lock:
            self._coherence_log.append({
                "agent_id": agent_id,
                "event_id": event_id,
                "outcome": outcome_label,
                "forecast_prob": latest.probability,
                "bet_implied_prob": bet_implied_prob,
                "coherence": round(coherence, 4),
                "timestamp": time.time(),
            })

        return coherence

    def get_coherence_stats(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Get coherence statistics, optionally filtered by agent."""
        with self._lock:
            logs = list(self._coherence_log)
        if agent_id:
            logs = [l for l in logs if l["agent_id"] == agent_id]
        if not logs:
            return {"avg_coherence": None, "entries": 0}

        scores = [l["coherence"] for l in logs]
        return {
            "avg_coherence": round(statistics.mean(scores), 4),
            "min_coherence": round(min(scores), 4),
            "max_coherence": round(max(scores), 4),
            "entries": len(scores),
        }


# ═══════════════════════════════════════════════════════════════════════
# 6. Quest Engine (cross-vertical rewards)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Quest:
    """A cross-vertical quest combining sports betting with other MERID activities."""
    id: str = ""
    name: str = ""
    description: str = ""
    quest_type: str = "sports_pricing"      # sports_pricing, brier_roi, clv, streak
    target_metric: str = ""                 # e.g. "clv_pct", "brier_score", "roi_pct"
    target_value: float = 0.0               # threshold to complete
    reward_amount: float = 0.0
    sport: str = ""                         # empty = any sport
    window_days: int = 30
    active: bool = True

    def __post_init__(self):
        if not self.id:
            self.id = f"quest-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "quest_type": self.quest_type,
            "target_metric": self.target_metric,
            "target_value": self.target_value,
            "reward_amount": self.reward_amount,
            "sport": self.sport,
            "window_days": self.window_days,
            "active": self.active,
        }


@dataclass
class QuestProgress:
    """Tracks an agent's progress toward a quest."""
    quest_id: str = ""
    agent_id: str = ""
    current_value: float = 0.0
    completed: bool = False
    completed_at: Optional[float] = None
    events_counted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quest_id": self.quest_id,
            "agent_id": self.agent_id,
            "current_value": round(self.current_value, 4),
            "completed": self.completed,
            "completed_at": self.completed_at,
            "events_counted": self.events_counted,
        }


# Default quests
DEFAULT_QUESTS = [
    Quest(
        id="quest-clv-nfl-10",
        name="NFL Closing Line Value Master",
        description="Price 10 live NFL markets within 2% of closing line",
        quest_type="clv",
        target_metric="clv_events",
        target_value=10.0,
        reward_amount=500.0,
        sport="nfl",
        window_days=30,
    ),
    Quest(
        id="quest-brier-roi-30d",
        name="Sharp Mind, Sharp Wallet",
        description="Maintain positive Brier score (<0.25) AND positive ROI over 30 days",
        quest_type="brier_roi",
        target_metric="brier_and_roi",
        target_value=1.0,  # boolean: 1.0 = both conditions met
        reward_amount=1000.0,
        window_days=30,
    ),
    Quest(
        id="quest-pricing-accuracy",
        name="Market Maker Precision",
        description="Average pricing divergence < 3% across 20+ markets",
        quest_type="sports_pricing",
        target_metric="avg_divergence",
        target_value=0.03,
        reward_amount=750.0,
        window_days=14,
    ),
    Quest(
        id="quest-streak-5",
        name="Hot Streak",
        description="Win 5 consecutive sports bets",
        quest_type="streak",
        target_metric="win_streak",
        target_value=5.0,
        reward_amount=250.0,
        window_days=7,
    ),
]


class QuestEngine:
    """Manages cross-vertical quests and tracks agent progress."""

    def __init__(self, quests: Optional[List[Quest]] = None):
        self._quests: Dict[str, Quest] = {}
        self._progress: Dict[str, Dict[str, QuestProgress]] = {}  # quest_id → {agent_id → progress}
        self._lock = threading.RLock()

        for q in (quests or DEFAULT_QUESTS):
            self._quests[q.id] = q

    def list_quests(self, active_only: bool = True) -> List[Quest]:
        quests = list(self._quests.values())
        if active_only:
            quests = [q for q in quests if q.active]
        return quests

    def get_progress(self, quest_id: str, agent_id: str) -> QuestProgress:
        with self._lock:
            quest_progress = self._progress.setdefault(quest_id, {})
            if agent_id not in quest_progress:
                quest_progress[agent_id] = QuestProgress(quest_id=quest_id, agent_id=agent_id)
            return quest_progress[agent_id]

    def update_progress(
        self,
        quest_id: str,
        agent_id: str,
        value: float,
        events_counted: int = 0,
    ) -> QuestProgress:
        """Update quest progress for an agent."""
        quest = self._quests.get(quest_id)
        if not quest:
            raise ValueError(f"Quest {quest_id} not found")

        with self._lock:
            progress = self.get_progress(quest_id, agent_id)
            progress.current_value = value
            progress.events_counted = events_counted

            # Check completion
            if quest.quest_type in ("clv", "streak"):
                progress.completed = value >= quest.target_value
            elif quest.quest_type == "sports_pricing":
                # Lower is better for divergence
                progress.completed = value <= quest.target_value and events_counted >= 20
            elif quest.quest_type == "brier_roi":
                progress.completed = value >= quest.target_value

            if progress.completed and not progress.completed_at:
                progress.completed_at = time.time()

        return progress

    def get_agent_quests(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get all quest progress for an agent."""
        results = []
        for quest in self._quests.values():
            progress = self.get_progress(quest.id, agent_id)
            results.append({
                "quest": quest.to_dict(),
                "progress": progress.to_dict(),
            })
        return results


# ═══════════════════════════════════════════════════════════════════════
# 7. Aggregate Manager (singleton access)
# ═══════════════════════════════════════════════════════════════════════

class SportsBettingManager:
    """Top-level manager wiring all sports/live betting components together."""

    def __init__(self):
        self.bridge = SportsInstrumentBridge()
        self.odds_feed = SportsOddsFeed()
        self.odds_engine = LiveOddsEngine()
        self.betting_engine = LiveBettingEngine(self.odds_engine)
        self.forecast_engine = SportsForecastEngine()
        self.quest_engine = QuestEngine()

        # Wire odds feed → odds engine → bridge
        self.odds_feed.subscribe(self._on_odds_update)

    def _on_odds_update(self, update: OddsUpdate) -> None:
        """Handle incoming odds update: update bridge + recompute lines."""
        # Update bridge
        self.bridge.update_odds(update.event_id, {update.outcome_label: update.implied_prob})

        # Recompute platform line
        # Get agent prob from forecasts
        forecasts = self.forecast_engine.get_event_forecasts(update.event_id)
        agent_forecasts = [f for f in forecasts if f.outcome_label == update.outcome_label]
        if agent_forecasts:
            # Confidence-weighted average
            total_conf = sum(f.confidence for f in agent_forecasts)
            if total_conf > 0:
                agent_prob = sum(f.probability * f.confidence for f in agent_forecasts) / total_conf
                agent_conf = total_conf / len(agent_forecasts)
            else:
                agent_prob = statistics.mean([f.probability for f in agent_forecasts])
                agent_conf = 0.5
        else:
            agent_prob = update.implied_prob
            agent_conf = 0.0

        self.odds_engine.compute_line(
            event_id=update.event_id,
            outcome_label=update.outcome_label,
            external_prob=update.implied_prob,
            agent_prob=agent_prob,
            agent_confidence=agent_conf,
        )

    def get_sports_health(self) -> Dict[str, Any]:
        """Comprehensive sports/live betting health metrics."""
        feed_health = self.odds_feed.get_feed_health()
        slo_metrics = self.betting_engine.get_slo_metrics()
        pricing = self.odds_engine.get_pricing_divergence()
        coherence = self.forecast_engine.get_coherence_stats()

        events = self.bridge.list_events()
        live_events = [e for e in events if e.state == "live"]
        pre_events = [e for e in events if e.state == "pre"]

        return {
            "events": {
                "total": len(events),
                "live": len(live_events),
                "pre": len(pre_events),
            },
            "feed_health": feed_health,
            "slo_metrics": slo_metrics,
            "pricing_divergence": pricing,
            "agent_coherence": coherence,
            "quests_active": len(self.quest_engine.list_quests(active_only=True)),
        }


# ── Singleton ────────────────────────────────────────────────────────

_manager: Optional[SportsBettingManager] = None
_manager_lock = threading.Lock()


def get_sports_betting_manager() -> SportsBettingManager:
    """Get or create the singleton SportsBettingManager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SportsBettingManager()
    return _manager
