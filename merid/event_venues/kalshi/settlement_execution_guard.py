"""Settlement Execution Guard — RTI settlement-window order filter.

Prevents buy orders from being placed on RTI-settled Kalshi crypto markets
during the settlement observation window, when prices converge to 0/100 and
execution quality collapses.

Usage::

    from merid.event_venues.kalshi.settlement_execution_guard import (
        evaluate_settlement_order,
        is_rti_settled_kalshi_crypto_ticker,
    )

    result = evaluate_settlement_order(intent)
    if not result.allowed:
        return OrderResult(status="rejected", reason=result.reason, ...)
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.settlement_execution_guard")

# Minutes before settlement at which we block new buy orders.
SETTLEMENT_BLOCK_MINUTES = float(
    os.getenv("MERID_SETTLEMENT_BLOCK_MINUTES", "5.0")
)

# RTI-settled crypto series prefixes / patterns.
# Covers: KXBTC*, KXETH*, KXSOL*, KXXRP*, KXDOGE* (and full-name variants).
_RTI_CRYPTO_PATTERN = re.compile(
    r"^KX(?:BTC|BITCOIN|ETH|ETHEREUM|SOL|SOLANA|XRP|RIPPLE|DOGE|DOGECOIN)\b",
    re.IGNORECASE,
)


def is_rti_settled_kalshi_crypto_ticker(ticker: str) -> bool:
    """Return True if *ticker* belongs to an RTI-settled Kalshi crypto series.

    Covers BTC, ETH, SOL, XRP, DOGE (and their full-name variants).

    Examples::

        is_rti_settled_kalshi_crypto_ticker("KXBTC-26MAR25-T95000")   # True
        is_rti_settled_kalshi_crypto_ticker("KXETH-D1-26MAR25-T3500") # True
        is_rti_settled_kalshi_crypto_ticker("KXXRP-26MAR2508-B1.59")  # True
        is_rti_settled_kalshi_crypto_ticker("INXD-23DEC24-10000")     # False
    """
    return bool(_RTI_CRYPTO_PATTERN.match(ticker.upper()))


@dataclass
class SettlementGuardResult:
    """Result from evaluate_settlement_order."""
    allowed: bool
    reason: Optional[str] = None


def evaluate_settlement_order(
    intent: object,
    now_ts: Optional[float] = None,
) -> SettlementGuardResult:
    """Evaluate whether *intent* should be allowed during a settlement window.

    Parameters
    ----------
    intent:
        An ``OrderIntent``-like object.  Must have at least:
        - ``ticker: str``
        - ``action: str``  (``"buy"`` | ``"sell"``)
        Optionally:
        - ``expires_ts: float``  UTC timestamp when the market settles.
          If absent the guard is a pass-through (no block).
    now_ts:
        Current UTC timestamp in seconds.  Defaults to ``time.time()``.

    Returns
    -------
    SettlementGuardResult
        ``allowed=True`` if the order may proceed; ``allowed=False`` with a
        ``reason`` string if it should be blocked.
    """
    ticker: str = getattr(intent, "ticker", "")
    action: str = getattr(intent, "action", "")
    expires_ts: Optional[float] = getattr(intent, "expires_ts", None)

    # Only applies to RTI-settled crypto tickers.
    if not is_rti_settled_kalshi_crypto_ticker(ticker):
        return SettlementGuardResult(allowed=True)

    # Only block *buy* orders (sells may help close positions near settlement).
    if action.lower() != "buy":
        return SettlementGuardResult(allowed=True)

    # If no expiry information is available, skip the block (fail-open).
    if expires_ts is None:
        return SettlementGuardResult(allowed=True)

    if now_ts is None:
        now_ts = time.time()

    minutes_to_expiry = (expires_ts - now_ts) / 60.0
    if 0 <= minutes_to_expiry <= SETTLEMENT_BLOCK_MINUTES:
        reason = (
            f"settlement_window_block:{ticker}:"
            f"expires_in_{minutes_to_expiry:.1f}m"
        )
        logger.warning(
            "[settlement-guard] Blocking BUY on %s — %.1f min to settlement "
            "(block window %.0f min)",
            ticker,
            minutes_to_expiry,
            SETTLEMENT_BLOCK_MINUTES,
        )
        return SettlementGuardResult(allowed=False, reason=reason)

    return SettlementGuardResult(allowed=True)
