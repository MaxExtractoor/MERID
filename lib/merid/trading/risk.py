"""Risk utilities for pre-trade validation and a simple circuit breaker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


def pre_trade_check(order: dict, account: dict) -> Tuple[bool, str]:
    """Perform basic pre-trade checks.

    Current checks:
      - quantity > 0
      - price > 0 (if provided)
      - notional (qty * price) <= max_notional (default 50% of account balance)
    """
    qty = order.get("quantity")
    if qty is None or qty <= 0:
        return False, "invalid quantity"

    price = order.get("price") or 0
    if price is not None and price < 0:
        return False, "invalid price"

    balance = account.get("balance", 0)
    max_notional = account.get("max_notional_pct", 0.5) * balance
    if price and qty * price > max_notional:
        return False, "notional exceeds account limits"

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
