from __future__ import annotations

import os
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvironmentFlags:
    """Lightweight feature flags describing runtime environment constraints."""

    offline_mode: bool = False
    telemetry_restricted: bool = False
    social_stream_enabled: bool = True
    allow_external_calls: bool = False


def _bool_from_env(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_cached_flags: EnvironmentFlags | None = None
_cached_flags_lock = threading.Lock()


def _load_flags_from_env() -> EnvironmentFlags:
    return EnvironmentFlags(
        offline_mode=_bool_from_env("MERID_OFFLINE_MODE", False),
        telemetry_restricted=_bool_from_env("MERID_TELEMETRY_RESTRICTED", False),
        social_stream_enabled=_bool_from_env("MERID_SOCIAL_STREAM_ENABLED", True),
        allow_external_calls=_bool_from_env("MERID_ALLOW_EXTERNAL_CALLS", False),
    )


def get_environment_flags() -> EnvironmentFlags:
    """Return cached EnvironmentFlags built from environment variables."""

    global _cached_flags
    if _cached_flags is None:
        with _cached_flags_lock:
            if _cached_flags is None:
                _cached_flags = _load_flags_from_env()
    return _cached_flags


def override_environment_flags(flags: EnvironmentFlags) -> None:
    """Test helper to replace cached flags."""

    global _cached_flags
    _cached_flags = flags


def reset_environment_flags() -> None:
    """Clear cached flags so the next access reloads from env."""

    global _cached_flags
    _cached_flags = None
