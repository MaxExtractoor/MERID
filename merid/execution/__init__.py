"""Execution-layer primitives for MERID's unified trading router."""

from __future__ import annotations

from .base import Position, Quote, TradeExecutor, TradeResult
from .executors import (
    AlpacaExecutor,
    CoinbaseExecutor,
    CryptoComExecutor,
    CronosOnchainExecutor,
    FulcromExecutor,
    JupiterExecutor,
    KalshiExecutor,
    WebullExecutor,
)
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
    "CoinbaseExecutor",
    "JupiterExecutor",
    "FulcromExecutor",
    "CronosOnchainExecutor",
    "KalshiExecutor",
    "AlpacaExecutor",
    "WebullExecutor",
    "CryptoComExecutor",
]
