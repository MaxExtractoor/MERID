"""Trading package exports for core execution components."""

from __future__ import annotations

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

# PEP 562 lazy loading: trading.execution (and its transitive deps) are
# heavy and pull in core/agents/neo4j.  We defer those imports until a
# consumer actually requests one of these symbols, so that lightweight
# submodules like trading.trade_mode can be imported without triggering
# the full dependency chain.

_EXECUTION_NAMES = frozenset(__all__)


def __getattr__(name: str):  # noqa: N807
    if name not in _EXECUTION_NAMES:
        raise AttributeError(f"module 'trading' has no attribute {name!r}")
    from trading.execution import (  # noqa: F401
        ExecutionEngine as _ExecutionEngine,
        ExecutionConfig as _ExecutionConfig,
        ExecutionMode as _ExecutionMode,
        Order as _Order,
        OrderSide as _OrderSide,
        OrderType as _OrderType,
        OrderStatus as _OrderStatus,
        Position as _Position,
        PositionSide as _PositionSide,
        ExecutionError as _ExecutionError,
        InsufficientFundsError as _InsufficientFundsError,
        PositionLimitError as _PositionLimitError,
        OrderRejectedError as _OrderRejectedError,
    )
    import sys as _sys
    _exports = {
        "ExecutionEngine": _ExecutionEngine,
        "ExecutionConfig": _ExecutionConfig,
        "ExecutionMode": _ExecutionMode,
        "Order": _Order,
        "OrderSide": _OrderSide,
        "OrderType": _OrderType,
        "OrderStatus": _OrderStatus,
        "Position": _Position,
        "PositionSide": _PositionSide,
        "ExecutionError": _ExecutionError,
        "InsufficientFundsError": _InsufficientFundsError,
        "PositionLimitError": _PositionLimitError,
        "OrderRejectedError": _OrderRejectedError,
    }
    _mod = _sys.modules[__name__]
    for _k, _v in _exports.items():
        setattr(_mod, _k, _v)
    return _exports[name]
