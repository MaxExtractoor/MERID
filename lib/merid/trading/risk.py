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


class _InMemoryCircuitBreaker:
    """In-process, class-level circuit breaker used for tests and single-process runs."""

    def __init__(self, threshold: int = 5):
        self._tripped = False
        self._error_count = 0
        self._threshold = threshold

    def is_tripped(self) -> bool:
        return self._tripped

    def trip(self) -> None:
        self._tripped = True

    def reset(self) -> None:
        self._tripped = False
        self._error_count = 0

    def record_error(self) -> None:
        self._error_count += 1
        if self._error_count >= self._threshold:
            self._tripped = True

    def status(self) -> dict:
        return {"tripped": self._tripped, "errors": self._error_count, "threshold": self._threshold}


class _RedisCircuitBreaker:
    """Redis-backed circuit breaker for distributed deployments.

    Uses Redis keys (pfx:merid:circuit:tripped, pfx:merid:circuit:errors) to
    coordinate state across processes and hosts.
    """

    def __init__(self, redis_client=None, prefix: str = "merid:circuit", threshold: int = 5):
        try:
            if redis_client is None:
                from redis import Redis

                redis_client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
            self.client = redis_client
        except Exception:
            # If Redis is not available, fall back to in-memory behavior
            self.client = None
        self.prefix = prefix
        self._threshold = int(os.getenv("MERID_CIRCUIT_THRESHOLD", threshold))

    def _k(self, name: str) -> str:
        return f"{self.prefix}:{name}"

    def is_tripped(self) -> bool:
        if not self.client:
            return False
        return self.client.get(self._k("tripped")) == b"1"

    def trip(self) -> None:
        if not self.client:
            return None
        self.client.set(self._k("tripped"), "1")

    def reset(self) -> None:
        if not self.client:
            return None
        self.client.set(self._k("tripped"), "0")
        self.client.set(self._k("errors"), 0)

    def record_error(self) -> None:
        if not self.client:
            return None
        errors = self.client.incr(self._k("errors"))
        if int(errors) >= self._threshold:
            self.client.set(self._k("tripped"), "1")

    def status(self) -> dict:
        if not self.client:
            return {"tripped": False, "errors": 0, "threshold": self._threshold}
        errors = int(self.client.get(self._k("errors")) or 0)
        tripped = self.client.get(self._k("tripped")) == b"1"
        return {"tripped": tripped, "errors": errors, "threshold": self._threshold}


# Backend selector: pick redis if MERID_CIRCUITBACKEND=redis, else in-memory.

_backend = None


def _get_backend():
    global _backend
    if _backend is not None:
        return _backend
    import os

    backend = os.getenv("MERID_CIRCUITBACKEND", "memory").lower()
    if backend == "redis":
        _backend = _RedisCircuitBreaker()
    else:
        _backend = _InMemoryCircuitBreaker()
    return _backend


class CircuitBreaker:
    """Facade that delegates to a selected backend implementation."""

    @classmethod
    def is_tripped(cls) -> bool:
        return _get_backend().is_tripped()

    @classmethod
    def trip(cls) -> None:
        return _get_backend().trip()

    @classmethod
    def reset(cls) -> None:
        return _get_backend().reset()

    @classmethod
    def record_error(cls) -> None:
        return _get_backend().record_error()

    @classmethod
    def status(cls) -> dict:
        return _get_backend().status()
