"""
Order book reconstructor from incremental deltas.

Provides minimal in-memory book per venue/symbol with apply_delta and snapshot
APIs. Useful for analytics tasks and cross-venue checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class OrderBook:
    bids: Dict[float, float] = field(default_factory=dict)
    asks: Dict[float, float] = field(default_factory=dict)

    def apply_delta(self, side: str, price: float, size: float) -> None:
        book = self.bids if side == "bid" else self.asks
        if size == 0:
            book.pop(price, None)
        else:
            book[price] = size

    def top_of_book(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        best_bid = max(self.bids.items(), default=(0.0, 0.0))
        best_ask = min(self.asks.items(), default=(0.0, 0.0))
        return best_bid, best_ask


class OrderBookReconstructor:
    def __init__(self) -> None:
        self._books: Dict[str, OrderBook] = {}

    def ingest_delta(self, symbol: str, side: str, price: float, size: float) -> None:
        book = self._books.setdefault(symbol, OrderBook())
        book.apply_delta(side, price, size)

    def get_snapshot(self, symbol: str) -> OrderBook:
        return self._books.setdefault(symbol, OrderBook())
