"""
In-process acknowledgment state for risk alerts.
Acknowledgments persist for the lifetime of the server process.
A persistent store (Redis/DB) can replace this in production.
"""
import threading
from typing import Set

_lock = threading.Lock()
_acknowledged: Set[str] = set()


def mark_acknowledged(alert_id: str) -> None:
    with _lock:
        _acknowledged.add(alert_id)


def mark_all_acknowledged(known_ids: Set[str] | None = None) -> int:
    with _lock:
        if known_ids:
            _acknowledged.update(known_ids)
            return len(known_ids)
        # Without known_ids we can only report 0 new acks (no registry available)
        return 0


def is_acknowledged(alert_id: str) -> bool:
    with _lock:
        return alert_id in _acknowledged


def get_acknowledged() -> Set[str]:
    with _lock:
        return set(_acknowledged)
