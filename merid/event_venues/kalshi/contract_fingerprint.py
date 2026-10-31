"""Contract-semantics and execution-metadata fingerprints for Kalshi markets.

Binds each approved order intent to the exact market proposition and trading
constraints it was approved against, so a material exchange-metadata change
invalidates stale approvals instead of silently reinterpreting them.

Two related fingerprints (per the audit spec):

- ``contract_semantics_hash``: covers the rules/payout proposition the model
  forecast — primary/secondary rules text, settlement source, result/timing
  semantics that define *what* the contract pays on.
- ``execution_metadata_version``: covers current trading constraints —
  status, close/expiration timing, and the price-grid (``price_ranges``)
  applicable to new orders.

Volatile market fields (bid/ask/last price, volume, open interest, status
counters) are deliberately excluded: hashing them would invalidate approvals
on every tick.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Tuple


# Fields that define the contract proposition (what is being forecast).
_SEMANTIC_FIELDS = (
    "rules_primary",
    "rules_secondary",
    "settlement_source",
    "settlement_source_url",
    "result",
    "primary_contract",
    "category",
    "series_ticker",
    "event_ticker",
    "strike_type",
    "floor_strike",
    "cap_strike",
    "custom_strike",
    "functional_strike",
    "markets",  # range-bound market legs, when present
    "mve_collection_ticker",
    "mve_selected_legs",
)

# Fields that define current trading constraints (how/when it can trade).
_EXECUTION_FIELDS = (
    "status",
    "close_time",
    "expiration_time",
    "expected_expiration_time",
    "latest_expiration_time",
    "price_ranges",
    "price_level_structure",
    "tick_size",
    "open_time",
    "settlement_timer_seconds",
    "fee_waiver_expiration_time_ms",
    "fee_type",
    "fee_multiplier",
)


def _stable(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def compute_contract_fingerprints(
    market: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(contract_semantics_hash, execution_metadata_version)``.

    Both are 16-hex-char digests of the canonical JSON projection of the
    relevant market fields, or ``(None, None)`` when no market metadata is
    available.  ``None`` means "unverified", never "verified" — callers must
    not treat a missing fingerprint as a match.
    """
    if not market or not isinstance(market, dict):
        return None, None

    semantics = {k: market.get(k) for k in _SEMANTIC_FIELDS if market.get(k) is not None}
    execution = {k: market.get(k) for k in _EXECUTION_FIELDS if market.get(k) is not None}

    sem_hash = (
        hashlib.sha256(_stable(semantics).encode("utf-8")).hexdigest()[:16]
        if semantics
        else None
    )
    exec_ver = (
        hashlib.sha256(_stable(execution).encode("utf-8")).hexdigest()[:16]
        if execution
        else None
    )
    return sem_hash, exec_ver


def fingerprints_match(
    approved: Tuple[Optional[str], Optional[str]],
    current: Tuple[Optional[str], Optional[str]],
) -> bool:
    """True only when both fingerprints are present AND equal on both sides.

    A missing fingerprint on either side is a mismatch — fail closed.
    """
    a_sem, a_exec = approved
    c_sem, c_exec = current
    if not a_sem or not a_exec or not c_sem or not c_exec:
        return False
    return a_sem == c_sem and a_exec == c_exec
