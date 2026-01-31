"""Execution package exports (core engine + advanced components)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from trading.execution.optimal import (
    get_optimal_executor,
    OptimalExecutionEngine,
    ExecutionStrategy,
    AlmgrenChriss,
    VWAP,
    TWAP,
)

from trading.execution.defense import (
    get_mev_defense,
    MEVDefenseEngine,
    ManipulationDetector,
)

_CORE_MODULE_NAME = "trading._execution_core"
_CORE_MODULE_PATH = Path(__file__).resolve().parents[1] / "execution.py"
_core_spec = importlib.util.spec_from_file_location(_CORE_MODULE_NAME, _CORE_MODULE_PATH)
if _core_spec is None or _core_spec.loader is None:  # pragma: no cover - defensive
    raise ImportError("Unable to locate trading.execution core implementation")

_core_module = importlib.util.module_from_spec(_core_spec)
sys.modules.setdefault(_CORE_MODULE_NAME, _core_module)
_core_spec.loader.exec_module(_core_module)

ExecutionEngine = _core_module.ExecutionEngine
ExecutionConfig = _core_module.ExecutionConfig
ExecutionMode = _core_module.ExecutionMode
Order = _core_module.Order
OrderSide = _core_module.OrderSide
OrderType = _core_module.OrderType
OrderStatus = _core_module.OrderStatus
Position = _core_module.Position
PositionSide = _core_module.PositionSide
ExecutionError = _core_module.ExecutionError
InsufficientFundsError = _core_module.InsufficientFundsError
PositionLimitError = _core_module.PositionLimitError
OrderRejectedError = _core_module.OrderRejectedError
_is_abort_action = _core_module._is_abort_action
_is_high_threat = _core_module._is_high_threat

__all__ = [
    # Core execution engine
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
    "_is_abort_action",
    "_is_high_threat",
    # Optimal execution helpers
    "get_optimal_executor",
    "OptimalExecutionEngine",
    "ExecutionStrategy",
    "AlmgrenChriss",
    "VWAP",
    "TWAP",
    # Defense components
    "get_mev_defense",
    "MEVDefenseEngine",
    "ManipulationDetector",
]
