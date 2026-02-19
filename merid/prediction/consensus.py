"""Prediction Market Consensus — Swarm opinions vs Kalshi odds.

Provides:
  - PredictionInstrument: canonical symbol + metadata for each Kalshi market
  - PredictionOpinion: probabilistic agent opinion on a prediction market
  - PredictionPlan: edge-gated trade plan for a prediction market
  - PredictionConsensusStore: SQLite persistence + aggregation
  - Brier score computation for resolved markets

Canonical symbol format: PRED:KALSHI:<TICKER>:YES / PRED:KALSHI:<TICKER>:NO
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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.consensus")

# ── Constants ────────────────────────────────────────────────────────

PRED_STANCES = ("strong_yes", "weak_yes", "neutral", "weak_no", "strong_no")
PRED_PLAN_STATUSES = ("proposed", "approved", "executing", "closed", "expired")
PRED_CATEGORIES = ("macro", "politics", "equities", "crypto", "sports", "weather", "entertainment", "economics", "finance", "science", "other")

# Edge thresholds for stance classification
STRONG_EDGE_THRESHOLD = 0.10   # |edge| >= 10% → strong
WEAK_EDGE_THRESHOLD = 0.03     # |edge| >= 3%  → weak
# Below WEAK_EDGE_THRESHOLD → neutral


# ── Domain objects ───────────────────────────────────────────────────

def _make_pred_symbol(venue: str, ticker: str, outcome: str = "YES") -> str:
    """Build canonical prediction symbol."""
    return f"PRED:{venue.upper()}:{ticker}:{outcome.upper()}"


def _parse_pred_symbol(symbol: str) -> Optional[Dict[str, str]]:
    """Parse PRED:VENUE:TICKER:OUTCOME → dict or None."""
    parts = symbol.split(":")
    if len(parts) == 4 and parts[0] == "PRED":
        return {"venue": parts[1].lower(), "ticker": parts[2], "outcome": parts[3].upper()}
    return None


@dataclass
class PredictionInstrument:
    """A tradeable prediction market instrument in MERID's universe."""
    symbol: str = ""                  # PRED:KALSHI:<TICKER>:YES
    venue: str = "kalshi"
    event_id: str = ""                # Kalshi event ticker
    ticker: str = ""                  # Kalshi market ticker
    outcome: str = "YES"              # YES or NO
    asset_class: str = "prediction"
    category: str = "other"           # macro, politics, equities, etc.
    title: str = ""
    description: str = ""
    expiry: Optional[float] = None    # Unix timestamp
    market_implied_prob: float = 0.5  # 0–1, derived from Kalshi mid
    volume: float = 0.0
    open_interest: float = 0.0
    status: str = "active"            # active, closing, closed, settled_yes, settled_no
    last_refreshed: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "symbol": self.symbol,
            "venue": self.venue,
            "event_id": self.event_id,
            "ticker": self.ticker,
            "outcome": self.outcome,
            "asset_class": self.asset_class,
            "category": self.category,
            "title": self.title,
            "expiry": datetime.fromtimestamp(self.expiry, tz=timezone.utc).isoformat() if self.expiry else None,
            "market_implied_prob": round(self.market_implied_prob, 4),
            "volume": self.volume,
            "open_interest": self.open_interest,
            "status": self.status,
        }
        return d


@dataclass
class PredictionOpinion:
    """An agent's probabilistic opinion on a prediction market."""
    id: str = field(default_factory=lambda: f"pop-{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    agent_name: str = ""
    symbol: str = ""                  # PRED:KALSHI:<TICKER>:YES
    probability: float = 0.5          # Agent's belief P(YES) 0–1
    confidence: float = 0.5           # How sure the agent is (distinct from probability)
    reasoning: str = ""
    signal_sources: List[str] = field(default_factory=list)
    horizon: str = "event"            # event, short, medium
    explanation: Optional[Dict[str, Any]] = None  # Structured explanation metadata
    created_at: float = field(default_factory=time.time)

    def to_dict(self, include_explanation: bool = True) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "symbol": self.symbol,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "signal_sources": self.signal_sources,
            "horizon": self.horizon,
            "timestamp": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }
        if include_explanation and self.explanation:
            d["explanation"] = self.explanation
        return d


@dataclass
class PredictionPlan:
    """An edge-gated trade plan for a prediction market."""
    id: str = field(default_factory=lambda: f"pplan-{uuid.uuid4().hex[:12]}")
    symbol: str = ""
    direction: str = "yes"            # yes or no
    target_size_usd: float = 0.0
    max_edge_threshold: float = 0.05  # Minimum |edge| required
    confidence: float = 0.5
    status: str = "proposed"
    supporting_agents: List[str] = field(default_factory=list)
    opposing_agents: List[str] = field(default_factory=list)
    max_spread_cents: Optional[float] = None
    min_liquidity: Optional[float] = None
    cutoff_hours_before_expiry: float = 1.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "direction": self.direction,
            "target_size_usd": self.target_size_usd,
            "max_edge_threshold": self.max_edge_threshold,
            "confidence": round(self.confidence, 4),
            "status": self.status,
            "supporting_agents": self.supporting_agents,
            "opposing_agents": self.opposing_agents,
            "max_spread_cents": self.max_spread_cents,
            "min_liquidity": self.min_liquidity,
            "cutoff_hours_before_expiry": self.cutoff_hours_before_expiry,
            "timestamp": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }


@dataclass
class ResolvedMarket:
    """Outcome of a resolved prediction market for Brier scoring."""
    symbol: str = ""
    outcome: int = 0                  # 1 = YES happened, 0 = NO happened
    resolved_at: float = field(default_factory=time.time)
    pnl_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "outcome": self.outcome,
            "resolved_at": datetime.fromtimestamp(self.resolved_at, tz=timezone.utc).isoformat(),
            "pnl_usd": round(self.pnl_usd, 2),
        }


# ── SQLite store ─────────────────────────────────────────────────────

_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
_DB_PATH = os.environ.get("MERID_PRED_CONSENSUS_DB", os.path.join(_DB_DIR, "prediction_consensus.db"))

_CREATE_INSTRUMENTS = """
CREATE TABLE IF NOT EXISTS pred_instruments (
    symbol          TEXT PRIMARY KEY,
    venue           TEXT NOT NULL DEFAULT 'kalshi',
    event_id        TEXT NOT NULL DEFAULT '',
    ticker          TEXT NOT NULL DEFAULT '',
    outcome         TEXT NOT NULL DEFAULT 'YES',
    category        TEXT NOT NULL DEFAULT 'other',
    title           TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    expiry          REAL,
    market_implied_prob REAL NOT NULL DEFAULT 0.5,
    volume          REAL NOT NULL DEFAULT 0,
    open_interest   REAL NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active',
    last_refreshed  REAL NOT NULL
);
"""

_CREATE_PRED_OPINIONS = """
CREATE TABLE IF NOT EXISTS pred_opinions (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL DEFAULT '',
    agent_name      TEXT NOT NULL DEFAULT '',
    symbol          TEXT NOT NULL DEFAULT '',
    probability     REAL NOT NULL DEFAULT 0.5,
    confidence      REAL NOT NULL DEFAULT 0.5,
    reasoning       TEXT NOT NULL DEFAULT '',
    signal_sources  TEXT NOT NULL DEFAULT '[]',
    horizon         TEXT NOT NULL DEFAULT 'event',
    explanation     TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL
);
"""

_MIGRATE_EXPLANATION_COL = """
ALTER TABLE pred_opinions ADD COLUMN explanation TEXT NOT NULL DEFAULT '';
"""

_CREATE_PRED_PLANS = """
CREATE TABLE IF NOT EXISTS pred_plans (
    id                      TEXT PRIMARY KEY,
    symbol                  TEXT NOT NULL DEFAULT '',
    direction               TEXT NOT NULL DEFAULT 'yes',
    target_size_usd         REAL NOT NULL DEFAULT 0,
    max_edge_threshold      REAL NOT NULL DEFAULT 0.05,
    confidence              REAL NOT NULL DEFAULT 0.5,
    status                  TEXT NOT NULL DEFAULT 'proposed',
    supporting_agents       TEXT NOT NULL DEFAULT '[]',
    opposing_agents         TEXT NOT NULL DEFAULT '[]',
    max_spread_cents        REAL,
    min_liquidity           REAL,
    cutoff_hours_before_expiry REAL NOT NULL DEFAULT 1.0,
    created_at              REAL NOT NULL
);
"""

_CREATE_RESOLVED = """
CREATE TABLE IF NOT EXISTS pred_resolved (
    symbol          TEXT PRIMARY KEY,
    outcome         INTEGER NOT NULL DEFAULT 0,
    resolved_at     REAL NOT NULL,
    pnl_usd         REAL NOT NULL DEFAULT 0
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_pred_opinions_created ON pred_opinions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pred_opinions_symbol ON pred_opinions(symbol);
CREATE INDEX IF NOT EXISTS idx_pred_plans_created ON pred_plans(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pred_plans_status ON pred_plans(status);
CREATE INDEX IF NOT EXISTS idx_pred_instruments_status ON pred_instruments(status);
"""


class PredictionConsensusStore:
    """Thread-safe SQLite store for prediction market consensus data."""

    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._summary_cache: Optional[List[Dict[str, Any]]] = None
        self._summary_cache_ts: float = 0.0
        self._summary_cache_ttl: float = 15.0  # seconds
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_INSTRUMENTS)
            conn.execute(_CREATE_PRED_OPINIONS)
            conn.execute(_CREATE_PRED_PLANS)
            conn.execute(_CREATE_RESOLVED)
            conn.executescript(_CREATE_INDEXES)
            # Migration: add explanation column if missing (existing DBs)
            try:
                conn.execute(_MIGRATE_EXPLANATION_COL)
            except sqlite3.OperationalError:
                pass  # Column already exists
        logger.info("Prediction consensus store initialized: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Instruments ───────────────────────────────────────────────────

    def upsert_instrument(self, inst: PredictionInstrument) -> PredictionInstrument:
        """Insert or update a prediction instrument."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO pred_instruments "
                    "(symbol, venue, event_id, ticker, outcome, category, title, description, "
                    " expiry, market_implied_prob, volume, open_interest, status, last_refreshed) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (inst.symbol, inst.venue, inst.event_id, inst.ticker, inst.outcome,
                     inst.category, inst.title, inst.description, inst.expiry,
                     inst.market_implied_prob, inst.volume, inst.open_interest,
                     inst.status, inst.last_refreshed),
                )
        return inst

    def list_instruments(self, status: Optional[str] = None, category: Optional[str] = None,
                         limit: int = 200) -> List[PredictionInstrument]:
        """List prediction instruments, optionally filtered."""
        with self._connect() as conn:
            clauses = []
            params: list = []
            if status:
                clauses.append("status = ?")
                params.append(status)
            if category:
                clauses.append("category = ?")
                params.append(category)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM pred_instruments{where} ORDER BY volume DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_instrument(r) for r in rows]

    def get_instrument(self, symbol: str) -> Optional[PredictionInstrument]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pred_instruments WHERE symbol = ?", (symbol,)).fetchone()
        return self._row_to_instrument(row) if row else None

    def instrument_count(self, status: Optional[str] = None) -> int:
        with self._connect() as conn:
            if status:
                return conn.execute("SELECT COUNT(*) FROM pred_instruments WHERE status = ?", (status,)).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM pred_instruments").fetchone()[0]

    # ── Opinions ─────────────────────────────────────────────────────

    # Dedup window: reject opinions from same agent+symbol within this many seconds
    OPINION_DEDUP_WINDOW: float = 60.0

    def validate_opinion(self, op: PredictionOpinion) -> Optional[str]:
        """Validate an opinion before insertion. Returns error message or None if valid."""
        if not op.agent_id or not op.agent_id.strip():
            return "agent_id is required"
        if not op.symbol or not op.symbol.strip():
            return "symbol is required"
        if not (0.0 <= op.probability <= 1.0):
            return f"probability must be 0–1, got {op.probability}"
        if not (0.0 <= op.confidence <= 1.0):
            return f"confidence must be 0–1, got {op.confidence}"
        if op.horizon not in ("event", "short", "medium"):
            return f"horizon must be event/short/medium, got {op.horizon}"
        return None

    def add_opinion(self, op: PredictionOpinion) -> PredictionOpinion:
        """Add an opinion with validation and dedup.

        Raises ValueError if the opinion is malformed.
        Silently skips if a duplicate (same agent+symbol) exists within the dedup window.
        """
        error = self.validate_opinion(op)
        if error:
            raise ValueError(f"Invalid opinion: {error}")

        with self._lock:
            with self._connect() as conn:
                # Dedup: check for recent opinion from same agent on same symbol
                cutoff = time.time() - self.OPINION_DEDUP_WINDOW
                existing = conn.execute(
                    "SELECT id FROM pred_opinions "
                    "WHERE agent_id = ? AND symbol = ? AND created_at > ? "
                    "LIMIT 1",
                    (op.agent_id, op.symbol, cutoff),
                ).fetchone()
                if existing:
                    logger.debug("Dedup: skipping opinion from %s on %s (recent exists)", op.agent_id, op.symbol)
                    return op  # Return without inserting

                explanation_json = json.dumps(op.explanation) if op.explanation else ""
                conn.execute(
                    "INSERT INTO pred_opinions "
                    "(id, agent_id, agent_name, symbol, probability, confidence, reasoning, "
                    " signal_sources, horizon, explanation, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (op.id, op.agent_id, op.agent_name, op.symbol, op.probability,
                     op.confidence, op.reasoning, json.dumps(op.signal_sources),
                     op.horizon, explanation_json, op.created_at),
                )
        return op

    def list_opinions(self, symbol: Optional[str] = None, limit: int = 50) -> List[PredictionOpinion]:
        with self._connect() as conn:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM pred_opinions WHERE symbol = ? ORDER BY created_at DESC LIMIT ?",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pred_opinions ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_opinion(r) for r in rows]

    # ── Plans ────────────────────────────────────────────────────────

    def add_plan(self, plan: PredictionPlan) -> PredictionPlan:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO pred_plans "
                    "(id, symbol, direction, target_size_usd, max_edge_threshold, confidence, "
                    " status, supporting_agents, opposing_agents, max_spread_cents, min_liquidity, "
                    " cutoff_hours_before_expiry, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (plan.id, plan.symbol, plan.direction, plan.target_size_usd,
                     plan.max_edge_threshold, plan.confidence, plan.status,
                     json.dumps(plan.supporting_agents), json.dumps(plan.opposing_agents),
                     plan.max_spread_cents, plan.min_liquidity,
                     plan.cutoff_hours_before_expiry, plan.created_at),
                )
        return plan

    def update_plan_status(self, plan_id: str, status: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("UPDATE pred_plans SET status = ? WHERE id = ?", (status, plan_id))
                return cur.rowcount > 0

    def list_plans(self, symbol: Optional[str] = None, status: Optional[str] = None,
                   limit: int = 50) -> List[PredictionPlan]:
        with self._connect() as conn:
            clauses = []
            params: list = []
            if symbol:
                clauses.append("symbol = ?")
                params.append(symbol)
            if status:
                clauses.append("status = ?")
                params.append(status)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM pred_plans{where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_plan(r) for r in rows]

    # ── Resolved markets ─────────────────────────────────────────────

    def record_resolution(self, rm: ResolvedMarket) -> ResolvedMarket:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO pred_resolved (symbol, outcome, resolved_at, pnl_usd) "
                    "VALUES (?, ?, ?, ?)",
                    (rm.symbol, rm.outcome, rm.resolved_at, rm.pnl_usd),
                )
                # Update instrument status
                settled_status = "settled_yes" if rm.outcome == 1 else "settled_no"
                conn.execute(
                    "UPDATE pred_instruments SET status = ? WHERE symbol = ?",
                    (settled_status, rm.symbol),
                )
        return rm

    def list_resolved(self, limit: int = 100) -> List[ResolvedMarket]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pred_resolved ORDER BY resolved_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [ResolvedMarket(symbol=r["symbol"], outcome=r["outcome"],
                               resolved_at=r["resolved_at"], pnl_usd=r["pnl_usd"]) for r in rows]

    # ── Consensus summary ────────────────────────────────────────────

    def invalidate_summary_cache(self) -> None:
        """Force summary to be recomputed on next call."""
        self._summary_cache = None
        self._summary_cache_ts = 0.0

    def get_consensus_summary(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Per-symbol prediction consensus: swarm_prob vs market_prob, edge, stance.

        Uses batch SQL queries (3 total) instead of per-symbol N+1 pattern.
        Results cached for 15s to avoid redundant recomputation.
        """
        now = time.monotonic()
        if (
            self._summary_cache is not None
            and (now - self._summary_cache_ts) < self._summary_cache_ttl
            and category is None
        ):
            return self._summary_cache

        summaries = self._build_consensus_summary(category)

        if category is None:
            self._summary_cache = summaries
            self._summary_cache_ts = time.monotonic()

        return summaries

    def _build_consensus_summary(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Batch-query instruments, opinions, and plans, then aggregate in Python."""
        instruments = self.list_instruments(status="active", category=category, limit=500)
        if not instruments:
            return []

        symbols = [inst.symbol for inst in instruments]

        # Batch fetch all opinions for these symbols in ONE query
        opinions_by_symbol: Dict[str, List[PredictionOpinion]] = {s: [] for s in symbols}
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in symbols)
            rows = conn.execute(
                f"SELECT * FROM pred_opinions WHERE symbol IN ({placeholders}) "
                f"ORDER BY created_at DESC",
                symbols,
            ).fetchall()
            for r in rows:
                op = self._row_to_opinion(r)
                if op.symbol in opinions_by_symbol:
                    if len(opinions_by_symbol[op.symbol]) < 50:
                        opinions_by_symbol[op.symbol].append(op)

        # Batch fetch all plans for these symbols in ONE query
        plans_by_symbol: Dict[str, List[PredictionPlan]] = {s: [] for s in symbols}
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM pred_plans WHERE symbol IN ({placeholders}) "
                f"ORDER BY created_at DESC",
                symbols,
            ).fetchall()
            for r in rows:
                plan = self._row_to_plan(r)
                if plan.symbol in plans_by_symbol:
                    if len(plans_by_symbol[plan.symbol]) < 20:
                        plans_by_symbol[plan.symbol].append(plan)

        # Aggregate in Python — no more per-symbol queries
        summaries: List[Dict[str, Any]] = []
        for inst in instruments:
            opinions = opinions_by_symbol.get(inst.symbol, [])
            plans = plans_by_symbol.get(inst.symbol, [])

            swarm_prob = self._aggregate_swarm_prob(opinions)
            market_prob = inst.market_implied_prob
            edge = swarm_prob - market_prob
            stance = self._classify_stance(edge)

            yes_agents = [o.agent_id for o in opinions if o.probability >= 0.5]
            no_agents = [o.agent_id for o in opinions if o.probability < 0.5]
            avg_confidence = sum(o.confidence for o in opinions) / len(opinions) if opinions else 0.0

            plan_counts = {"proposed": 0, "approved": 0, "executing": 0}
            for p in plans:
                if p.status in plan_counts:
                    plan_counts[p.status] += 1

            summaries.append({
                "symbol": inst.symbol,
                "venue": inst.venue,
                "event_id": inst.event_id,
                "ticker": inst.ticker,
                "outcome": inst.outcome,
                "category": inst.category,
                "title": inst.title,
                "expiry": datetime.fromtimestamp(inst.expiry, tz=timezone.utc).isoformat() if inst.expiry else None,
                "swarm_prob": round(swarm_prob, 4),
                "market_prob": round(market_prob, 4),
                "edge": round(edge, 4),
                "stance": stance,
                "confidence": round(avg_confidence, 4),
                "supporting_agents": len(set(yes_agents)),
                "opposing_agents": len(set(no_agents)),
                "active_plans": plan_counts,
                "opinion_count": len(opinions),
                "volume": inst.volume,
            })

        return summaries

    @staticmethod
    def _aggregate_swarm_prob(opinions: List[PredictionOpinion]) -> float:
        """Confidence-weighted average of agent probabilities."""
        if not opinions:
            return 0.5
        total_weight = sum(o.confidence for o in opinions)
        if total_weight <= 0:
            return sum(o.probability for o in opinions) / len(opinions)
        return sum(o.probability * o.confidence for o in opinions) / total_weight

    @staticmethod
    def _classify_stance(edge: float) -> str:
        if edge >= STRONG_EDGE_THRESHOLD:
            return "strong_yes"
        elif edge >= WEAK_EDGE_THRESHOLD:
            return "weak_yes"
        elif edge <= -STRONG_EDGE_THRESHOLD:
            return "strong_no"
        elif edge <= -WEAK_EDGE_THRESHOLD:
            return "weak_no"
        return "neutral"

    # ── Brier scores ─────────────────────────────────────────────────

    def compute_brier_scores(self, window: int = 50) -> Dict[str, Any]:
        """Compute Brier scores for the swarm and per-agent over resolved markets.

        Brier score = (1/N) * Σ (forecast_prob - outcome)²
        Lower is better (0 = perfect, 1 = worst).
        """
        resolved = self.list_resolved(limit=window)
        if not resolved:
            return {
                "swarm_brier": None,
                "market_brier": None,
                "agent_briers": {},
                "resolved_count": 0,
                "calibration": [],
            }

        swarm_brier_sum = 0.0
        market_brier_sum = 0.0
        agent_scores: Dict[str, List[float]] = {}  # agent_id -> list of squared errors
        calibration_bins: Dict[int, Tuple[int, int]] = {}  # decile -> (total, correct)

        for rm in resolved:
            outcome = float(rm.outcome)

            # Instrument for market_prob
            inst = self.get_instrument(rm.symbol)
            market_prob = inst.market_implied_prob if inst else 0.5

            # Agent opinions for this symbol (most recent per agent)
            opinions = self.list_opinions(symbol=rm.symbol, limit=100)
            seen_agents: set = set()
            agent_probs: List[Tuple[str, float]] = []
            for op in opinions:
                if op.agent_id not in seen_agents:
                    seen_agents.add(op.agent_id)
                    agent_probs.append((op.agent_id, op.probability))

            # Swarm prob (weighted)
            swarm_prob = self._aggregate_swarm_prob(
                [op for op in opinions if op.agent_id in seen_agents][:len(seen_agents)]
            ) if opinions else 0.5

            swarm_brier_sum += (swarm_prob - outcome) ** 2
            market_brier_sum += (market_prob - outcome) ** 2

            # Per-agent Brier
            for agent_id, prob in agent_probs:
                agent_scores.setdefault(agent_id, []).append((prob - outcome) ** 2)

            # Calibration: bucket swarm_prob into deciles
            bucket = min(int(swarm_prob * 10), 9)
            total, correct = calibration_bins.get(bucket, (0, 0))
            calibration_bins[bucket] = (total + 1, correct + rm.outcome)

        n = len(resolved)
        swarm_brier = round(swarm_brier_sum / n, 4)
        market_brier = round(market_brier_sum / n, 4)

        agent_briers = {}
        for agent_id, scores in agent_scores.items():
            agent_briers[agent_id] = round(sum(scores) / len(scores), 4)

        # Sort agents by Brier (best first)
        agent_ranking = sorted(agent_briers.items(), key=lambda x: x[1])

        calibration = []
        for bucket in range(10):
            total, correct = calibration_bins.get(bucket, (0, 0))
            expected = (bucket + 0.5) / 10
            actual = correct / total if total > 0 else 0.0
            calibration.append({
                "bucket": f"{bucket * 10}-{(bucket + 1) * 10}%",
                "expected_rate": round(expected, 2),
                "actual_rate": round(actual, 4),
                "count": total,
            })

        return {
            "swarm_brier": swarm_brier,
            "market_brier": market_brier,
            "swarm_vs_market": "better" if swarm_brier < market_brier else "worse" if swarm_brier > market_brier else "equal",
            "agent_briers": dict(agent_ranking),
            "agent_ranking": [{"agent_id": a, "brier": b} for a, b in agent_ranking],
            "resolved_count": n,
            "total_pnl_usd": round(sum(rm.pnl_usd for rm in resolved), 2),
            "calibration": calibration,
        }

    # ── Plan execution check ─────────────────────────────────────────

    def check_plan_executable(self, plan: PredictionPlan) -> Dict[str, Any]:
        """Check if a prediction plan should execute given current market conditions."""
        inst = self.get_instrument(plan.symbol)
        if not inst:
            return {"executable": False, "reason": "Instrument not found"}

        if inst.status not in ("active", "closing"):
            return {"executable": False, "reason": f"Market status is {inst.status}"}

        # Recompute edge
        opinions = self.list_opinions(symbol=plan.symbol, limit=50)
        swarm_prob = self._aggregate_swarm_prob(opinions)
        market_prob = inst.market_implied_prob
        edge = swarm_prob - market_prob if plan.direction == "yes" else market_prob - swarm_prob

        if abs(edge) < plan.max_edge_threshold:
            return {
                "executable": False,
                "reason": f"|edge| {abs(edge):.4f} < threshold {plan.max_edge_threshold}",
                "edge": round(edge, 4),
            }

        # Check time to expiry
        if inst.expiry:
            hours_left = (inst.expiry - time.time()) / 3600
            if hours_left < plan.cutoff_hours_before_expiry:
                return {
                    "executable": False,
                    "reason": f"Only {hours_left:.1f}h to expiry, cutoff is {plan.cutoff_hours_before_expiry}h",
                }

        return {
            "executable": True,
            "edge": round(edge, 4),
            "swarm_prob": round(swarm_prob, 4),
            "market_prob": round(market_prob, 4),
        }

    # ── Brier-degradation risk ─────────────────────────────────────────

    def check_brier_degradation(self, threshold: float = 0.35, window: int = 50) -> Dict[str, Any]:
        """Check if swarm Brier score has degraded beyond threshold.

        Returns risk assessment with throttle recommendation.
        """
        brier = self.compute_brier_scores(window=window)
        swarm_brier = brier.get("swarm_brier")

        if swarm_brier is None or brier["resolved_count"] < 5:
            return {
                "degraded": False,
                "reason": "Insufficient resolved markets for assessment",
                "swarm_brier": swarm_brier,
                "threshold": threshold,
                "recommendation": "none",
            }

        degraded = swarm_brier > threshold
        if degraded:
            market_brier = brier.get("market_brier", 1.0)
            underperforming = swarm_brier > market_brier if market_brier else False
            return {
                "degraded": True,
                "reason": f"Swarm Brier {swarm_brier:.4f} exceeds threshold {threshold}",
                "swarm_brier": swarm_brier,
                "market_brier": market_brier,
                "threshold": threshold,
                "underperforming_market": underperforming,
                "recommendation": "pause" if underperforming else "throttle",
            }

        return {
            "degraded": False,
            "reason": "Swarm Brier within acceptable range",
            "swarm_brier": swarm_brier,
            "threshold": threshold,
            "recommendation": "none",
        }

    def get_store_metrics(self) -> Dict[str, Any]:
        """Operational metrics for the consensus store.

        Exposes instrument counts, opinion volume, update rates, and
        staleness indicators so operators can see whether agents are
        keeping the store fresh.
        """
        now = time.time()
        with self._connect() as conn:
            # Instrument counts by status
            inst_rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM pred_instruments GROUP BY status"
            ).fetchall()
            inst_by_status = {r["status"]: r["cnt"] for r in inst_rows}
            total_instruments = sum(inst_by_status.values())

            # Opinion volume
            total_opinions = conn.execute("SELECT COUNT(*) FROM pred_opinions").fetchone()[0]

            # Opinions in last hour / last 24h
            opinions_1h = conn.execute(
                "SELECT COUNT(*) FROM pred_opinions WHERE created_at > ?",
                (now - 3600,),
            ).fetchone()[0]
            opinions_24h = conn.execute(
                "SELECT COUNT(*) FROM pred_opinions WHERE created_at > ?",
                (now - 86400,),
            ).fetchone()[0]

            # Distinct active agents (submitted opinion in last hour)
            active_agents = conn.execute(
                "SELECT COUNT(DISTINCT agent_id) FROM pred_opinions WHERE created_at > ?",
                (now - 3600,),
            ).fetchone()[0]

            # Staleness: newest opinion age
            newest_opinion = conn.execute(
                "SELECT MAX(created_at) FROM pred_opinions"
            ).fetchone()[0]
            opinion_age_s = round(now - newest_opinion, 1) if newest_opinion else None

            # Staleness: newest instrument refresh age
            newest_refresh = conn.execute(
                "SELECT MAX(last_refreshed) FROM pred_instruments"
            ).fetchone()[0]
            instrument_age_s = round(now - newest_refresh, 1) if newest_refresh else None

            # Resolved count
            resolved_count = conn.execute("SELECT COUNT(*) FROM pred_resolved").fetchone()[0]

            # Plans by status
            plan_rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM pred_plans GROUP BY status"
            ).fetchall()
            plans_by_status = {r["status"]: r["cnt"] for r in plan_rows}

        return {
            "instruments": {
                "total": total_instruments,
                "by_status": inst_by_status,
                "newest_refresh_age_s": instrument_age_s,
                "stale": instrument_age_s is not None and instrument_age_s > 300,
            },
            "opinions": {
                "total": total_opinions,
                "last_1h": opinions_1h,
                "last_24h": opinions_24h,
                "active_agents": active_agents,
                "newest_age_s": opinion_age_s,
                "stale": opinion_age_s is not None and opinion_age_s > 600,
            },
            "resolved": {
                "total": resolved_count,
            },
            "plans": plans_by_status,
        }

    def get_explainability_metrics(self, window_s: float = 3600.0) -> Dict[str, Any]:
        """Compute explainability metrics for recent opinions.

        Returns:
            coverage: % of recent opinions with non-null explanations.
            rationale_distribution: count of each rationale tag.
            strategy_variety: distinct rationale tags per strategy.
            stability: proportion of instruments where agent opinion direction
                flipped (YES↔NO) within the window — frequent unexplained
                flips are a warning sign.
        """
        now = time.time()
        cutoff = now - window_s

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pred_opinions WHERE created_at > ? ORDER BY created_at DESC",
                (cutoff,),
            ).fetchall()

        if not rows:
            return {
                "coverage": {"total": 0, "with_explanation": 0, "pct": 0.0},
                "rationale_distribution": {},
                "strategy_variety": {},
                "stability": {"instruments_checked": 0, "flips": 0, "flip_rate": 0.0},
                "window_s": window_s,
            }

        total = len(rows)
        with_explanation = 0
        rationale_counts: Dict[str, int] = {}
        # Track per-agent-symbol direction history for stability
        direction_history: Dict[str, List[float]] = {}  # "agent:symbol" -> [prob, prob, ...]

        for r in rows:
            explanation_raw = r["explanation"] if "explanation" in r.keys() else ""
            if explanation_raw:
                try:
                    exp = json.loads(explanation_raw)
                    if exp:
                        with_explanation += 1
                        rationale = exp.get("rationale", "unknown")
                        rationale_counts[rationale] = rationale_counts.get(rationale, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

            key = f"{r['agent_id']}:{r['symbol']}"
            direction_history.setdefault(key, []).append(r["probability"])

        # Strategy variety: group rationale tags by strategy prefix
        strategy_variety: Dict[str, int] = {}
        for tag in rationale_counts:
            # Infer strategy from rationale tag
            if tag.startswith("hash"):
                strategy = "hash_bias"
            elif tag.startswith("mean_reversion") or tag.startswith("mild_mean"):
                strategy = "mean_reversion"
            elif tag.startswith("calibration"):
                strategy = "calibration_aware"
            else:
                strategy = "other"
            strategy_variety[strategy] = strategy_variety.get(strategy, 0) + 1

        # Stability: count direction flips per agent-symbol pair
        flips = 0
        instruments_checked = 0
        for key, probs in direction_history.items():
            if len(probs) < 2:
                continue
            instruments_checked += 1
            for i in range(1, len(probs)):
                prev_dir = "yes" if probs[i - 1] >= 0.5 else "no"
                curr_dir = "yes" if probs[i] >= 0.5 else "no"
                if prev_dir != curr_dir:
                    flips += 1
                    break  # Count at most one flip per pair in window

        coverage_pct = round(with_explanation / total * 100, 1) if total > 0 else 0.0
        flip_rate = round(flips / instruments_checked, 4) if instruments_checked > 0 else 0.0

        return {
            "coverage": {
                "total": total,
                "with_explanation": with_explanation,
                "pct": coverage_pct,
            },
            "rationale_distribution": rationale_counts,
            "strategy_variety": strategy_variety,
            "stability": {
                "instruments_checked": instruments_checked,
                "flips": flips,
                "flip_rate": flip_rate,
            },
            "window_s": window_s,
        }

    def get_category_exposure_summary(self) -> Dict[str, Dict[str, int]]:
        """Count active instruments and plans per category."""
        instruments = self.list_instruments(status="active", limit=1000)
        plans = self.list_plans(status="executing", limit=500)

        summary: Dict[str, Dict[str, int]] = {}
        for inst in instruments:
            cat = inst.category
            if cat not in summary:
                summary[cat] = {"instruments": 0, "executing_plans": 0}
            summary[cat]["instruments"] += 1

        # Count executing plans per category
        inst_map = {i.symbol: i for i in instruments}
        for p in plans:
            inst = inst_map.get(p.symbol)
            cat = inst.category if inst else "other"
            if cat not in summary:
                summary[cat] = {"instruments": 0, "executing_plans": 0}
            summary[cat]["executing_plans"] += 1

        return summary

    # ── Row converters ───────────────────────────────────────────────

    @staticmethod
    def _row_to_instrument(row: sqlite3.Row) -> PredictionInstrument:
        return PredictionInstrument(
            symbol=row["symbol"], venue=row["venue"], event_id=row["event_id"],
            ticker=row["ticker"], outcome=row["outcome"], category=row["category"],
            title=row["title"], description=row["description"], expiry=row["expiry"],
            market_implied_prob=row["market_implied_prob"], volume=row["volume"],
            open_interest=row["open_interest"], status=row["status"],
            last_refreshed=row["last_refreshed"],
        )

    @staticmethod
    def _row_to_opinion(row: sqlite3.Row) -> PredictionOpinion:
        explanation_raw = row["explanation"] if "explanation" in row.keys() else ""
        explanation = None
        if explanation_raw:
            try:
                explanation = json.loads(explanation_raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return PredictionOpinion(
            id=row["id"], agent_id=row["agent_id"], agent_name=row["agent_name"],
            symbol=row["symbol"], probability=row["probability"],
            confidence=row["confidence"], reasoning=row["reasoning"],
            signal_sources=json.loads(row["signal_sources"]),
            horizon=row["horizon"], explanation=explanation,
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> PredictionPlan:
        return PredictionPlan(
            id=row["id"], symbol=row["symbol"], direction=row["direction"],
            target_size_usd=row["target_size_usd"],
            max_edge_threshold=row["max_edge_threshold"],
            confidence=row["confidence"], status=row["status"],
            supporting_agents=json.loads(row["supporting_agents"]),
            opposing_agents=json.loads(row["opposing_agents"]),
            max_spread_cents=row["max_spread_cents"],
            min_liquidity=row["min_liquidity"],
            cutoff_hours_before_expiry=row["cutoff_hours_before_expiry"],
            created_at=row["created_at"],
        )


# ── Singleton ────────────────────────────────────────────────────────

_store: Optional[PredictionConsensusStore] = None


def get_prediction_consensus_store() -> PredictionConsensusStore:
    """Get or create the singleton PredictionConsensusStore."""
    global _store
    if _store is None:
        _store = PredictionConsensusStore()
    return _store


# ── Convenience API ──────────────────────────────────────────────────

def add_prediction_instrument(**kwargs: Any) -> PredictionInstrument:
    inst = PredictionInstrument(**kwargs)
    if not inst.symbol and inst.ticker:
        inst.symbol = _make_pred_symbol(inst.venue, inst.ticker, inst.outcome)
    return get_prediction_consensus_store().upsert_instrument(inst)


def add_prediction_opinion(**kwargs: Any) -> PredictionOpinion:
    op = PredictionOpinion(**kwargs)
    return get_prediction_consensus_store().add_opinion(op)


def add_prediction_plan(**kwargs: Any) -> PredictionPlan:
    plan = PredictionPlan(**kwargs)
    return get_prediction_consensus_store().add_plan(plan)
