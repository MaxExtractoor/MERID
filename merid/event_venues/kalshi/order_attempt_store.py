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
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

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


class ExitOrderAttemptState(StrEnum):
    """Finite-state machine states for an exit-order attempt lifecycle."""

    INTENT_PERSISTED = "INTENT_PERSISTED"
    SUBMITTING = "SUBMITTING"
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    RESOLVING_ON_EXCHANGE = "RESOLVING_ON_EXCHANGE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACKNOWLEDGED_LATE = "ACKNOWLEDGED_LATE"
    RESTING = "RESTING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED_EXCHANGE = "REJECTED_EXCHANGE"
    EXPIRED_EXCHANGE = "EXPIRED_EXCHANGE"
    TERMINAL_UNFILLED = "TERMINAL_UNFILLED"
    NOT_ACCEPTED_CONFIRMED = "NOT_ACCEPTED_CONFIRMED"
    EXCHANGE_CONFIRMED_FLAT = "EXCHANGE_CONFIRMED_FLAT"
    SUPERSEDED_AFTER_CONFIRMED_TERMINAL = "SUPERSEDED_AFTER_CONFIRMED_TERMINAL"


class ExitOrderAttemptConflict(Exception):
    """Raised when an active nonterminal exit attempt already exists for a position."""


@dataclass(frozen=True)
class ExitOrderAttemptRecord:
    attempt_id: str
    exit_intent_id: str
    position_key: str
    ticker: str
    reason: str
    state: str
    client_order_id: str
    exchange_order_id: Optional[str]
    requested_quantity: int
    confirmed_quantity: Optional[int]
    requested_limit_cents: Optional[int]
    policy_version: int
    basis_version: int
    created_at: float
    updated_at: float
    state_version: int
    payload_json: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ExitOrderAttemptRecord":
        return cls(
            attempt_id=row["attempt_id"],
            exit_intent_id=row["exit_intent_id"],
            position_key=row["position_key"],
            ticker=row["ticker"],
            reason=row["reason"],
            state=row["state"],
            client_order_id=row["client_order_id"],
            exchange_order_id=row["exchange_order_id"],
            requested_quantity=row["requested_quantity"],
            confirmed_quantity=row["confirmed_quantity"],
            requested_limit_cents=row["requested_limit_cents"],
            policy_version=row["policy_version"],
            basis_version=row["basis_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            state_version=row["state_version"],
            payload_json=row["payload_json"],
        )


@dataclass(frozen=True)
class ExitOrderAttemptEventRecord:
    event_id: str
    attempt_id: str
    old_state: str
    new_state: str
    reason: str
    observed_at: float
    exchange_order_id: Optional[str]
    raw_exchange_payload: Optional[str]
    actor: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ExitOrderAttemptEventRecord":
        return cls(
            event_id=row["event_id"],
            attempt_id=row["attempt_id"],
            old_state=row["old_state"],
            new_state=row["new_state"],
            reason=row["reason"],
            observed_at=row["observed_at"],
            exchange_order_id=row["exchange_order_id"],
            raw_exchange_payload=row["raw_exchange_payload"],
            actor=row["actor"],
        )


_EXIT_NONTERMINAL_STATES: Set[ExitOrderAttemptState] = {
    ExitOrderAttemptState.INTENT_PERSISTED,
    ExitOrderAttemptState.SUBMITTING,
    ExitOrderAttemptState.SUBMISSION_UNKNOWN,
    ExitOrderAttemptState.RESOLVING_ON_EXCHANGE,
    ExitOrderAttemptState.ACKNOWLEDGED,
    ExitOrderAttemptState.ACKNOWLEDGED_LATE,
    ExitOrderAttemptState.RESTING,
    ExitOrderAttemptState.PARTIALLY_FILLED,
}

EXIT_TERMINAL_STATES: Set[ExitOrderAttemptState] = set(ExitOrderAttemptState) - _EXIT_NONTERMINAL_STATES

EXIT_VALID_TRANSITIONS: Dict[ExitOrderAttemptState, Set[ExitOrderAttemptState]] = {
    ExitOrderAttemptState.INTENT_PERSISTED: {
        ExitOrderAttemptState.SUBMITTING,
        ExitOrderAttemptState.CANCELED,
    },
    ExitOrderAttemptState.SUBMITTING: {
        ExitOrderAttemptState.ACKNOWLEDGED,
        ExitOrderAttemptState.SUBMISSION_UNKNOWN,
        ExitOrderAttemptState.CANCELED,
    },
    ExitOrderAttemptState.SUBMISSION_UNKNOWN: {
        ExitOrderAttemptState.RESOLVING_ON_EXCHANGE,
        ExitOrderAttemptState.ACKNOWLEDGED_LATE,
        ExitOrderAttemptState.CANCELED,
        ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED,
    },
    ExitOrderAttemptState.RESOLVING_ON_EXCHANGE: {
        ExitOrderAttemptState.ACKNOWLEDGED,
        ExitOrderAttemptState.ACKNOWLEDGED_LATE,
        ExitOrderAttemptState.CANCELED,
        ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED,
    },
    ExitOrderAttemptState.ACKNOWLEDGED: {
        ExitOrderAttemptState.RESTING,
        ExitOrderAttemptState.PARTIALLY_FILLED,
        ExitOrderAttemptState.FILLED,
        ExitOrderAttemptState.CANCELED,
        ExitOrderAttemptState.REJECTED_EXCHANGE,
        ExitOrderAttemptState.EXPIRED_EXCHANGE,
    },
    ExitOrderAttemptState.ACKNOWLEDGED_LATE: {
        ExitOrderAttemptState.RESTING,
        ExitOrderAttemptState.PARTIALLY_FILLED,
        ExitOrderAttemptState.FILLED,
        ExitOrderAttemptState.CANCELED,
        ExitOrderAttemptState.REJECTED_EXCHANGE,
        ExitOrderAttemptState.EXPIRED_EXCHANGE,
    },
    ExitOrderAttemptState.RESTING: {
        ExitOrderAttemptState.PARTIALLY_FILLED,
        ExitOrderAttemptState.FILLED,
        ExitOrderAttemptState.CANCELED,
        ExitOrderAttemptState.REJECTED_EXCHANGE,
        ExitOrderAttemptState.EXPIRED_EXCHANGE,
    },
    ExitOrderAttemptState.PARTIALLY_FILLED: {
        ExitOrderAttemptState.FILLED,
        ExitOrderAttemptState.CANCELED,
        ExitOrderAttemptState.REJECTED_EXCHANGE,
        ExitOrderAttemptState.EXPIRED_EXCHANGE,
        ExitOrderAttemptState.TERMINAL_UNFILLED,
    },
}

for _terminal_state in EXIT_TERMINAL_STATES:
    if _terminal_state is not ExitOrderAttemptState.SUPERSEDED_AFTER_CONFIRMED_TERMINAL:
        EXIT_VALID_TRANSITIONS.setdefault(_terminal_state, set()).add(
            ExitOrderAttemptState.SUPERSEDED_AFTER_CONFIRMED_TERMINAL
        )
EXIT_VALID_TRANSITIONS[ExitOrderAttemptState.SUPERSEDED_AFTER_CONFIRMED_TERMINAL] = set()


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
                instance._init_exit_tables()
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

    def _init_exit_tables(self) -> None:
        """Initialize durable exit-order attempt tables in the same SQLite DB."""
        conn = self._get_conn()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS exit_order_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    exit_intent_id TEXT NOT NULL,
                    position_key TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'INTENT_PERSISTED',
                    client_order_id TEXT NOT NULL UNIQUE,
                    exchange_order_id TEXT,
                    requested_quantity INTEGER NOT NULL,
                    confirmed_quantity INTEGER,
                    requested_limit_cents INTEGER,
                    policy_version INTEGER NOT NULL DEFAULT 0,
                    basis_version INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    state_version INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS exit_order_attempt_events (
                    event_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    old_state TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    observed_at REAL NOT NULL,
                    exchange_order_id TEXT,
                    raw_exchange_payload TEXT,
                    actor TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_exit_order_attempts_position_key
                    ON exit_order_attempts(position_key);
                CREATE INDEX IF NOT EXISTS idx_exit_order_attempts_state
                    ON exit_order_attempts(state);
                CREATE INDEX IF NOT EXISTS idx_exit_order_attempts_client_order_id
                    ON exit_order_attempts(client_order_id);
                CREATE INDEX IF NOT EXISTS idx_exit_order_attempt_events_attempt_id
                    ON exit_order_attempt_events(attempt_id);
            """
            )
            conn.commit()
        except Exception:
            logger.exception("[EXIT-ORDER-ATTEMPT-STORE] Failed to initialize exit tables")
            raise

    def create_exit_attempt(
        self,
        exit_intent_id: str,
        position_key: str,
        ticker: str,
        reason: str,
        client_order_id: str,
        requested_quantity: int,
        requested_limit_cents: Optional[int] = None,
        exchange_order_id: Optional[str] = None,
        confirmed_quantity: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
        policy_version: int = 0,
        basis_version: int = 0,
        attempt_id: Optional[str] = None,
    ) -> ExitOrderAttemptRecord:
        """Create a new exit-order attempt and persist the INTENT_PERSISTED state.

        Raises:
            ExitOrderAttemptConflict: if an active nonterminal attempt already
                exists for the same ``position_key``.
            sqlite3.IntegrityError: if the ``client_order_id`` is already in use.
        """
        terminal_values = tuple(s.value for s in EXIT_TERMINAL_STATES)
        now = self._now()
        attempt_id = attempt_id or str(uuid.uuid4())
        payload_json = json.dumps(payload or {}, default=str, sort_keys=True)
        state = ExitOrderAttemptState.INTENT_PERSISTED.value

        conn = self._get_conn()
        with conn:
            cur = conn.execute(
                f"""
                SELECT attempt_id FROM exit_order_attempts
                WHERE position_key = ? AND state NOT IN ({','.join('?' for _ in terminal_values)})
                LIMIT 1
                """,
                (position_key, *terminal_values),
            )
            if cur.fetchone() is not None:
                raise ExitOrderAttemptConflict(
                    f"Active exit attempt already exists for position_key={position_key}"
                )
            conn.execute(
                """
                INSERT INTO exit_order_attempts (
                    attempt_id, exit_intent_id, position_key, ticker, reason, state,
                    client_order_id, exchange_order_id, requested_quantity,
                    confirmed_quantity, requested_limit_cents, policy_version,
                    basis_version, created_at, updated_at, state_version, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    exit_intent_id,
                    position_key,
                    ticker,
                    reason,
                    state,
                    client_order_id,
                    exchange_order_id,
                    requested_quantity,
                    confirmed_quantity,
                    requested_limit_cents,
                    policy_version,
                    basis_version,
                    now,
                    now,
                    1,
                    payload_json,
                ),
            )
        return self.get_exit_attempt(attempt_id)

    def get_exit_attempt(self, attempt_id: str) -> Optional[ExitOrderAttemptRecord]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM exit_order_attempts WHERE attempt_id = ?", (attempt_id,)
        )
        row = cur.fetchone()
        return ExitOrderAttemptRecord.from_row(row) if row else None

    def get_exit_attempt_by_client_order_id(
        self, client_order_id: str
    ) -> Optional[ExitOrderAttemptRecord]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM exit_order_attempts WHERE client_order_id = ?", (client_order_id,)
        )
        row = cur.fetchone()
        return ExitOrderAttemptRecord.from_row(row) if row else None

    def get_active_exit_attempt_for_position(
        self, position_key: str
    ) -> Optional[ExitOrderAttemptRecord]:
        conn = self._get_conn()
        terminal_values = tuple(s.value for s in EXIT_TERMINAL_STATES)
        cur = conn.execute(
            f"""
            SELECT * FROM exit_order_attempts
            WHERE position_key = ? AND state NOT IN ({','.join('?' for _ in terminal_values)})
            LIMIT 1
            """,
            (position_key, *terminal_values),
        )
        row = cur.fetchone()
        return ExitOrderAttemptRecord.from_row(row) if row else None

    def list_nonterminal_exit_attempts(self) -> List[ExitOrderAttemptRecord]:
        conn = self._get_conn()
        terminal_values = tuple(s.value for s in EXIT_TERMINAL_STATES)
        cur = conn.execute(
            f"""
            SELECT * FROM exit_order_attempts
            WHERE state NOT IN ({','.join('?' for _ in terminal_values)})
            ORDER BY created_at ASC
            """,
            terminal_values,
        )
        return [ExitOrderAttemptRecord.from_row(r) for r in cur.fetchall()]

    @staticmethod
    def is_terminal_state(state: str) -> bool:
        try:
            return ExitOrderAttemptState(state) in EXIT_TERMINAL_STATES
        except ValueError:
            return False

    def transition_exit_attempt(
        self,
        attempt_id: str,
        new_state: str,
        actor: str,
        reason: str,
        exchange_order_id: Optional[str] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
        expected_state_version: Optional[int] = None,
    ) -> Optional[ExitOrderAttemptRecord]:
        """Transition an exit attempt to a new state with optimistic concurrency.

        Appends an event row. Returns the updated record, or ``None`` if the
        transition is invalid, the attempt does not exist, or the expected
        state version does not match.
        """
        conn = self._get_conn()
        now = self._now()
        raw_payload_json: Optional[str] = None
        if raw_payload is not None:
            if isinstance(raw_payload, str):
                raw_payload_json = raw_payload
            else:
                raw_payload_json = json.dumps(raw_payload, default=str, sort_keys=True)

        with conn:
            cur = conn.execute(
                "SELECT * FROM exit_order_attempts WHERE attempt_id = ?", (attempt_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            record = ExitOrderAttemptRecord.from_row(row)

            if expected_state_version is not None and record.state_version != expected_state_version:
                return None

            old_state = ExitOrderAttemptState(record.state)
            try:
                new_state_enum = ExitOrderAttemptState(new_state)
            except ValueError:
                logger.warning(
                    "[EXIT-ORDER-ATTEMPT-STORE] Unknown target state %s for attempt %s",
                    new_state,
                    attempt_id,
                )
                return None
            if new_state_enum not in EXIT_VALID_TRANSITIONS.get(old_state, set()):
                logger.warning(
                    "[EXIT-ORDER-ATTEMPT-STORE] Invalid transition %s -> %s for attempt %s",
                    record.state,
                    new_state,
                    attempt_id,
                )
                return None

            expected_version = (
                expected_state_version if expected_state_version is not None else record.state_version
            )
            conn.execute(
                """
                UPDATE exit_order_attempts
                SET state = ?, updated_at = ?, state_version = state_version + 1,
                    exchange_order_id = COALESCE(?, exchange_order_id)
                WHERE attempt_id = ? AND state_version = ?
                """,
                (new_state, now, exchange_order_id, attempt_id, expected_version),
            )
            cur = conn.execute(
                "SELECT * FROM exit_order_attempts WHERE attempt_id = ?", (attempt_id,)
            )
            updated_row = cur.fetchone()
            if not updated_row or updated_row["state"] != new_state:
                return None

            conn.execute(
                """
                INSERT INTO exit_order_attempt_events (
                    event_id, attempt_id, old_state, new_state, reason, observed_at,
                    exchange_order_id, raw_exchange_payload, actor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    attempt_id,
                    record.state,
                    new_state,
                    reason,
                    now,
                    exchange_order_id,
                    raw_payload_json,
                    actor,
                ),
            )
            return ExitOrderAttemptRecord.from_row(updated_row)
