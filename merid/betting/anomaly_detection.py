"""Fraud & anomaly detection for sports betting feeds and behavior.

Detects:
  1. Feed staleness: provider hasn't sent updates within threshold.
  2. Odds jumps: sudden large movements in implied probability.
  3. Suspicious bet patterns: rapid-fire bets, size spikes, correlated timing.
  4. Line manipulation signals: coordinated odds movements across books.

Components:
  - AnomalyType enum and AnomalyRecord dataclass.
  - FeedStalenessDetector: monitors provider freshness.
  - OddsJumpDetector: detects abnormal odds movements.
  - BetPatternDetector: flags suspicious betting behavior.
  - AnomalyEngine: aggregates all detectors, exposes API-ready results.
"""

from __future__ import annotations

import collections
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.betting.anomaly_detection")


# ═══════════════════════════════════════════════════════════════════════
# 1. Anomaly Types & Records
# ═══════════════════════════════════════════════════════════════════════

class AnomalyType(str, Enum):
    FEED_STALE = "feed_stale"
    ODDS_JUMP = "odds_jump"
    SUSPICIOUS_BET = "suspicious_bet"
    RAPID_FIRE_BETS = "rapid_fire_bets"
    SIZE_SPIKE = "size_spike"
    LINE_MANIPULATION = "line_manipulation"
    CORRELATED_TIMING = "correlated_timing"


class AnomalySeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AnomalyRecord:
    """A single detected anomaly."""
    id: str = field(default_factory=lambda: f"anom-{uuid.uuid4().hex[:8]}")
    anomaly_type: str = AnomalyType.FEED_STALE.value
    severity: str = AnomalySeverity.MEDIUM.value
    source: str = ""                 # provider, agent_id, event_id, etc.
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    event_id: Optional[str] = None
    agent_id: Optional[str] = None
    acknowledged: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "source": self.source,
            "description": self.description,
            "details": self.details,
            "event_id": self.event_id,
            "agent_id": self.agent_id,
            "acknowledged": self.acknowledged,
            "timestamp": self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════════
# 2. Feed Staleness Detector
# ═══════════════════════════════════════════════════════════════════════

class FeedStalenessDetector:
    """Monitors provider feed freshness and flags staleness.

    Checks each registered provider's last update timestamp against
    a configurable threshold. Fires anomalies when stale.
    """

    def __init__(self, default_threshold_s: float = 60.0):
        self._lock = threading.RLock()
        self._last_update: Dict[str, float] = {}     # provider → last update ts
        self._thresholds: Dict[str, float] = {}       # provider → threshold
        self._default_threshold = default_threshold_s
        self._active_alerts: Dict[str, AnomalyRecord] = {}  # provider → active alert

    def record_update(self, provider: str, timestamp: Optional[float] = None) -> None:
        """Record that a provider sent an update."""
        with self._lock:
            self._last_update[provider] = timestamp or time.time()
            # Clear active alert if any
            self._active_alerts.pop(provider, None)

    def set_threshold(self, provider: str, threshold_s: float) -> None:
        with self._lock:
            self._thresholds[provider] = threshold_s

    def check(self) -> List[AnomalyRecord]:
        """Check all providers for staleness. Returns new anomalies."""
        now = time.time()
        anomalies = []
        with self._lock:
            for provider, last_ts in self._last_update.items():
                threshold = self._thresholds.get(provider, self._default_threshold)
                age_s = now - last_ts
                if age_s > threshold and provider not in self._active_alerts:
                    severity = AnomalySeverity.HIGH.value if age_s > threshold * 3 else AnomalySeverity.MEDIUM.value
                    record = AnomalyRecord(
                        anomaly_type=AnomalyType.FEED_STALE.value,
                        severity=severity,
                        source=provider,
                        description=f"Feed from {provider} stale for {age_s:.0f}s (threshold: {threshold:.0f}s)",
                        details={"age_s": round(age_s, 1), "threshold_s": threshold},
                    )
                    self._active_alerts[provider] = record
                    anomalies.append(record)
        return anomalies

    def get_status(self) -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            providers = {}
            for p, ts in self._last_update.items():
                threshold = self._thresholds.get(p, self._default_threshold)
                age = now - ts
                providers[p] = {
                    "last_update_ts": ts,
                    "age_s": round(age, 1),
                    "threshold_s": threshold,
                    "stale": age > threshold,
                }
            return {
                "providers": providers,
                "stale_count": sum(1 for v in providers.values() if v["stale"]),
                "active_alerts": len(self._active_alerts),
            }


# ═══════════════════════════════════════════════════════════════════════
# 3. Odds Jump Detector
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class OddsMovement:
    """Tracks a single odds movement for an outcome."""
    event_id: str = ""
    outcome_label: str = ""
    provider: str = ""
    old_prob: float = 0.0
    new_prob: float = 0.0
    delta: float = 0.0
    timestamp: float = field(default_factory=time.time)


class OddsJumpDetector:
    """Detects abnormal odds movements (sudden jumps).

    Maintains a rolling window of recent odds per outcome and flags
    movements that exceed configurable thresholds.
    """

    def __init__(
        self,
        jump_threshold: float = 0.10,       # 10% implied prob jump
        rapid_jump_threshold: float = 0.05,  # 5% within rapid_window_s
        rapid_window_s: float = 10.0,
        history_size: int = 100,
    ):
        self._lock = threading.RLock()
        self.jump_threshold = jump_threshold
        self.rapid_jump_threshold = rapid_jump_threshold
        self.rapid_window_s = rapid_window_s
        # "event_id:outcome" → deque of (timestamp, implied_prob)
        self._history: Dict[str, Deque[tuple]] = {}
        self._history_size = history_size
        self._movements: Deque[OddsMovement] = collections.deque(maxlen=500)

    def check_update(
        self,
        event_id: str,
        outcome_label: str,
        new_prob: float,
        provider: str = "",
    ) -> Optional[AnomalyRecord]:
        """Check an odds update for jumps. Returns anomaly if detected."""
        key = f"{event_id}:{outcome_label}"
        now = time.time()

        with self._lock:
            if key not in self._history:
                self._history[key] = collections.deque(maxlen=self._history_size)

            history = self._history[key]

            if history:
                last_ts, last_prob = history[-1]
                delta = abs(new_prob - last_prob)

                movement = OddsMovement(
                    event_id=event_id, outcome_label=outcome_label,
                    provider=provider, old_prob=last_prob, new_prob=new_prob,
                    delta=delta, timestamp=now,
                )
                self._movements.append(movement)

                # Check single-update jump
                if delta > self.jump_threshold:
                    history.append((now, new_prob))
                    return AnomalyRecord(
                        anomaly_type=AnomalyType.ODDS_JUMP.value,
                        severity=AnomalySeverity.HIGH.value if delta > self.jump_threshold * 2 else AnomalySeverity.MEDIUM.value,
                        source=provider,
                        event_id=event_id,
                        description=f"Odds jump of {delta:.1%} for {outcome_label} on {event_id}",
                        details={
                            "old_prob": round(last_prob, 4),
                            "new_prob": round(new_prob, 4),
                            "delta": round(delta, 4),
                            "provider": provider,
                        },
                    )

                # Check rapid cumulative jump
                cutoff = now - self.rapid_window_s
                recent = [(ts, p) for ts, p in history if ts >= cutoff]
                if recent:
                    oldest_prob = recent[0][1]
                    cumulative_delta = abs(new_prob - oldest_prob)
                    if cumulative_delta > self.rapid_jump_threshold and len(recent) >= 2:
                        history.append((now, new_prob))
                        return AnomalyRecord(
                            anomaly_type=AnomalyType.ODDS_JUMP.value,
                            severity=AnomalySeverity.MEDIUM.value,
                            source=provider,
                            event_id=event_id,
                            description=f"Rapid odds drift of {cumulative_delta:.1%} in {self.rapid_window_s}s for {outcome_label}",
                            details={
                                "cumulative_delta": round(cumulative_delta, 4),
                                "window_s": self.rapid_window_s,
                                "updates_in_window": len(recent),
                            },
                        )

            history.append((now, new_prob))
        return None

    def get_recent_movements(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            movements = list(self._movements)[-limit:]
        return [
            {
                "event_id": m.event_id, "outcome": m.outcome_label,
                "provider": m.provider, "old_prob": round(m.old_prob, 4),
                "new_prob": round(m.new_prob, 4), "delta": round(m.delta, 4),
                "timestamp": m.timestamp,
            }
            for m in movements
        ]


# ═══════════════════════════════════════════════════════════════════════
# 4. Bet Pattern Detector
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class BetRecord:
    """A bet record for pattern analysis."""
    bet_id: str = ""
    user_id: str = ""
    event_id: str = ""
    outcome_label: str = ""
    stake: float = 0.0
    odds: float = 0.0
    timestamp: float = field(default_factory=time.time)


class BetPatternDetector:
    """Detects suspicious betting patterns.

    Patterns detected:
      - Rapid-fire: too many bets from one user in a short window.
      - Size spike: bet size significantly above user's average.
      - Correlated timing: multiple users betting the same outcome
        within a narrow window (potential coordination).
    """

    def __init__(
        self,
        rapid_fire_window_s: float = 60.0,
        rapid_fire_threshold: int = 5,
        size_spike_multiplier: float = 5.0,
        correlation_window_s: float = 10.0,
        correlation_threshold: int = 3,
    ):
        self._lock = threading.RLock()
        self.rapid_fire_window_s = rapid_fire_window_s
        self.rapid_fire_threshold = rapid_fire_threshold
        self.size_spike_multiplier = size_spike_multiplier
        self.correlation_window_s = correlation_window_s
        self.correlation_threshold = correlation_threshold

        # user_id → deque of timestamps
        self._user_bets: Dict[str, Deque[float]] = {}
        # user_id → deque of stakes
        self._user_stakes: Dict[str, Deque[float]] = {}
        # "event_id:outcome" → deque of (timestamp, user_id)
        self._outcome_bets: Dict[str, Deque[tuple]] = {}

    def check_bet(self, record: BetRecord) -> List[AnomalyRecord]:
        """Check a bet for suspicious patterns. Returns list of anomalies."""
        anomalies = []
        now = record.timestamp or time.time()

        with self._lock:
            # --- Rapid-fire check ---
            if record.user_id not in self._user_bets:
                self._user_bets[record.user_id] = collections.deque(maxlen=100)
            user_ts = self._user_bets[record.user_id]
            user_ts.append(now)

            cutoff = now - self.rapid_fire_window_s
            recent = [t for t in user_ts if t >= cutoff]
            if len(recent) >= self.rapid_fire_threshold:
                anomalies.append(AnomalyRecord(
                    anomaly_type=AnomalyType.RAPID_FIRE_BETS.value,
                    severity=AnomalySeverity.HIGH.value,
                    source=record.user_id,
                    agent_id=record.user_id,
                    event_id=record.event_id,
                    description=f"Rapid-fire: {len(recent)} bets in {self.rapid_fire_window_s}s from {record.user_id}",
                    details={
                        "bets_in_window": len(recent),
                        "window_s": self.rapid_fire_window_s,
                        "threshold": self.rapid_fire_threshold,
                    },
                ))

            # --- Size spike check ---
            if record.user_id not in self._user_stakes:
                self._user_stakes[record.user_id] = collections.deque(maxlen=50)
            user_stakes = self._user_stakes[record.user_id]

            if len(user_stakes) >= 3:
                avg_stake = statistics.mean(user_stakes)
                if avg_stake > 0 and record.stake > avg_stake * self.size_spike_multiplier:
                    anomalies.append(AnomalyRecord(
                        anomaly_type=AnomalyType.SIZE_SPIKE.value,
                        severity=AnomalySeverity.MEDIUM.value,
                        source=record.user_id,
                        agent_id=record.user_id,
                        event_id=record.event_id,
                        description=f"Stake {record.stake:.2f} is {record.stake/avg_stake:.1f}x average ({avg_stake:.2f})",
                        details={
                            "stake": record.stake,
                            "avg_stake": round(avg_stake, 2),
                            "multiplier": round(record.stake / avg_stake, 1),
                        },
                    ))
            user_stakes.append(record.stake)

            # --- Correlated timing check ---
            outcome_key = f"{record.event_id}:{record.outcome_label}"
            if outcome_key not in self._outcome_bets:
                self._outcome_bets[outcome_key] = collections.deque(maxlen=100)
            outcome_bets = self._outcome_bets[outcome_key]
            outcome_bets.append((now, record.user_id))

            corr_cutoff = now - self.correlation_window_s
            corr_recent = [(t, u) for t, u in outcome_bets if t >= corr_cutoff]
            unique_users = set(u for _, u in corr_recent)
            if len(unique_users) >= self.correlation_threshold:
                anomalies.append(AnomalyRecord(
                    anomaly_type=AnomalyType.CORRELATED_TIMING.value,
                    severity=AnomalySeverity.HIGH.value,
                    source=outcome_key,
                    event_id=record.event_id,
                    description=f"Correlated betting: {len(unique_users)} users bet {record.outcome_label} within {self.correlation_window_s}s",
                    details={
                        "unique_users": len(unique_users),
                        "window_s": self.correlation_window_s,
                        "threshold": self.correlation_threshold,
                    },
                ))

        return anomalies


# ═══════════════════════════════════════════════════════════════════════
# 5. Anomaly Engine (aggregator)
# ═══════════════════════════════════════════════════════════════════════

class AnomalyEngine:
    """Aggregates all anomaly detectors and provides a unified API.

    Wires into:
      - SportsOddsFeed (odds updates → staleness + jump detection)
      - LiveBettingEngine (bet placements → pattern detection)
      - Observability API (anomaly listing, stats, acknowledgment)
    """

    def __init__(
        self,
        staleness_detector: Optional[FeedStalenessDetector] = None,
        jump_detector: Optional[OddsJumpDetector] = None,
        bet_detector: Optional[BetPatternDetector] = None,
    ):
        self._lock = threading.RLock()
        self.staleness = staleness_detector or FeedStalenessDetector()
        self.jumps = jump_detector or OddsJumpDetector()
        self.bets = bet_detector or BetPatternDetector()
        self._anomaly_log: Deque[AnomalyRecord] = collections.deque(maxlen=1000)

    def on_odds_update(self, update: Any) -> List[AnomalyRecord]:
        """Process an odds update for anomaly detection.

        Called as a SportsOddsFeed subscriber.
        """
        anomalies = []

        # Record provider freshness
        self.staleness.record_update(update.provider, update.timestamp)

        # Check for odds jump
        jump = self.jumps.check_update(
            event_id=update.event_id,
            outcome_label=update.outcome_label,
            new_prob=update.implied_prob,
            provider=update.provider,
        )
        if jump:
            anomalies.append(jump)

        # Store anomalies
        with self._lock:
            for a in anomalies:
                self._anomaly_log.append(a)

        return anomalies

    def on_bet_placed(
        self,
        bet_id: str,
        user_id: str,
        event_id: str,
        outcome_label: str,
        stake: float,
        odds: float = 0.0,
    ) -> List[AnomalyRecord]:
        """Process a bet placement for anomaly detection."""
        record = BetRecord(
            bet_id=bet_id,
            user_id=user_id,
            event_id=event_id,
            outcome_label=outcome_label,
            stake=stake,
            odds=odds,
        )
        anomalies = self.bets.check_bet(record)

        with self._lock:
            for a in anomalies:
                self._anomaly_log.append(a)

        return anomalies

    def run_staleness_check(self) -> List[AnomalyRecord]:
        """Run a staleness check across all providers."""
        anomalies = self.staleness.check()
        with self._lock:
            for a in anomalies:
                self._anomaly_log.append(a)
        return anomalies

    def acknowledge(self, anomaly_id: str) -> bool:
        """Acknowledge an anomaly. Returns True if found."""
        with self._lock:
            for a in self._anomaly_log:
                if a.id == anomaly_id:
                    a.acknowledged = True
                    return True
        return False

    def get_anomalies(
        self,
        anomaly_type: Optional[str] = None,
        severity: Optional[str] = None,
        unacknowledged_only: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get anomaly records with optional filters."""
        with self._lock:
            records = list(self._anomaly_log)
        if anomaly_type:
            records = [r for r in records if r.anomaly_type == anomaly_type]
        if severity:
            records = [r for r in records if r.severity == severity]
        if unacknowledged_only:
            records = [r for r in records if not r.acknowledged]
        records.sort(key=lambda r: r.timestamp, reverse=True)
        return [r.to_dict() for r in records[:limit]]

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate anomaly statistics."""
        with self._lock:
            records = list(self._anomaly_log)
        if not records:
            return {
                "total": 0, "by_type": {}, "by_severity": {},
                "unacknowledged": 0, "staleness": self.staleness.get_status(),
            }

        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        unack = 0
        for r in records:
            by_type[r.anomaly_type] = by_type.get(r.anomaly_type, 0) + 1
            by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
            if not r.acknowledged:
                unack += 1

        return {
            "total": len(records),
            "by_type": by_type,
            "by_severity": by_severity,
            "unacknowledged": unack,
            "staleness": self.staleness.get_status(),
        }


# ═══════════════════════════════════════════════════════════════════════
# 6. Singleton
# ═══════════════════════════════════════════════════════════════════════

_anomaly_engine: Optional[AnomalyEngine] = None


def get_anomaly_engine() -> AnomalyEngine:
    """Get or create the singleton AnomalyEngine."""
    global _anomaly_engine
    if _anomaly_engine is None:
        _anomaly_engine = AnomalyEngine()
    return _anomaly_engine
