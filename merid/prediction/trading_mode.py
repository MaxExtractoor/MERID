"""Canonical TradingMode enum for MERID Kalshi venue stack.

This module provides the single source of truth for trading mode enumeration
across the entire codebase. All other mode types (TradeMode, venue_gate.TradingMode,
etc.) must be converted to this canonical enum at module boundaries.

Usage::

    from merid.prediction.trading_mode import TradingMode, resolve_trading_mode

    # Canonical enum
    mode = TradingMode.LIVE

    # Convert from legacy types
    mode = resolve_trading_mode(some_legacy_mode)

Design (per behavior contract):
- Exactly one canonical TradingMode enum used end-to-end
- Explicit mapping from legacy values/strings at the perimeter
- Router never "guesses" the mode; receives TradingMode or derives from single source
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union


class TradingMode(str, Enum):
    """Canonical trading mode for MERID Kalshi venue stack.

    Invariants:
    - LIVE: Real money execution against Kalshi production API
    - PAPER: Simulated execution with real market data
    - MOCK: Fully synthetic execution for testing
    """
    LIVE = "live"
    PAPER = "paper"
    MOCK = "mock"

    def is_live(self) -> bool:
        """True if this is live trading mode."""
        return self == TradingMode.LIVE

    def is_paper(self) -> bool:
        """True if this is paper trading mode."""
        return self == TradingMode.PAPER

    def is_mock(self) -> bool:
        """True if this is mock trading mode."""
        return self == TradingMode.MOCK

    def is_execution(self) -> bool:
        """True if this mode involves actual order submission."""
        return self in (TradingMode.LIVE, TradingMode.PAPER)


def resolve_trading_mode(value: Optional[Union[str, TradingMode, Any]]) -> TradingMode:
    """Convert any legacy mode value to canonical TradingMode.

    Args:
        value: Legacy mode value (string, enum, or object with .value)

    Returns:
        Canonical TradingMode enum

    Mapping rules:
    - TradingMode instances pass through
    - "live", "LIVE", "Live" → TradingMode.LIVE
    - "paper", "PAPER", "Paper" → TradingMode.PAPER
    - "mock", "MOCK", "Mock", "test", "TEST" → TradingMode.MOCK
    - Objects with .value attribute: resolve_trading_mode(value.value)
    - None → TradingMode.MOCK (safest default for testing)

    Raises:
        ValueError: If value cannot be mapped to a known mode
    """
    # Already canonical
    if isinstance(value, TradingMode):
        return value

    # None safety
    if value is None:
        return TradingMode.MOCK

    # Extract string value from enums or objects
    str_value: str
    if hasattr(value, "value"):
        inner = getattr(value, "value")
        if isinstance(inner, str):
            str_value = inner
        else:
            # Nested enum (e.g., TradeMode.LIVE.value might be another enum)
            return resolve_trading_mode(inner)
    elif isinstance(value, str):
        str_value = value
    else:
        raise ValueError(f"Cannot resolve trading mode from {type(value).__name__}: {value}")

    # Normalize and map
    normalized = str_value.lower().strip()

    mapping = {
        "live": TradingMode.LIVE,
        "paper": TradingMode.PAPER,
        "mock": TradingMode.MOCK,
        "test": TradingMode.MOCK,
        "simulation": TradingMode.MOCK,
    }

    if normalized in mapping:
        return mapping[normalized]

    raise ValueError(f"Unknown trading mode: {value!r}")


def is_live_mode(value: Optional[Union[str, TradingMode, Any]]) -> bool:
    """Convenience: check if mode is LIVE."""
    try:
        return resolve_trading_mode(value).is_live()
    except ValueError:
        return False


def is_execution_mode(value: Optional[Union[str, TradingMode, Any]]) -> bool:
    """Convenience: check if mode involves execution (LIVE or PAPER)."""
    try:
        return resolve_trading_mode(value).is_execution()
    except ValueError:
        return False
