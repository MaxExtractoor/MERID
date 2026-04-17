"""KalshiContinuousTrader vs AgentGrid PM — single live execution brain.

When AgentGrid PM is live *or* legacy venue gates unlock real execution
(MERID_TRADE_MODE=live and MERID_ALLOW_LIVE_TRADES=true), KalshiContinuousTrader
is **legacy / research only**: it must not start or submit orders unless
MERID_CT_RESEARCH_ALLOW_LOOP is set.
"""

from __future__ import annotations

import os


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def agentgrid_pm_live_primary() -> bool:
    """True when PM is configured for live trading (AgentGrid is the primary brain)."""
    mode = (os.getenv("MERID_PM_TRADING_MODE") or "paper").strip().lower()
    return mode == "live" and _truthy(os.getenv("MERID_PM_LIVE_ENABLED"))


def ct_research_loop_allowed() -> bool:
    """Opt-in: allow the legacy CT asyncio loop / orders while PM live is enabled."""
    return _truthy(os.getenv("MERID_CT_RESEARCH_ALLOW_LOOP"))


def merid_venue_live_execution_unlocked() -> bool:
    """True when legacy global gates allow real venue orders (MERID_TRADE_MODE + ALLOW_LIVE).

    This is independent of MERID_PM_* — operators often enable these while AgentGrid PM
    flags are still paper, which previously let KalshiContinuousTrader hijack the live stack.
    """
    trade = (os.getenv("MERID_TRADE_MODE") or "").strip().lower()
    if trade != "live":
        return False
    return _truthy(os.getenv("MERID_ALLOW_LIVE_TRADES"))


def ct_loop_suppressed() -> bool:
    """True: do not start or run the KalshiContinuousTrader asyncio loop (server startup + run())."""
    if ct_research_loop_allowed():
        return False
    if agentgrid_pm_live_primary():
        return True
    if merid_venue_live_execution_unlocked():
        return True
    return False


def ct_legacy_must_not_trade() -> tuple[bool, str]:
    """If True, CT must not submit orders (nor run meaningful dry-run cycles that imply live CT)."""
    if ct_research_loop_allowed():
        return False, ""
    if agentgrid_pm_live_primary():
        return True, (
            "[CT-LEGACY] KalshiContinuousTrader is disabled while AgentGrid PM live is primary "
            "(MERID_PM_TRADING_MODE=live, MERID_PM_LIVE_ENABLED=true). "
            "Set MERID_CT_RESEARCH_ALLOW_LOOP=true for research-only CT."
        )
    if merid_venue_live_execution_unlocked():
        return True, (
            "[CT-LEGACY] KalshiContinuousTrader does not submit orders while live venue execution is unlocked "
            "(MERID_TRADE_MODE=live, MERID_ALLOW_LIVE_TRADES=true). "
            "AgentGrid PM owns execution; set MERID_CT_RESEARCH_ALLOW_LOOP=true for research-only CT."
        )
    return False, ""
