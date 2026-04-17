"""Prediction-market runtime profile helpers (AgentGrid production belt)."""

from __future__ import annotations

import logging
import os
from typing import Any

from utils.logger import get_logger

logger = get_logger("merid.pm_runtime")

_PRODUCTION_LOGGERS = (
    "merid.prediction.trading_agent",
    "merid.prediction.agent_grid",
    "merid.prediction.venue_gate",
    "merid.event_venues.kalshi.order_router",
)


def is_production_pm_profile() -> bool:
    return os.getenv("MERID_PM_PROFILE", "development").strip().lower() == "production"


def apply_pm_production_logging_belt() -> None:
    """Ensure veto / grid loggers emit at INFO when running production PM profile."""
    if not is_production_pm_profile():
        return
    for name in _PRODUCTION_LOGGERS:
        lg = logging.getLogger(name)
        if lg.level > logging.INFO or lg.level == logging.NOTSET:
            lg.setLevel(logging.INFO)


def assert_production_agent_grid_preconditions(agent_count: int) -> None:
    """Fail fast before AgentGrid spends minutes booting (production profile only)."""
    if not is_production_pm_profile():
        return
    if agent_count <= 0:
        raise RuntimeError(
            "MERID_PM_PROFILE=production: AgentGrid has zero enabled agents — refusing to start"
        )

    pm = os.getenv("MERID_PM_TRADING_MODE", "paper").lower()
    if pm != "live":
        raise RuntimeError(
            "MERID_PM_PROFILE=production requires MERID_PM_TRADING_MODE=live "
            f"(got {pm!r})"
        )
    if os.getenv("MERID_PM_LIVE_ENABLED", "").lower() not in ("1", "true", "yes", "on"):
        raise RuntimeError(
            "MERID_PM_PROFILE=production requires MERID_PM_LIVE_ENABLED=true"
        )

    from merid.prediction.venue_gate import VenueGate

    gate = VenueGate()
    if gate.mode.value.lower() == "mock":
        raise RuntimeError(
            "MERID_PM_PROFILE=production: VenueGate is MOCK — check MERID_PM_TRADING_MODE / sim aliases"
        )
    if not gate.is_live:
        raise RuntimeError(
            "MERID_PM_PROFILE=production: VenueGate is not live "
            "(need MERID_PM_TRADING_MODE=live, MERID_PM_LIVE_ENABLED=true, MERID_ALLOW_LIVE_TRADES=true)"
        )

    try:
        from merid.risk.kill_switches import risk_controller

        if not risk_controller.can_trade():
            reason = risk_controller.get_kill_reason()
            raise RuntimeError(
                "MERID_PM_PROFILE=production: global kill switch blocks trading "
                f"({reason or 'no reason'})"
            )
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Production grid: could not read risk_controller (%s) — continuing", exc)


def log_grid_start_banner(grid: Any) -> None:
    """Single-line operator-friendly banner (search logs for [GRID-START])."""
    try:
        from merid.prediction.venue_gate import VenueGate

        vg = VenueGate()
    except Exception as exc:
        logger.warning("[GRID-START] VenueGate unavailable: %s", exc)
        return

    risk_halted = False
    try:
        from merid.risk.kill_switches import risk_controller

        risk_halted = not risk_controller.can_trade()
    except Exception:
        pass

    n = len(getattr(grid, "_agents", []) or [])
    logger.info(
        "[GRID-START] mode=%s live_enabled=%s risk_halted=%s agents=%d profile=%s",
        vg.mode.value,
        vg.live_enabled,
        risk_halted,
        n,
        os.getenv("MERID_PM_PROFILE", "development"),
    )
