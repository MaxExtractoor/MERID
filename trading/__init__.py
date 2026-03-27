"""Trading package exports for core execution components."""

from __future__ import annotations

try:
    from trading.execution import (  # noqa: F401
        ExecutionEngine,
        ExecutionConfig,
        ExecutionMode,
        Order,
        OrderSide,
        OrderType,
        OrderStatus,
        Position,
        PositionSide,
        ExecutionError,
        InsufficientFundsError,
        PositionLimitError,
        OrderRejectedError,
    )
except Exception:  # pragma: no cover — guard against complex import chains
    pass

__all__ = [
    "ExecutionEngine",
    "ExecutionConfig",
    "ExecutionMode",
    "Order",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "Position",
    "PositionSide",
    "ExecutionError",
    "InsufficientFundsError",
    "PositionLimitError",
    "OrderRejectedError",
]
