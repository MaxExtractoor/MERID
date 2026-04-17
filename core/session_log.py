"""Session Event Log — time-ordered record of safety-relevant events.

Captures: mode changes, kill-switch toggles, gate block/unblock,
feed outages, reconciliation runs, and operator actions.

All events are stored in-memory for the current session and
exposed via ``get_events()`` for the UI timeline.

Persistence: events are periodically flushed to ``data/session_log.jsonl``
and reloaded on startup so the dashboard survives restarts.
"""

from __future__ import annotations

import json
import os
import time
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any

from utils.logger import get_logger

logger = get_logger("core.session_log")

# ── Session identity ──────────────────────────────────────────────────

_SESSION_ID: str = uuid.uuid4().hex[:12]
_SESSION_START: float = time.time()
_SESSION_BRACKET: Optional[str] = None  # e.g. "Sandbox ($1K)", "Rookie ($5K)"

LOG_FILE = Path("data/session_log.jsonl")
_FLUSH_INTERVAL = 30  # seconds between disk flushes
_RELOAD_LIMIT = 200   # max events to reload from previous session


def get_session_info() -> Dict[str, Any]:
    """Return current session metadata."""
    return {
        "session_id": _SESSION_ID,
        "start_time": _SESSION_START,
        "uptime_seconds": round(time.time() - _SESSION_START, 1),
        "bracket": _SESSION_BRACKET,
    }


def set_session_bracket(bracket: str) -> None:
    """Set the current ladder bracket label for this session.

    Records a session event so the timeline shows bracket transitions.
    """
    global _SESSION_BRACKET
    old = _SESSION_BRACKET
    _SESSION_BRACKET = bracket
    logger.info("Session bracket set: %s", bracket)
    record_event(
        category="system",
        severity="info",
        title=f"Bracket: {bracket}",
        detail=f"Ladder bracket changed from {old or 'none'} to {bracket}",
        hint="Monitor drawdown and PnL consistency as capital scales.",
        metadata={"bracket": bracket, "previous": old},
    )


class EventCategory(str, Enum):
    GATE = "gate"
    KILL_SWITCH = "kill_switch"
    MODE = "mode"
    RECONCILIATION = "reconciliation"
    FEED = "feed"
    OPERATOR = "operator"
    SYSTEM = "system"


class EventSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class SessionEvent:
    """A single session event."""
    timestamp: float
    category: str
    severity: str
    title: str
    detail: Optional[str] = None
    hint: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    session_id: str = field(default_factory=lambda: _SESSION_ID)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "hint": self.hint,
            "metadata": self.metadata,
            "session_id": self.session_id,
        }


# ── Singleton event store ───────────────────────────────────────────

_lock = threading.Lock()
_events: List[SessionEvent] = []
_MAX_EVENTS = 500  # rolling window
_unflushed_count = 0
_last_flush: float = 0.0


def record_event(
    category: str,
    severity: str,
    title: str,
    detail: Optional[str] = None,
    hint: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SessionEvent:
    """Record a session event. Thread-safe."""
    global _unflushed_count
    evt = SessionEvent(
        timestamp=time.time(),
        category=category,
        severity=severity,
        title=title,
        detail=detail,
        hint=hint,
        metadata=metadata or {},
    )
    with _lock:
        _events.append(evt)
        _unflushed_count += 1
        # Trim to rolling window
        if len(_events) > _MAX_EVENTS:
            _events[:] = _events[-_MAX_EVENTS:]

    logger.info(
        "session_event | %s | %s | %s%s",
        category, severity, title,
        f" | {detail}" if detail else "",
    )

    # Auto-flush to disk periodically
    _maybe_flush()

    return evt


def get_events(
    limit: int = 50,
    category: Optional[str] = None,
    since: Optional[float] = None,
) -> List[SessionEvent]:
    """Get recent session events, newest first."""
    with _lock:
        filtered = list(_events)

    if category:
        filtered = [e for e in filtered if e.category == category]
    if since:
        filtered = [e for e in filtered if e.timestamp >= since]

    # Newest first, limited
    filtered.sort(key=lambda e: e.timestamp, reverse=True)
    return filtered[:limit]


def clear_events() -> None:
    """Clear all events (for testing)."""
    global _unflushed_count
    with _lock:
        _events.clear()
        _unflushed_count = 0


# ── Persistence ───────────────────────────────────────────────────────

def _maybe_flush() -> None:
    """Flush unflushed events to disk if interval has elapsed."""
    global _last_flush, _unflushed_count
    now = time.time()
    if now - _last_flush < _FLUSH_INTERVAL:
        return
    if _unflushed_count == 0:
        return
    # Run flush in background to avoid blocking callers
    threading.Thread(target=_flush_to_disk, daemon=True).start()


def _flush_to_disk() -> None:
    """Append unflushed events to the JSONL log file."""
    global _last_flush, _unflushed_count
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            to_flush = [e.to_dict() for e in _events[-_unflushed_count:]] if _unflushed_count > 0 else []
            _unflushed_count = 0
            _last_flush = time.time()

        if to_flush:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                for evt_dict in to_flush:
                    f.write(json.dumps(evt_dict, default=str) + "\n")
            logger.debug("Flushed %d session events to %s", len(to_flush), LOG_FILE)
    except Exception as exc:
        logger.warning("Failed to flush session log: %s", exc)


def flush_now() -> int:
    """Force an immediate flush. Returns number of events flushed."""
    global _unflushed_count
    with _lock:
        count = _unflushed_count
    if count > 0:
        _flush_to_disk()
    return count


def reload_from_disk(session_id: Optional[str] = None) -> int:
    """Reload recent events from the JSONL log file into memory.

    If session_id is given, only loads events from that session.
    Otherwise loads the most recent _RELOAD_LIMIT events.

    Returns number of events loaded.
    """
    if not LOG_FILE.exists():
        return 0

    loaded = 0
    try:
        lines: List[str] = []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)

        # Take only the tail
        tail = lines[-_RELOAD_LIMIT * 2:] if len(lines) > _RELOAD_LIMIT * 2 else lines

        reloaded: List[SessionEvent] = []
        for line in tail:
            try:
                d = json.loads(line)
                if session_id and d.get("session_id") != session_id:
                    continue
                evt = SessionEvent(
                    timestamp=d["timestamp"],
                    category=d["category"],
                    severity=d["severity"],
                    title=d["title"],
                    detail=d.get("detail"),
                    hint=d.get("hint"),
                    metadata=d.get("metadata", {}),
                    session_id=d.get("session_id", "unknown"),
                )
                reloaded.append(evt)
            except (json.JSONDecodeError, KeyError):
                continue

        # Take only the most recent ones
        reloaded.sort(key=lambda e: e.timestamp)
        reloaded = reloaded[-_RELOAD_LIMIT:]

        with _lock:
            # Prepend reloaded events before any current-session events
            existing_ts = {e.timestamp for e in _events}
            new_events = [e for e in reloaded if e.timestamp not in existing_ts]
            _events[:0] = new_events
            loaded = len(new_events)

        if loaded:
            logger.info("Reloaded %d session events from %s", loaded, LOG_FILE)
    except Exception as exc:
        logger.warning("Failed to reload session log: %s", exc)

    return loaded


# ── Auto-reload on import ─────────────────────────────────────────────
try:
    reload_from_disk()
except Exception as _reload_exc:
    import logging as _logging
    _logging.getLogger(__name__).debug("session_log auto-reload failed: %s", _reload_exc)
