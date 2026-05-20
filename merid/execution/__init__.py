"""Execution-layer primitives for MERID's unified trading router."""

from __future__ import annotations

from .base import Position, Quote, TradeExecutor, TradeResult
from .executors import KalshiExecutor

# Lazy imports for optional executors (only if modules exist)
try:
    from .executors import AlpacaExecutor
except ImportError:
    AlpacaExecutor = None  # type: ignore

from .portfolio import PortfolioAggregator, PortfolioSnapshot
from .router import ExecutionRouter, TradeIntent, TraderIdentity

__all__ = [
    "Quote",
    "Position",
    "TradeResult",
    "TradeExecutor",
    "TraderIdentity",
    "TradeIntent",
    "ExecutionRouter",
    "PortfolioAggregator",
    "PortfolioSnapshot",
    "KalshiExecutor",
    "AlpacaExecutor",
]
