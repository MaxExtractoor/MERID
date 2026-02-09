"""BettingStore — SQLite persistence for events, odds, consensus, bets.

Thread-safe, follows the same pattern as PredictionConsensusStore.
DB path configurable via MERID_BETTING_DB env (default: data/betting.db).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

from merid.betting.models import (
    BettingEvent,
    BettingEventConsensus,
    BettingOutcome,
    BookOdds,
    LiveBetPlan,
    OddsSnapshot,
    SettledBet,
    remove_vig,
)

logger = get_logger("merid.betting.store")

_DEFAULT_DB = os.path.join("data", "betting.db")


class BettingStore:
    """SQLite store for the betting domain."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.environ.get("MERID_BETTING_DB", _DEFAULT_DB)
        self._lock = threading.Lock()
        self._persistent_conn: Optional[sqlite3.Connection] = None
        if self._db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.execute("PRAGMA foreign_keys=ON")
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._lock:
            conn = self._connect()
            conn.executescript("""
                    CREATE TABLE IF NOT EXISTS betting_events (
                        id TEXT PRIMARY KEY,
                        sport TEXT NOT NULL DEFAULT '',
                        league TEXT NOT NULL DEFAULT '',
                        title TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        home_team TEXT NOT NULL DEFAULT '',
                        away_team TEXT NOT NULL DEFAULT '',
                        start_time REAL NOT NULL DEFAULT 0,
                        state TEXT NOT NULL DEFAULT 'pre',
                        score_home INTEGER,
                        score_away INTEGER,
                        period TEXT NOT NULL DEFAULT '',
                        clock TEXT NOT NULL DEFAULT '',
                        outcomes_json TEXT NOT NULL DEFAULT '[]',
                        market_types_json TEXT NOT NULL DEFAULT '["moneyline"]',
                        kalshi_event_id TEXT,
                        created_at REAL NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS betting_odds_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL,
                        market_type TEXT NOT NULL DEFAULT 'moneyline',
                        book_odds_json TEXT NOT NULL DEFAULT '[]',
                        consensus_prob_json TEXT NOT NULL DEFAULT '{}',
                        sharp_prob_json TEXT NOT NULL DEFAULT '{}',
                        best_odds_json TEXT NOT NULL DEFAULT '{}',
                        timestamp REAL NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS betting_swarm_opinions (
                        id TEXT PRIMARY KEY,
                        agent_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        outcome_id TEXT NOT NULL,
                        probability REAL NOT NULL DEFAULT 0.5,
                        confidence REAL NOT NULL DEFAULT 0.5,
                        reasoning TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS betting_plans (
                        id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        outcome_id TEXT NOT NULL,
                        outcome_name TEXT NOT NULL DEFAULT '',
                        market_type TEXT NOT NULL DEFAULT 'moneyline',
                        direction TEXT NOT NULL DEFAULT 'back',
                        stake_usd REAL NOT NULL DEFAULT 100,
                        min_edge_vs_books REAL NOT NULL DEFAULT 0.03,
                        min_edge_vs_prediction REAL NOT NULL DEFAULT 0,
                        max_odds_age_seconds REAL NOT NULL DEFAULT 30,
                        max_line_move_tolerance REAL NOT NULL DEFAULT 0.03,
                        confidence REAL NOT NULL DEFAULT 0.5,
                        supporting_agents_json TEXT NOT NULL DEFAULT '[]',
                        status TEXT NOT NULL DEFAULT 'proposed',
                        placed_odds REAL NOT NULL DEFAULT 0,
                        placed_at REAL NOT NULL DEFAULT 0,
                        settled_at REAL NOT NULL DEFAULT 0,
                        pnl_usd REAL NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS betting_settled (
                        bet_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        outcome_id TEXT NOT NULL,
                        stake_usd REAL NOT NULL DEFAULT 0,
                        placed_odds REAL NOT NULL DEFAULT 0,
                        result TEXT NOT NULL DEFAULT 'pending',
                        pnl_usd REAL NOT NULL DEFAULT 0,
                        settled_at REAL NOT NULL DEFAULT 0
                    );

                    CREATE INDEX IF NOT EXISTS idx_odds_event ON betting_odds_snapshots(event_id);
                    CREATE INDEX IF NOT EXISTS idx_opinions_event ON betting_swarm_opinions(event_id);
                    CREATE INDEX IF NOT EXISTS idx_plans_event ON betting_plans(event_id);
                    CREATE INDEX IF NOT EXISTS idx_plans_status ON betting_plans(status);
                """)

    # ── Events ────────────────────────────────────────────────────────

    def upsert_event(self, ev: BettingEvent) -> BettingEvent:
        ev.updated_at = time.time()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO betting_events
                       (id, sport, league, title, description, home_team, away_team,
                        start_time, state, score_home, score_away, period, clock,
                        outcomes_json, market_types_json, kalshi_event_id,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (ev.id, ev.sport, ev.league, ev.title, ev.description,
                     ev.home_team, ev.away_team, ev.start_time, ev.state,
                     ev.score_home, ev.score_away, ev.period, ev.clock,
                     json.dumps([o.to_dict() for o in ev.outcomes]),
                     json.dumps(ev.market_types), ev.kalshi_event_id,
                     ev.created_at, ev.updated_at),
                )
        return ev

    def get_event(self, event_id: str) -> Optional[BettingEvent]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM betting_events WHERE id = ?", (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def list_events(self, sport: Optional[str] = None, state: Optional[str] = None, limit: int = 100) -> List[BettingEvent]:
        clauses, params = [], []
        if sport:
            clauses.append("sport = ?")
            params.append(sport)
        if state:
            clauses.append("state = ?")
            params.append(state)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM betting_events{where} ORDER BY start_time ASC LIMIT ?", params
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def event_count(self, state: Optional[str] = None) -> int:
        with self._connect() as conn:
            if state:
                row = conn.execute("SELECT COUNT(*) FROM betting_events WHERE state = ?", (state,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM betting_events").fetchone()
        return row[0] if row else 0

    # ── Odds snapshots ────────────────────────────────────────────────

    def store_odds_snapshot(self, snap: OddsSnapshot) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO betting_odds_snapshots
                       (event_id, market_type, book_odds_json, consensus_prob_json,
                        sharp_prob_json, best_odds_json, timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
                    (snap.event_id, snap.market_type,
                     json.dumps([bo.to_dict() for bo in snap.book_odds]),
                     json.dumps(snap.consensus_prob),
                     json.dumps(snap.sharp_prob),
                     json.dumps({k: v.to_dict() for k, v in snap.best_odds.items()}),
                     snap.timestamp),
                )

    def get_latest_odds(self, event_id: str, market_type: str = "moneyline") -> Optional[OddsSnapshot]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM betting_odds_snapshots
                   WHERE event_id = ? AND market_type = ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (event_id, market_type),
            ).fetchone()
        return self._row_to_snapshot(row) if row else None

    # ── Swarm opinions ────────────────────────────────────────────────

    def add_swarm_opinion(self, agent_id: str, event_id: str, outcome_id: str,
                          probability: float, confidence: float = 0.5,
                          reasoning: str = "") -> str:
        import uuid
        oid = str(uuid.uuid4())[:12]
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO betting_swarm_opinions
                       (id, agent_id, event_id, outcome_id, probability, confidence, reasoning, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (oid, agent_id, event_id, outcome_id, probability, confidence, reasoning, time.time()),
                )
        return oid

    def list_swarm_opinions(self, event_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM betting_swarm_opinions WHERE event_id = ? ORDER BY created_at DESC LIMIT ?",
                (event_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Plans ─────────────────────────────────────────────────────────

    def add_plan(self, plan: LiveBetPlan) -> LiveBetPlan:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO betting_plans
                       (id, event_id, outcome_id, outcome_name, market_type, direction,
                        stake_usd, min_edge_vs_books, min_edge_vs_prediction,
                        max_odds_age_seconds, max_line_move_tolerance, confidence,
                        supporting_agents_json, status, placed_odds, placed_at,
                        settled_at, pnl_usd, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (plan.id, plan.event_id, plan.outcome_id, plan.outcome_name,
                     plan.market_type, plan.direction, plan.stake_usd,
                     plan.min_edge_vs_books, plan.min_edge_vs_prediction,
                     plan.max_odds_age_seconds, plan.max_line_move_tolerance,
                     plan.confidence, json.dumps(plan.supporting_agents),
                     plan.status, plan.placed_odds, plan.placed_at,
                     plan.settled_at, plan.pnl_usd, plan.created_at),
                )
        return plan

    def update_plan_status(self, plan_id: str, status: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE betting_plans SET status = ? WHERE id = ?", (status, plan_id)
                )
        return cur.rowcount > 0

    def list_plans(self, event_id: Optional[str] = None, status: Optional[str] = None, limit: int = 100) -> List[LiveBetPlan]:
        clauses, params = [], []
        if event_id:
            clauses.append("event_id = ?")
            params.append(event_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM betting_plans{where} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        return [self._row_to_plan(r) for r in rows]

    # ── Settlements ───────────────────────────────────────────────────

    def settle_bet(self, sb: SettledBet) -> SettledBet:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO betting_settled
                       (bet_id, event_id, outcome_id, stake_usd, placed_odds, result, pnl_usd, settled_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (sb.bet_id, sb.event_id, sb.outcome_id, sb.stake_usd,
                     sb.placed_odds, sb.result, sb.pnl_usd, sb.settled_at),
                )
        return sb

    def list_settled(self, limit: int = 100) -> List[SettledBet]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM betting_settled ORDER BY settled_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [SettledBet(**dict(r)) for r in rows]

    # ── Consensus aggregation ─────────────────────────────────────────

    def build_consensus(self, event_id: str) -> Optional[BettingEventConsensus]:
        """Build a BettingEventConsensus by merging sportsbook odds + swarm opinions."""
        ev = self.get_event(event_id)
        if not ev:
            return None

        snap = self.get_latest_odds(event_id)
        opinions = self.list_swarm_opinions(event_id, limit=50)
        plans = self.list_plans(event_id=event_id, limit=50)

        # Sportsbook layer
        sportsbook_prob = snap.consensus_prob if snap else {}
        sharp_prob = snap.sharp_prob if snap else {}
        best_odds = snap.best_odds if snap else {}
        book_count = len(set(bo.book for bo in snap.book_odds)) if snap else 0

        # Prediction market layer — check if this event has a Kalshi match
        prediction_prob: Dict[str, float] = {}
        pm_source = ""
        if ev.kalshi_event_id:
            try:
                from merid.prediction.consensus import get_prediction_consensus_store
                pm_store = get_prediction_consensus_store()
                # Look for matching instruments
                instruments = pm_store.list_instruments(limit=500)
                for inst in instruments:
                    if ev.kalshi_event_id and ev.kalshi_event_id in inst.ticker:
                        # Map YES outcome
                        for oc in ev.outcomes:
                            if "yes" in oc.name.lower() or oc.market_type == "yes_no":
                                prediction_prob[oc.id] = inst.market_implied_prob
                                break
                        pm_source = "kalshi"
                        break
            except Exception:
                pass

        # Swarm layer
        swarm_prob: Dict[str, float] = {}
        swarm_conf_total = 0.0
        swarm_weight_total = 0.0
        supporting = set()
        opposing = set()

        if opinions:
            from collections import defaultdict
            by_outcome: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for op in opinions:
                by_outcome[op["outcome_id"]].append(op)

            for oid, ops in by_outcome.items():
                total_w = sum(o["confidence"] for o in ops)
                if total_w > 0:
                    swarm_prob[oid] = sum(o["probability"] * o["confidence"] for o in ops) / total_w
                else:
                    swarm_prob[oid] = sum(o["probability"] for o in ops) / len(ops)
                swarm_conf_total += sum(o["confidence"] for o in ops)
                swarm_weight_total += len(ops)

            # Determine supporting/opposing based on primary outcome
            for op in opinions:
                if op["probability"] >= 0.5:
                    supporting.add(op["agent_id"])
                else:
                    opposing.add(op["agent_id"])

        avg_conf = swarm_conf_total / swarm_weight_total if swarm_weight_total else 0.0

        # Plan counts
        plan_counts = {"proposed": 0, "approved": 0, "executing": 0}
        for p in plans:
            if p.status in plan_counts:
                plan_counts[p.status] += 1

        consensus = BettingEventConsensus(
            event_id=event_id,
            event=ev,
            sportsbook_consensus_prob=sportsbook_prob,
            sharp_book_prob=sharp_prob,
            best_book_odds={k: v for k, v in best_odds.items()} if isinstance(best_odds, dict) else {},
            book_count=book_count,
            prediction_market_prob=prediction_prob,
            prediction_market_source=pm_source,
            swarm_prob=swarm_prob,
            swarm_confidence=avg_conf,
            swarm_supporting_agents=len(supporting),
            swarm_opposing_agents=len(opposing),
            swarm_opinion_count=len(opinions),
            active_plans=plan_counts,
            state=ev.state,
        )
        consensus.compute_edges()
        return consensus

    def build_all_consensus(self, sport: Optional[str] = None, state: Optional[str] = None) -> List[BettingEventConsensus]:
        """Build consensus for all events matching filters."""
        events = self.list_events(sport=sport, state=state, limit=200)
        results = []
        for ev in events:
            c = self.build_consensus(ev.id)
            if c:
                results.append(c)
        return results

    # ── Paper book: check plan executability ───────────────────────────

    def check_plan_executable(self, plan: LiveBetPlan) -> Dict[str, Any]:
        """Check if a betting plan should execute given current odds and edges."""
        ev = self.get_event(plan.event_id)
        if not ev:
            return {"executable": False, "reason": "Event not found"}
        if ev.state == "final":
            return {"executable": False, "reason": "Event already final"}

        snap = self.get_latest_odds(plan.event_id)
        if not snap:
            return {"executable": False, "reason": "No odds available"}

        odds_age = time.time() - snap.timestamp
        if odds_age > plan.max_odds_age_seconds:
            return {"executable": False, "reason": f"Odds are {odds_age:.0f}s old (max {plan.max_odds_age_seconds}s)"}

        # Compute current edge
        consensus = self.build_consensus(plan.event_id)
        if not consensus:
            return {"executable": False, "reason": "Cannot build consensus"}

        edge = consensus.edge_vs_books.get(plan.outcome_id, 0.0)
        if abs(edge) < plan.min_edge_vs_books:
            return {
                "executable": False,
                "reason": f"|edge| {abs(edge):.4f} < min {plan.min_edge_vs_books}",
                "edge": edge,
            }

        return {
            "executable": True,
            "edge": edge,
            "odds_age_seconds": round(odds_age, 1),
            "consensus_prob": consensus.sportsbook_consensus_prob.get(plan.outcome_id, 0.0),
            "swarm_prob": consensus.swarm_prob.get(plan.outcome_id, 0.0),
        }

    # ── Betting metrics ───────────────────────────────────────────────

    def get_betting_metrics(self) -> Dict[str, Any]:
        """Overall betting performance metrics."""
        settled = self.list_settled(limit=500)
        total_pnl = sum(s.pnl_usd for s in settled)
        wins = sum(1 for s in settled if s.result == "won")
        losses = sum(1 for s in settled if s.result == "lost")
        total = wins + losses
        win_rate = wins / total if total > 0 else 0.0
        total_staked = sum(s.stake_usd for s in settled)
        roi = total_pnl / total_staked if total_staked > 0 else 0.0

        plans = self.list_plans(limit=500)
        plan_counts = {"proposed": 0, "approved": 0, "executing": 0, "placed": 0, "settled": 0}
        for p in plans:
            if p.status in plan_counts:
                plan_counts[p.status] += 1

        return {
            "total_bets": len(settled),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "total_staked_usd": round(total_staked, 2),
            "total_pnl_usd": round(total_pnl, 2),
            "roi": round(roi, 4),
            "active_events": self.event_count(state="pre") + self.event_count(state="live"),
            "live_events": self.event_count(state="live"),
            "plans": plan_counts,
        }

    # ── Row converters ────────────────────────────────────────────────

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> BettingEvent:
        outcomes_raw = json.loads(row["outcomes_json"])
        outcomes = [BettingOutcome(**o) for o in outcomes_raw]
        return BettingEvent(
            id=row["id"], sport=row["sport"], league=row["league"],
            title=row["title"], description=row["description"],
            home_team=row["home_team"], away_team=row["away_team"],
            start_time=row["start_time"], state=row["state"],
            score_home=row["score_home"], score_away=row["score_away"],
            period=row["period"], clock=row["clock"],
            outcomes=outcomes,
            market_types=json.loads(row["market_types_json"]),
            kalshi_event_id=row["kalshi_event_id"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> OddsSnapshot:
        book_odds_raw = json.loads(row["book_odds_json"])
        book_odds = [BookOdds(**bo) for bo in book_odds_raw]
        best_raw = json.loads(row["best_odds_json"])
        best_odds = {k: BookOdds(**v) for k, v in best_raw.items()}
        return OddsSnapshot(
            event_id=row["event_id"], market_type=row["market_type"],
            book_odds=book_odds,
            consensus_prob=json.loads(row["consensus_prob_json"]),
            sharp_prob=json.loads(row["sharp_prob_json"]),
            best_odds=best_odds,
            timestamp=row["timestamp"],
        )

    @staticmethod
    def _row_to_plan(row: sqlite3.Row) -> LiveBetPlan:
        return LiveBetPlan(
            id=row["id"], event_id=row["event_id"],
            outcome_id=row["outcome_id"], outcome_name=row["outcome_name"],
            market_type=row["market_type"], direction=row["direction"],
            stake_usd=row["stake_usd"],
            min_edge_vs_books=row["min_edge_vs_books"],
            min_edge_vs_prediction=row["min_edge_vs_prediction"],
            max_odds_age_seconds=row["max_odds_age_seconds"],
            max_line_move_tolerance=row["max_line_move_tolerance"],
            confidence=row["confidence"],
            supporting_agents=json.loads(row["supporting_agents_json"]),
            status=row["status"], placed_odds=row["placed_odds"],
            placed_at=row["placed_at"], settled_at=row["settled_at"],
            pnl_usd=row["pnl_usd"], created_at=row["created_at"],
        )


# ── Singleton ─────────────────────────────────────────────────────────

_store: Optional[BettingStore] = None


def get_betting_store() -> BettingStore:
    global _store
    if _store is None:
        _store = BettingStore()
    return _store
