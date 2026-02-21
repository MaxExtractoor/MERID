"""Debate, Teamwork & Rewards layer for prediction market consensus.

Extends the existing opinion/consensus spine with:
  - DebateSession: structured multi-agent debate per instrument
  - DebateArgument: individual argument within a debate (propose/challenge/revise)
  - AgentTeam: named group of agents with team-level scoring
  - RewardLedger: point-based rewards for accuracy, debate lift, explanation quality
  - Leaderboard + badge computation

All data persisted in the same SQLite DB as PredictionConsensusStore.
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
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.debate")


# ── Domain objects ───────────────────────────────────────────────────

DEBATE_STATUSES = ("open", "closed", "resolved")
ARGUMENT_ROLES = ("proposer", "challenger", "arbiter")
BADGE_TYPES = (
    "reliable_contrarian",    # Frequently disagrees with market and is right
    "consensus_builder",      # Often moves team toward better outcomes
    "explainer",              # High explanation coverage/quality
    "debate_champion",        # High debate lift contribution
    "team_player",            # Consistently improves team accuracy
)


@dataclass
class DebateArgument:
    """A single argument within a debate session."""
    id: str = field(default_factory=lambda: f"darg-{uuid.uuid4().hex[:12]}")
    debate_id: str = ""
    agent_id: str = ""
    role: str = "proposer"           # proposer, challenger, arbiter
    opinion_id: str = ""             # Links to PredictionOpinion
    probability: float = 0.5         # Agent's probability at time of argument
    confidence: float = 0.5
    rationale: str = ""              # Machine-readable rationale tag
    explanation: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "debate_id": self.debate_id,
            "agent_id": self.agent_id,
            "role": self.role,
            "opinion_id": self.opinion_id,
            "probability": round(self.probability, 4),
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
            "timestamp": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }
        if self.explanation:
            d["explanation"] = self.explanation
        return d


@dataclass
class DebateSession:
    """A structured multi-agent debate on a prediction instrument."""
    id: str = field(default_factory=lambda: f"deb-{uuid.uuid4().hex[:12]}")
    symbol: str = ""                 # PRED:KALSHI:<TICKER>:YES
    status: str = "open"             # open, closed, resolved
    team_id: str = ""                # Optional team context
    pre_debate_prob: float = 0.5     # Swarm prob before debate
    post_debate_prob: Optional[float] = None  # Swarm prob after debate
    outcome: Optional[int] = None    # 1=YES, 0=NO (set on resolution)
    debate_lift: Optional[float] = None  # Brier improvement from debate
    rounds: int = 0                  # Number of argument rounds
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "symbol": self.symbol,
            "status": self.status,
            "team_id": self.team_id,
            "pre_debate_prob": round(self.pre_debate_prob, 4),
            "rounds": self.rounds,
            "created_at": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }
        if self.post_debate_prob is not None:
            d["post_debate_prob"] = round(self.post_debate_prob, 4)
        if self.debate_lift is not None:
            d["debate_lift"] = round(self.debate_lift, 4)
        if self.outcome is not None:
            d["outcome"] = self.outcome
        if self.closed_at is not None:
            d["closed_at"] = datetime.fromtimestamp(self.closed_at, tz=timezone.utc).isoformat()
        return d


@dataclass
class AgentTeam:
    """A named group of agents for team-level scoring."""
    id: str = field(default_factory=lambda: f"team-{uuid.uuid4().hex[:12]}")
    name: str = ""
    member_ids: List[str] = field(default_factory=list)
    strategy_mix: str = ""           # e.g. "mean_reversion+calibration_aware"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "member_ids": self.member_ids,
            "strategy_mix": self.strategy_mix,
            "created_at": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }


@dataclass
class RewardEntry:
    """A single reward event in the ledger."""
    id: str = field(default_factory=lambda: f"rew-{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    team_id: str = ""
    reward_type: str = ""            # accuracy, debate_lift, explanation, cooperation, timeliness
    points: float = 0.0
    detail: str = ""                 # Human-readable reason
    symbol: str = ""                 # Related instrument
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "team_id": self.team_id,
            "reward_type": self.reward_type,
            "points": round(self.points, 2),
            "detail": self.detail,
            "symbol": self.symbol,
            "timestamp": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
        }


# ── SQLite schema ────────────────────────────────────────────────────

_CREATE_DEBATES = """
CREATE TABLE IF NOT EXISTS pred_debates (
    id                TEXT PRIMARY KEY,
    symbol            TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'open',
    team_id           TEXT NOT NULL DEFAULT '',
    pre_debate_prob   REAL NOT NULL DEFAULT 0.5,
    post_debate_prob  REAL,
    outcome           INTEGER,
    debate_lift       REAL,
    rounds            INTEGER NOT NULL DEFAULT 0,
    created_at        REAL NOT NULL,
    closed_at         REAL
);
"""

_CREATE_DEBATE_ARGS = """
CREATE TABLE IF NOT EXISTS pred_debate_args (
    id                TEXT PRIMARY KEY,
    debate_id         TEXT NOT NULL DEFAULT '',
    agent_id          TEXT NOT NULL DEFAULT '',
    role              TEXT NOT NULL DEFAULT 'proposer',
    opinion_id        TEXT NOT NULL DEFAULT '',
    probability       REAL NOT NULL DEFAULT 0.5,
    confidence        REAL NOT NULL DEFAULT 0.5,
    rationale         TEXT NOT NULL DEFAULT '',
    explanation       TEXT NOT NULL DEFAULT '',
    created_at        REAL NOT NULL
);
"""

_CREATE_TEAMS = """
CREATE TABLE IF NOT EXISTS pred_teams (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL DEFAULT '',
    member_ids        TEXT NOT NULL DEFAULT '[]',
    strategy_mix      TEXT NOT NULL DEFAULT '',
    created_at        REAL NOT NULL
);
"""

_CREATE_REWARDS = """
CREATE TABLE IF NOT EXISTS pred_rewards (
    id                TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL DEFAULT '',
    team_id           TEXT NOT NULL DEFAULT '',
    reward_type       TEXT NOT NULL DEFAULT '',
    points            REAL NOT NULL DEFAULT 0,
    detail            TEXT NOT NULL DEFAULT '',
    symbol            TEXT NOT NULL DEFAULT '',
    created_at        REAL NOT NULL
);
"""

_CREATE_DEBATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_debates_symbol ON pred_debates(symbol);
CREATE INDEX IF NOT EXISTS idx_debates_status ON pred_debates(status);
CREATE INDEX IF NOT EXISTS idx_debate_args_debate ON pred_debate_args(debate_id);
CREATE INDEX IF NOT EXISTS idx_debate_args_agent ON pred_debate_args(agent_id);
CREATE INDEX IF NOT EXISTS idx_rewards_agent ON pred_rewards(agent_id);
CREATE INDEX IF NOT EXISTS idx_rewards_type ON pred_rewards(reward_type);
CREATE INDEX IF NOT EXISTS idx_rewards_created ON pred_rewards(created_at DESC);
"""


# ── Reward calculation constants ─────────────────────────────────────

REWARD_ACCURACY_BASE = 10.0          # Points for submitting a timely opinion
REWARD_ACCURACY_BRIER_BONUS = 50.0   # Max bonus for Brier < 0.1
REWARD_DEBATE_LIFT_BONUS = 30.0      # Points for positive debate lift
REWARD_EXPLANATION_BONUS = 5.0       # Points for having explanation attached
REWARD_COOPERATION_BONUS = 20.0      # Points when team accuracy is high + non-trivial disagreement


# ── DebateStore ──────────────────────────────────────────────────────

class DebateStore:
    """SQLite store for debate sessions, teams, and rewards.

    Shares the same DB as PredictionConsensusStore for unified querying.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_DEBATES)
            conn.execute(_CREATE_DEBATE_ARGS)
            conn.execute(_CREATE_TEAMS)
            conn.execute(_CREATE_REWARDS)
            conn.executescript(_CREATE_DEBATE_INDEXES)
        logger.info("Debate store initialized: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Debate sessions ──────────────────────────────────────────────

    def create_debate(self, debate: DebateSession) -> DebateSession:
        """Create a new debate session."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO pred_debates "
                    "(id, symbol, status, team_id, pre_debate_prob, post_debate_prob, "
                    " outcome, debate_lift, rounds, created_at, closed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (debate.id, debate.symbol, debate.status, debate.team_id,
                     debate.pre_debate_prob, debate.post_debate_prob,
                     debate.outcome, debate.debate_lift, debate.rounds,
                     debate.created_at, debate.closed_at),
                )
        return debate

    def get_debate(self, debate_id: str) -> Optional[DebateSession]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pred_debates WHERE id = ?", (debate_id,)).fetchone()
        return self._row_to_debate(row) if row else None

    def list_debates(self, symbol: Optional[str] = None, status: Optional[str] = None,
                     limit: int = 50) -> List[DebateSession]:
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
                f"SELECT * FROM pred_debates{where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_debate(r) for r in rows]

    def close_debate(self, debate_id: str, post_debate_prob: float) -> Optional[DebateSession]:
        """Close a debate session with the post-debate consensus probability."""
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE pred_debates SET status = 'closed', post_debate_prob = ?, "
                    "closed_at = ? WHERE id = ?",
                    (post_debate_prob, now, debate_id),
                )
        return self.get_debate(debate_id)

    def resolve_debate(self, debate_id: str, outcome: int) -> Optional[DebateSession]:
        """Resolve a debate with the actual outcome and compute debate lift."""
        debate = self.get_debate(debate_id)
        if not debate:
            return None

        # Compute debate lift: Brier improvement from pre→post debate
        pre_brier = (debate.pre_debate_prob - outcome) ** 2
        post_prob = debate.post_debate_prob if debate.post_debate_prob is not None else debate.pre_debate_prob
        post_brier = (post_prob - outcome) ** 2
        lift = round(pre_brier - post_brier, 4)  # Positive = debate improved accuracy

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE pred_debates SET status = 'resolved', outcome = ?, "
                    "debate_lift = ? WHERE id = ?",
                    (outcome, lift, debate_id),
                )
        return self.get_debate(debate_id)

    # ── Debate arguments ─────────────────────────────────────────────

    def add_argument(self, arg: DebateArgument) -> DebateArgument:
        """Add an argument to a debate session and increment round count."""
        explanation_json = json.dumps(arg.explanation) if arg.explanation else ""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO pred_debate_args "
                    "(id, debate_id, agent_id, role, opinion_id, probability, "
                    " confidence, rationale, explanation, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (arg.id, arg.debate_id, arg.agent_id, arg.role,
                     arg.opinion_id, arg.probability, arg.confidence,
                     arg.rationale, explanation_json, arg.created_at),
                )
                conn.execute(
                    "UPDATE pred_debates SET rounds = rounds + 1 WHERE id = ?",
                    (arg.debate_id,),
                )
        return arg

    def list_arguments(self, debate_id: str) -> List[DebateArgument]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pred_debate_args WHERE debate_id = ? ORDER BY created_at ASC",
                (debate_id,),
            ).fetchall()
        return [self._row_to_argument(r) for r in rows]

    # ── Teams ────────────────────────────────────────────────────────

    def create_team(self, team: AgentTeam) -> AgentTeam:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO pred_teams (id, name, member_ids, strategy_mix, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (team.id, team.name, json.dumps(team.member_ids),
                     team.strategy_mix, team.created_at),
                )
        return team

    def get_team(self, team_id: str) -> Optional[AgentTeam]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM pred_teams WHERE id = ?", (team_id,)).fetchone()
        return self._row_to_team(row) if row else None

    def list_teams(self, limit: int = 50) -> List[AgentTeam]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pred_teams ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_team(r) for r in rows]

    def get_team_for_agent(self, agent_id: str) -> Optional[AgentTeam]:
        """Find the team an agent belongs to."""
        teams = self.list_teams(limit=200)
        for team in teams:
            if agent_id in team.member_ids:
                return team
        return None

    # ── Rewards ──────────────────────────────────────────────────────

    def add_reward(self, entry: RewardEntry) -> RewardEntry:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO pred_rewards "
                    "(id, agent_id, team_id, reward_type, points, detail, symbol, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry.id, entry.agent_id, entry.team_id, entry.reward_type,
                     entry.points, entry.detail, entry.symbol, entry.created_at),
                )
        return entry

    def get_agent_rewards(self, agent_id: str, limit: int = 100) -> List[RewardEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pred_rewards WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        return [self._row_to_reward(r) for r in rows]

    def get_agent_total_points(self, agent_id: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(points), 0) as total FROM pred_rewards WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return row["total"] if row else 0.0

    def get_team_total_points(self, team_id: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(points), 0) as total FROM pred_rewards WHERE team_id = ?",
                (team_id,),
            ).fetchone()
        return row["total"] if row else 0.0

    # ── Reward calculation ───────────────────────────────────────────

    def compute_rewards_for_resolution(
        self, symbol: str, outcome: int, opinions: List[Any],
        min_disagreement_for_reward: float = 0.03,
    ) -> List[RewardEntry]:
        """Compute and store rewards when a market resolves.

        Awards points for:
          - Base: submitting a timely, explained opinion
          - Accuracy: Brier-based bonus (lower Brier = more points)
          - Debate lift: bonus if agent participated in a debate that improved
            accuracy AND the agent's own Brier also improved (B1 accuracy gate)
          - Cooperation: bonus when team accuracy is high

        Anti-spam gates (B3):
          - Debate lift bonus requires disagreement_width >= min_disagreement_for_reward
          - Explanation bonus requires non-empty rationale
        """
        entries: List[RewardEntry] = []
        outcome_f = float(outcome)

        # Get debates for this symbol
        debates = self.list_debates(symbol=symbol, status="resolved")

        # Build agent→debate participation map with lift and disagreement
        agent_debate_lift: Dict[str, float] = {}
        agent_debate_disagreement: Dict[str, float] = {}
        debate_pre_brier: Dict[str, float] = {}
        for deb in debates:
            args = self.list_arguments(deb.id)
            pre_brier = (deb.pre_debate_prob - outcome_f) ** 2
            debate_pre_brier[deb.id] = pre_brier
            # Compute disagreement from arguments
            probs = [a.probability for a in args]
            # Only compute disagreement when 2+ arguments; single-arg debates bypass anti-spam
            disagreement = max(probs) - min(probs) if len(probs) >= 2 else float('inf')
            for arg in args:
                if deb.debate_lift is not None:
                    existing = agent_debate_lift.get(arg.agent_id, 0.0)
                    agent_debate_lift[arg.agent_id] = max(existing, deb.debate_lift)
                existing_d = agent_debate_disagreement.get(arg.agent_id, 0.0)
                agent_debate_disagreement[arg.agent_id] = max(existing_d, disagreement)

        for op in opinions:
            agent_id = op.agent_id if hasattr(op, "agent_id") else ""
            prob = op.probability if hasattr(op, "probability") else 0.5
            has_explanation = (op.explanation is not None) if hasattr(op, "explanation") else False
            rationale = ""
            if has_explanation and hasattr(op, "explanation") and op.explanation:
                rationale = op.explanation.get("rationale", "") if isinstance(op.explanation, dict) else ""

            # Base points for submitting
            base = REWARD_ACCURACY_BASE
            entries.append(RewardEntry(
                agent_id=agent_id, reward_type="timeliness",
                points=base, detail="Timely opinion submitted", symbol=symbol,
            ))

            # Explanation bonus (B3: require non-empty rationale)
            if has_explanation and rationale:
                entries.append(RewardEntry(
                    agent_id=agent_id, reward_type="explanation",
                    points=REWARD_EXPLANATION_BONUS,
                    detail="Explanation attached to opinion", symbol=symbol,
                ))

            # Accuracy bonus (Brier-based: lower Brier = more points)
            brier = (prob - outcome_f) ** 2
            accuracy_bonus = round(REWARD_ACCURACY_BRIER_BONUS * (1.0 - brier), 2)
            if accuracy_bonus > 0:
                entries.append(RewardEntry(
                    agent_id=agent_id, reward_type="accuracy",
                    points=accuracy_bonus,
                    detail=f"Brier={brier:.4f}, bonus={accuracy_bonus:.2f}",
                    symbol=symbol,
                ))

            # Debate lift bonus (B1: accuracy-gated, B3: anti-spam gated)
            lift = agent_debate_lift.get(agent_id, 0.0)
            disagreement = agent_debate_disagreement.get(agent_id, 0.0)
            if lift > 0 and disagreement >= min_disagreement_for_reward:
                # B1: Only award if agent's own Brier is better than pre-debate
                agent_brier = (prob - outcome_f) ** 2
                # Find the pre-debate Brier for debates this agent participated in
                pre_briers = list(debate_pre_brier.values())
                avg_pre_brier = sum(pre_briers) / len(pre_briers) if pre_briers else 1.0
                if agent_brier < avg_pre_brier:
                    lift_bonus = round(REWARD_DEBATE_LIFT_BONUS * min(lift * 4, 1.0), 2)
                    entries.append(RewardEntry(
                        agent_id=agent_id, reward_type="debate_lift",
                        points=lift_bonus,
                        detail=f"Debate lift={lift:.4f}, individual_lift={avg_pre_brier - agent_brier:.4f}, bonus={lift_bonus:.2f}",
                        symbol=symbol,
                    ))

        # Store all rewards
        for entry in entries:
            # Attach team_id if agent belongs to a team
            team = self.get_team_for_agent(entry.agent_id)
            if team:
                entry.team_id = team.id
            self.add_reward(entry)

        return entries

    # ── Debate metrics ───────────────────────────────────────────────

    def get_debate_metrics(self, window_s: float = 3600.0) -> Dict[str, Any]:
        """Compute debate health metrics over a time window.

        Returns:
            active_debates: count of open debates
            total_debates: count in window
            avg_rounds: average argument rounds per debate
            avg_debate_lift: average Brier improvement from debates
            disagreement_width: average probability spread between debaters
            argument_effectiveness: how often arguments lead to improved accuracy
        """
        now = time.time()
        cutoff = now - window_s

        with self._connect() as conn:
            # Debate counts
            active = conn.execute(
                "SELECT COUNT(*) FROM pred_debates WHERE status = 'open'"
            ).fetchone()[0]

            debates_in_window = conn.execute(
                "SELECT * FROM pred_debates WHERE created_at > ?", (cutoff,)
            ).fetchall()

            resolved_debates = conn.execute(
                "SELECT * FROM pred_debates WHERE status = 'resolved' AND created_at > ?",
                (cutoff,),
            ).fetchall()

            # Arguments in window
            args_in_window = conn.execute(
                "SELECT * FROM pred_debate_args WHERE created_at > ?", (cutoff,)
            ).fetchall()

        total = len(debates_in_window)
        avg_rounds = 0.0
        if total > 0:
            avg_rounds = round(sum(r["rounds"] for r in debates_in_window) / total, 1)

        # Debate lift stats
        lifts = [r["debate_lift"] for r in resolved_debates if r["debate_lift"] is not None]
        avg_lift = round(sum(lifts) / len(lifts), 4) if lifts else 0.0
        positive_lift_count = sum(1 for l in lifts if l > 0)
        negative_lift_count = sum(1 for l in lifts if l < 0)

        # Disagreement width: per-debate, avg distance between debaters' probabilities
        disagreement_widths: List[float] = []
        debate_args_map: Dict[str, List[float]] = {}
        for a in args_in_window:
            debate_args_map.setdefault(a["debate_id"], []).append(a["probability"])
        for probs in debate_args_map.values():
            if len(probs) >= 2:
                width = max(probs) - min(probs)
                disagreement_widths.append(width)
        avg_disagreement = round(sum(disagreement_widths) / len(disagreement_widths), 4) if disagreement_widths else 0.0

        return {
            "active_debates": active,
            "total_debates": total,
            "avg_rounds": avg_rounds,
            "resolved_debates": len(resolved_debates),
            "avg_debate_lift": avg_lift,
            "positive_lift_count": positive_lift_count,
            "negative_lift_count": negative_lift_count,
            "avg_disagreement_width": avg_disagreement,
            "total_arguments": len(args_in_window),
            "window_s": window_s,
        }

    # ── Leaderboard + badges ─────────────────────────────────────────

    def compute_leaderboard(self, limit: int = 20, decay_lambda: Optional[float] = None) -> Dict[str, Any]:
        """Compute agent and team leaderboards from reward data.

        When ``decay_lambda`` is set (B2), applies exponential time-decay:
          effective_points = points × exp(-λ × age_days)
        Raw points are stored; decay is applied at query time only.
        Default decay_lambda comes from MERID_LEADERBOARD_DECAY_LAMBDA env var
        (default 0.0 = no decay for backward compatibility).
        """
        import math as _math

        if decay_lambda is None:
            decay_lambda = float(os.environ.get("MERID_LEADERBOARD_DECAY_LAMBDA", "0.0"))

        now = time.time()

        with self._connect() as conn:
            # Fetch all rewards for decay computation
            all_rewards = conn.execute(
                "SELECT agent_id, team_id, reward_type, points, created_at "
                "FROM pred_rewards"
            ).fetchall()

        # Apply decay and aggregate
        agent_totals: Dict[str, Dict[str, Any]] = {}
        team_totals: Dict[str, Dict[str, Any]] = {}
        debate_totals: Dict[str, float] = {}

        for r in all_rewards:
            age_days = (now - r["created_at"]) / 86400.0
            decay = _math.exp(-decay_lambda * age_days) if decay_lambda > 0 else 1.0
            effective = r["points"] * decay

            aid = r["agent_id"]
            if aid not in agent_totals:
                agent_totals[aid] = {"total": 0.0, "events": 0}
            agent_totals[aid]["total"] += effective
            agent_totals[aid]["events"] += 1

            tid = r["team_id"]
            if tid:
                if tid not in team_totals:
                    team_totals[tid] = {"total": 0.0, "events": 0}
                team_totals[tid]["total"] += effective
                team_totals[tid]["events"] += 1

            if r["reward_type"] == "debate_lift":
                debate_totals[aid] = debate_totals.get(aid, 0.0) + effective

        # Sort and limit
        agents_sorted = sorted(agent_totals.items(), key=lambda x: x[1]["total"], reverse=True)[:limit]
        teams_sorted = sorted(team_totals.items(), key=lambda x: x[1]["total"], reverse=True)[:limit]
        debate_sorted = sorted(debate_totals.items(), key=lambda x: x[1], reverse=True)[:limit]

        return {
            "agents": [
                {"agent_id": aid, "total_points": round(data["total"], 2),
                 "reward_events": data["events"]}
                for aid, data in agents_sorted
            ],
            "teams": [
                {"team_id": tid, "total_points": round(data["total"], 2),
                 "reward_events": data["events"]}
                for tid, data in teams_sorted
            ],
            "debate_impact": [
                {"agent_id": aid, "debate_lift_points": round(pts, 2)}
                for aid, pts in debate_sorted
            ],
            "decay_lambda": decay_lambda,
        }

    def compute_badges(self, agent_id: str) -> List[Dict[str, Any]]:
        """Compute badges earned by an agent based on reward history.

        B4: Each badge has bronze/silver/gold tiers with escalating thresholds.
        """
        badges: List[Dict[str, Any]] = []
        rewards = self.get_agent_rewards(agent_id, limit=500)
        if not rewards:
            return badges

        # Count reward types
        type_points: Dict[str, float] = {}
        for r in rewards:
            type_points[r.reward_type] = type_points.get(r.reward_type, 0.0) + r.points

        total_points = sum(type_points.values())

        # Explainer: explanation coverage tiers
        timeliness_count = sum(1 for r in rewards if r.reward_type == "timeliness")
        explanation_count = sum(1 for r in rewards if r.reward_type == "explanation")
        if timeliness_count > 0:
            coverage = explanation_count / timeliness_count
            tier = None
            if coverage >= 0.95:
                tier = "gold"
            elif coverage >= 0.80:
                tier = "silver"
            elif coverage >= 0.60:
                tier = "bronze"
            if tier:
                badges.append({
                    "badge": "explainer", "tier": tier,
                    "description": f"Explanation coverage ({coverage:.0%})",
                    "score": round(coverage, 2),
                })

        # Debate champion: debate lift points tiers
        debate_lift_points = type_points.get("debate_lift", 0.0)
        dlb = REWARD_DEBATE_LIFT_BONUS
        tier = None
        if debate_lift_points >= dlb * 5:
            tier = "gold"
        elif debate_lift_points >= dlb * 3:
            tier = "silver"
        elif debate_lift_points >= dlb * 1:
            tier = "bronze"
        if tier:
            badges.append({
                "badge": "debate_champion", "tier": tier,
                "description": "Positive debate lift contributions",
                "score": round(debate_lift_points, 2),
            })

        # Reliable contrarian: accuracy points tiers
        accuracy_points = type_points.get("accuracy", 0.0)
        abb = REWARD_ACCURACY_BRIER_BONUS
        tier = None
        if accuracy_points >= abb * 10:
            tier = "gold"
        elif accuracy_points >= abb * 5:
            tier = "silver"
        elif accuracy_points >= abb * 3:
            tier = "bronze"
        if tier:
            badges.append({
                "badge": "reliable_contrarian", "tier": tier,
                "description": "Consistently accurate forecaster",
                "score": round(accuracy_points, 2),
            })

        # Team player: cooperation rewards tiers
        coop_points = type_points.get("cooperation", 0.0)
        cb = REWARD_COOPERATION_BONUS
        tier = None
        if coop_points >= cb * 4:
            tier = "gold"
        elif coop_points >= cb * 2:
            tier = "silver"
        elif coop_points >= cb * 1:
            tier = "bronze"
        if tier:
            badges.append({
                "badge": "team_player", "tier": tier,
                "description": "Improves team accuracy through cooperation",
                "score": round(coop_points, 2),
            })

        # Consensus builder: debates with positive lift tiers
        debate_rewards = [r for r in rewards if r.reward_type == "debate_lift" and r.points > 0]
        n_debates = len(debate_rewards)
        tier = None
        if n_debates >= 10:
            tier = "gold"
        elif n_debates >= 5:
            tier = "silver"
        elif n_debates >= 3:
            tier = "bronze"
        if tier:
            badges.append({
                "badge": "consensus_builder", "tier": tier,
                "description": "Moves team toward better outcomes through debate",
                "score": n_debates,
            })

        return badges

    # ── Team diversity (B5) ──────────────────────────────────────────

    def compute_team_diversity_score(self, team_id: str) -> Dict[str, Any]:
        """Compute strategy diversity score for a team.

        Measures how many distinct strategies team members use in debates.
        Teams using only 1 strategy get 0.0; 2 strategies get 0.5; 3+ get 1.0.
        """
        team = self.get_team(team_id)
        if not team:
            return {"team_id": team_id, "diversity_score": 0.0, "strategies": [], "error": "team_not_found"}

        # Find all debate arguments by team members
        strategies_used: set = set()
        with self._connect() as conn:
            for member_id in team.member_ids:
                rows = conn.execute(
                    "SELECT DISTINCT rationale FROM pred_debate_args WHERE agent_id = ?",
                    (member_id,),
                ).fetchall()
                for row in rows:
                    if row["rationale"]:
                        strategies_used.add(row["rationale"])

        n = len(strategies_used)
        if n <= 1:
            score = 0.0
        elif n == 2:
            score = 0.5
        else:
            score = 1.0

        return {
            "team_id": team_id,
            "diversity_score": score,
            "strategies": sorted(strategies_used),
            "strategy_count": n,
        }

    # ── Calibration (B6) ──────────────────────────────────────────────

    def compute_calibration_score(
        self,
        agent_id: str,
        brier_data: Optional[List[Dict[str, Any]]] = None,
        n_bins: int = 10,
    ) -> Dict[str, Any]:
        """Compute calibration score for an agent — single source of truth.

        Buckets the agent's historical predictions into bins and compares
        predicted probability vs actual outcome rate per bin.

        Args:
            agent_id: Agent to compute calibration for.
            brier_data: Optional pre-computed list of dicts with 'probability'
                and 'outcome' keys (reuses existing Brier history to avoid
                redundant DB hits). If None, pulls from debate arguments +
                resolved debates.
            n_bins: Number of calibration bins (default 10).

        Returns:
            Dict with scalar calibration_score (1 - mean absolute error),
            full calibration curve, and bin details.
        """
        # Gather prediction/outcome pairs
        pairs: List[Dict[str, Any]] = []

        if brier_data is not None:
            pairs = brier_data
        else:
            # Pull from resolved debates where this agent participated
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT a.probability, d.outcome "
                    "FROM pred_debate_args a "
                    "JOIN pred_debates d ON a.debate_id = d.id "
                    "WHERE a.agent_id = ? AND d.status = 'resolved' AND d.outcome IS NOT NULL",
                    (agent_id,),
                ).fetchall()
                pairs = [{"probability": r["probability"], "outcome": r["outcome"]} for r in rows]

        if not pairs:
            return {
                "agent_id": agent_id,
                "calibration_score": None,
                "total_predictions": 0,
                "bins": [],
            }

        # Bucket into bins
        bin_width = 1.0 / n_bins
        bins: List[Dict[str, Any]] = []
        total_abs_error = 0.0
        bins_with_data = 0

        for i in range(n_bins):
            lo = i * bin_width
            hi = (i + 1) * bin_width
            in_bin = [p for p in pairs if lo <= p["probability"] < hi or (i == n_bins - 1 and p["probability"] == 1.0)]

            if not in_bin:
                bins.append({
                    "bin_lo": round(lo, 2), "bin_hi": round(hi, 2),
                    "count": 0, "predicted_mean": None, "actual_rate": None,
                    "abs_error": None,
                })
                continue

            predicted_mean = sum(p["probability"] for p in in_bin) / len(in_bin)
            actual_rate = sum(p["outcome"] for p in in_bin) / len(in_bin)
            abs_error = abs(predicted_mean - actual_rate)
            total_abs_error += abs_error
            bins_with_data += 1

            bins.append({
                "bin_lo": round(lo, 2), "bin_hi": round(hi, 2),
                "count": len(in_bin),
                "predicted_mean": round(predicted_mean, 4),
                "actual_rate": round(actual_rate, 4),
                "abs_error": round(abs_error, 4),
            })

        mean_abs_error = total_abs_error / bins_with_data if bins_with_data > 0 else 1.0
        calibration_score = round(1.0 - mean_abs_error, 4)

        return {
            "agent_id": agent_id,
            "calibration_score": calibration_score,
            "mean_absolute_error": round(mean_abs_error, 4),
            "total_predictions": len(pairs),
            "bins_with_data": bins_with_data,
            "bins": bins,
        }

    # ── Row converters ───────────────────────────────────────────────

    @staticmethod
    def _row_to_debate(row: sqlite3.Row) -> DebateSession:
        return DebateSession(
            id=row["id"], symbol=row["symbol"], status=row["status"],
            team_id=row["team_id"], pre_debate_prob=row["pre_debate_prob"],
            post_debate_prob=row["post_debate_prob"], outcome=row["outcome"],
            debate_lift=row["debate_lift"], rounds=row["rounds"],
            created_at=row["created_at"], closed_at=row["closed_at"],
        )

    @staticmethod
    def _row_to_argument(row: sqlite3.Row) -> DebateArgument:
        explanation_raw = row["explanation"] if "explanation" in row.keys() else ""
        explanation = None
        if explanation_raw:
            try:
                explanation = json.loads(explanation_raw)
            except (json.JSONDecodeError, TypeError):
                pass
        return DebateArgument(
            id=row["id"], debate_id=row["debate_id"], agent_id=row["agent_id"],
            role=row["role"], opinion_id=row["opinion_id"],
            probability=row["probability"], confidence=row["confidence"],
            rationale=row["rationale"], explanation=explanation,
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_team(row: sqlite3.Row) -> AgentTeam:
        return AgentTeam(
            id=row["id"], name=row["name"],
            member_ids=json.loads(row["member_ids"]),
            strategy_mix=row["strategy_mix"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _row_to_reward(row: sqlite3.Row) -> RewardEntry:
        return RewardEntry(
            id=row["id"], agent_id=row["agent_id"], team_id=row["team_id"],
            reward_type=row["reward_type"], points=row["points"],
            detail=row["detail"], symbol=row["symbol"],
            created_at=row["created_at"],
        )


# ── Debate Backtest Harness ────────────────────────────────────────────

class DebateBacktester:
    """Replay resolved markets through the debate protocol and measure lift.

    Runs each market through a configurable proposer→challenger→arbiter
    pipeline and computes aggregate debate lift statistics with per-agent
    and per-team attribution.
    """

    def __init__(self, store: Optional["DebateStore"] = None):
        self._store = store

    def _get_store(self) -> "DebateStore":
        if self._store is not None:
            return self._store
        return get_debate_store()

    def run_backtest(
        self,
        markets: List[Dict[str, Any]],
        proposer_strategy: str = "mean_reversion",
        arbiter_strategy: str = "arbiter",
        proposer_agent_id: str = "bt-proposer-01",
        challenger_agent_id: str = "bt-challenger-01",
        arbiter_agent_id: str = "bt-arbiter-01",
        team_id: str = "",
    ) -> Dict[str, Any]:
        """Run a backtest over a list of resolved markets.

        Args:
            markets: List of dicts with keys: symbol, ticker, market_prob,
                     outcome (1 or 0), and optionally category.
            proposer_strategy: Name of the proposer strategy to use.
            arbiter_strategy: Name of the arbiter strategy to use.
            proposer_agent_id: Agent ID for the proposer.
            challenger_agent_id: Agent ID for the challenger.
            arbiter_agent_id: Agent ID for the arbiter.
            team_id: Optional team ID for attribution.

        Returns:
            Structured report with aggregate and per-market lift stats.
        """
        from merid.prediction.opinion_strategy import get_strategy

        try:
            prop_strat = get_strategy(proposer_strategy)
            chal_strat = get_strategy("challenger")
            arb_strat = get_strategy(arbiter_strategy)
        except Exception as exc:
            return {"error": f"Strategy init failed: {exc}", "markets_tested": 0}

        results: List[Dict[str, Any]] = []
        lifts: List[float] = []
        improved_count = 0
        skipped_count = 0

        for mkt in markets:
            symbol = mkt.get("symbol", "")
            ticker = mkt.get("ticker", symbol)
            market_prob = mkt.get("market_prob", 0.5)
            outcome = mkt.get("outcome", 0)
            category = mkt.get("category", "")

            # Step 1: Proposer
            prop_est = prop_strat.estimate(
                agent_id=proposer_agent_id, ticker=ticker,
                market_prob=market_prob, category=category,
            )
            if prop_est is None:
                skipped_count += 1
                continue

            # Step 2: Challenger
            chal_ctx = {
                "proposer_prob": prop_est.agent_prob,
                "proposer_rationale": prop_est.reasoning_tag,
            }
            chal_est = chal_strat.estimate(
                agent_id=challenger_agent_id, ticker=ticker,
                market_prob=market_prob, category=category,
                context=chal_ctx,
            )

            # Step 3: Arbiter
            arb_ctx = {
                "proposer_prob": prop_est.agent_prob,
                "proposer_confidence": prop_est.confidence,
                "challenger_prob": chal_est.agent_prob if chal_est else market_prob,
                "challenger_confidence": chal_est.confidence if chal_est else 0.3,
            }
            arb_est = arb_strat.estimate(
                agent_id=arbiter_agent_id, ticker=ticker,
                market_prob=market_prob, category=category,
                context=arb_ctx,
            )

            post_prob = arb_est.agent_prob if arb_est else prop_est.agent_prob
            pre_brier = (market_prob - outcome) ** 2
            post_brier = (post_prob - outcome) ** 2
            lift = round(pre_brier - post_brier, 6)

            if lift > 0:
                improved_count += 1
            lifts.append(lift)

            results.append({
                "symbol": symbol,
                "market_prob": round(market_prob, 4),
                "outcome": outcome,
                "proposer": {
                    "agent_id": proposer_agent_id,
                    "strategy": proposer_strategy,
                    "prob": prop_est.agent_prob,
                    "confidence": prop_est.confidence,
                },
                "challenger": {
                    "agent_id": challenger_agent_id,
                    "prob": chal_est.agent_prob if chal_est else None,
                    "confidence": chal_est.confidence if chal_est else None,
                },
                "arbiter": {
                    "agent_id": arbiter_agent_id,
                    "strategy": arbiter_strategy,
                    "prob": arb_est.agent_prob if arb_est else None,
                },
                "post_debate_prob": round(post_prob, 4),
                "pre_brier": round(pre_brier, 6),
                "post_brier": round(post_brier, 6),
                "debate_lift": lift,
            })

        n = len(lifts)
        mean_lift = round(sum(lifts) / n, 6) if n > 0 else 0.0
        worst_lift = round(min(lifts), 6) if n > 0 else 0.0
        best_lift = round(max(lifts), 6) if n > 0 else 0.0

        # Per-agent attribution: how much lift each agent contributed
        agent_lifts: Dict[str, List[float]] = {}
        for r in results:
            for role in ("proposer", "challenger", "arbiter"):
                aid = r[role].get("agent_id", "") if isinstance(r[role], dict) else ""
                if aid:
                    agent_lifts.setdefault(aid, []).append(r["debate_lift"])

        agent_attribution = {
            aid: {
                "debates": len(ls),
                "mean_lift": round(sum(ls) / len(ls), 6),
                "total_lift": round(sum(ls), 6),
            }
            for aid, ls in agent_lifts.items()
        }

        return {
            "config": {
                "proposer_strategy": proposer_strategy,
                "arbiter_strategy": arbiter_strategy,
                "proposer_agent_id": proposer_agent_id,
                "challenger_agent_id": challenger_agent_id,
                "arbiter_agent_id": arbiter_agent_id,
                "team_id": team_id,
            },
            "markets_tested": n,
            "markets_skipped": skipped_count,
            "markets_improved": improved_count,
            "pct_improved": round(improved_count / n * 100, 1) if n > 0 else 0.0,
            "mean_debate_lift": mean_lift,
            "worst_lift": worst_lift,
            "best_lift": best_lift,
            "agent_attribution": agent_attribution,
            "team_id": team_id,
            "per_market": results,
        }

    def evaluate_strategy_combos(
        self,
        markets: List[Dict[str, Any]],
        proposer_strategies: Optional[List[str]] = None,
        arbiter_strategies: Optional[List[str]] = None,
        team_id: str = "",
    ) -> Dict[str, Any]:
        """Test all proposer × arbiter combinations and rank by mean lift.

        Args:
            markets: Resolved markets to test against.
            proposer_strategies: List of proposer strategy names to test.
                Defaults to all non-debate strategies.
            arbiter_strategies: List of arbiter strategy names to test.
                Defaults to all arbiter variants.
            team_id: Optional team ID for attribution.

        Returns:
            Ranked list of combos by mean debate lift with agent attribution.
        """
        from merid.prediction.opinion_strategy import list_strategies

        all_strats = list_strategies()

        if proposer_strategies is None:
            # Use non-debate strategies as proposers
            proposer_strategies = [
                s for s in all_strats
                if s not in ("challenger", "arbiter", "arbiter_bayesian",
                             "arbiter_extremizing", "arbiter_median")
            ]

        if arbiter_strategies is None:
            arbiter_strategies = [
                s for s in all_strats if s.startswith("arbiter")
            ]

        combo_results: List[Dict[str, Any]] = []

        for prop_name in proposer_strategies:
            for arb_name in arbiter_strategies:
                prop_aid = f"bt-{prop_name}-proposer"
                chal_aid = f"bt-{prop_name}-challenger"
                arb_aid = f"bt-{arb_name}-arbiter"

                report = self.run_backtest(
                    markets=markets,
                    proposer_strategy=prop_name,
                    arbiter_strategy=arb_name,
                    proposer_agent_id=prop_aid,
                    challenger_agent_id=chal_aid,
                    arbiter_agent_id=arb_aid,
                    team_id=team_id,
                )

                if "error" not in report:
                    combo_results.append({
                        "proposer_strategy": prop_name,
                        "arbiter_strategy": arb_name,
                        "proposer_agent_id": prop_aid,
                        "challenger_agent_id": chal_aid,
                        "arbiter_agent_id": arb_aid,
                        "team_id": team_id,
                        "markets_tested": report["markets_tested"],
                        "markets_improved": report["markets_improved"],
                        "pct_improved": report["pct_improved"],
                        "mean_debate_lift": report["mean_debate_lift"],
                        "worst_lift": report["worst_lift"],
                        "best_lift": report["best_lift"],
                        "agent_attribution": report["agent_attribution"],
                    })

        # Sort by mean_debate_lift descending
        combo_results.sort(key=lambda x: x["mean_debate_lift"], reverse=True)

        return {
            "total_combos": len(combo_results),
            "proposer_strategies_tested": proposer_strategies,
            "arbiter_strategies_tested": arbiter_strategies,
            "rankings": combo_results,
        }


# ── Reward Parameter Sensitivity Sweep ────────────────────────────────

class RewardParameterSweep:
    """Varies reward constants and measures how they affect agent rankings.

    For each parameter set, computes total rewards for a synthetic agent
    history and reports which parameters most affect the ranking of
    "accurate debater" vs "spammy participant" vs "silent accurate agent".
    """

    # Agent archetypes for sensitivity analysis
    ARCHETYPES = {
        "accurate_debater": {
            "opinions": 20, "explanations": 18, "avg_brier": 0.08,
            "debate_lifts": [0.05, 0.03, 0.04, 0.02, 0.06],
            "cooperation_events": 3,
        },
        "spammy_participant": {
            "opinions": 50, "explanations": 10, "avg_brier": 0.35,
            "debate_lifts": [0.01, -0.02, 0.0, 0.01, -0.01],
            "cooperation_events": 1,
        },
        "silent_accurate": {
            "opinions": 10, "explanations": 10, "avg_brier": 0.05,
            "debate_lifts": [],
            "cooperation_events": 0,
        },
    }

    def sweep(
        self,
        param_sets: Optional[List[Dict[str, float]]] = None,
    ) -> Dict[str, Any]:
        """Run sensitivity sweep over parameter sets.

        Args:
            param_sets: List of dicts with keys matching reward constants.
                If None, generates a default sweep grid.

        Returns:
            Results with per-param-set rankings and sensitivity analysis.
        """
        if param_sets is None:
            param_sets = self._default_grid()

        results = []
        for params in param_sets:
            rankings = self._evaluate_params(params)
            results.append({
                "params": params,
                "rankings": rankings,
                "top_agent": rankings[0]["archetype"] if rankings else None,
            })

        # Sensitivity: which param changes the top ranking most?
        top_counts: Dict[str, int] = {}
        for r in results:
            top = r["top_agent"]
            if top:
                top_counts[top] = top_counts.get(top, 0) + 1

        return {
            "total_param_sets": len(param_sets),
            "results": results,
            "top_agent_distribution": top_counts,
        }

    def _evaluate_params(self, params: Dict[str, float]) -> List[Dict[str, Any]]:
        """Compute total rewards for each archetype under given params."""
        acc_base = params.get("accuracy_base", REWARD_ACCURACY_BASE)
        brier_bonus = params.get("brier_bonus", REWARD_ACCURACY_BRIER_BONUS)
        lift_bonus = params.get("lift_bonus", REWARD_DEBATE_LIFT_BONUS)
        expl_bonus = params.get("explanation_bonus", REWARD_EXPLANATION_BONUS)
        coop_bonus = params.get("cooperation_bonus", REWARD_COOPERATION_BONUS)

        rankings = []
        for name, arch in self.ARCHETYPES.items():
            total = 0.0
            # Timeliness
            total += arch["opinions"] * acc_base
            # Explanation
            total += arch["explanations"] * expl_bonus
            # Accuracy (Brier-based)
            accuracy_per = brier_bonus * (1.0 - arch["avg_brier"])
            total += arch["opinions"] * accuracy_per
            # Debate lift
            for lift in arch["debate_lifts"]:
                if lift > 0:
                    total += lift_bonus * min(lift * 4, 1.0)
            # Cooperation
            total += arch["cooperation_events"] * coop_bonus

            rankings.append({
                "archetype": name,
                "total_points": round(total, 2),
            })

        rankings.sort(key=lambda x: x["total_points"], reverse=True)
        return rankings

    def _default_grid(self) -> List[Dict[str, float]]:
        """Generate a default parameter sweep grid."""
        grid = []
        # Baseline
        grid.append({
            "accuracy_base": 10.0, "brier_bonus": 50.0,
            "lift_bonus": 30.0, "explanation_bonus": 5.0,
            "cooperation_bonus": 20.0,
        })
        # High accuracy emphasis
        grid.append({
            "accuracy_base": 10.0, "brier_bonus": 100.0,
            "lift_bonus": 15.0, "explanation_bonus": 5.0,
            "cooperation_bonus": 10.0,
        })
        # High debate emphasis
        grid.append({
            "accuracy_base": 5.0, "brier_bonus": 30.0,
            "lift_bonus": 60.0, "explanation_bonus": 5.0,
            "cooperation_bonus": 30.0,
        })
        # High explanation emphasis
        grid.append({
            "accuracy_base": 10.0, "brier_bonus": 50.0,
            "lift_bonus": 30.0, "explanation_bonus": 20.0,
            "cooperation_bonus": 20.0,
        })
        # Participation-heavy (rewards volume)
        grid.append({
            "accuracy_base": 30.0, "brier_bonus": 20.0,
            "lift_bonus": 10.0, "explanation_bonus": 2.0,
            "cooperation_bonus": 5.0,
        })
        return grid


# ── Singleton ────────────────────────────────────────────────────────

_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")
_DB_PATH = os.environ.get("MERID_PRED_CONSENSUS_DB", os.path.join(_DB_DIR, "prediction_consensus.db"))

_debate_store: Optional[DebateStore] = None


def get_debate_store() -> DebateStore:
    """Get or create the singleton DebateStore (shares DB with consensus store)."""
    global _debate_store
    if _debate_store is None:
        _debate_store = DebateStore(_DB_PATH)
    return _debate_store
