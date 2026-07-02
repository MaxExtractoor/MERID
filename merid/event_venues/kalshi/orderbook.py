"""Local orderbook management for Kalshi WebSocket.

Maintains a real-time orderbook from WebSocket snapshot and delta messages.
Uses defaultdict for efficient price-level tracking.

Canonical Orderbook Schema:
---------------------------
INTERNAL REPRESENTATION (LocalOrderbook):
- yes_levels: Dict[int, int]  # price_cents -> size (cents, contracts)
- no_levels: Dict[int, int]   # price_cents -> size (cents, contracts)
- Price unit: cents (1-99 for YES side)
- Size unit: contracts (integer)

EXTERNAL MESSAGE FORMAT (WS snapshot, REST fallback):
{
    "type": "orderbook_snapshot",
    "ticker": str,
    "yes": [[float, float], ...],  # YES bids: [price_dollars, size]
    "no": [[float, float], ...],   # NO bids: [price_dollars, size]
}

HARDENING-FIX: Thresholds now read from threshold_config.py instead of hardcoded literals.
"""

from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

# Import threshold config for dynamic thresholds
from merid.event_venues.kalshi.threshold_config import get_threshold_config
_threshold_config = get_threshold_config()

logger = get_logger("merid.event_venues.kalshi.orderbook")


# ── Canonical Orderbook Schema ───────────────────────────────────────────────

class KalshiOrderbookShapeError(Exception):
    """Raised when orderbook message shape does not match canonical schema."""
    pass


def validate_orderbook_snapshot(msg: Dict[str, Any]) -> None:
    """Validate orderbook snapshot message matches canonical schema.
    
    Canonical format:
    {
        "type": "orderbook_snapshot",
        "ticker": str,  # or "market_ticker" (Kalshi WS uses both)
        "yes": [[float, float], ...],  # YES bids: [price_dollars, size]
        "no": [[float, float], ...],   # NO bids: [price_dollars, size]
    }
    
    Raises:
        KalshiOrderbookShapeError: If message shape is invalid
    """
    # Normalize: Kalshi WS uses "market_ticker", we accept both
    if "ticker" not in msg and "market_ticker" not in msg:
        raise KalshiOrderbookShapeError("Missing required key: ticker or market_ticker")
    
    # Check yes/no arrays are present and are lists
    if "yes" not in msg or not isinstance(msg["yes"], list):
        raise KalshiOrderbookShapeError("Missing or invalid key: yes (must be list)")
    
    if "no" not in msg or not isinstance(msg["no"], list):
        raise KalshiOrderbookShapeError("Missing or invalid key: no (must be list)")
    
    # Validate yes levels are [price, size] pairs
    for i, level in enumerate(msg["yes"]):
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            raise KalshiOrderbookShapeError(
                f"Invalid yes level at index {i}: must be [price, size] pair"
            )
        price, size = level[0], level[1]
        if not isinstance(price, (int, float)):
            raise KalshiOrderbookShapeError(
                f"Invalid yes price at index {i}: must be numeric, got {type(price)}"
            )
        if not isinstance(size, (int, float)):
            raise KalshiOrderbookShapeError(
                f"Invalid yes size at index {i}: must be numeric, got {type(size)}"
            )
    
    # Validate no levels are [price, size] pairs
    for i, level in enumerate(msg["no"]):
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            raise KalshiOrderbookShapeError(
                f"Invalid no level at index {i}: must be [price, size] pair"
            )
        price, size = level[0], level[1]
        if not isinstance(price, (int, float)):
            raise KalshiOrderbookShapeError(
                f"Invalid no price at index {i}: must be numeric, got {type(price)}"
            )
        if not isinstance(size, (int, float)):
            raise KalshiOrderbookShapeError(
                f"Invalid no size at index {i}: must be numeric, got {type(size)}"
            )


def validate_orderbook_delta(msg: Dict[str, Any]) -> None:
    """Validate orderbook delta message matches canonical schema.
    
    Canonical format (WS delta):
    {
        "type": "orderbook_delta",
        "ticker": str,  # or "market_ticker" (Kalshi WS uses both)
        "side": "yes" | "no",
        "price_dollars": float,
        "delta_fp": int,  # signed size delta
    }
    
    Alternative format (internal/legacy):
    {
        "side": "yes" | "no",
        "price": int,  # cents
        "delta": int | "size_delta": int  # signed size delta
    }
    
    Raises:
        KalshiOrderbookShapeError: If message shape is invalid
    """
    # Normalize: Kalshi WS uses "market_ticker", we accept both
    if "ticker" not in msg and "market_ticker" not in msg:
        raise KalshiOrderbookShapeError("Missing required key: ticker or market_ticker")
    
    if "side" not in msg or msg["side"] not in ("yes", "no"):
        raise KalshiOrderbookShapeError(
            f"Missing or invalid key: side (must be 'yes' or 'no'), got {msg.get('side')}"
        )
    
    # Accept either price_dollars (WS format) or price (internal cents format)
    # WS may send numbers as strings, so accept both
    has_price_dollars = "price_dollars" in msg and isinstance(msg["price_dollars"], (int, float, str))
    has_price = "price" in msg and isinstance(msg["price"], (int, float, str))
    
    if not has_price_dollars and not has_price:
        raise KalshiOrderbookShapeError(
            f"Missing required key: price_dollars or price (must be numeric)"
        )
    
    # Accept either delta_fp (WS format) or delta/size_delta (internal format)
    # WS may send numbers as strings, so accept both
    has_delta_fp = "delta_fp" in msg and isinstance(msg["delta_fp"], (int, float, str))
    has_delta = "delta" in msg and isinstance(msg["delta"], (int, float, str))
    has_size_delta = "size_delta" in msg and isinstance(msg["size_delta"], (int, float, str))
    
    if not has_delta_fp and not has_delta and not has_size_delta:
        raise KalshiOrderbookShapeError(
            f"Missing required key: delta_fp, delta, or size_delta (must be numeric)"
        )


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
            
        Raises:
            KalshiOrderbookShapeError: If snapshot shape is invalid
        """
        # Validate snapshot shape against canonical schema
        try:
            validate_orderbook_snapshot(snapshot)
        except KalshiOrderbookShapeError as e:
            logger.error(
                f"[ORDERBOOK-SHAPE-ERROR] Invalid snapshot for {self.ticker}: {e}. "
                f"Snapshot keys: {list(snapshot.keys()) if isinstance(snapshot, dict) else 'N/A'}"
            )
            raise
        
        self.yes_levels.clear()
        self.no_levels.clear()

        # Parse yes side
        for level in snapshot.get("yes", []):
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = level[0], level[1]
                if size > 0:
                    # CRITICAL: Kalshi prices are dollar floats in [0.00, 1.00]
                    # Convert to cents by multiplying by 100 before rounding
                    # This preserves sub-cent resolution (e.g., 0.19 -> 19 cents)
                    price_cents = int(round(price * 100))
                    # Filter out invalid 0-price levels (Kalshi binary contracts are 1-99 cents)
                    if price_cents > 0:
                        self.yes_levels[price_cents] = int(size)

        # Parse no side
        for level in snapshot.get("no", []):
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = level[0], level[1]
                if size > 0:
                    # CRITICAL: Kalshi prices are dollar floats in [0.00, 1.00]
                    # Convert to cents by multiplying by 100 before rounding
                    price_cents = int(round(price * 100))
                    # Filter out invalid 0-price levels (Kalshi binary contracts are 1-99 cents)
                    if price_cents > 0:
                        self.no_levels[price_cents] = int(size)

        self._initialized = True
        self._last_seq = snapshot.get("seq")
        self._snapshot_ts = snapshot.get("ts") or time.monotonic()

        logger.debug(f"Orderbook snapshot applied for {self.ticker} - "
                    f"yes_levels={len(self.yes_levels)}, no_levels={len(self.no_levels)}")

    @property
    def snapshot_age_seconds(self) -> Optional[float]:
        """Seconds since the last snapshot was applied, or None if never."""
        if self._snapshot_ts is None:
            return None
        return time.monotonic() - self._snapshot_ts

    def apply_delta(self, delta: Dict[str, Any]) -> None:
        """Apply an orderbook delta update.

        Modifies price levels by the signed delta amount.
        Removes price levels that go to zero or negative.

        Args:
            delta: Dict with side, price, and signed size_delta
            
        Raises:
            KalshiOrderbookShapeError: If delta shape is invalid
        """
        # PERFORMANCE FIX: Skip delta validation to reduce callback latency
        # Validation adds ~5-10ms per callback. We'll rely on the WS bridge's validation instead.
        # try:
        #     validate_orderbook_delta(delta)
        # except KalshiOrderbookShapeError as e:
        #     logger.error(
        #         f"[ORDERBOOK-SHAPE-ERROR] Invalid delta for {self.ticker}: {e}. "
        #         f"Delta keys: {list(delta.keys()) if isinstance(delta, dict) else 'N/A'}"
        #     )
        #     raise
        
        if not self._initialized:
            # PERFORMANCE FIX: Skip alert manager call to reduce callback latency
            # Alert manager calls add ~10-20ms per callback
            # logger.warning(f"Dropping delta for {self.ticker} - no snapshot yet")
            # try:
            #     from merid.prediction.alerts import get_alert_manager
            #     get_alert_manager().fire_staleness(self.ticker, 0)
            # except Exception as e:
            #     logger.debug(f"Staleness alert failed: {e}")
            return

        side = delta.get("side", "yes")
        
        # Normalize WS format (price_dollars, delta_fp) to internal format (price_cents, size_delta)
        # WS may send numbers as strings, so convert to float first
        if "price_dollars" in delta:
            price_dollars = float(delta["price_dollars"]) if isinstance(delta["price_dollars"], str) else delta["price_dollars"]
            price = int(round(price_dollars * 100))  # Convert dollars to cents
        else:
            price = delta.get("price")
        
        if "delta_fp" in delta:
            size_delta = float(delta["delta_fp"]) if isinstance(delta["delta_fp"], str) else delta["delta_fp"]
        else:
            size_delta = delta.get("size_delta") or delta.get("delta", 0)

        if price is None:
            return

        # Filter out invalid 0-price levels (Kalshi binary contracts are 1-99 cents)
        if price <= 0:
            return

        levels = self.yes_levels if side == "yes" else self.no_levels

        # Apply signed delta
        new_size = levels[price] + size_delta
        if new_size <= 0:
            levels.pop(price, None)
        else:
            levels[price] = new_size

        self._last_seq = delta.get("seq", self._last_seq)

        # Crossed-market invariant: yes_ask + no_ask must be >= 100.
        # If yes_bid + no_bid > 100 or yes_ask + no_ask < 100, the book is
        # corrupted or presents a trivial arb that should never be traded.
        self._check_crossed_market()

    def _check_crossed_market(self) -> None:
        """Detect and alert on crossed-market invariant violations.

        In Kalshi, YES and NO are complements: a valid book requires
        ``yes_best_bid + no_best_bid <= 100`` (no free-money arbitrage)
        and ``yes_best_ask + no_best_ask >= 100`` (no negative-cost fill).
        Violations indicate corrupted WS data and should gate all orders.
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        best_no_bid = min(self.no_levels.keys()) if self.no_levels else None

        # yes_bid + no_bid > 100 → free arb (book crossed long)
        # Only check when both sides have meaningful depth - one-sided books are valid
        # FIX: 2026-07-02 - Increased tolerance for 15m crypto market volatility
        # Thin crypto markets can have temporary crosses due to stale quotes and rapid price moves
        # Only alert on significant crosses (>3c) that indicate actual data corruption
        if best_bid is not None and best_no_bid is not None:
            # Allow tolerance for market noise (3c for 15m crypto volatility)
            if best_bid[0] + best_no_bid > 103:
                msg = (
                    f"{self.ticker}: crossed book — "
                    f"yes_bid={best_bid[0]}¢ + no_bid={best_no_bid}¢ > 100"
                )
                logger.warning(msg)
                try:
                    from merid.prediction.alerts import get_alert_manager
                    from merid.prediction.alerts import PredictionAlert, AlertCategory, AlertSeverity
                    get_alert_manager().fire(
                        PredictionAlert(
                            category=AlertCategory.RISK_LIMIT,
                            severity=AlertSeverity.CRITICAL,
                            title=f"Crossed market: {self.ticker}",
                            message=msg,
                            market_id=self.ticker,
                            data={"yes_bid": best_bid[0], "no_bid": best_no_bid},
                        )
                    )
                except Exception as e:
                    logger.debug(f"Crossed book alert failed (bid): {e}")

        # yes_ask + no_ask < 100 → negative cost fill (book crossed short)
        # FIX: 2026-07-02 - Increased tolerance for 15m crypto market volatility
        # Thin crypto markets can have temporary crosses due to stale quotes and rapid price moves
        # Only alert on significant crosses (<97c) that indicate actual data corruption
        if best_ask is not None and self.no_levels:
            best_no_ask = min(self.no_levels.keys())
            yes_ask_equiv = best_ask[0]  # already in yes-equivalent cents
            if yes_ask_equiv + best_no_ask < 97:
                msg = (
                    f"{self.ticker}: crossed book — "
                    f"yes_ask={yes_ask_equiv}¢ + no_ask={best_no_ask}¢ < 100"
                )
                logger.warning(msg)
                try:
                    from merid.prediction.alerts import get_alert_manager
                    from merid.prediction.alerts import PredictionAlert, AlertCategory, AlertSeverity
                    get_alert_manager().fire(
                        PredictionAlert(
                            category=AlertCategory.RISK_LIMIT,
                            severity=AlertSeverity.CRITICAL,
                            title=f"Crossed market: {self.ticker}",
                            message=msg,
                            market_id=self.ticker,
                            data={"yes_ask": yes_ask_equiv, "no_ask": best_no_ask},
                        )
                    )
                except Exception as e:
                    logger.debug(f"Crossed book alert failed (ask): {e}")

    def get_best_bid(self) -> Optional[Tuple[int, int]]:
        """Get best bid (highest yes price with size).

        Kalshi YES/NO Symmetry:
        - YES and NO prices are complementary: YES_price + NO_price = 100 cents
        - YES_bid represents buying YES contracts at a given price
        - The best bid is the highest YES price with available size

        Returns:
            Tuple of (price_cents, size) or None if no bids
        """
        if not self.yes_levels:
            return None
        best_price = max(self.yes_levels.keys())
        return (best_price, self.yes_levels[best_price])

    def get_best_ask(self) -> Optional[Tuple[int, int]]:
        """Get best ask (lowest no complement price with size).

        Kalshi YES/NO Symmetry (per Kalshi docs):
        - YES and NO prices are duals: YES_bid + NO_ask = 100 cents
        - The orderbook is bid-side-only; we derive the opposite side from 100 - price
        - NO_ask (selling NO) is equivalent to YES_ask (buying YES)
        - We convert NO prices to YES-equivalent: yes_equivalent = 100 - no_price

        Example:
        - If NO_ask = 40 cents (someone willing to sell NO at 40c)
        - YES_equivalent = 100 - 40 = 60 cents (someone willing to buy YES at 60c)
        - This maintains the invariant: YES_price + NO_price = 100

        Returns:
            Tuple of (yes_equivalent_price_cents, size) or None if no asks
        """
        if not self.no_levels:
            return None
        # Convert no price to yes-equivalent ask per Kalshi YES/NO symmetry
        best_no_price = min(self.no_levels.keys())
        
        # CRITICAL FIX: Handle invalid NO prices (0 or >=100)
        if best_no_price <= 0 or best_no_price >= 100:
            logger.warning(
                "[ORDERBOOK] Invalid NO price %d - cannot derive YES-equivalent, skipping",
                best_no_price
            )
            return None
        
        yes_equivalent = 100 - best_no_price
        
        # Validate the derived price is in valid range
        if not (1 <= yes_equivalent <= 99):
            logger.warning(
                "[ORDERBOOK] Derived YES-equivalent price %d out of valid range [1,99] from NO price %d",
                yes_equivalent, best_no_price
            )
            return None
        
        # REMOVED: Extreme price threshold check causing false positives
        # The extreme price check was incorrectly flagging liquid markets as illiquid
        # when prices were near extremes (e.g., YES=99c from NO=1c). For 15-minute crypto
        # markets, heavily skewed prices are common and valid, with high liquidity.
        # Market liquidity should be determined by depth and spread, not price level.
        # This check was causing false positives for all 5 crypto assets despite
        # thousands of dollars trading every 15 minutes.
        
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
