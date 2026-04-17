"""Trading package exports for core execution components."""

from __future__ import annotations

# Lazy imports to avoid Neo4j dependency chain at import time
_imports_done = False
_exports = {}

def _ensure_imports():
    """Lazy import heavy modules on first access."""
    global _imports_done, _exports
    if _imports_done:
        return
    
    # Import directly from submodules to avoid circular imports
    # when trading.execution.defense is being loaded
    from trading.execution.core import (
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
    
    _exports.update({
        "ExecutionEngine": ExecutionEngine,
        "ExecutionConfig": ExecutionConfig,
        "ExecutionMode": ExecutionMode,
        "Order": Order,
        "OrderSide": OrderSide,
        "OrderType": OrderType,
        "OrderStatus": OrderStatus,
        "Position": Position,
        "PositionSide": PositionSide,
        "ExecutionError": ExecutionError,
        "InsufficientFundsError": InsufficientFundsError,
        "PositionLimitError": PositionLimitError,
        "OrderRejectedError": OrderRejectedError,
    })
    _imports_done = True

def __getattr__(name: str):
    """Lazy import on first attribute access."""
    if name.startswith("_"):
        raise AttributeError(f"module has no attribute '{name}'")
    
    _ensure_imports()
    if name in _exports:
        return _exports[name]
    raise AttributeError(f"cannot import '{name}' from 'trading'")

def __dir__():
    """Return list of available exports."""
    return list(__all__)

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
