"""Cognitive Store — SQLite persistence for hypotheses, snapshots, and history.

Provides CRUD operations for CognitiveSnapshots and their Hypotheses,
plus history tracking and query APIs for the reality debugger.

Tables:
  cognitive_snapshots  — point-in-time snapshot records
  cognitive_hypotheses — individual hypotheses with lifecycle
  cognitive_evidence   — evidence links attached to hypotheses
  cognitive_actions    — audit log of all hypothesis actions
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

from merid.cognitive.models import (
    CognitiveSnapshot,
    EvidenceLink,
    EvidenceType,
    Hypothesis,
    HypothesisAction,
    HypothesisStatus,
    RegimeTag,
    SnapshotDomain,
)

logger = get_logger("merid.cognitive.store")

# ── SQLite schema ─────────────────────────────────────────────────────

_CREATE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS cognitive_snapshots (
    id                      TEXT PRIMARY KEY,
    market_id               TEXT NOT NULL DEFAULT '',
    domain                  TEXT NOT NULL DEFAULT 'market',
    overall_regime_confidence REAL NOT NULL DEFAULT 0.5,
    owner                   TEXT NOT NULL DEFAULT '',
    opinion_id              TEXT NOT NULL DEFAULT '',
    debate_id               TEXT NOT NULL DEFAULT '',
    notes                   TEXT NOT NULL DEFAULT '',
    created_at              REAL NOT NULL
);
"""

_CREATE_HYPOTHESES = """
CREATE TABLE IF NOT EXISTS cognitive_hypotheses (
    id                TEXT PRIMARY KEY,
    snapshot_id       TEXT NOT NULL DEFAULT '',
    market_id         TEXT NOT NULL DEFAULT '',
    text              TEXT NOT NULL DEFAULT '',
    regime_category   TEXT NOT NULL DEFAULT '',
    regime_label      TEXT NOT NULL DEFAULT '',
    regime_description TEXT NOT NULL DEFAULT '',
    confidence        REAL NOT NULL DEFAULT 0.5,
    prior_confidence  REAL,
    status            TEXT NOT NULL DEFAULT 'active',
    owner             TEXT NOT NULL DEFAULT '',
    broken_at         REAL,
    broken_reason     TEXT NOT NULL DEFAULT '',
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);
"""

_CREATE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS cognitive_evidence (
    id              TEXT PRIMARY KEY,
    hypothesis_id   TEXT NOT NULL DEFAULT '',
    evidence_type   TEXT NOT NULL DEFAULT 'external_data',
    reference_id    TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    supports        INTEGER NOT NULL DEFAULT 1,
    strength        REAL NOT NULL DEFAULT 0.5,
    added_by        TEXT NOT NULL DEFAULT '',
    added_at        REAL NOT NULL,
    notes           TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_ACTIONS = """
CREATE TABLE IF NOT EXISTS cognitive_actions (
    id              TEXT PRIMARY KEY,
    hypothesis_id   TEXT NOT NULL DEFAULT '',
    snapshot_id     TEXT NOT NULL DEFAULT '',
    market_id       TEXT NOT NULL DEFAULT '',
    action          TEXT NOT NULL DEFAULT '',
    actor           TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    old_confidence  REAL,
    new_confidence  REAL,
    created_at      REAL NOT NULL
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_snap_market ON cognitive_snapshots(market_id);",
    "CREATE INDEX IF NOT EXISTS idx_snap_owner ON cognitive_snapshots(owner);",
    "CREATE INDEX IF NOT EXISTS idx_snap_debate ON cognitive_snapshots(debate_id);",
    "CREATE INDEX IF NOT EXISTS idx_snap_opinion ON cognitive_snapshots(opinion_id);",
    "CREATE INDEX IF NOT EXISTS idx_hyp_snapshot ON cognitive_hypotheses(snapshot_id);",
    "CREATE INDEX IF NOT EXISTS idx_hyp_market ON cognitive_hypotheses(market_id);",
    "CREATE INDEX IF NOT EXISTS idx_hyp_owner ON cognitive_hypotheses(owner);",
    "CREATE INDEX IF NOT EXISTS idx_hyp_status ON cognitive_hypotheses(status);",
    "CREATE INDEX IF NOT EXISTS idx_ev_hyp ON cognitive_evidence(hypothesis_id);",
    "CREATE INDEX IF NOT EXISTS idx_act_hyp ON cognitive_actions(hypothesis_id);",
    "CREATE INDEX IF NOT EXISTS idx_act_market ON cognitive_actions(market_id);",
    "CREATE INDEX IF NOT EXISTS idx_act_time ON cognitive_actions(created_at);",
]


class CognitiveStore:
    """SQLite-backed store for cognitive snapshots, hypotheses, and actions."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.environ.get("MERID_COGNITIVE_DB", "data/cognitive.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._persistent_conn: Optional[sqlite3.Connection] = None
        if self._db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._persistent_conn.row_factory = sqlite3.Row
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _release(self, conn: sqlite3.Connection) -> None:
        """Close a connection unless it's the persistent in-memory one."""
        if conn is not self._persistent_conn:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(_CREATE_SNAPSHOTS)
                conn.execute(_CREATE_HYPOTHESES)
                conn.execute(_CREATE_EVIDENCE)
                conn.execute(_CREATE_ACTIONS)
                for idx in _CREATE_INDEXES:
                    conn.execute(idx)
                conn.commit()
            finally:
                self._release(conn)

    # ── Snapshot CRUD ─────────────────────────────────────────────────

    def save_snapshot(self, snap: CognitiveSnapshot) -> CognitiveSnapshot:
        """Persist a snapshot and all its hypotheses + evidence."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO cognitive_snapshots
                       (id, market_id, domain, overall_regime_confidence, owner,
                        opinion_id, debate_id, notes, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (snap.id, snap.market_id, snap.domain,
                     snap.overall_regime_confidence, snap.owner,
                     snap.opinion_id, snap.debate_id, snap.notes, snap.created_at),
                )
                for hyp in snap.hypotheses:
                    self._save_hypothesis(conn, hyp, snap.id, snap.market_id)
                conn.commit()
            finally:
                self._release(conn)
        return snap

    def get_snapshot(self, snapshot_id: str) -> Optional[CognitiveSnapshot]:
        """Retrieve a snapshot by ID with all hypotheses and evidence."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM cognitive_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_snapshot(conn, row)
        finally:
            self._release(conn)

    def get_snapshots_for_market(
        self, market_id: str, limit: int = 50
    ) -> List[CognitiveSnapshot]:
        """Get snapshot history for a market, newest first."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cognitive_snapshots
                   WHERE market_id = ? ORDER BY created_at DESC LIMIT ?""",
                (market_id, limit),
            ).fetchall()
            return [self._row_to_snapshot(conn, r) for r in rows]
        finally:
            self._release(conn)

    def get_latest_snapshot(self, market_id: str) -> Optional[CognitiveSnapshot]:
        """Get the most recent snapshot for a market."""
        snaps = self.get_snapshots_for_market(market_id, limit=1)
        return snaps[0] if snaps else None

    def get_snapshots_for_debate(self, debate_id: str) -> List[CognitiveSnapshot]:
        """Get all snapshots linked to a debate session."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cognitive_snapshots
                   WHERE debate_id = ? ORDER BY created_at""",
                (debate_id,),
            ).fetchall()
            return [self._row_to_snapshot(conn, r) for r in rows]
        finally:
            self._release(conn)

    def get_snapshots_for_opinion(self, opinion_id: str) -> List[CognitiveSnapshot]:
        """Get all snapshots linked to an opinion."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cognitive_snapshots
                   WHERE opinion_id = ? ORDER BY created_at""",
                (opinion_id,),
            ).fetchall()
            return [self._row_to_snapshot(conn, r) for r in rows]
        finally:
            self._release(conn)

    def list_snapshots(
        self,
        domain: Optional[str] = None,
        owner: Optional[str] = None,
        limit: int = 50,
    ) -> List[CognitiveSnapshot]:
        """List snapshots with optional filters."""
        conn = self._connect()
        try:
            clauses = []
            params: list = []
            if domain:
                clauses.append("domain = ?")
                params.append(domain)
            if owner:
                clauses.append("owner = ?")
                params.append(owner)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM cognitive_snapshots {where} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return [self._row_to_snapshot(conn, r) for r in rows]
        finally:
            self._release(conn)

    # ── Hypothesis operations ─────────────────────────────────────────

    def update_hypothesis_confidence(
        self,
        hypothesis_id: str,
        new_confidence: float,
        actor: str = "",
        reason: str = "",
    ) -> Optional[Hypothesis]:
        """Update a hypothesis's confidence and log the action."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM cognitive_hypotheses WHERE id = ?", (hypothesis_id,)
                ).fetchone()
                if not row:
                    return None
                old_conf = row["confidence"]
                now = time.time()
                conn.execute(
                    """UPDATE cognitive_hypotheses
                       SET confidence = ?, prior_confidence = ?, updated_at = ?
                       WHERE id = ?""",
                    (new_confidence, old_conf, now, hypothesis_id),
                )
                self._log_action(
                    conn, hypothesis_id, row["snapshot_id"], row["market_id"],
                    HypothesisAction.CONFIDENCE_ADJUSTED.value, actor,
                    reason, old_conf, new_confidence,
                )
                conn.commit()
                return self._row_to_hypothesis(conn, dict(row) | {
                    "confidence": new_confidence,
                    "prior_confidence": old_conf,
                    "updated_at": now,
                })
            finally:
                self._release(conn)

    def mark_hypothesis_broken(
        self,
        hypothesis_id: str,
        actor: str = "",
        reason: str = "",
    ) -> Optional[Hypothesis]:
        """Mark a hypothesis as broken (reality contradicted it)."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM cognitive_hypotheses WHERE id = ?", (hypothesis_id,)
                ).fetchone()
                if not row:
                    return None
                now = time.time()
                conn.execute(
                    """UPDATE cognitive_hypotheses
                       SET status = ?, broken_at = ?, broken_reason = ?, updated_at = ?
                       WHERE id = ?""",
                    (HypothesisStatus.BROKEN.value, now, reason, now, hypothesis_id),
                )
                self._log_action(
                    conn, hypothesis_id, row["snapshot_id"], row["market_id"],
                    HypothesisAction.BROKEN.value, actor, reason,
                    row["confidence"], row["confidence"],
                )
                conn.commit()
                return self._row_to_hypothesis(conn, dict(row) | {
                    "status": HypothesisStatus.BROKEN.value,
                    "broken_at": now,
                    "broken_reason": reason,
                    "updated_at": now,
                })
            finally:
                self._release(conn)

    def retire_hypothesis(
        self,
        hypothesis_id: str,
        actor: str = "",
        reason: str = "",
    ) -> Optional[Hypothesis]:
        """Retire a hypothesis (superseded or no longer relevant)."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM cognitive_hypotheses WHERE id = ?", (hypothesis_id,)
                ).fetchone()
                if not row:
                    return None
                now = time.time()
                conn.execute(
                    """UPDATE cognitive_hypotheses
                       SET status = ?, updated_at = ?
                       WHERE id = ?""",
                    (HypothesisStatus.RETIRED.value, now, hypothesis_id),
                )
                self._log_action(
                    conn, hypothesis_id, row["snapshot_id"], row["market_id"],
                    HypothesisAction.RETIRED.value, actor, reason,
                    row["confidence"], row["confidence"],
                )
                conn.commit()
                return self._row_to_hypothesis(conn, dict(row) | {
                    "status": HypothesisStatus.RETIRED.value,
                    "updated_at": now,
                })
            finally:
                self._release(conn)

    def add_evidence(
        self,
        hypothesis_id: str,
        evidence: EvidenceLink,
        actor: str = "",
    ) -> bool:
        """Add an evidence link to a hypothesis."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM cognitive_hypotheses WHERE id = ?", (hypothesis_id,)
                ).fetchone()
                if not row:
                    return False
                conn.execute(
                    """INSERT INTO cognitive_evidence
                       (id, hypothesis_id, evidence_type, reference_id, title,
                        url, supports, strength, added_by, added_at, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (evidence.id, hypothesis_id, evidence.evidence_type,
                     evidence.reference_id, evidence.title, evidence.url,
                     1 if evidence.supports else 0, evidence.strength,
                     evidence.added_by or actor, evidence.added_at, evidence.notes),
                )
                self._log_action(
                    conn, hypothesis_id, row["snapshot_id"], row["market_id"],
                    HypothesisAction.EVIDENCE_ADDED.value, actor,
                    f"{'Supporting' if evidence.supports else 'Contradicting'}: {evidence.title}",
                    row["confidence"], row["confidence"],
                )
                conn.commit()
                return True
            finally:
                self._release(conn)

    def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Get a single hypothesis by ID with evidence."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM cognitive_hypotheses WHERE id = ?", (hypothesis_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_hypothesis(conn, row)
        finally:
            self._release(conn)

    def get_active_hypotheses_for_market(self, market_id: str) -> List[Hypothesis]:
        """Get all active hypotheses for a market across all snapshots."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cognitive_hypotheses
                   WHERE market_id = ? AND status = ?
                   ORDER BY updated_at DESC""",
                (market_id, HypothesisStatus.ACTIVE.value),
            ).fetchall()
            return [self._row_to_hypothesis(conn, r) for r in rows]
        finally:
            self._release(conn)

    # ── Action log queries ────────────────────────────────────────────

    def get_actions_for_market(
        self, market_id: str, window_s: float = 604800.0, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get recent actions for a market (default 7 days)."""
        cutoff = time.time() - window_s
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cognitive_actions
                   WHERE market_id = ? AND created_at >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (market_id, cutoff, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._release(conn)

    def get_actions_for_hypothesis(self, hypothesis_id: str) -> List[Dict[str, Any]]:
        """Get all actions for a hypothesis."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cognitive_actions
                   WHERE hypothesis_id = ? ORDER BY created_at""",
                (hypothesis_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._release(conn)

    def get_all_actions(
        self, window_s: float = 604800.0, limit: int = 200
    ) -> List[Dict[str, Any]]:
        """Get all recent actions across all markets."""
        cutoff = time.time() - window_s
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM cognitive_actions
                   WHERE created_at >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            self._release(conn)

    # ── Metrics ───────────────────────────────────────────────────────

    def get_cognitive_metrics(self, window_s: float = 604800.0) -> Dict[str, Any]:
        """Compute cognitive health metrics over a time window."""
        cutoff = time.time() - window_s
        conn = self._connect()
        try:
            # Snapshot counts
            total_snaps = conn.execute(
                "SELECT COUNT(*) FROM cognitive_snapshots WHERE created_at >= ?",
                (cutoff,),
            ).fetchone()[0]

            # Hypothesis counts by status
            hyp_rows = conn.execute(
                """SELECT status, COUNT(*) as cnt FROM cognitive_hypotheses
                   WHERE created_at >= ? GROUP BY status""",
                (cutoff,),
            ).fetchall()
            by_status = {r["status"]: r["cnt"] for r in hyp_rows}

            # Action counts by type
            act_rows = conn.execute(
                """SELECT action, COUNT(*) as cnt FROM cognitive_actions
                   WHERE created_at >= ? GROUP BY action""",
                (cutoff,),
            ).fetchall()
            by_action = {r["action"]: r["cnt"] for r in act_rows}

            # Unique markets with hypotheses
            market_count = conn.execute(
                """SELECT COUNT(DISTINCT market_id) FROM cognitive_hypotheses
                   WHERE created_at >= ?""",
                (cutoff,),
            ).fetchone()[0]

            # Unique owners
            owner_count = conn.execute(
                """SELECT COUNT(DISTINCT owner) FROM cognitive_hypotheses
                   WHERE created_at >= ?""",
                (cutoff,),
            ).fetchone()[0]

            total_hyp = sum(by_status.values())
            broken_count = by_status.get(HypothesisStatus.BROKEN.value, 0)
            active_count = by_status.get(HypothesisStatus.ACTIVE.value, 0)

            return {
                "total_snapshots": total_snaps,
                "total_hypotheses": total_hyp,
                "by_status": by_status,
                "by_action": by_action,
                "active_hypotheses": active_count,
                "broken_hypotheses": broken_count,
                "markets_covered": market_count,
                "unique_owners": owner_count,
                "window_seconds": window_s,
            }
        finally:
            self._release(conn)

    def snapshot_count(self) -> int:
        """Total number of snapshots in the store."""
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM cognitive_snapshots").fetchone()[0]
        finally:
            self._release(conn)

    def hypothesis_count(self) -> int:
        """Total number of hypotheses in the store."""
        conn = self._connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM cognitive_hypotheses").fetchone()[0]
        finally:
            self._release(conn)

    # ── Internal helpers ──────────────────────────────────────────────

    def _save_hypothesis(
        self, conn: sqlite3.Connection, hyp: Hypothesis,
        snapshot_id: str, market_id: str,
    ) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO cognitive_hypotheses
               (id, snapshot_id, market_id, text, regime_category, regime_label,
                regime_description, confidence, prior_confidence, status, owner,
                broken_at, broken_reason, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (hyp.id, snapshot_id, market_id, hyp.text,
             hyp.regime_tag.category, hyp.regime_tag.label,
             hyp.regime_tag.description, hyp.confidence, hyp.prior_confidence,
             hyp.status, hyp.owner, hyp.broken_at, hyp.broken_reason,
             hyp.created_at, hyp.updated_at),
        )
        for ev in hyp.evidence_links:
            conn.execute(
                """INSERT OR REPLACE INTO cognitive_evidence
                   (id, hypothesis_id, evidence_type, reference_id, title,
                    url, supports, strength, added_by, added_at, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ev.id, hyp.id, ev.evidence_type, ev.reference_id,
                 ev.title, ev.url, 1 if ev.supports else 0, ev.strength,
                 ev.added_by, ev.added_at, ev.notes),
            )
        # Log creation action
        self._log_action(
            conn, hyp.id, snapshot_id, market_id,
            HypothesisAction.CREATED.value, hyp.owner,
            f"Hypothesis created: {hyp.text[:80]}",
            None, hyp.confidence,
        )

    def _log_action(
        self, conn: sqlite3.Connection,
        hypothesis_id: str, snapshot_id: str, market_id: str,
        action: str, actor: str, detail: str,
        old_confidence: Optional[float], new_confidence: Optional[float],
    ) -> None:
        conn.execute(
            """INSERT INTO cognitive_actions
               (id, hypothesis_id, snapshot_id, market_id, action, actor,
                detail, old_confidence, new_confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"act-{uuid.uuid4().hex[:12]}", hypothesis_id, snapshot_id,
             market_id, action, actor, detail,
             old_confidence, new_confidence, time.time()),
        )

    def _row_to_snapshot(
        self, conn: sqlite3.Connection, row: Any
    ) -> CognitiveSnapshot:
        hyp_rows = conn.execute(
            "SELECT * FROM cognitive_hypotheses WHERE snapshot_id = ?",
            (row["id"],),
        ).fetchall()
        hypotheses = [self._row_to_hypothesis(conn, hr) for hr in hyp_rows]
        return CognitiveSnapshot(
            id=row["id"],
            market_id=row["market_id"],
            domain=row["domain"],
            hypotheses=hypotheses,
            overall_regime_confidence=row["overall_regime_confidence"],
            owner=row["owner"],
            opinion_id=row["opinion_id"],
            debate_id=row["debate_id"],
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def _row_to_hypothesis(
        self, conn: sqlite3.Connection, row: Any
    ) -> Hypothesis:
        row_dict = dict(row) if not isinstance(row, dict) else row
        ev_rows = conn.execute(
            "SELECT * FROM cognitive_evidence WHERE hypothesis_id = ?",
            (row_dict["id"],),
        ).fetchall()
        evidence = [
            EvidenceLink(
                id=er["id"],
                evidence_type=er["evidence_type"],
                reference_id=er["reference_id"],
                title=er["title"],
                url=er["url"],
                supports=bool(er["supports"]),
                strength=er["strength"],
                added_by=er["added_by"],
                added_at=er["added_at"],
                notes=er["notes"],
            )
            for er in ev_rows
        ]
        return Hypothesis(
            id=row_dict["id"],
            text=row_dict["text"],
            regime_tag=RegimeTag(
                category=row_dict.get("regime_category", ""),
                label=row_dict.get("regime_label", ""),
                description=row_dict.get("regime_description", ""),
            ),
            confidence=row_dict["confidence"],
            prior_confidence=row_dict.get("prior_confidence"),
            status=row_dict["status"],
            owner=row_dict.get("owner", ""),
            evidence_links=evidence,
            created_at=row_dict["created_at"],
            updated_at=row_dict["updated_at"],
            broken_at=row_dict.get("broken_at"),
            broken_reason=row_dict.get("broken_reason", ""),
        )


# ── Singleton ─────────────────────────────────────────────────────────

_STORE: Optional[CognitiveStore] = None
_STORE_LOCK = threading.Lock()


def get_cognitive_store() -> CognitiveStore:
    """Get or create the global CognitiveStore singleton."""
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = CognitiveStore()
    return _STORE
