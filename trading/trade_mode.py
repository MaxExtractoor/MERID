"""Canonical trade-mode enum and global accessor.

Every layer — agents, routers, venues, adapters, UI — must import
``TradeMode`` and ``get_trade_mode()`` from this module.  There is
exactly **one** source of truth for the current process-wide mode.

Canonical process mode is derived from **prediction-market** env vars when
``MERID_PM_TRADING_MODE`` is **exported into the process environment**
(``MERID_PM_TRADING_MODE`` + ``MERID_PM_LIVE_ENABLED`` +
``MERID_ALLOW_LIVE_TRADES`` — same live triad as ``VenueGate``). If that key
is absent from ``os.environ``, legacy ``MERID_TRADE_MODE`` (default ``paper``)
is used (typical dotenv / docker injects both).

Programmatic override via ``set_trade_mode()``.
"""

from __future__ import annotations

import os
import threading
from enum import Enum
from typing import Optional

from utils.logger import get_logger

logger = get_logger("trading.trade_mode")

# ------------------------------------------------------------------ #
# Canonical enum
# ------------------------------------------------------------------ #

class TradeMode(str, Enum):
    """Process-wide trading mode.

    * **MOCK** – pure in-memory simulation, no external calls at all.
    * **PAPER** – real market data, simulated fills, no real money.
    * **LIVE** – real orders on real-money endpoints.
    """
    MOCK = "mock"
    PAPER = "paper"
    LIVE = "live"


# Backward-compat aliases used across older tests/modules.
# All non-canonical names map to MOCK (the safe default).
# ZT2-02: Centralised here so every alias import resolves consistently.
for _alias in ("SIM", "SIMULATION", "OFFLINE", "HYBRID"):
    if not hasattr(TradeMode, _alias):
        setattr(TradeMode, _alias, TradeMode.MOCK)  # type: ignore[attr-defined]


# ------------------------------------------------------------------ #
# Global singleton
# ------------------------------------------------------------------ #

# RLock: set_trade_mode() holds the lock while calling get_trade_mode(); after
# _reset_for_tests() _current_mode is None and get_trade_mode() must re-enter.
_lock = threading.RLock()
_current_mode: Optional[TradeMode] = None


def _resolve_initial_mode() -> TradeMode:
    allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # Canonical when export'd: MERID_PM_TRADING_MODE must appear in os.environ
    # (same live triad as VenueGate). Otherwise fall back to MERID_TRADE_MODE.
    if "MERID_PM_TRADING_MODE" in os.environ:
        pm = os.environ["MERID_PM_TRADING_MODE"].strip().lower()
        if pm in ("mock", "sim", "simulation", "offline", "hybrid"):
            return TradeMode.MOCK
        if pm == "live":
            pm_live = os.getenv("MERID_PM_LIVE_ENABLED", "").lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
            if pm_live and allow_live:
                return TradeMode.LIVE
            if pm_live and not allow_live:
                logger.warning(
                    "MERID_PM_TRADING_MODE=live but MERID_ALLOW_LIVE_TRADES is not set — using PAPER",
                )
            return TradeMode.PAPER
        try:
            return TradeMode(pm)
        except ValueError:
            logger.warning(
                "Unknown MERID_PM_TRADING_MODE=%r — defaulting to PAPER",
                pm,
            )
            return TradeMode.PAPER

    raw = os.getenv("MERID_TRADE_MODE", "paper").lower().strip()
    try:
        tm = TradeMode(raw)
    except ValueError:
        logger.warning(
            "Unknown MERID_TRADE_MODE=%r, defaulting to PAPER", raw,
        )
        return TradeMode.PAPER
    if tm == TradeMode.LIVE and not allow_live:
        logger.warning(
            "MERID_TRADE_MODE=live but MERID_ALLOW_LIVE_TRADES is not set — using PAPER",
        )
        return TradeMode.PAPER
    return tm


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
                logger.warning("execution_gate module not available — skipping gate check for LIVE switch")

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
        except Exception as _sl_exc:
            logger.debug("session_log record_event failed for mode change: %s", _sl_exc)

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


# ------------------------------------------------------------------ #
# TEST-ONLY: Reset hook for test isolation
# ------------------------------------------------------------------ #

def _reset_for_tests() -> None:
    """TEST-ONLY: Reset TradeMode singleton state for test isolation.
    
    WARNING: This function is for test suite use only. Calling this in
    production code will cause undefined behavior and trading mode
    inconsistencies. Do not use outside of tests.
    
    This resets the internal singleton state, allowing each test to have
    a clean TradeMode state without interference from previous tests.
    """
    global _current_mode
    with _lock:
        old_mode = _current_mode
        _current_mode = None
        logger.debug(
            "TEST-ONLY: TradeMode singleton reset (was %s)",
            old_mode.value if old_mode else "None"
        )

