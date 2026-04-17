"""Minimal lockdown manager stub used for test/dev contexts.

This lightweight module preserves the public API that higher layers expect from
the true lockdown subsystem. It intentionally defaults to permissive behavior so
critical modules (e.g., web APIs, simulations) can import and run in CI without
requiring the full hardening stack. Replace with the production implementation
before relying on lockdown semantics in production.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class LockdownLevel(Enum):
    NONE = "none"
    WATCH = "watch"
    STRICT = "strict"
    FULL = "full"


class LockdownReason(Enum):
    NONE = "none"
    SECURITY_EVENT = "security_event"
    MANUAL = "manual"
    INCIDENT = "incident"


@dataclass
class LockdownState:
    level: LockdownLevel = LockdownLevel.NONE
    reason: LockdownReason = LockdownReason.NONE
    triggered_by: str = "dev"
    is_locked: bool = False


class LockdownManager:
    """Stub manager that tracks lockdown state in-memory."""

    def __init__(self) -> None:
        self._state = LockdownState()

    @property
    def is_locked(self) -> bool:  # pragma: no cover - trivial
        return self._state.is_locked

    @property
    def level(self) -> LockdownLevel:
        return self._state.level

    @property
    def reason(self) -> LockdownReason:
        return self._state.reason

    def enable_lockdown(
        self,
        level: LockdownLevel = LockdownLevel.STRICT,
        reason: LockdownReason = LockdownReason.MANUAL,
        triggered_by: str = "dev",
    ) -> None:
        self._state = LockdownState(level=level, reason=reason, triggered_by=triggered_by, is_locked=True)

    def disable_lockdown(self, triggered_by: str = "dev") -> None:
        self._state = LockdownState(triggered_by=triggered_by)

    def check_operation_allowed(self, operation: str, context: Dict[str, Any] | None = None) -> bool:
        # In tests we allow all operations; add assertions via context if needed.
        return True


_manager: LockdownManager | None = None


def get_lockdown_manager() -> LockdownManager:
    global _manager
    if _manager is None:
        _manager = LockdownManager()
    return _manager


def enable_lockdown(level: str = "strict", reason: str = "manual", triggered_by: str = "dev") -> None:
    manager = get_lockdown_manager()
    manager.enable_lockdown(LockdownLevel(level), LockdownReason(reason), triggered_by)


def disable_lockdown(triggered_by: str = "dev") -> None:
    get_lockdown_manager().disable_lockdown(triggered_by)


def is_lockdown_active() -> bool:
    return get_lockdown_manager().is_locked


def check_operation_allowed(operation: str, context: Dict[str, Any] | None = None) -> bool:
    return get_lockdown_manager().check_operation_allowed(operation, context)
