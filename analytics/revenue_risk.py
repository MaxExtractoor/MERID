"""Revenue-at-risk analytics helpers for onboarding and ARR monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class FxAdjustedARR:
    """ARR contribution for a currency converted to USD."""

    currency: str
    arr_local: float
    fx_rate_to_usd: float

    @property
    def arr_usd(self) -> float:
        return self.arr_local * self.fx_rate_to_usd


@dataclass(frozen=True)
class ContractEvent:
    """Represents ARR deltas from churn, downgrades, or expansions."""

    account_id: str
    delta_arr_usd: float
    reason: str


@dataclass(frozen=True)
class RevenueRiskIncident:
    """Structured report returned to CI when ARR risk crosses thresholds."""

    flagged: bool
    arr_at_risk_usd: float
    reason: str
    breakdown: Dict[str, float]


def _compute_fx_risk(entries: Sequence[FxAdjustedARR], fx_shock_pct: float) -> float:
    total_usd = sum(entry.arr_usd for entry in entries)
    fx_shock_pct = max(0.0, fx_shock_pct)
    return total_usd * fx_shock_pct


def _compute_contract_loss(events: Sequence[ContractEvent]) -> float:
    return sum(max(0.0, -event.delta_arr_usd) for event in events)


def compute_revenue_at_risk(
    fx_adjusted: Sequence[FxAdjustedARR],
    *,
    churn_events: Sequence[ContractEvent],
    fx_shock_pct: float,
    threshold_usd: float,
) -> RevenueRiskIncident:
    """Aggregate ARR-at-risk across FX shocks and churn/downgrades."""

    fx_loss = _compute_fx_risk(fx_adjusted, fx_shock_pct)
    contract_loss = _compute_contract_loss(churn_events)
    arr_at_risk = fx_loss + contract_loss

    breakdown = {
        "fx_shock": fx_loss,
        "contract_events": contract_loss,
    }
    reason_parts: List[str] = []
    if fx_loss:
        reason_parts.append("fx_shock")
    if contract_loss:
        reason_parts.append("contract_events")
    reason = "_and_".join(reason_parts) or "none"

    flagged = arr_at_risk >= threshold_usd
    return RevenueRiskIncident(
        flagged=flagged,
        arr_at_risk_usd=arr_at_risk,
        reason=reason,
        breakdown=breakdown,
    )
