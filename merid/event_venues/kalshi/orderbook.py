"""Local orderbook management for Kalshi WebSocket.

Maintains a real-time orderbook from WebSocket snapshot and delta messages.
Uses defaultdict for efficient price-level tracking.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.orderbook")


class LocalOrderbook:
    """Local orderbook state maintained from WebSocket updates.

    Consumes orderbook_snapshot and orderbook_delta messages from Kalshi
    WebSocket to maintain a live view of the market depth.

    Features:
    - Snapshot initialization for full book rebuilds
    - Delta application for incremental updates
    - Bid/ask spread calculation
    - Best bid/ask tracking
    - Volume at price level aggregation

    Example:
        ob = LocalOrderbook("KXBTC-24DEC-ABOVE-60000")
        ob.apply_snapshot(snapshot_data)
        ob.apply_delta(delta_data)
        spread = ob.get_spread()
        best_bid = ob.get_best_bid()
    """

    def __init__(self, ticker: str):
        self.ticker = ticker
        self.yes_levels: Dict[int, int] = defaultdict(int)  # price_cents -> size
        self.no_levels: Dict[int, int] = defaultdict(int)
        self._initialized = False
        self._last_seq: Optional[int] = None
        self._snapshot_ts: Optional[float] = None

    @property
    def initialized(self) -> bool:
        """Whether the orderbook has received a snapshot."""
        return self._initialized

    @property
    def last_seq(self) -> Optional[int]:
        """Last sequence number received."""
        return self._last_seq

    def apply_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Apply a full orderbook snapshot.

        Clears existing levels and rebuilds from snapshot data.

        Args:
            snapshot: Dict with "yes" and "no" lists of [price, size] levels
        """
        self.yes_levels.clear()
        self.no_levels.clear()

        # Parse yes side
        for level in snapshot.get("yes", []):
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = level[0], level[1]
                if size > 0:
                    self.yes_levels[price] = size

        # Parse no side
        for level in snapshot.get("no", []):
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = level[0], level[1]
                if size > 0:
                    self.no_levels[price] = size

        self._initialized = True
        self._last_seq = snapshot.get("seq")
        self._snapshot_ts = snapshot.get("ts")

        logger.debug(f"Orderbook snapshot applied for {self.ticker} - "
                    f"yes_levels={len(self.yes_levels)}, no_levels={len(self.no_levels)}")

    def apply_delta(self, delta: Dict[str, Any]) -> None:
        """Apply an orderbook delta update.

        Modifies price levels by the signed delta amount.
        Removes price levels that go to zero or negative.

        Args:
            delta: Dict with side, price, and signed size_delta
        """
        if not self._initialized:
            logger.warning(f"Dropping delta for {self.ticker} - no snapshot yet")
            return

        side = delta.get("side", "yes")
        price = delta.get("price")
        size_delta = delta.get("size_delta") or delta.get("delta", 0)

        if price is None:
            return

        levels = self.yes_levels if side == "yes" else self.no_levels

        # Apply signed delta
        new_size = levels[price] + size_delta
        if new_size <= 0:
            levels.pop(price, None)
        else:
            levels[price] = new_size

        self._last_seq = delta.get("seq", self._last_seq)

    def get_best_bid(self) -> Optional[Tuple[int, int]]:
        """Get best bid (highest yes price with size).

        Returns:
            Tuple of (price_cents, size) or None if no bids
        """
        if not self.yes_levels:
            return None
        best_price = max(self.yes_levels.keys())
        return (best_price, self.yes_levels[best_price])

    def get_best_ask(self) -> Optional[Tuple[int, int]]:
        """Get best ask (lowest no complement price with size).

        Kalshi's no prices are complementary (100 - yes_price).

        Returns:
            Tuple of (price_cents, size) or None if no asks
        """
        if not self.no_levels:
            return None
        # Convert no price to yes-equivalent ask
        best_no_price = min(self.no_levels.keys())
        yes_equivalent = 100 - best_no_price
        return (yes_equivalent, self.no_levels[best_no_price])

    def get_spread(self) -> Optional[int]:
        """Get bid-ask spread in cents.

        Returns:
            Spread in cents, or None if book incomplete
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is None or best_ask is None:
            return None
        return best_ask[0] - best_bid[0]

    def get_midpoint(self) -> Optional[float]:
        """Get midpoint price in cents.

        Returns:
            Midpoint price, or None if book incomplete
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid is None or best_ask is None:
            return None
        return (best_bid[0] + best_ask[0]) / 2.0

    def get_depth(self, side: str, price_limit: Optional[int] = None) -> int:
        """Get total size at price levels up to limit.

        Args:
            side: "yes" or "no"
            price_limit: Maximum (for yes) or minimum (for no) price to include

        Returns:
            Total contracts at specified price levels
        """
        levels = self.yes_levels if side == "yes" else self.no_levels

        if price_limit is None:
            return sum(levels.values())

        if side == "yes":
            # For yes, sum levels at or below price_limit
            return sum(size for price, size in levels.items() if price <= price_limit)
        else:
            # For no, sum levels at or above price_limit
            return sum(size for price, size in levels.items() if price >= price_limit)

    def get_book(self, side: str, top_n: int = 10) -> List[Tuple[int, int]]:
        """Get sorted book levels.

        Args:
            side: "yes" or "no"
            top_n: Number of levels to return

        Returns:
            List of (price, size) tuples, sorted by price (desc for yes, asc for no)
        """
        levels = self.yes_levels if side == "yes" else self.no_levels

        if side == "yes":
            # Sort by price descending (best bids first)
            sorted_levels = sorted(levels.items(), key=lambda x: x[0], reverse=True)
        else:
            # Sort by price ascending (lowest no prices first)
            sorted_levels = sorted(levels.items(), key=lambda x: x[0])

        return sorted_levels[:top_n]

    def get_yes_book_dollars(self, top_n: int = 10) -> List[Tuple[Decimal, int]]:
        """Get yes side book in dollar prices.

        Args:
            top_n: Number of levels

        Returns:
            List of (price_dollars, size) tuples
        """
        book = self.get_book("yes", top_n)
        return [(Decimal(p) / 100, s) for p, s in book]

    def get_no_book_dollars(self, top_n: int = 10) -> List[Tuple[Decimal, int]]:
        """Get no side book in dollar prices (complement).

        Args:
            top_n: Number of levels

        Returns:
            List of (price_dollars, size) tuples
        """
        book = self.get_book("no", top_n)
        return [(Decimal(100 - p) / 100, s) for p, s in book]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize orderbook to dict.

        Returns:
            Dict representation of current state
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        return {
            "ticker": self.ticker,
            "initialized": self._initialized,
            "last_seq": self._last_seq,
            "best_bid_cents": best_bid[0] if best_bid else None,
            "best_bid_size": best_bid[1] if best_bid else None,
            "best_ask_cents": best_ask[0] if best_ask else None,
            "best_ask_size": best_ask[1] if best_ask else None,
            "spread_cents": self.get_spread(),
            "midpoint_cents": self.get_midpoint(),
            "yes_depth": self.get_depth("yes"),
            "no_depth": self.get_depth("no"),
            "yes_levels": dict(self.yes_levels),
            "no_levels": dict(self.no_levels),
        }

    def clear(self) -> None:
        """Clear all orderbook state."""
        self.yes_levels.clear()
        self.no_levels.clear()
        self._initialized = False
        self._last_seq = None


class MultiMarketOrderbook:
    """Manages orderbooks for multiple markets.

    Maintains a collection of LocalOrderbook instances keyed by ticker.
    """

    def __init__(self):
        self._books: Dict[str, LocalOrderbook] = {}

    def get_book(self, ticker: str) -> LocalOrderbook:
        """Get or create orderbook for a ticker."""
        if ticker not in self._books:
            self._books[ticker] = LocalOrderbook(ticker)
        return self._books[ticker]

    def remove_book(self, ticker: str) -> None:
        """Remove orderbook for a ticker."""
        if ticker in self._books:
            del self._books[ticker]

    def apply_snapshot(self, ticker: str, snapshot: Dict[str, Any]) -> None:
        """Apply snapshot to a market's orderbook."""
        book = self.get_book(ticker)
        book.apply_snapshot(snapshot)

    def apply_delta(self, ticker: str, delta: Dict[str, Any]) -> None:
        """Apply delta to a market's orderbook."""
        if ticker in self._books:
            self._books[ticker].apply_delta(delta)

    def get_all_tickers(self) -> List[str]:
        """Get list of all tracked tickers."""
        return list(self._books.keys())

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all orderbooks."""
        return {
            ticker: {
                "initialized": book.initialized,
                "spread_cents": book.get_spread(),
                "yes_depth": book.get_depth("yes"),
                "no_depth": book.get_depth("no"),
            }
            for ticker, book in self._books.items()
        }

    def clear_all(self) -> None:
        """Clear all orderbooks."""
        self._books.clear()
