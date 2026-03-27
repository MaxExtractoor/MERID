"""Swarm Orchestrator — per-symbol sizing guardrails.

Defines SYMBOL_LIMITS, the authoritative per-asset dictionary that enforces
maximum fractional Kelly usage (max_f_used) and maximum contract count
(max_size_contracts) for each tradable crypto asset on Kalshi.

Gap S-1 addressed: DOGE was previously absent from SYMBOL_LIMITS, allowing
DOGE proposals to bypass the max_f_used and max_size_contracts guardrails
entirely.  DOGE is now included with conservative limits.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.swarm.orchestrator")

# ── Per-symbol sizing guardrails ─────────────────────────────────────────────
#
# max_f_used        : maximum fraction of Kelly-optimal stake (0–1).
#                     Lower values produce more conservative sizing.
# max_size_contracts: hard cap on contracts per order for this asset.
#
# All five Kalshi crypto assets MUST be represented here.  CI enforces:
#     assert set(SYMBOL_LIMITS) >= {"BTC", "ETH", "SOL", "XRP", "DOGE"}
#
SYMBOL_LIMITS: Dict[str, Dict[str, Any]] = {
    "BTC": {"max_f_used": 0.25, "max_size_contracts": 500},
    "ETH": {"max_f_used": 0.25, "max_size_contracts": 500},
    "SOL": {"max_f_used": 0.20, "max_size_contracts": 300},
    "XRP": {"max_f_used": 0.20, "max_size_contracts": 300},
    # S-1 fix: DOGE was missing; added with conservative limits given higher
    # per-contract variance and lower liquidity relative to BTC/ETH.
    "DOGE": {"max_f_used": 0.20, "max_size_contracts": 300},
}

_REQUIRED_ASSETS = frozenset(SYMBOL_LIMITS)


def get_symbol_limits(symbol: str) -> Optional[Dict[str, Any]]:
    """Return the sizing guardrails for *symbol*, or ``None`` if unrecognised.

    Parameters
    ----------
    symbol:
        Asset symbol, e.g. ``"BTC"``, ``"DOGE"``.  Case-insensitive.
    """
    return SYMBOL_LIMITS.get(symbol.upper())


def check_symbol_limits(symbol: str, f_used: float, contracts: int) -> tuple[bool, str]:
    """Validate a proposed order against SYMBOL_LIMITS guardrails.

    Parameters
    ----------
    symbol:
        Asset symbol.
    f_used:
        Fractional Kelly stake being applied (0–1).
    contracts:
        Number of contracts in the proposed order.

    Returns
    -------
    tuple[bool, str]
        ``(allowed, reason)`` where *reason* is an empty string when allowed.
    """
    limits = get_symbol_limits(symbol)
    if limits is None:
        return False, f"symbol_not_in_limits:{symbol}"

    if f_used > limits["max_f_used"]:
        return False, (
            f"f_used_exceeds_limit:{symbol}:"
            f"requested={f_used:.3f},max={limits['max_f_used']:.3f}"
        )

    if contracts > limits["max_size_contracts"]:
        return False, (
            f"contracts_exceeds_limit:{symbol}:"
            f"requested={contracts},max={limits['max_size_contracts']}"
        )

    return True, ""
