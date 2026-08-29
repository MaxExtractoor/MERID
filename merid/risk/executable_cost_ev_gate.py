"""Executable-cost EV gate.

The gate is the sole entry authorization for new positions.  It rejects any
trade whose expected net value, after executable entry/exit costs, adverse-
selection and uncertainty reserves, is not positive, and it enforces a minimum
dollar EV and a minimum EV-to-tail-risk ratio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Literal, Optional, Tuple

from utils.logger import get_logger

from merid.config.live_config import get_resolved_live_config

logger = get_logger("merid.risk.executable_cost_ev_gate")


def _env_decimal(name: str, default: Decimal) -> Decimal:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return Decimal(val)
    except Exception:
        return default


@dataclass
class EVInput:
    """Inputs required for the executable-cost EV gate."""

    p_model: Decimal  # calibrated model probability of the selected side
    p_exec: Decimal  # executable entry price (premium per $1 notional)
    qty_cc: int  # intended quantity in centi-contracts
    entry_fee_per_contract: Decimal = Decimal("0")
    expected_exit_cost_per_contract: Decimal = Decimal("0")
    adverse_selection_reserve_per_contract: Decimal = Decimal("0")
    uncertainty_reserve_per_contract: Decimal = Decimal("0")
    quote_age_ms: Optional[int] = None
    quote_stale_threshold_ms: int = int(
        os.getenv("MERID_EV_GATE_STALE_QUOTE_MS", "10000")
    )
    ticker: str = ""
    decision_id: str = ""
    min_dollar_ev: Optional[Decimal] = None
    min_ev_to_tail_ratio: Optional[Decimal] = None


@dataclass
class EVResult:
    """Result of the executable-cost EV gate."""

    allowed: bool
    p_model: Decimal
    p_exec: Decimal
    qty_cc: int
    count: int
    gross_ev: Decimal
    expected_entry_fee: Decimal
    expected_exit_cost: Decimal
    adverse_selection_reserve: Decimal
    uncertainty_reserve: Decimal
    total_costs: Decimal
    net_ev: Decimal
    tail_risk: Decimal
    ev_to_tail_ratio: Optional[Decimal]
    min_dollar_ev: Decimal
    min_ev_to_tail_ratio: Decimal
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "p_model": str(self.p_model),
            "p_exec": str(self.p_exec),
            "qty_cc": self.qty_cc,
            "count": self.count,
            "gross_ev": str(self.gross_ev),
            "expected_entry_fee": str(self.expected_entry_fee),
            "expected_exit_cost": str(self.expected_exit_cost),
            "adverse_selection_reserve": str(self.adverse_selection_reserve),
            "uncertainty_reserve": str(self.uncertainty_reserve),
            "total_costs": str(self.total_costs),
            "net_ev": str(self.net_ev),
            "tail_risk": str(self.tail_risk),
            "ev_to_tail_ratio": str(self.ev_to_tail_ratio) if self.ev_to_tail_ratio is not None else None,
            "min_dollar_ev": str(self.min_dollar_ev),
            "min_ev_to_tail_ratio": str(self.min_ev_to_tail_ratio),
            "reasons": self.reasons,
        }


def _get_thresholds() -> Tuple[Decimal, Decimal]:
    """Return (min_dollar_ev, min_ev_to_tail_ratio).

    Priority: resolved live config > env > defaults.
    """
    min_dollar_ev = _env_decimal("MERID_EV_GATE_MIN_DOLLAR_EV", Decimal("0.0"))
    min_ev_to_tail_ratio = _env_decimal("MERID_EV_GATE_MIN_EV_TO_TAIL_RATIO", Decimal("0.0"))

    try:
        resolved = get_resolved_live_config(allow_unresolved=True)
        if resolved and resolved.resolved:
            if getattr(resolved, "min_ev_dollar", None) is not None:
                min_dollar_ev = Decimal(str(resolved.min_ev_dollar))
            if getattr(resolved, "min_ev_to_tail_ratio", None) is not None:
                min_ev_to_tail_ratio = Decimal(str(resolved.min_ev_to_tail_ratio))
    except Exception:
        pass

    return min_dollar_ev, min_ev_to_tail_ratio


def evaluate_executable_cost_ev(input: EVInput) -> EVResult:
    """Return the EV gate result for a single candidate decision.

    The gate never falls back to midpoint prices.  If ``p_exec`` is missing or
    the quote is stale, the trade is rejected.
    """
    reasons: List[str] = []

    if input.p_exec is None or not _is_finite_decimal(input.p_exec):
        return _rejected(input, reasons=["missing_executable_price"])

    if input.quote_age_ms is not None and input.quote_age_ms > input.quote_stale_threshold_ms:
        return _rejected(input, reasons=[f"stale_executable_price:age_ms={input.quote_age_ms}"])

    if input.qty_cc is None or input.qty_cc <= 0:
        return _rejected(input, reasons=["non_positive_quantity"])

    count = int(Decimal(input.qty_cc) / Decimal("100"))
    if count <= 0:
        return _rejected(input, reasons=["quantity_less_than_one_contract"])

    # Notional per contract is $1 for Kalshi binaries; total notional = count * $1.
    notional = Decimal(count)

    # Gross expected value = (p_model - p_exec) * notional.
    gross_ev = (input.p_model - input.p_exec) * notional

    # Cost stack.
    expected_entry_fee = input.entry_fee_per_contract * notional
    expected_exit_cost = input.expected_exit_cost_per_contract * notional
    adverse_selection_reserve = input.adverse_selection_reserve_per_contract * notional
    uncertainty_reserve = input.uncertainty_reserve_per_contract * notional
    total_costs = (
        expected_entry_fee
        + expected_exit_cost
        + adverse_selection_reserve
        + uncertainty_reserve
    )

    # Net EV after all costs.
    net_ev = gross_ev - total_costs

    # Tail risk = expected loss if wrong = (1 - p_model) * notional.
    # EV/tail-risk ratio caps tiny edges against large adverse outcomes.
    one = Decimal("1")
    tail_risk = (one - input.p_model) * notional
    ev_to_tail_ratio: Optional[Decimal] = None
    if tail_risk > Decimal("0"):
        ev_to_tail_ratio = (net_ev / tail_risk).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    min_dollar_ev, min_ev_to_tail_ratio = _get_thresholds()
    if input.min_dollar_ev is not None:
        min_dollar_ev = input.min_dollar_ev
    if input.min_ev_to_tail_ratio is not None:
        min_ev_to_tail_ratio = input.min_ev_to_tail_ratio

    allowed = True

    if net_ev <= min_dollar_ev:
        allowed = False
        reasons.append(
            f"net_ev_below_min_dollar:net_ev={net_ev:.6f}:min={min_dollar_ev}"
        )

    if ev_to_tail_ratio is not None and ev_to_tail_ratio < min_ev_to_tail_ratio:
        allowed = False
        reasons.append(
            f"ev_to_tail_ratio_below_min:ratio={ev_to_tail_ratio}:min={min_ev_to_tail_ratio}"
        )

    return EVResult(
        allowed=allowed,
        p_model=input.p_model,
        p_exec=input.p_exec,
        qty_cc=input.qty_cc,
        count=count,
        gross_ev=gross_ev.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        expected_entry_fee=expected_entry_fee.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        expected_exit_cost=expected_exit_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        adverse_selection_reserve=adverse_selection_reserve.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        uncertainty_reserve=uncertainty_reserve.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        total_costs=total_costs.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        net_ev=net_ev.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        tail_risk=tail_risk.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        ev_to_tail_ratio=ev_to_tail_ratio,
        min_dollar_ev=min_dollar_ev,
        min_ev_to_tail_ratio=min_ev_to_tail_ratio,
        reasons=reasons,
    )


def _rejected(input: EVInput, reasons: List[str]) -> EVResult:
    return EVResult(
        allowed=False,
        p_model=input.p_model,
        p_exec=input.p_exec,
        qty_cc=input.qty_cc,
        count=0,
        gross_ev=Decimal("0"),
        expected_entry_fee=Decimal("0"),
        expected_exit_cost=Decimal("0"),
        adverse_selection_reserve=Decimal("0"),
        uncertainty_reserve=Decimal("0"),
        total_costs=Decimal("0"),
        net_ev=Decimal("0"),
        tail_risk=Decimal("0"),
        ev_to_tail_ratio=None,
        min_dollar_ev=input.min_dollar_ev or _get_thresholds()[0],
        min_ev_to_tail_ratio=input.min_ev_to_tail_ratio or _get_thresholds()[1],
        reasons=reasons,
    )


def _is_finite_decimal(d: Decimal) -> bool:
    if d is None:
        return False
    return d.is_finite()


def evaluate_executable_cost_ev_from_record(
    record: "OrderDecisionRecord",
    *,
    min_dollar_ev: Optional[Decimal] = None,
    min_ev_to_tail_ratio: Optional[Decimal] = None,
) -> EVResult:
    """Evaluate the EV gate directly from an :class:`OrderDecisionRecord`."""
    from merid.execution.order_decision_schema import OrderDecisionRecord
    input = EVInput(
        p_model=record.p_selected or Decimal("0"),
        p_exec=Decimal(str(record.executable_price_cents)) / Decimal("100")
        if record.executable_price_cents is not None
        else Decimal("0"),
        qty_cc=record.intended_qty_cc or record.filled_qty_cc or 0,
        entry_fee_per_contract=record.entry_fee_per_contract,
        expected_exit_cost_per_contract=record.expected_exit_cost_per_contract,
        adverse_selection_reserve_per_contract=record.adverse_selection_reserve,
        uncertainty_reserve_per_contract=record.uncertainty_reserve,
        quote_age_ms=record.executable_price_age_ms,
        quote_stale_threshold_ms=int(os.getenv("MERID_EV_GATE_STALE_QUOTE_MS", "10000")),
        ticker=record.ticker,
        decision_id=record.decision_id,
        min_dollar_ev=min_dollar_ev,
        min_ev_to_tail_ratio=min_ev_to_tail_ratio,
    )
    return evaluate_executable_cost_ev(input)


def build_decision_record_from_ev(
    ev: EVResult,
    *,
    decision_id: str,
    run_id: str,
    ticker: str,
    asset: str,
    side: Literal["yes", "no"],
    quote_age_ms: Optional[int],
    **kwargs: Any,
) -> "OrderDecisionRecord":
    """Materialize an :class:`OrderDecisionRecord` from an EV gate result.

    This is the canonical bridge: the gate evaluates the economics, then the
    ledger records the decision before any order is submitted.
    """
    from datetime import datetime as _dt, timezone as _tz
    from merid.execution.order_decision_schema import OrderDecisionRecord

    record = OrderDecisionRecord(
        decision_id=decision_id,
        run_id=run_id,
        ticker=ticker,
        asset=asset,
        timestamp_utc=_dt.now(_tz),
        selected_side=side,
        executable_price_cents=int(ev.p_exec * Decimal("100")) if ev.p_exec.is_finite() else None,
        executable_price_age_ms=quote_age_ms,
        executable_price_stale=(quote_age_ms or 0) > int(
            os.getenv("MERID_EV_GATE_STALE_QUOTE_MS", "10000")
        ),
        p_selected=ev.p_model,
        net_ev=ev.net_ev,
        gross_ev=ev.gross_ev,
        expected_entry_fee=ev.expected_entry_fee,
        expected_exit_cost=ev.expected_exit_cost,
        adverse_selection_reserve=ev.adverse_selection_reserve,
        uncertainty_reserve=ev.uncertainty_reserve,
        tail_risk=ev.tail_risk,
        ev_to_tail_ratio=ev.ev_to_tail_ratio,
        min_dollar_ev=ev.min_dollar_ev,
        min_ev_to_tail_ratio=ev.min_ev_to_tail_ratio,
        intended_qty_cc=ev.qty_cc,
        entry_fee_per_contract=ev.expected_entry_fee / Decimal(ev.count) if ev.count > 0 else Decimal("0"),
        expected_exit_cost_per_contract=ev.expected_exit_cost / Decimal(ev.count) if ev.count > 0 else Decimal("0"),
        **kwargs,
    )
    return record
