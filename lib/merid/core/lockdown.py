"""Server-side lockdown state.

Provides a simple in-memory lockdown flag and helpers. In production this
should be backed by a shared store (Redis) and include auditing.
"""

_lockdown_flag = False


def set_lockdown(flag: bool) -> None:
    global _lockdown_flag
    _lockdown_flag = bool(flag)


def is_lockdown() -> bool:
    return bool(_lockdown_flag)
