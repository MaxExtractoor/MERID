"""Risk utilities for pre-trade validation and a simple circuit breaker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


def pre_trade_check(
    order: dict,
    account: dict,
    portfolio_limits: Optional[dict] = None,
    projected_loss: float = 0.0,
    current_day_loss: float = 0.0,
    open_orders: int = 0,
) -> Tuple[bool, str]:
    """Perform pre-trade checks.

    Extended checks now support optional `portfolio_limits` to enforce:
      - max_daily_loss (projected + current > max -> block)
      - per-portfolio max_notional (absolute)
      - max_open_orders

    Backwards-compatible behavior: if `portfolio_limits` is None we fall back
    to the previous account-level `max_notional_pct` check.
    """
    qty = order.get("quantity")
    if qty is None or qty <= 0:
        return False, "invalid quantity"

    price = order.get("price") or 0
    if price is not None and price < 0:
        return False, "invalid price"

    balance = account.get("balance", 0)

    # Account-level notional (backwards-compatible)
    max_notional_account = account.get("max_notional_pct", 0.5) * balance
    if price and qty * price > max_notional_account and not portfolio_limits:
        return False, "notional exceeds account limits"

    # Portfolio-level checks (if provided)
    if portfolio_limits:
        max_notional = portfolio_limits.get("max_notional")
        if max_notional and price and qty * price > max_notional:
            return False, "notional exceeds portfolio limits"

        max_daily_loss = portfolio_limits.get("max_daily_loss")
        if max_daily_loss is not None and (current_day_loss + projected_loss) > max_daily_loss:
            return False, "would exceed daily loss"

        max_open_orders = portfolio_limits.get("max_open_orders")
        if max_open_orders is not None and (open_orders + 1) > max_open_orders:
            return False, "max open orders exceeded"

    # Hard cap to avoid runaway tests: 1,000,000 units
    if qty > 1_000_000:
        return False, "quantity exceeds absolute cap"

    return True, "ok"


class CircuitBreaker:
    """Simple circuit breaker that can be tripped programmatically.

    This class stores state in class-level attributes for simplicity. In a
    distributed setting, this should be backed by a shared store (Redis).
    """

    _tripped = False
    _error_count = 0
    _threshold = 5

    @classmethod
    def is_tripped(cls) -> bool:
        return cls._tripped

    @classmethod
    def trip(cls) -> None:
        cls._tripped = True

    @classmethod
    def reset(cls) -> None:
        cls._tripped = False
        cls._error_count = 0

    @classmethod
    def record_error(cls) -> None:
        cls._error_count += 1
        if cls._error_count >= cls._threshold:
            cls._tripped = True

    @classmethod
    def status(cls) -> dict:
        return {"tripped": cls._tripped, "errors": cls._error_count, "threshold": cls._threshold}
