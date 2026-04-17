"""Persistent frontend error store — SQLite-backed with automatic rotation.

Provides:
  - ``record_error(message, stack, route, client_tag)`` — persist a frontend error
  - ``list_errors(limit, since_ms, route)`` — query recent errors
  - ``get_stats()`` — lightweight aggregate stats for health widgets
  - ``rotate(max_age_days)`` — prune old entries (called automatically)

The ``/api/v1/errors/report`` endpoint in ``kalshi_shims.py`` writes here.
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

logger = get_logger("core.error_store")

# ── Domain object ────────────────────────────────────────────────────

@dataclass
class FrontendError:
    """A single frontend error report."""
    id: str = field(default_factory=lambda: f"fe-{uuid.uuid4().hex[:12]}")
    timestamp: str = ""
    message: str = ""
    stack: Optional[str] = None
    route: Optional[str] = None
    client_tag: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp or datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "message": self.message,
            "stack": self.stack,
            "route": self.route,
            "client_tag": self.client_tag,
            "created_at": self.created_at,
        }


# ── SQLite store ─────────────────────────────────────────────────────

_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_DB_PATH = os.environ.get("MERID_ERROR_STORE_DB", os.path.join(_DB_DIR, "frontend_errors.db"))

_DEFAULT_MAX_AGE_DAYS = 30
_DEFAULT_MAX_ROWS = 10_000

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS frontend_errors (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL DEFAULT '',
    stack       TEXT,
    route       TEXT,
    client_tag  TEXT,
    created_at  REAL NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_fe_created ON frontend_errors(created_at DESC);
"""

_CREATE_ROUTE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_fe_route ON frontend_errors(route);
"""


class FrontendErrorStore:
    """Thread-safe, append-only SQLite store for frontend error reports."""

    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._last_rotation: float = time.time()
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)
            conn.execute(_CREATE_ROUTE_INDEX)
        logger.info("Frontend error store initialized: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Write ────────────────────────────────────────────────────────

    def record(self, error: FrontendError) -> FrontendError:
        """Persist a frontend error report. Returns the error with its id."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO frontend_errors (id, timestamp, message, stack, route, client_tag, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (error.id, error.timestamp, error.message,
                     error.stack, error.route, error.client_tag,
                     error.created_at),
                )
        self._maybe_rotate()
        return error

    # ── Read ─────────────────────────────────────────────────────────

    def list_errors(
        self,
        limit: int = 50,
        since_ms: Optional[int] = None,
        route: Optional[str] = None,
    ) -> List[FrontendError]:
        """Return newest errors, optionally filtered."""
        clauses: List[str] = []
        params: List[Any] = []

        if since_ms is not None:
            clauses.append("created_at >= ?")
            params.append(since_ms / 1000.0)
        if route:
            clauses.append("route = ?")
            params.append(route)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM frontend_errors {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_error(r) for r in rows]

    def total_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM frontend_errors").fetchone()
            return row[0] if row else 0

    def get_stats(self) -> Dict[str, Any]:
        """Lightweight aggregate stats."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM frontend_errors").fetchone()[0]

            last_row = conn.execute(
                "SELECT created_at FROM frontend_errors ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            last_created_at = last_row[0] if last_row else None

            # Errors in last hour / last 24h
            now = time.time()
            last_1h = conn.execute(
                "SELECT COUNT(*) FROM frontend_errors WHERE created_at >= ?",
                (now - 3600,),
            ).fetchone()[0]
            last_24h = conn.execute(
                "SELECT COUNT(*) FROM frontend_errors WHERE created_at >= ?",
                (now - 86400,),
            ).fetchone()[0]

            # Top routes
            top_routes = conn.execute(
                "SELECT route, COUNT(*) as cnt FROM frontend_errors "
                "WHERE route IS NOT NULL GROUP BY route ORDER BY cnt DESC LIMIT 5"
            ).fetchall()

        return {
            "total": total,
            "last_1h": last_1h,
            "last_24h": last_24h,
            "last_error_at": last_created_at,
            "top_routes": {r["route"]: r["cnt"] for r in top_routes},
            "store_path": self._db_path,
            "healthy": True,
        }

    # ── Rotation ─────────────────────────────────────────────────────

    def rotate(self, max_age_days: int = _DEFAULT_MAX_AGE_DAYS, max_rows: int = _DEFAULT_MAX_ROWS) -> int:
        """Prune old entries. Returns count deleted."""
        cutoff = time.time() - (max_age_days * 86400)
        deleted = 0
        with self._lock:
            with self._connect() as conn:
                # Age-based pruning
                cur = conn.execute(
                    "DELETE FROM frontend_errors WHERE created_at < ?", (cutoff,)
                )
                deleted += cur.rowcount

                # Row-count cap
                total = conn.execute("SELECT COUNT(*) FROM frontend_errors").fetchone()[0]
                if total > max_rows:
                    excess = total - max_rows
                    conn.execute(
                        "DELETE FROM frontend_errors WHERE id IN "
                        "(SELECT id FROM frontend_errors ORDER BY created_at ASC LIMIT ?)",
                        (excess,),
                    )
                    deleted += excess

        if deleted > 0:
            logger.info("Error store rotation: pruned %d entries", deleted)
        self._last_rotation = time.time()
        return deleted

    def _maybe_rotate(self) -> None:
        """Auto-rotate at most once per hour."""
        if time.time() - self._last_rotation > 3600:
            try:
                self.rotate()
            except Exception as exc:
                logger.debug("Auto-rotation failed: %s", exc)

    # ── Internal ─────────────────────────────────────────────────────

    @staticmethod
    def _row_to_error(row: sqlite3.Row) -> FrontendError:
        return FrontendError(
            id=row["id"],
            timestamp=row["timestamp"],
            message=row["message"],
            stack=row["stack"],
            route=row["route"],
            client_tag=row["client_tag"],
            created_at=row["created_at"],
        )


# ── Singleton ────────────────────────────────────────────────────────

_store: Optional[FrontendErrorStore] = None
_store_lock = threading.Lock()


def get_error_store() -> FrontendErrorStore:
    """Get or create the singleton FrontendErrorStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = FrontendErrorStore()
    return _store


# ── Convenience API ──────────────────────────────────────────────────

def record_frontend_error(
    message: str,
    timestamp: Optional[str] = None,
    stack: Optional[str] = None,
    route: Optional[str] = None,
    client_tag: Optional[str] = None,
) -> FrontendError:
    """Record a frontend error. Call from the /errors/report endpoint."""
    err = FrontendError(
        timestamp=timestamp or datetime.now(tz=timezone.utc).isoformat(),
        message=message,
        stack=stack,
        route=route,
        client_tag=client_tag,
    )
    return get_error_store().record(err)
