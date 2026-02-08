"""Persistent consensus store — agent opinions and trade plans.

Provides:
  - ``add_opinion(agent_id, symbol, stance, confidence, reasoning, ...)``
  - ``add_plan(symbol, direction, confidence, supporting_agents, ...)``
  - ``list_opinions(limit, since_ms)``
  - ``list_plans(limit, status)``
  - ``vote_on_plan(plan_id, agent_id, vote)``
  - ``update_plan_status(plan_id, status)``
  - ``get_metrics()``

Other modules (agents, orchestrator) call the convenience API to
persist consensus artifacts that surface in the operator UI.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.consensus_store")

# ── Domain objects ───────────────────────────────────────────────────

STANCES = ("bullish", "bearish", "neutral", "cautious")
PLAN_STATUSES = ("proposed", "pending", "approved", "rejected", "executed", "expired")


@dataclass
class Opinion:
    """An agent's opinion on a symbol or market condition."""
    id: str = field(default_factory=lambda: f"op-{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    agent_name: str = ""
    role: str = ""
    symbol: str = ""
    stance: str = "neutral"
    confidence: float = 0.5
    reasoning: str = ""
    horizon: str = "short"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent": self.agent_name,
            "role": self.role,
            "symbol": self.symbol,
            "position": self.stance,
            "stance": self.stance,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "horizon": self.horizon,
            "timestamp": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }


@dataclass
class TradePlan:
    """A consensus trade plan proposed by the swarm."""
    id: str = field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:12]}")
    symbol: str = ""
    title: str = ""
    direction: str = "long"
    target_size_usd: float = 0.0
    confidence: float = 0.5
    consensus_score: float = 0.0
    status: str = "proposed"
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    votes_for: int = 0
    votes_against: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "title": self.title,
            "direction": self.direction,
            "target_size_usd": self.target_size_usd,
            "confidence": self.confidence,
            "consensus_score": self.consensus_score,
            "status": self.status,
            "supporting_agents": self.supporting_agents,
            "opposing_agents": self.opposing_agents,
            "votes_for": self.votes_for,
            "votes_against": self.votes_against,
            "agents_involved": self.supporting_agents + self.opposing_agents,
            "created_at": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "timestamp": self.created_at,
        }


# ── SQLite store ─────────────────────────────────────────────────────

_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_DB_PATH = os.environ.get("MERID_CONSENSUS_DB", os.path.join(_DB_DIR, "consensus.db"))

_CREATE_OPINIONS = """
CREATE TABLE IF NOT EXISTS opinions (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL DEFAULT '',
    agent_name  TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT '',
    symbol      TEXT NOT NULL DEFAULT '',
    stance      TEXT NOT NULL DEFAULT 'neutral',
    confidence  REAL NOT NULL DEFAULT 0.5,
    reasoning   TEXT NOT NULL DEFAULT '',
    horizon     TEXT NOT NULL DEFAULT 'short',
    created_at  REAL NOT NULL
);
"""

_CREATE_PLANS = """
CREATE TABLE IF NOT EXISTS plans (
    id                TEXT PRIMARY KEY,
    symbol            TEXT NOT NULL DEFAULT '',
    title             TEXT NOT NULL DEFAULT '',
    direction         TEXT NOT NULL DEFAULT 'long',
    target_size_usd   REAL NOT NULL DEFAULT 0.0,
    confidence        REAL NOT NULL DEFAULT 0.5,
    consensus_score   REAL NOT NULL DEFAULT 0.0,
    status            TEXT NOT NULL DEFAULT 'proposed',
    supporting_agents TEXT NOT NULL DEFAULT '[]',
    opposing_agents   TEXT NOT NULL DEFAULT '[]',
    votes_for         INTEGER NOT NULL DEFAULT 0,
    votes_against     INTEGER NOT NULL DEFAULT 0,
    created_at        REAL NOT NULL
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_opinions_created ON opinions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_plans_created ON plans(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);
"""


class ConsensusStore:
    """Thread-safe SQLite store for consensus opinions and plans."""

    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_OPINIONS)
            conn.execute(_CREATE_PLANS)
            conn.executescript(_CREATE_INDEXES)
        logger.info("Consensus store initialized: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Opinions ─────────────────────────────────────────────────────

    def add_opinion(self, opinion: Opinion) -> Opinion:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO opinions (id, agent_id, agent_name, role, symbol, stance, confidence, reasoning, horizon, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (opinion.id, opinion.agent_id, opinion.agent_name, opinion.role,
                     opinion.symbol, opinion.stance, opinion.confidence, opinion.reasoning,
                     opinion.horizon, opinion.created_at),
                )
        return opinion

    def list_opinions(self, limit: int = 30, since_ms: Optional[int] = None) -> List[Opinion]:
        with self._connect() as conn:
            if since_ms is not None:
                since_epoch = since_ms / 1000.0
                rows = conn.execute(
                    "SELECT * FROM opinions WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
                    (since_epoch, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM opinions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_opinion(r) for r in rows]

    def opinion_count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM opinions").fetchone()[0]

    # ── Plans ────────────────────────────────────────────────────────

    def add_plan(self, plan: TradePlan) -> TradePlan:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO plans (id, symbol, title, direction, target_size_usd, confidence, consensus_score, status, supporting_agents, opposing_agents, votes_for, votes_against, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (plan.id, plan.symbol, plan.title, plan.direction,
                     plan.target_size_usd, plan.confidence, plan.consensus_score,
                     plan.status, json.dumps(plan.supporting_agents),
                     json.dumps(plan.opposing_agents), plan.votes_for,
                     plan.votes_against, plan.created_at),
                )
        return plan

    def list_plans(self, limit: int = 20, status: Optional[str] = None) -> List[TradePlan]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM plans WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM plans ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_plan(r) for r in rows]

    def update_plan_status(self, plan_id: str, status: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE plans SET status = ? WHERE id = ?",
                    (status, plan_id),
                )
                return cur.rowcount > 0

    def vote_on_plan(self, plan_id: str, agent_id: str, vote: str) -> bool:
        """Record a vote on a plan. vote='for' or vote='against'."""
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
                if not row:
                    return False

                supporting = json.loads(row["supporting_agents"])
                opposing = json.loads(row["opposing_agents"])

                if vote == "for" and agent_id not in supporting:
                    supporting.append(agent_id)
                elif vote == "against" and agent_id not in opposing:
                    opposing.append(agent_id)

                conn.execute(
                    "UPDATE plans SET supporting_agents = ?, opposing_agents = ?, votes_for = ?, votes_against = ? WHERE id = ?",
                    (json.dumps(supporting), json.dumps(opposing),
                     len(supporting), len(opposing), plan_id),
                )
                return True

    def plan_count(self, status: Optional[str] = None) -> int:
        with self._connect() as conn:
            if status:
                return conn.execute("SELECT COUNT(*) FROM plans WHERE status = ?", (status,)).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]

    # ── Metrics ──────────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        """Return consensus metrics for the /metrics endpoint."""
        with self._connect() as conn:
            total_opinions = conn.execute("SELECT COUNT(*) FROM opinions").fetchone()[0]
            total_plans = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
            approved = conn.execute("SELECT COUNT(*) FROM plans WHERE status = 'approved'").fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM plans WHERE status = 'rejected'").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM plans WHERE status IN ('proposed', 'pending')").fetchone()[0]

            # Consensus rate = approved / (approved + rejected) if any decided
            decided = approved + rejected
            consensus_rate = (approved / decided) if decided > 0 else 0.0

            # Unanimous = plans where votes_against == 0 and votes_for > 0
            unanimous = conn.execute(
                "SELECT COUNT(*) FROM plans WHERE votes_against = 0 AND votes_for > 0"
            ).fetchone()[0]

        return {
            "total_opinions": total_opinions,
            "total_decisions": total_plans,
            "approved": approved,
            "rejected": rejected,
            "pending": pending,
            "consensus_rate": round(consensus_rate, 3),
            "unanimous_count": unanimous,
            "veto_count": rejected,
            "average_time_to_consensus_ms": 0,
            "timestamp": int(time.time() * 1000),
        }

    # ── Row converters ───────────────────────────────────────────────

    @staticmethod
    def _row_to_opinion(row: sqlite3.Row) -> Opinion:
        return Opinion(
            id=row["id"],
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            role=row["role"],
            symbol=row["symbol"],
            stance=row["stance"],
            confidence=row["confidence"],
            reasoning=row["reasoning"],
            horizon=row["horizon"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> TradePlan:
        return TradePlan(
            id=row["id"],
            symbol=row["symbol"],
            title=row["title"],
            direction=row["direction"],
            target_size_usd=row["target_size_usd"],
            confidence=row["confidence"],
            consensus_score=row["consensus_score"],
            status=row["status"],
            supporting_agents=json.loads(row["supporting_agents"]),
            opposing_agents=json.loads(row["opposing_agents"]),
            votes_for=row["votes_for"],
            votes_against=row["votes_against"],
            created_at=row["created_at"],
        )


# ── Singleton ────────────────────────────────────────────────────────

_store: Optional[ConsensusStore] = None


def get_consensus_store() -> ConsensusStore:
    """Get or create the singleton ConsensusStore."""
    global _store
    if _store is None:
        _store = ConsensusStore()
    return _store


# ── Convenience API ──────────────────────────────────────────────────

def add_opinion(
    agent_id: str = "",
    agent_name: str = "",
    role: str = "",
    symbol: str = "",
    stance: str = "neutral",
    confidence: float = 0.5,
    reasoning: str = "",
    horizon: str = "short",
) -> Opinion:
    """Add an opinion to the store. Call from anywhere."""
    op = Opinion(
        agent_id=agent_id,
        agent_name=agent_name,
        role=role,
        symbol=symbol,
        stance=stance,
        confidence=confidence,
        reasoning=reasoning,
        horizon=horizon,
    )
    return get_consensus_store().add_opinion(op)


def add_plan(
    symbol: str = "",
    title: str = "",
    direction: str = "long",
    target_size_usd: float = 0.0,
    confidence: float = 0.5,
    supporting_agents: Optional[List[str]] = None,
    status: str = "proposed",
) -> TradePlan:
    """Add a trade plan to the store. Call from anywhere."""
    plan = TradePlan(
        symbol=symbol,
        title=title,
        direction=direction,
        target_size_usd=target_size_usd,
        confidence=confidence,
        supporting_agents=supporting_agents or [],
        status=status,
    )
    return get_consensus_store().add_plan(plan)
