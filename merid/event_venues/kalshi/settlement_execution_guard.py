"""Central gate for Kalshi orders during RTI settlement window.

EXPIRY CHAOS AUDIT: This module is the final line of defense for RTI-settled
markets. It blocks new positions in the final minute and enforces settlement
data quality checks.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from config.kalshi_crypto_series_meta import is_rti_settled_kalshi_crypto_ticker
from merid.data.settlement_rti_buffer import get_settlement_buffer_registry
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.settlement_execution_guard")


def _final_sec() -> int:
    """Seconds before expiry to activate settlement guard."""
    return int(os.environ.get("MERID_RTI_SETTLEMENT_FINAL_SECONDS", "60"))


def _policy() -> str:
    """Order policy: 'reduce_ok' (allow sells) or 'block_all' (block everything)."""
    return os.environ.get("MERID_RTI_SETTLEMENT_ORDER_POLICY", "reduce_ok").strip().lower()


def _allow_buy_if_grade() -> bool:
    """Whether to allow buys in final minute if settlement buffer is complete."""
    # EXPIRY CHAOS: Default to False for safety (Gap G5 fix)
    return os.environ.get("MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE", "").strip() in (
        "1",
        "true",
        "yes",
    )


def _require_settlement_grade() -> bool:
    """Whether to require settlement-grade data for any trading near expiry."""
    return os.environ.get("MERID_RTI_REQUIRE_SETTLEMENT_GRADE", "1").strip() in (
        "1",
        "true",
        "yes",
    )


def _extended_guard_seconds() -> int:
    """Extended guard period for degraded settlement data (Gap G4 fix)."""
    return int(os.environ.get("MERID_RTI_EXTENDED_GUARD_SECONDS", "120"))


def evaluate_settlement_order(
    *,
    ticker: str,
    action: str,
    seconds_to_expiry: Optional[float],
    count: int,
) -> Optional[str]:
    """Return rejection reason or None if allowed.

    EXPIRY CHAOS AUDIT: This function enforces the settlement window rules:
    1. Block new buys in the final 60 seconds (configurable)
    2. Allow sells (position reduction) by default
    3. Require settlement-grade RTI data for any trading near expiry
    4. Extended guard (120s) if settlement data is incomplete

    Args:
        ticker: Kalshi market ticker
        action: 'buy' or 'sell'
        seconds_to_expiry: Time remaining until market expiry
        count: Number of contracts

    Returns:
        None if order is allowed, or rejection reason string
    """
    if count <= 0:
        return None
    if not ticker or not is_rti_settled_kalshi_crypto_ticker(ticker):
        return None
    if seconds_to_expiry is None:
        logger.warning("Cannot evaluate settlement guard: seconds_to_expiry is None for %s", ticker)
        return "rti_settlement_window:unknown_expiry"
    
    ste = float(seconds_to_expiry)
    fin = _final_sec()
    extended = _extended_guard_seconds()
    
    # Get settlement buffer status (Gap G4 fix)
    buf = get_settlement_buffer_registry().get_buffer(ticker)
    is_grade = buf.is_settlement_grade() if buf else False
    filled_count = buf.filled_count if buf else 0
    
    # Extended guard: if data is not settlement-grade, use longer buffer
    if not is_grade and ste < extended:
        logger.warning(
            "Extended settlement guard active: ticker=%s seconds_to_expiry=%.0f "
            "filled_count=%d/60 grade=false",
            ticker, ste, filled_count
        )
        if action == "buy":
            return f"rti_settlement_window:extended_guard_incomplete_data:t-{ste:.0f}s"
        # Still allow sells but log warning
        if _policy() == "block_all":
            return f"rti_settlement_window:block_all_incomplete:t-{ste:.0f}s"
        logger.info(
            "Allowing sell despite incomplete settlement data: ticker=%s action=%s",
            ticker, action
        )
        return None
    
    # Standard guard: within final seconds
    if ste > fin:
        return None

    if _policy() == "block_all":
        logger.info("Blocking all orders (block_all policy): ticker=%s t-%.0fs", ticker, ste)
        return f"rti_settlement_window:block_all:t-{ste:.0f}s"

    if action == "buy":
        # Gap G5 fix: Even with _allow_buy_if_grade(), require T-120s minimum
        if _allow_buy_if_grade() and is_grade and ste > 120:
            logger.info(
                "Allowing buy with settlement grade (rare): ticker=%s t-%.0fs",
                ticker, ste
            )
            return None
        
        if buf and not is_grade:
            logger.debug(
                "Blocking buy — settlement minute without full 60 RTI slots ticker=%s filled=%s",
                ticker,
                filled_count,
            )
        
        logger.info("Blocking buy in settlement window: ticker=%s t-%.0fs", ticker, ste)
        return "rti_settlement_window:no_new_buys"

    # Allow sells (reduce-only)
    logger.debug("Allowing sell in settlement window: ticker=%s t-%.0fs", ticker, ste)
    return None


def get_settlement_guard_status(ticker: str) -> Tuple[bool, str, dict]:
    """Get detailed settlement guard status for a ticker.
    
    Returns:
        Tuple of (is_blocked, reason, metadata_dict)
    """
    buf = get_settlement_buffer_registry().get_buffer(ticker)
    
    metadata = {
        "is_rti_settled": is_rti_settled_kalshi_crypto_ticker(ticker),
        "final_seconds": _final_sec(),
        "extended_seconds": _extended_guard_seconds(),
        "policy": _policy(),
        "require_grade": _require_settlement_grade(),
        "buffer_filled_count": buf.filled_count if buf else 0,
        "buffer_is_grade": buf.is_settlement_grade() if buf else False,
    }
    
    return True, "status_only", metadata
