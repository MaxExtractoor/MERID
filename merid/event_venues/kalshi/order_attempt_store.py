"""Durable SQLite store for Kalshi order attempts.

One row per ``order_attempt_id``. ``client_order_id`` has a UNIQUE constraint so
the venue idempotency key cannot be reused for a different attempt. The store is
the source of truth for canonical (``order_attempt_id``, ``client_order_id``)
pairs and their lifecycle state.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_attempt_store")

DEFAULT_DB_PATH = os.environ.get(
    "MERID_KALSHI_ORDER_ATTEMPT_DB", "data/kalshi_order_attempts.db"
)


@dataclass(frozen=True)
class OrderAttemptRecord:
    order_attempt_id: str
    client_order_id: str
    decision_id: Optional[str]
    replaces_order_attempt_id: Optional[str]
    intent_id: str
    client_tag: Optional[str]
    run_id: Optional[str]
    process_id: Optional[str]
    fingerprint: str
    status: str
    created_at: float
    updated_at: float
    payload_json: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OrderAttemptRecord":
        return cls(
            order_attempt_id=row["order_attempt_id"],
            client_order_id=row["client_order_id"],
            decision_id=row["decision_id"],
            replaces_order_attempt_id=row["replaces_order_attempt_id"],
            intent_id=row["intent_id"],
            client_tag=row["client_tag"],
            run_id=row["run_id"],
            process_id=row["process_id"],
            fingerprint=row["fingerprint"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            payload_json=row["payload_json"],
        )


class OrderAttemptStore:
    """SQLite-backed store for order attempt identity and lifecycle.

    The store is a singleton keyed by ``db_path`` so multiple importers in the
    same process share one connection.  It is safe for the single-process
    Kalshi router; concurrent writers should rely on SQLite row locking.
    """

    _instances: Dict[str, "OrderAttemptStore"] = {}
    _lock = threading.Lock()

    def __new__(cls, db_path: Optional[str] = None) -> "OrderAttemptStore":
        db_path = db_path or DEFAULT_DB_PATH
        with cls._lock:
            if db_path not in cls._instances:
                instance = super().__new__(cls)
                instance._db_path = db_path
                instance._persistent_conn: Optional[sqlite3.Connection] = None
                instance._init_db()
                cls._instances[db_path] = instance
            return cls._instances[db_path]

    def _get_conn(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS order_attempts (
                    order_attempt_id TEXT PRIMARY KEY,
                    client_order_id TEXT NOT NULL UNIQUE,
                    decision_id TEXT,
                    replaces_order_attempt_id TEXT,
                    intent_id TEXT NOT NULL,
                    client_tag TEXT,
                    run_id TEXT,
                    process_id TEXT,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PERSISTED',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_order_attempts_client_order_id
                    ON order_attempts(client_order_id);
                CREATE INDEX IF NOT EXISTS idx_order_attempts_intent_id
                    ON order_attempts(intent_id);
                CREATE INDEX IF NOT EXISTS idx_order_attempts_decision_id
                    ON order_attempts(decision_id);
                CREATE INDEX IF NOT EXISTS idx_order_attempts_status
                    ON order_attempts(status);
                CREATE INDEX IF NOT EXISTS idx_order_attempts_replaces
                    ON order_attempts(replaces_order_attempt_id);
            """
            )
            conn.commit()
        except Exception:
            logger.exception("[ORDER-ATTEMPT-STORE] Failed to initialize database")
            raise

    @staticmethod
    def _now() -> float:
        return datetime.now(timezone.utc).timestamp()

    def get_by_client_order_id(self, client_order_id: str) -> Optional[OrderAttemptRecord]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM order_attempts WHERE client_order_id = ?", (client_order_id,)
        )
        row = cur.fetchone()
        return OrderAttemptRecord.from_row(row) if row else None

    def get_by_order_attempt_id(self, order_attempt_id: str) -> Optional[OrderAttemptRecord]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM order_attempts WHERE order_attempt_id = ?", (order_attempt_id,)
        )
        row = cur.fetchone()
        return OrderAttemptRecord.from_row(row) if row else None

    def get_by_intent_id(self, intent_id: str) -> List[OrderAttemptRecord]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM order_attempts WHERE intent_id = ?", (intent_id,)
        )
        return [OrderAttemptRecord.from_row(r) for r in cur.fetchall()]

    def get_by_fingerprint(self, fingerprint: str) -> List[OrderAttemptRecord]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM order_attempts WHERE fingerprint = ? ORDER BY created_at DESC",
            (fingerprint,),
        )
        return [OrderAttemptRecord.from_row(r) for r in cur.fetchall()]

    def get_by_decision_id(self, decision_id: str) -> List[OrderAttemptRecord]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM order_attempts WHERE decision_id = ?", (decision_id,)
        )
        return [OrderAttemptRecord.from_row(r) for r in cur.fetchall()]

    def get_unresolved(self, lookback_seconds: float = 300.0) -> List[OrderAttemptRecord]:
        conn = self._get_conn()
        cutoff = self._now() - lookback_seconds
        cur = conn.execute(
            """
            SELECT * FROM order_attempts
            WHERE status IN ('SUBMITTING','SUBMISSION_UNKNOWN','ACKNOWLEDGED')
              AND created_at > ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        )
        return [OrderAttemptRecord.from_row(r) for r in cur.fetchall()]

    def persist_attempt(self, record: OrderAttemptRecord) -> None:
        """Insert a new attempt. Raises on uniqueness conflict."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO order_attempts (
                    order_attempt_id, client_order_id, decision_id, replaces_order_attempt_id,
                    intent_id, client_tag, run_id, process_id, fingerprint, status,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.order_attempt_id,
                    record.client_order_id,
                    record.decision_id,
                    record.replaces_order_attempt_id,
                    record.intent_id,
                    record.client_tag,
                    record.run_id,
                    record.process_id,
                    record.fingerprint,
                    record.status,
                    record.created_at,
                    record.updated_at,
                    record.payload_json,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            logger.critical(
                "[ORDER-ATTEMPT-STORE] client_order_id uniqueness violation: %s", exc
            )
            raise

    def update_status(
        self,
        order_attempt_id: str,
        status: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        conn = self._get_conn()
        now = self._now()
        payload_json = json.dumps(payload, default=str, sort_keys=True) if payload is not None else None
        try:
            if payload_json is not None:
                conn.execute(
                    """
                    UPDATE order_attempts
                    SET status = ?, updated_at = ?, payload_json = ?
                    WHERE order_attempt_id = ?
                    """,
                    (status, now, payload_json, order_attempt_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE order_attempts
                    SET status = ?, updated_at = ?
                    WHERE order_attempt_id = ?
                    """,
                    (status, now, order_attempt_id),
                )
            conn.commit()
            return conn.total_changes > 0
        except Exception:
            logger.exception("[ORDER-ATTEMPT-STORE] Failed to update status")
            return False

    def update_payload(self, order_attempt_id: str, payload: Dict[str, Any]) -> bool:
        conn = self._get_conn()
        payload_json = json.dumps(payload, default=str, sort_keys=True)
        try:
            conn.execute(
                """
                UPDATE order_attempts
                SET payload_json = ?, updated_at = ?
                WHERE order_attempt_id = ?
                """,
                (payload_json, self._now(), order_attempt_id),
            )
            conn.commit()
            return conn.total_changes > 0
        except Exception:
            logger.exception("[ORDER-ATTEMPT-STORE] Failed to update payload")
            return False
