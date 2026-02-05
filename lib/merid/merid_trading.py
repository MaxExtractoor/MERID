"""DEPRECATED / UNUSED - Not integrated into main system

Compatibility shim to expose local trading module to ensure trading imports work correctly.

This avoids conflicts with an existing top-level `trading` package in the repo
root during local tests and CI. We load the local module files directly to
ensure the correct implementation is used.
"""

import importlib.util
import os
from typing import Any

ROOT = os.path.dirname(__file__)

def _load_module_from_path(name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    return module

# Prepare a placeholder so dataclass and other module-level machinery can
# find a module object at 'trading.risk' during module execution.
import sys
import types
if "trading" not in sys.modules:
    sys.modules["trading"] = types.ModuleType("trading")
if "trading.risk" not in sys.modules:
    sys.modules["trading.risk"] = types.ModuleType("trading.risk")

_risk_mod = _load_module_from_path("merid_trading.risk", os.path.join(ROOT, "trading", "risk.py"))
# Replace placeholder with the real loaded module
sys.modules["trading.risk"] = _risk_mod
sys.modules["merid_trading.risk"] = _risk_mod

_exec_mod = _load_module_from_path("merid_trading.execution", os.path.join(ROOT, "trading", "execution.py"))
# also map execution for other importers
sys.modules["trading.execution"] = _exec_mod
sys.modules["merid_trading.execution"] = _exec_mod

place_order = _exec_mod.place_order
cancel_order = _exec_mod.cancel_order
modify_order = _exec_mod.modify_order
ExecutionError = _exec_mod.ExecutionError

pre_trade_check = _risk_mod.pre_trade_check
CircuitBreaker = _risk_mod.CircuitBreaker

__all__ = ["place_order", "cancel_order", "modify_order", "ExecutionError", "pre_trade_check", "CircuitBreaker"]
