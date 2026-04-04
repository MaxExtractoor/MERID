"""Canonical trade-mode enum and global accessor.

Every layer — agents, routers, venues, adapters, UI — must import
``TradeMode`` and ``get_trade_mode()`` from this module.  There is
exactly **one** source of truth for the current process-wide mode.

Environment variable: ``MERID_TRADE_MODE`` (default ``paper``).
Programmatic override via ``set_trade_mode()``.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from utils.logger import get_logger

# TradeMode is the single canonical definition; importing from config avoids
# the shadow problem that occurs when tests run from a directory named
# ``trading/`` (which would intercept ``from trading.trade_mode import …``).
from config.trading_mode import TradeMode  # noqa: F401  (re-export)

logger = get_logger("trading.trade_mode")


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

_lock = threading.Lock()
_current_mode: Optional[TradeMode] = None


def _resolve_initial_mode() -> TradeMode:
    raw = os.getenv("MERID_TRADE_MODE", "paper").lower().strip()
    try:
        return TradeMode(raw)
    except ValueError:
        logger.warning(
            "Unknown MERID_TRADE_MODE=%r, defaulting to PAPER", raw,
        )
        return TradeMode.PAPER


def get_trade_mode() -> TradeMode:
    """Return the current process-wide trade mode (thread-safe)."""
    global _current_mode
    if _current_mode is None:
        with _lock:
            if _current_mode is None:
                _current_mode = _resolve_initial_mode()
                logger.info("Trade mode initialised: %s", _current_mode.value)
    return _current_mode


def set_trade_mode(mode: TradeMode, *, reason: str = "") -> TradeMode:
    """Change the process-wide trade mode.

    Returns the *previous* mode so callers can restore it if needed.

    Transition rules:
    * MOCK → PAPER: allowed
    * PAPER → MOCK: allowed
    * PAPER → LIVE: only if ``MERID_ALLOW_LIVE_TRADES=true``
    * LIVE → PAPER: always allowed (safe direction)
    * LIVE → MOCK: always allowed (safe direction)
    * MOCK → LIVE: blocked (must go through PAPER first)
    """
    global _current_mode
    with _lock:
        old = get_trade_mode()

        # Guard: MOCK → LIVE is forbidden
        if old == TradeMode.MOCK and mode == TradeMode.LIVE:
            raise RuntimeError(
                "Cannot transition directly from MOCK to LIVE. "
                "Switch to PAPER first and verify the system."
            )

        # Guard: anything → LIVE requires explicit env flag
        if mode == TradeMode.LIVE:
            allow = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower()
            if allow not in {"1", "true", "yes", "on"}:
                raise RuntimeError(
                    "Cannot switch to LIVE: MERID_ALLOW_LIVE_TRADES is not set. "
                    "Set MERID_ALLOW_LIVE_TRADES=true to enable live trading."
                )

        # Guard: → LIVE blocked when execution gate is not clear
        if mode == TradeMode.LIVE:
            try:
                from core.execution_gate import check_execution_gate
                gate = check_execution_gate()
                if gate.blocked:
                    reasons_str = "; ".join(r.message for r in gate.reasons)
                    raise RuntimeError(
                        f"Cannot switch to LIVE: execution gate blocked. "
                        f"Resolve: {reasons_str}"
                    )
            except ImportError:
                pass

        _current_mode = mode
        logger.info(
            "Trade mode changed: %s → %s%s",
            old.value,
            mode.value,
            f" ({reason})" if reason else "",
        )

        # Record session event
        try:
            from core.session_log import record_event
            sev = "critical" if mode == TradeMode.LIVE else "info"
            record_event(
                category="mode",
                severity=sev,
                title=f"Mode changed: {old.value} → {mode.value}",
                detail=reason or None,
                metadata={"old_mode": old.value, "new_mode": mode.value},
            )
        except Exception:
            pass

        return old


def is_paper_or_mock() -> bool:
    """Convenience: True when the process must NOT send real orders."""
    return get_trade_mode() in (TradeMode.MOCK, TradeMode.PAPER)


def assert_not_live(context: str = "") -> None:
    """Hard assertion — raises RuntimeError if mode is LIVE.

    Use this as a safety net in code paths that must never execute
    against real-money endpoints.
    """
    mode = get_trade_mode()
    if mode == TradeMode.LIVE:
        msg = "SAFETY: live execution attempted"
        if context:
            msg += f" in {context}"
        msg += " — blocked by assert_not_live()"
        logger.error(msg)
        raise RuntimeError(msg)
