"""
Order Sanity Check — pre-execution guard for order size limits.

Rejects orders that exceed:
- Max single order as % of portfolio (default: 10%)
- Max single order absolute notional (default: $10,000)
- Max daily order count (default: 500)
- Min order size (default: $1)

Readiness Impact: S9-02 hardening — "Add a pre-execution sanity check:
reject orders > X% of portfolio or > Y notional."
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.order_sanity_check")


@dataclass
class OrderSanityConfig:
    """Configuration for order sanity checks."""
    max_order_pct_of_portfolio: float = 0.10  # 10% of portfolio
    max_order_notional_usd: float = 10_000.0  # $10K absolute cap
    min_order_notional_usd: float = 1.0  # $1 minimum
    max_daily_order_count: int = 500
    max_order_notional_per_symbol_usd: float = 25_000.0  # per-symbol daily cap


@dataclass
class SanityCheckResult:
    """Result of a pre-execution sanity check."""
    passed: bool
    violations: List[Dict[str, Any]] = field(default_factory=list)
    order_notional_usd: float = 0.0
    order_pct_of_portfolio: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": self.violations,
            "order_notional_usd": round(self.order_notional_usd, 2),
            "order_pct_of_portfolio": round(self.order_pct_of_portfolio, 4),
        }


class OrderSanityChecker:
    """Pre-execution order sanity checker.

    Call check() before every order submission. Maintains daily counters
    for order count and per-symbol notional tracking.
    """

    def __init__(self, config: Optional[OrderSanityConfig] = None):
        self.config = config or OrderSanityConfig()
        self._daily_order_count: int = 0
        self._daily_symbol_notional: Dict[str, float] = {}
        self._last_reset_day: str = ""
        self._check_count: int = 0
        self._reject_count: int = 0

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters at day boundary."""
        today = time.strftime("%Y-%m-%d")
        if today != self._last_reset_day:
            self._daily_order_count = 0
            self._daily_symbol_notional.clear()
            self._last_reset_day = today

    def check(
        self,
        symbol: str,
        quantity: float,
        price: float,
        portfolio_value: float,
        side: str = "buy",
    ) -> SanityCheckResult:
        """Run all sanity checks on a proposed order.

        Args:
            symbol: Instrument symbol (e.g. "BTC/USDT")
            quantity: Order quantity (units)
            price: Order price per unit (USD)
            portfolio_value: Current total portfolio value (USD)
            side: "buy" or "sell"

        Returns:
            SanityCheckResult with pass/fail and violation details.
        """
        self._maybe_reset_daily()
        self._check_count += 1

        violations: List[Dict[str, Any]] = []
        notional = abs(quantity * price)

        # 1. Max order as % of portfolio
        pct = notional / portfolio_value if portfolio_value > 0 else 1.0
        if pct > self.config.max_order_pct_of_portfolio:
            violations.append({
                "check": "max_order_pct_of_portfolio",
                "limit": self.config.max_order_pct_of_portfolio,
                "actual": round(pct, 4),
                "message": (
                    f"Order is {pct:.1%} of portfolio "
                    f"(limit: {self.config.max_order_pct_of_portfolio:.0%})"
                ),
            })

        # 2. Max absolute notional
        if notional > self.config.max_order_notional_usd:
            violations.append({
                "check": "max_order_notional_usd",
                "limit": self.config.max_order_notional_usd,
                "actual": round(notional, 2),
                "message": (
                    f"Order notional ${notional:,.2f} exceeds "
                    f"limit ${self.config.max_order_notional_usd:,.2f}"
                ),
            })

        # 3. Min order notional
        if notional < self.config.min_order_notional_usd:
            violations.append({
                "check": "min_order_notional_usd",
                "limit": self.config.min_order_notional_usd,
                "actual": round(notional, 4),
                "message": (
                    f"Order notional ${notional:.4f} below "
                    f"minimum ${self.config.min_order_notional_usd:.2f}"
                ),
            })

        # 4. Daily order count
        if self._daily_order_count >= self.config.max_daily_order_count:
            violations.append({
                "check": "max_daily_order_count",
                "limit": self.config.max_daily_order_count,
                "actual": self._daily_order_count,
                "message": (
                    f"Daily order count {self._daily_order_count} "
                    f"reached limit {self.config.max_daily_order_count}"
                ),
            })

        # 5. Per-symbol daily notional
        symbol_total = self._daily_symbol_notional.get(symbol, 0.0) + notional
        if symbol_total > self.config.max_order_notional_per_symbol_usd:
            violations.append({
                "check": "max_order_notional_per_symbol_usd",
                "limit": self.config.max_order_notional_per_symbol_usd,
                "actual": round(symbol_total, 2),
                "message": (
                    f"Daily notional for {symbol} would be ${symbol_total:,.2f} "
                    f"(limit: ${self.config.max_order_notional_per_symbol_usd:,.2f})"
                ),
            })

        # 6. Zero/negative quantity
        if quantity <= 0:
            violations.append({
                "check": "positive_quantity",
                "limit": ">0",
                "actual": quantity,
                "message": f"Order quantity must be positive, got {quantity}",
            })

        # 7. Zero/negative price
        if price <= 0:
            violations.append({
                "check": "positive_price",
                "limit": ">0",
                "actual": price,
                "message": f"Order price must be positive, got {price}",
            })

        passed = len(violations) == 0

        if passed:
            # Update daily counters only on pass
            self._daily_order_count += 1
            self._daily_symbol_notional[symbol] = (
                self._daily_symbol_notional.get(symbol, 0.0) + notional
            )
        else:
            self._reject_count += 1
            logger.warning(
                "Order rejected by sanity check: %s %s %.4f @ %.2f — %d violations",
                side, symbol, quantity, price, len(violations),
            )

        return SanityCheckResult(
            passed=passed,
            violations=violations,
            order_notional_usd=notional,
            order_pct_of_portfolio=pct,
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Return sanity checker metrics."""
        self._maybe_reset_daily()
        return {
            "total_checks": self._check_count,
            "total_rejects": self._reject_count,
            "reject_rate": (
                self._reject_count / self._check_count
                if self._check_count > 0
                else 0.0
            ),
            "daily_order_count": self._daily_order_count,
            "daily_symbol_notionals": dict(self._daily_symbol_notional),
            "config": {
                "max_order_pct_of_portfolio": self.config.max_order_pct_of_portfolio,
                "max_order_notional_usd": self.config.max_order_notional_usd,
                "min_order_notional_usd": self.config.min_order_notional_usd,
                "max_daily_order_count": self.config.max_daily_order_count,
                "max_order_notional_per_symbol_usd": self.config.max_order_notional_per_symbol_usd,
            },
        }


# Singleton
_checker: Optional[OrderSanityChecker] = None


def get_order_sanity_checker() -> OrderSanityChecker:
    """Get the singleton order sanity checker."""
    global _checker
    if _checker is None:
        _checker = OrderSanityChecker()
    return _checker
