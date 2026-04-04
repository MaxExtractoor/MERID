"""Canonical ``TradeMode`` enum — shared across all packages.

This module is intentionally minimal so it can be imported by any layer
(``merid``, ``trading``, ``config``, ``web``) without triggering circular
imports or colliding with the ``tests/trading/`` test-directory namespace.

Every other module that needs ``TradeMode`` should import from here rather
than from ``trading.trade_mode``, which lives inside the ``trading`` package
and can be shadowed when tests run from a directory also named ``trading``.

The stateful helpers (``get_trade_mode``, ``set_trade_mode``, etc.) remain
in ``trading.trade_mode``; only the *value type* is defined here so that all
packages share the same enum class identity.
"""

from __future__ import annotations

from enum import Enum


class TradeMode(str, Enum):
    """Process-wide trading mode.

    * **MOCK**  – pure in-memory simulation; no external calls at all.
    * **PAPER** – real market data, simulated fills, no real money.
    * **LIVE**  – real orders on real-money endpoints.
    """

    MOCK = "mock"
    PAPER = "paper"
    LIVE = "live"


# Backward-compat alias: ``SIM`` was the old name for ``MOCK``.
# Tests and legacy code that reference ``TradeMode.SIM`` continue to work.
if not hasattr(TradeMode, "SIM"):
    TradeMode.SIM = TradeMode.MOCK  # type: ignore[attr-defined]
