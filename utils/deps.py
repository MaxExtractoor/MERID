"""Dependency availability helpers for MERID."""

from __future__ import annotations

from importlib import import_module
from functools import lru_cache
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("utils.deps")


@lru_cache(maxsize=None)
def _import_dependency(module_name: str) -> Optional[object]:
    """Best-effort import with caching.

    Returns imported module or ``None`` when unavailable.
    """

    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        logger.debug("Dependency '%s' is not installed", module_name)
        return None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Failed to import dependency '%s': %s", module_name, exc)
        return None


def optional_dependency(module_name: str) -> Optional[object]:
    """Return the module if available, otherwise ``None``."""

    return _import_dependency(module_name)


def dependency_available(module_name: str) -> bool:
    """Check whether a module can be imported."""

    return optional_dependency(module_name) is not None


def require_dependency(module_name: str, *, feature: str = "") -> object:
    """Ensure a dependency is present, raising RuntimeError otherwise."""

    module = optional_dependency(module_name)
    if module is None:
        hint = f"pip install {module_name}"
        prefix = f"{feature} requires {module_name}. " if feature else ""
        raise RuntimeError(f"{prefix}Install the dependency via `{hint}` and restart MERID.")
    return module


def dependency_report() -> Dict[str, bool]:
    """Return a terse availability report for dashboard/API consumption."""

    monitored = [
        "ccxt",
        "torch",
        "gymnasium",
        "networkx",
        "email_validator",
    ]
    return {name: dependency_available(name) for name in monitored}


def get_ccxt() -> Optional[object]:
    """Return the ccxt module if available."""

    return optional_dependency("ccxt")


def get_ccxt_async() -> Optional[object]:
    """Return the async ccxt module if available."""

    return optional_dependency("ccxt.async_support")


def torch_available() -> bool:
    return dependency_available("torch")


def gym_available() -> bool:
    return dependency_available("gymnasium")


def networkx_available() -> bool:
    return dependency_available("networkx")
