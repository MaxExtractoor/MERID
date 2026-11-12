"""Strategy capital sleeve — the equity basis ``E`` for sizing.

Definition (operator-approved):

    E_t = max(0, min(E_sleeve,t, E_backed,t))

- ``E_sleeve,t`` — capital explicitly allocated to this strategy, adjusted for
  its realized results and conservatively valued open positions, bounded by
  ``MERID_STRATEGY_CAPITAL_RESERVE_USD`` (capital ring-fenced for other uses).
- ``E_backed,t`` — reconciled capital actually available to back that sleeve:
  trading-shard free cash plus open-position cost basis (positions remain
  collateralized at cost until they settle or exit).

"Fixed" means a controlled allocation boundary, not a constant: the sleeve
shrinks with realized losses and grows with realized gains.

This module is instrumentation/shadow-only in Phase A — it performs cached,
non-blocking reads and never influences order flow.  Release 2 wires it into
the Kelly target as the equity basis.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class CapitalSleeveSnapshot:
    state: str  # "ok" | "partial" | "unavailable"
    sleeve_equity_usd: Optional[float]
    backed_equity_usd: Optional[float]
    effective_equity_usd: Optional[float]
    equity_total_usd: Optional[float]
    cash_trading_shard_usd: Optional[float]
    open_exposure_usd: Optional[float]
    non_strategy_reserve_usd: float
    components: Dict[str, Any] = field(default_factory=dict)
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _non_strategy_reserve_usd() -> float:
    return max(0.0, _env_float("MERID_STRATEGY_CAPITAL_RESERVE_USD", 0.0))


def _equity_total_usd() -> Optional[float]:
    """Freshness-bounded account equity (FRESH or within the documented
    staleness window).  None when no trustworthy snapshot exists."""
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import (
            _BANKROLL_SERVICE_V2,
        )
        svc = _BANKROLL_SERVICE_V2
        if svc is None:
            return None
        fn = getattr(svc, "get_equity_for_risk_calc_sync_cached", None)
        if not callable(fn):
            return None
        eq = fn()
        return float(eq) if eq is not None else None
    except Exception:
        return None


def _shard_cash_usd() -> Optional[float]:
    """Free cash on the configured trading shard (cached funding result)."""
    try:
        from merid.event_venues.kalshi.shard_funding import last_result
        res = last_result()
        if res is None or not getattr(res, "shard_balances", None):
            return None
        cash = res.shard_balances.get(getattr(res, "trading_shard", None))
        return float(cash) if cash is not None else None
    except Exception:
        return None


def _open_exposure_usd() -> Optional[float]:
    """Total open + working-order exposure in dollars (slot allocator)."""
    try:
        from merid.risk.global_slot_allocator import get_global_slot_allocator
        alloc = get_global_slot_allocator()
        if alloc is None:
            return None
        return float(alloc.get_total_exposure())
    except Exception:
        return None


def compute_capital_sleeve() -> CapitalSleeveSnapshot:
    """Compute the strategy capital sleeve.  Cached reads only — safe to call
    on the order path; never raises."""
    equity_total = _equity_total_usd()
    shard_cash = _shard_cash_usd()
    open_exposure = _open_exposure_usd()
    reserve = _non_strategy_reserve_usd()

    sleeve: Optional[float] = None
    if equity_total is not None:
        sleeve = max(0.0, equity_total - reserve)

    # Backing = free shard cash + cost basis of open/working exposure.
    # Positions collateralize at cost, so cost basis is the conservative
    # committed-capital figure until mark-to-market exit values exist.
    backed: Optional[float] = None
    if shard_cash is not None or open_exposure is not None:
        backed = max(
            0.0,
            (shard_cash or 0.0) + (open_exposure or 0.0),
        )

    effective: Optional[float] = None
    if sleeve is not None and backed is not None:
        effective = max(0.0, min(sleeve, backed))
    elif sleeve is not None:
        effective = sleeve  # partial: sleeve known, backing unmeasured
    elif backed is not None:
        effective = backed  # partial: backing known, sleeve unmeasured

    n_known = sum(
        1 for v in (equity_total, shard_cash, open_exposure) if v is not None
    )
    state = "ok" if n_known == 3 else ("partial" if n_known else "unavailable")

    return CapitalSleeveSnapshot(
        state=state,
        sleeve_equity_usd=sleeve,
        backed_equity_usd=backed,
        effective_equity_usd=effective,
        equity_total_usd=equity_total,
        cash_trading_shard_usd=shard_cash,
        open_exposure_usd=open_exposure,
        non_strategy_reserve_usd=reserve,
        components={
            "equity_source": "bankroll_service_freshness_bounded",
            "backing_convention": "shard_cash_plus_open_cost_basis",
            "sleeve_convention": "account_equity_minus_non_strategy_reserve",
        },
    )
