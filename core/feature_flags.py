"""Centralized feature flags for MERID.

Flags can be flipped at runtime without redeploying via:
  - Environment variables: MERID_FF_<FLAG_NAME>=0|1
  - The /api/v1/system/feature-flags PUT endpoint (operator UI)

Usage in code:
    from core.feature_flags import is_enabled
    if is_enabled("auto_downsize"):
        ...  # perform auto-downsize logic

Each flag has a default value (True = enabled).  Override with env var
``MERID_FF_AUTO_DOWNSIZE=0`` to disable at startup, or use the runtime
API to toggle without restart.
"""
from __future__ import annotations

import os
import threading
from typing import Dict

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Flag registry ─────────────────────────────────────────────────────
# {flag_name: default_enabled}
_FLAG_DEFAULTS: Dict[str, bool] = {
    "auto_downsize": True,
    "unusual_volume_reaction": True,
    "telegram_alerts": True,  # Re-enabled after dedup + latch + backoff fixes (2026-03-19)
}

_lock = threading.Lock()
_overrides: Dict[str, bool] = {}


def _env_key(flag: str) -> str:
    return f"MERID_FF_{flag.upper()}"


def _read_env(flag: str) -> bool | None:
    val = os.getenv(_env_key(flag))
    if val is None:
        return None
    return val.lower() in ("1", "true", "yes", "on")


def is_enabled(flag: str) -> bool:
    """Return whether *flag* is currently enabled."""
    with _lock:
        if flag in _overrides:
            return _overrides[flag]
    env = _read_env(flag)
    if env is not None:
        return env
    return _FLAG_DEFAULTS.get(flag, True)


def set_flag(flag: str, enabled: bool) -> None:
    """Override *flag* at runtime (survives until process restart)."""
    with _lock:
        _overrides[flag] = enabled
    logger.info("feature_flag_set flag=%s enabled=%s", flag, enabled)


def reset_flag(flag: str) -> None:
    """Remove a runtime override so the flag falls back to env/default."""
    with _lock:
        _overrides.pop(flag, None)
    logger.info("feature_flag_reset flag=%s", flag)


def get_all_flags() -> Dict[str, bool]:
    """Return the effective state of every known flag."""
    return {name: is_enabled(name) for name in _FLAG_DEFAULTS}


def get_flag_details() -> Dict[str, Dict]:
    """Return detailed info per flag (for operator UI)."""
    result: Dict[str, Dict] = {}
    with _lock:
        overrides_snap = dict(_overrides)
    for name, default in _FLAG_DEFAULTS.items():
        env = _read_env(name)
        result[name] = {
            "enabled": is_enabled(name),
            "default": default,
            "env_var": _env_key(name),
            "env_value": env,
            "runtime_override": overrides_snap.get(name),
        }
    return result
