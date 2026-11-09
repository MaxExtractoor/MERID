"""Snapshot and replay process configuration / reference data.

At tape start we capture the environment that affects trading behaviour.
During replay those same values are pinned before the production stack is
imported so no live config read can diverge from the captured run.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


# Keys that should never be written to a tape, even in masked form.
_SECRET_PATTERNS = (
    "KEY",
    "PASSWORD",
    "PASS",
    "SECRET",
    "TOKEN",
    "PRIVATE",
    "PEM",
    "CERT",
    "CREDENTIAL",
    "ANON_KEY",
    "SERVICE_ROLE",
    "APP_PASSWORD",
)


REPLAY_PROTECTED_KEYS = frozenset({
    "MERID_REPLAY_TAPE", "MERID_INGRESS_RECORDING", "TRADING_ENABLED",
    "MERID_PM_LIVE_ENABLED", "MERID_ALLOW_LIVE_TRADES", "MERID_EXECUTION_MODE",
    "MERID_LOOP_DRY_RUN", "MERID_ALLOW_CT_SCRIPT_BYPASS", "MERID_REQUIRE_EXIT_PARENTAGE",
    "MERID_EXIT_FIREWALL_OBSERVE_ONLY", "MERID_CIRCUIT_BREAKER_DISABLED",
    "MERID_PM_TRADING_MODE", "MERID_TRADE_MODE", "MERID_AUTO_EXECUTION_MODE",
    "MERID_OBSERVE_ONLY", "ALLOW_DIRECT_EXECUTION", "DEBUG_ALLOW_MANUAL_ORDERS",
})


def _looks_secret(key: str) -> bool:
    upper = key.upper()
    return any(p in upper for p in _SECRET_PATTERNS)


def _is_decision_relevant_environ_key(key: str) -> bool:
    """True for environment keys known to alter strategy/risk/router behaviour."""
    upper = key.upper()
    return upper.startswith(("MERID_", "KALSHI_", "TRADING_", "MERID"))


def _safe_environ() -> Dict[str, str]:
    """Return a filtered copy of ``os.environ`` with secret values omitted."""
    out: Dict[str, str] = {}
    for key, val in os.environ.items():
        if _looks_secret(key):
            continue
        if not _is_decision_relevant_environ_key(key):
            continue
        out[key] = val
    return out


def _is_sensitive_field(key: str) -> bool:
    from utils.secrets_manager import is_sensitive_field

    return is_sensitive_field(key)


def _redact_model_dump(dump: Dict[str, Any]) -> Dict[str, Any]:
    """Return a settings dump with secret fields set to None (not used for env)."""
    out: Dict[str, Any] = {}
    for key, val in dump.items():
        if _is_sensitive_field(key):
            out[key] = None
        elif isinstance(val, dict):
            # Nested model — shallow redact; nested secrets are omitted.
            out[key] = {k: "***" if _is_sensitive_field(k) else v for k, v in val.items()}
        else:
            out[key] = val
    return out


def capture_snapshot(
    tape_dir: Path,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write a config snapshot to the tape directory.

    This should be called once at tape start, before any non-deterministic
    config/reference data is consulted.
    """
    from merid.settings import settings

    snapshot = {
        "v": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "environ": _safe_environ(),
        "settings": _redact_model_dump(settings.model_dump()),
        "extra": extra or {},
    }
    path = tape_dir / "tape_config_snapshot.json"
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def load_snapshot(tape_dir: Path) -> Optional[Dict[str, Any]]:
    """Load a config snapshot if present in the tape directory."""
    path = tape_dir / "tape_config_snapshot.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _coerce(value: Any, current: Any) -> Any:
    """Best-effort cast of a captured value to the current field's type."""
    if value is None:
        return None
    if isinstance(current, bool) and isinstance(value, bool):
        return value
    if isinstance(current, int) and isinstance(value, int):
        return value
    if isinstance(current, (int, float)) and isinstance(value, (int, float)):
        return type(current)(value)
    if isinstance(current, str) and isinstance(value, str):
        return value
    if isinstance(current, (list, tuple)) and isinstance(value, list):
        return value
    return value


def apply_snapshot(tape_dir: Path, protected_keys: Optional[set] = None) -> bool:
    """Apply a captured snapshot to the current process.

    Environment variables are set first (so any not-yet-imported module picks
    them up).  If ``merid.settings.settings`` is already loaded, its scalar
    attributes are overwritten with the captured values as a best-effort pin.

    ``protected_keys`` are environment keys we must not overwrite (e.g. replay
    safety latches that were already set by the caller).
    """
    protected = REPLAY_PROTECTED_KEYS | (protected_keys or set())
    snapshot = load_snapshot(tape_dir)
    if snapshot is None:
        return False

    for key, val in snapshot.get("environ", {}).items():
        if key in protected or _looks_secret(key) or val is None:
            continue
        os.environ[key] = val

    # Pin already-loaded settings attributes.  Pydantic will not re-validate,
    # but this is only used for simple scalar override during replay tests/CLI.
    try:
        from merid.settings import settings

        captured_settings = snapshot.get("settings", {})
        for field in type(settings).model_fields:
            if field in protected or _looks_secret(field):
                continue
            if field in captured_settings:
                captured = captured_settings[field]
                current = getattr(settings, field)
                if isinstance(current, (str, int, float, bool, type(None), list)):
                    try:
                        setattr(settings, field, _coerce(captured, current))
                    except Exception:
                        pass
    except Exception:
        pass
    return True
