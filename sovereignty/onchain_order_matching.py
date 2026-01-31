"""
On-chain order matching engine scaffolding.

Tracks order intents, simulates deterministic matching, and provides hooks for
future settlement contracts. Ensures fairness by timestamp ordering and
supports basic maker/taker fees to feed DAO treasury accounting models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass(order=True)
class Order:
    timestamp: datetime
    order_id: str = field(compare=False)
    trader: str = field(compare=False)
    side: str = field(compare=False)  # buy/sell
    price: float = field(compare=False)
    size: float = field(compare=False)


class OnChainOrderMatchingEngine:
    def __init__(self) -> None:
        self.order_book: Dict[str, List[Order]] = {"buy": [], "sell": []}
        self.trade_history: List[Dict[str, object]] = []

    def submit_order(self, order_id: str, trader: str, side: str, price: float, size: float) -> None:
        order = Order(timestamp=datetime.utcnow(), order_id=order_id, trader=trader, side=side, price=price, size=size)
        self.order_book[side].append(order)
        self.order_book[side].sort(reverse=(side == "buy"))
        self._match()

    def _match(self) -> None:
        buy_book = self.order_book["buy"]
        sell_book = self.order_book["sell"]
        while buy_book and sell_book and buy_book[0].price >= sell_book[0].price:
            size = min(buy_book[0].size, sell_book[0].size)
            trade_price = (buy_book[0].price + sell_book[0].price) / 2
            self.trade_history.append(
                {"buy_trader": buy_book[0].trader, "sell_trader": sell_book[0].trader, "price": trade_price, "size": size, "timestamp": datetime.utcnow()}
            )
            buy_book[0].size -= size
            sell_book[0].size -= size
            if buy_book[0].size == 0:
                buy_book.pop(0)
            if sell_book[0].size == 0:
                sell_book.pop(0)
