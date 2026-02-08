"""Persistent notification store — append-only SQLite backend.

Provides:
  - ``add_notification(type, title, message, source, severity)``
  - ``list_notifications(limit, since_ms)``
  - ``mark_read(notification_id)``
  - ``unread_count()``

Other modules (risk, trading, health) call ``add_notification`` to
emit events that surface in the operator UI via ``/api/v1/notifications``.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.notifications")

# ── Domain objects ───────────────────────────────────────────────────

SEVERITY_LEVELS = ("info", "warning", "error", "critical")
NOTIFICATION_TYPES = ("info", "success", "warning", "error", "system", "trade", "risk", "health")


@dataclass
class Notification:
    """A single notification entry."""
    id: str = field(default_factory=lambda: f"n-{uuid.uuid4().hex[:12]}")
    type: str = "info"
    severity: str = "info"
    title: str = ""
    message: str = ""
    source: str = ""
    created_at: float = field(default_factory=time.time)
    read: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "timestamp": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "read": self.read,
        }


# ── SQLite store ─────────────────────────────────────────────────────

_DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_DB_PATH = os.environ.get("MERID_NOTIFICATIONS_DB", os.path.join(_DB_DIR, "notifications.db"))

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS notifications (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL DEFAULT 'info',
    severity    TEXT NOT NULL DEFAULT 'info',
    title       TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    read        INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at DESC);
"""


class NotificationStore:
    """Thread-safe, append-only SQLite notification store."""

    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_INDEX)
        logger.info("Notification store initialized: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Write ────────────────────────────────────────────────────────

    def add(self, notification: Notification) -> Notification:
        """Persist a notification. Returns the notification with its id."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO notifications (id, type, severity, title, message, source, created_at, read) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (notification.id, notification.type, notification.severity,
                     notification.title, notification.message, notification.source,
                     notification.created_at, int(notification.read)),
                )
        return notification

    def mark_read(self, notification_id: str) -> bool:
        """Mark a notification as read. Returns True if found."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "UPDATE notifications SET read = 1 WHERE id = ?",
                    (notification_id,),
                )
                return cur.rowcount > 0

    def mark_all_read(self) -> int:
        """Mark all unread notifications as read. Returns count updated."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
                return cur.rowcount

    # ── Read ─────────────────────────────────────────────────────────

    def list(self, limit: int = 50, since_ms: Optional[int] = None) -> List[Notification]:
        """Return newest notifications, optionally filtered by timestamp."""
        with self._connect() as conn:
            if since_ms is not None:
                since_epoch = since_ms / 1000.0
                rows = conn.execute(
                    "SELECT * FROM notifications WHERE created_at >= ? ORDER BY created_at DESC LIMIT ?",
                    (since_epoch, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notifications ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_notification(r) for r in rows]

    def unread_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM notifications WHERE read = 0").fetchone()
            return row[0] if row else 0

    def total_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()
            return row[0] if row else 0

    def get_stats(self) -> Dict[str, Any]:
        """Return lightweight stats for the notification store."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
            unread = conn.execute("SELECT COUNT(*) FROM notifications WHERE read = 0").fetchone()[0]
            last_row = conn.execute(
                "SELECT created_at FROM notifications ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            last_created_at = last_row[0] if last_row else None

            severity_rows = conn.execute(
                "SELECT severity, COUNT(*) FROM notifications GROUP BY severity"
            ).fetchall()
            by_severity = {row[0]: row[1] for row in severity_rows}

        return {
            "total": total,
            "unread": unread,
            "last_created_at": last_created_at,
            "by_severity": by_severity,
            "store_path": self._db_path,
            "healthy": True,
        }

    @staticmethod
    def _row_to_notification(row: sqlite3.Row) -> Notification:
        return Notification(
            id=row["id"],
            type=row["type"],
            severity=row["severity"],
            title=row["title"],
            message=row["message"],
            source=row["source"],
            created_at=row["created_at"],
            read=bool(row["read"]),
        )


# ── Singleton ────────────────────────────────────────────────────────

_store: Optional[NotificationStore] = None


def get_notification_store() -> NotificationStore:
    """Get or create the singleton NotificationStore."""
    global _store
    if _store is None:
        _store = NotificationStore()
    return _store


# ── Convenience API ──────────────────────────────────────────────────

def add_notification(
    type: str = "info",
    title: str = "",
    message: str = "",
    source: str = "",
    severity: str = "info",
) -> Notification:
    """Add a notification to the store. Call from anywhere in the codebase."""
    n = Notification(
        type=type,
        severity=severity,
        title=title,
        message=message,
        source=source,
    )
    return get_notification_store().add(n)


def list_notifications(limit: int = 50, since_ms: Optional[int] = None) -> List[Notification]:
    """List recent notifications."""
    return get_notification_store().list(limit=limit, since_ms=since_ms)
