"""Platform-wide Fresh Start mode.

When enabled, every subsystem skips loading persisted state and instead
resets to a clean baseline.  This guarantees that all metrics, charts,
and telemetry reflect *only* the current run — no stale history.

Activation (either works):
  - Environment variable: ``MERID_FRESH_START=1``
  - YAML config:  ``merid.fresh_start: true``

Kill-switch state is **always** preserved across a fresh start so that
a reset cannot silently re-enable trading.
"""

from __future__ import annotations

import os
import threading
from typing import List, Callable

from utils.logger import get_logger

logger = get_logger("core.fresh_start")

_lock = threading.Lock()
_resolved: bool | None = None

# Registry of cleanup callbacks that subsystems register at import time.
# Each callback is invoked exactly once during startup when fresh-start
# mode is active.  Callbacks run in registration order.
_reset_hooks: List[Callable[[], None]] = []


def is_fresh_start() -> bool:
    """Return True if the platform should wipe transient state on this boot."""
    global _resolved
    if _resolved is not None:
        return _resolved

    with _lock:
        if _resolved is not None:
            return _resolved

        # 1. Env var (highest priority)
        env = os.getenv("MERID_FRESH_START", "").strip().lower()
        if env in ("1", "true", "yes", "on"):
            _resolved = True
            logger.warning("FRESH START mode enabled via MERID_FRESH_START env var")
            return True

        # 2. YAML config (settings.yaml → merid.fresh_start)
        try:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"
            if cfg_path.exists():
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(f) or {}
                merid_block = cfg.get("merid", {})
                if isinstance(merid_block, dict) and merid_block.get("fresh_start"):
                    _resolved = True
                    logger.warning("FRESH START mode enabled via config/settings.yaml")
                    return True
        except Exception:
            pass  # YAML parsing failure → not fresh start

        _resolved = False
        return False


def assert_safe_for_fresh_start() -> None:
    """Raise RuntimeError if fresh start is active in LIVE mode.

    Must be called early in the startup sequence — before any reset
    hooks run — so that a misconfigured production deploy cannot
    accidentally nuke real trading state.
    """
    if not is_fresh_start():
        return
    try:
        from trading.trade_mode import get_trade_mode, TradeMode
        if get_trade_mode() == TradeMode.LIVE:
            raise RuntimeError(
                "FATAL: MERID_FRESH_START is not allowed in LIVE mode. "
                "Switch to MOCK or PAPER before enabling fresh start."
            )
    except ImportError:
        pass  # trade_mode module not available — safe to proceed


def register_reset_hook(fn: Callable[[], None]) -> None:
    """Register a callback to be invoked during fresh-start reset.

    Hooks run in registration order, synchronously, before the app
    starts serving requests.
    """
    _reset_hooks.append(fn)


def run_reset_hooks() -> int:
    """Execute all registered reset hooks.  Returns count of hooks run."""
    count = 0
    for fn in _reset_hooks:
        try:
            fn()
            count += 1
        except Exception as exc:
            logger.error("Fresh-start reset hook %s failed: %s", fn.__qualname__, exc)
    return count
