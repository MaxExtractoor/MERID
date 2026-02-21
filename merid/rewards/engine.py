"""RewardEngine — central event→mechanism→reward pipeline.

Accepts RewardEvents, applies all registered mechanisms, applies time-decay
and caps, persists normalized reward records, and emits RewardOutcomes.

The engine is the single source of truth for all reward computation across
MERID.  It replaces per-feature scoring logic with a unified pipeline.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from merid.rewards.events import RewardEvent, EventCategory, event_from_dict
from merid.rewards.mechanisms import (
    MechanismRegistry,
    PointAward,
    get_mechanism_registry,
)
from utils.logger import get_logger

logger = get_logger("merid.rewards.engine")


# ── Output dataclass ──────────────────────────────────────────────────

@dataclass
class RewardOutcome:
    """Normalized reward record produced by the engine for a single event."""
    id: str = field(default_factory=lambda: f"rout-{uuid.uuid4().hex[:12]}")
    event_id: str = ""
    agent_id: str = ""
    team_id: str = ""
    venue: str = ""
    total_points: float = 0.0
    awards: List[Dict[str, Any]] = field(default_factory=list)
    level_progress: float = 0.0          # how much this contributes to next level
    badge_updates: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "agent_id": self.agent_id,
            "team_id": self.team_id,
            "venue": self.venue,
            "total_points": round(self.total_points, 2),
            "awards": self.awards,
            "level_progress": round(self.level_progress, 4),
            "badge_updates": self.badge_updates,
            "created_at": self.created_at,
        }


# ── SQLite schema ─────────────────────────────────────────────────────

_CREATE_REWARD_EVENTS = """
CREATE TABLE IF NOT EXISTS reward_events (
    id          TEXT PRIMARY KEY,
    category    TEXT NOT NULL DEFAULT '',
    agent_id    TEXT NOT NULL DEFAULT '',
    team_id     TEXT NOT NULL DEFAULT '',
    venue       TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL
);
"""

_CREATE_REWARD_OUTCOMES = """
CREATE TABLE IF NOT EXISTS reward_outcomes (
    id            TEXT PRIMARY KEY,
    event_id      TEXT NOT NULL DEFAULT '',
    agent_id      TEXT NOT NULL DEFAULT '',
    team_id       TEXT NOT NULL DEFAULT '',
    venue         TEXT NOT NULL DEFAULT '',
    total_points  REAL NOT NULL DEFAULT 0,
    awards        TEXT NOT NULL DEFAULT '[]',
    created_at    REAL NOT NULL
);
"""

_CREATE_REWARD_ENGINE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_re_events_agent ON reward_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_re_events_category ON reward_events(category);
CREATE INDEX IF NOT EXISTS idx_re_events_created ON reward_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_re_outcomes_agent ON reward_outcomes(agent_id);
CREATE INDEX IF NOT EXISTS idx_re_outcomes_event ON reward_outcomes(event_id);
CREATE INDEX IF NOT EXISTS idx_re_outcomes_created ON reward_outcomes(created_at DESC);
"""


# ── RewardEngine ──────────────────────────────────────────────────────

class RewardEngine:
    """Central reward engine — processes events through mechanisms.

    Config keys (via constructor or env):
      decay_lambda       — exponential decay rate for time-weighted points
                           (env: MERID_REWARD_DECAY_LAMBDA, default 0.0 = no decay)
      global_cap         — max points per single event (default 200.0)
      level_points       — points required per level (default 500.0)
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        registry: Optional[MechanismRegistry] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._db_path = db_path or os.environ.get(
            "MERID_REWARD_ENGINE_DB",
            os.path.join("data", "reward_engine.db"),
        )
        self._registry = registry or get_mechanism_registry()
        self._config = config or {}
        self._lock = threading.Lock()

        self.decay_lambda = self._config.get(
            "decay_lambda",
            float(os.environ.get("MERID_REWARD_DECAY_LAMBDA", "0.0")),
        )
        self.global_cap = self._config.get("global_cap", 200.0)
        self.level_points = self._config.get("level_points", 500.0)

        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_REWARD_EVENTS)
            conn.execute(_CREATE_REWARD_OUTCOMES)
            conn.executescript(_CREATE_REWARD_ENGINE_INDEXES)
        logger.info("RewardEngine DB initialized: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Core pipeline ─────────────────────────────────────────────────

    def process_event(self, event: RewardEvent) -> RewardOutcome:
        """Process a single event through all mechanisms and persist results.

        Returns a RewardOutcome with total points, individual awards, and
        level progress contribution.
        """
        # 1. Run all applicable mechanisms
        awards = self._registry.evaluate_all(event)

        # 2. Apply global cap
        total = sum(a.points for a in awards)
        if total > self.global_cap:
            scale = self.global_cap / total if total > 0 else 1.0
            for a in awards:
                a.points = round(a.points * scale, 2)
            total = self.global_cap

        # 3. Build outcome
        outcome = RewardOutcome(
            event_id=event.id,
            agent_id=event.agent_id,
            team_id=event.team_id,
            venue=event.venue,
            total_points=round(total, 2),
            awards=[
                {
                    "reward_type": a.reward_type,
                    "points": round(a.points, 2),
                    "detail": a.detail,
                    "category": a.category,
                    "mechanism": a.mechanism_name,
                }
                for a in awards
            ],
            level_progress=round(total / self.level_points, 4) if self.level_points > 0 else 0.0,
        )

        # 4. Persist event + outcome
        self._persist(event, outcome)

        return outcome

    def process_events(self, events: List[RewardEvent]) -> List[RewardOutcome]:
        """Process a batch of events."""
        return [self.process_event(e) for e in events]

    # ── Persistence ───────────────────────────────────────────────────

    def _persist(self, event: RewardEvent, outcome: RewardOutcome) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO reward_events "
                    "(id, category, agent_id, team_id, venue, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (event.id, event.category, event.agent_id, event.team_id,
                     event.venue, json.dumps(event.to_dict()), event.timestamp),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO reward_outcomes "
                    "(id, event_id, agent_id, team_id, venue, total_points, awards, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (outcome.id, outcome.event_id, outcome.agent_id, outcome.team_id,
                     outcome.venue, outcome.total_points,
                     json.dumps(outcome.awards), outcome.created_at),
                )

    # ── Queries ───────────────────────────────────────────────────────

    def get_agent_total_points(
        self, agent_id: str, decay_lambda: Optional[float] = None,
    ) -> float:
        """Get total points for an agent, optionally with time decay."""
        lam = decay_lambda if decay_lambda is not None else self.decay_lambda
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT total_points, created_at FROM reward_outcomes WHERE agent_id = ?",
                (agent_id,),
            ).fetchall()

        now = time.time()
        total = 0.0
        for row in rows:
            pts = row["total_points"]
            if lam > 0:
                age_days = (now - row["created_at"]) / 86400.0
                pts *= math.exp(-lam * age_days)
            total += pts
        return round(total, 2)

    def get_leaderboard(
        self,
        limit: int = 20,
        decay_lambda: Optional[float] = None,
        venue: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Compute agent leaderboard with optional decay and venue filter."""
        lam = decay_lambda if decay_lambda is not None else self.decay_lambda
        query = "SELECT agent_id, total_points, created_at, venue FROM reward_outcomes"
        params: List[Any] = []
        if venue:
            query += " WHERE venue = ?"
            params.append(venue)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        now = time.time()
        agent_points: Dict[str, float] = {}
        for row in rows:
            pts = row["total_points"]
            if lam > 0:
                age_days = (now - row["created_at"]) / 86400.0
                pts *= math.exp(-lam * age_days)
            agent_points[row["agent_id"]] = agent_points.get(row["agent_id"], 0.0) + pts

        sorted_agents = sorted(agent_points.items(), key=lambda x: x[1], reverse=True)
        return [
            {"rank": i + 1, "agent_id": aid, "total_points": round(pts, 2)}
            for i, (aid, pts) in enumerate(sorted_agents[:limit])
        ]

    def get_reward_distribution(self, window_s: float = 86400.0) -> Dict[str, Any]:
        """Get reward distribution by category and mechanism over a time window.

        This is the core observability metric for the gamification layer.
        """
        cutoff = time.time() - window_s
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT awards, total_points FROM reward_outcomes WHERE created_at > ?",
                (cutoff,),
            ).fetchall()

        by_category: Dict[str, float] = {}
        by_mechanism: Dict[str, float] = {}
        by_reward_type: Dict[str, float] = {}
        total_points = 0.0
        total_events = len(rows)

        for row in rows:
            total_points += row["total_points"]
            awards = json.loads(row["awards"]) if row["awards"] else []
            for award in awards:
                cat = award.get("category", "unknown")
                mech = award.get("mechanism", "unknown")
                rtype = award.get("reward_type", "unknown")
                pts = award.get("points", 0.0)
                by_category[cat] = by_category.get(cat, 0.0) + pts
                by_mechanism[mech] = by_mechanism.get(mech, 0.0) + pts
                by_reward_type[rtype] = by_reward_type.get(rtype, 0.0) + pts

        return {
            "total_points": round(total_points, 2),
            "total_events": total_events,
            "by_category": {k: round(v, 2) for k, v in by_category.items()},
            "by_mechanism": {k: round(v, 2) for k, v in by_mechanism.items()},
            "by_reward_type": {k: round(v, 2) for k, v in by_reward_type.items()},
            "window_seconds": window_s,
        }

    def get_agent_history(
        self, agent_id: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get recent reward outcomes for an agent."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reward_outcomes WHERE agent_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "event_id": row["event_id"],
                "total_points": row["total_points"],
                "awards": json.loads(row["awards"]) if row["awards"] else [],
                "venue": row["venue"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_gaming_indicators(self, window_s: float = 86400.0) -> Dict[str, Any]:
        """Detect signs of gaming: high rewards with no underlying improvement.

        Returns indicators that the observability layer can alert on.
        """
        cutoff = time.time() - window_s
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT agent_id, total_points, awards FROM reward_outcomes "
                "WHERE created_at > ?",
                (cutoff,),
            ).fetchall()

        agent_total: Dict[str, float] = {}
        agent_improvement: Dict[str, float] = {}
        agent_event_count: Dict[str, int] = {}

        for row in rows:
            aid = row["agent_id"]
            agent_total[aid] = agent_total.get(aid, 0.0) + row["total_points"]
            agent_event_count[aid] = agent_event_count.get(aid, 0) + 1
            awards = json.loads(row["awards"]) if row["awards"] else []
            for award in awards:
                if award.get("reward_type") == "improvement":
                    agent_improvement[aid] = agent_improvement.get(aid, 0.0) + award.get("points", 0.0)

        # Flag agents with high total but zero improvement points
        suspects: List[Dict[str, Any]] = []
        for aid, total in agent_total.items():
            improvement = agent_improvement.get(aid, 0.0)
            if total > 50 and improvement <= 0:
                suspects.append({
                    "agent_id": aid,
                    "total_points": round(total, 2),
                    "improvement_points": round(improvement, 2),
                    "event_count": agent_event_count.get(aid, 0),
                    "flag": "high_reward_no_improvement",
                })

        return {
            "suspects": suspects,
            "total_agents": len(agent_total),
            "agents_with_improvement": len(agent_improvement),
            "window_seconds": window_s,
        }

    def get_engine_metrics(self) -> Dict[str, Any]:
        """Get overall engine health metrics."""
        with self._connect() as conn:
            event_count = conn.execute("SELECT COUNT(*) as c FROM reward_events").fetchone()["c"]
            outcome_count = conn.execute("SELECT COUNT(*) as c FROM reward_outcomes").fetchone()["c"]
            total_pts = conn.execute(
                "SELECT COALESCE(SUM(total_points), 0) as s FROM reward_outcomes"
            ).fetchone()["s"]

        return {
            "total_events_processed": event_count,
            "total_outcomes": outcome_count,
            "total_points_awarded": round(total_pts, 2),
            "mechanisms": self._registry.to_dict(),
            "config": {
                "decay_lambda": self.decay_lambda,
                "global_cap": self.global_cap,
                "level_points": self.level_points,
            },
        }


# ── Singleton ─────────────────────────────────────────────────────────

_ENGINE_INSTANCE: Optional[RewardEngine] = None


def get_reward_engine(db_path: Optional[str] = None) -> RewardEngine:
    """Get or create the singleton RewardEngine."""
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        _ENGINE_INSTANCE = RewardEngine(db_path=db_path)
    return _ENGINE_INSTANCE
