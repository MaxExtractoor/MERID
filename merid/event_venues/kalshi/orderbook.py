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

from merid.event_venues.kalshi.binary_price_space import (
    require_consistent_outcome_side,
    SideValidationError,
)

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
        # Per-level sequence numbers.  Kalshi orderbook_deltas are one-sided,
        # so the side that was *not* updated can carry stale prices.  When a
        # crossed/locked book is detected, we remove the price level with the
        # older sequence number (the stale side).
        self._yes_level_seq: Dict[int, int] = {}
        self._no_level_seq: Dict[int, int] = {}
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
        self._yes_level_seq.clear()
        self._no_level_seq.clear()

        # Parse yes side
        # CRITICAL FIX (2026-08-03): Unit-robust price normalization.
        # Callers now pass prices as either:
        #   - integer cents (e.g. 42) from local paths, or
        #   - dollar floats (e.g. 0.42) straight from the Kalshi API.
        # Float inputs are always treated as dollars and converted to cents;
        # integer inputs are used as-is.  This removes the previous heuristic
        # that mis-classified sub-penny cent values as dollars.
        def _to_cents(price) -> int:
            if isinstance(price, float):
                return int(round(price * 100))
            return int(price)

        snap_seq = snapshot.get("seq") or snapshot.get("sequence") or 0

        for level in snapshot.get("yes", []):
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = level[0], level[1]
                if size > 0:
                    price_cents = _to_cents(price)
                    # Filter out invalid price levels (Kalshi binary contracts are 1-99 cents)
                    # Clamp to valid range to handle rounding edge cases
                    price_cents = max(1, min(99, price_cents))
                    if price_cents > 0 and price_cents < 100:
                        self.yes_levels[price_cents] = int(size)
                        self._yes_level_seq[price_cents] = snap_seq

        # Parse no side
        for level in snapshot.get("no", []):
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                price, size = level[0], level[1]
                if size > 0:
                    price_cents = _to_cents(price)
                    # Filter out invalid price levels (Kalshi binary contracts are 1-99 cents)
                    # Clamp to valid range to handle rounding edge cases
                    price_cents = max(1, min(99, price_cents))
                    if price_cents > 0 and price_cents < 100:
                        self.no_levels[price_cents] = int(size)
                        self._no_level_seq[price_cents] = snap_seq

        self._initialized = True
        self._last_seq = snapshot.get("seq")
        # CRITICAL FIX (2026-08-22): Keep in-process staleness in a single monotonic
        # clock domain.  Exchange/wall timestamps from ``snapshot.get("ts")`` are
        # stored separately for logging only and must never be subtracted from
        # ``time.monotonic()``.
        self._snapshot_ts = time.monotonic()
        self._last_exchange_ts = snapshot.get("ts")

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
        # PERFORMANCE FIX: Validation removed - rely on WS bridge validation
        # This reduces callback latency by ~5-10ms per delta
        
        if not self._initialized:
            # PERFORMANCE FIX: Alert manager calls removed - reduces latency by ~10-20ms
            return

        # Fail-closed: orderbook deltas without a valid side are discarded.
        try:
            side = require_consistent_outcome_side(
                delta,
                context="orderbook.apply_delta",
                fields=("side", "outcome_side", "kalshi_side"),
            )
        except SideValidationError as side_err:
            logger.error("[ORDERBOOK-SIDE-INVALID] Discarding delta: %s", side_err)
            return
        
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

        # Filter out invalid price levels (Kalshi binary contracts are 1-99 cents)
        # Clamp to valid range to handle rounding edge cases
        price = max(1, min(99, price))
        if price <= 0 or price >= 100:
            return

        levels = self.yes_levels if side == "yes" else self.no_levels

        # CRITICAL FIX: Convert size_delta to int to match Dict[int, int] type
        # Kalshi WS sends delta_fp as float (e.g., 0.28), but orderbook levels store int sizes
        # Without this conversion, float values get stored in int dict, causing depth calculations
        # to fail microstructure gate checks (e.g., 0.28 < 1 threshold)
        size_delta = int(round(size_delta))

        # Apply signed delta
        new_size = levels[price] + size_delta
        if new_size <= 0:
            levels.pop(price, None)
        else:
            levels[price] = new_size

        seq = delta.get("seq")
        if seq is not None:
            self._last_seq = int(seq)

        # Record the sequence number for the price level that was touched.
        # This allows us to remove stale crossed levels from the side that
        # was *not* updated when the two best levels disagree.
        if side == "yes":
            if price in self.yes_levels:
                self._yes_level_seq[price] = self._last_seq or 0
            else:
                self._yes_level_seq.pop(price, None)
        else:
            if price in self.no_levels:
                self._no_level_seq[price] = self._last_seq or 0
            else:
                self._no_level_seq.pop(price, None)

        # Remove stale, crossed levels caused by one-sided delta streams.
        # Kalshi orderbook_delta messages are per-side; a fresh NO bid lowers
        # the YES ask, so stale YES bids above the new YES ask must be removed.
        # Conversely, a fresh YES bid raises the NO ask, so stale NO bids above
        # the new NO ask must be removed.  We use per-level sequence numbers to
        # decide which side is stale when both sides have crossed levels.
        self._sanitize_crossed_levels()

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
        # Both ``yes_levels`` and ``no_levels`` store bids.  Best bid on each
        # side is the highest price; the corresponding ask is 100 - best bid.
        best_no_bid = max(self.no_levels.keys()) if self.no_levels else None

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
        if best_ask is not None and best_bid is not None:
            # NO ask is the complement of the best YES bid.
            best_no_ask = 100 - best_bid[0]
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

    def _sanitize_crossed_levels(self) -> None:
        """Remove stale, crossed levels after a one-sided delta.

        Kalshi's ``orderbook_delta`` stream sends per-side updates.  When a
        fresh NO bid raises the best NO price, the YES ask drops.  Any YES
        bid above the new YES ask is stale and would have been matched by the
        exchange.  Symmetrically, a fresh YES bid drops the NO ask, so any NO
        bid above the new NO ask is stale.

        To decide which side is stale when both best levels cross, we compare
        the per-level sequence numbers recorded when each level was last
        touched.  The newer level wins; the older level is removed.
        """
        while self.yes_levels and self.no_levels:
            yes_best = max(self.yes_levels.keys())
            no_best = max(self.no_levels.keys())

            # Locked markets (yes_bid + no_bid == 100) are allowed.  A strict
            # cross (sum > 100) means one side is stale and must be removed.
            if yes_best + no_best <= 100:
                break

            yes_seq = self._yes_level_seq.get(yes_best, -1)
            no_seq = self._no_level_seq.get(no_best, -1)

            if yes_seq < no_seq:
                # YES best is older -> it is the stale side.
                self.yes_levels.pop(yes_best, None)
                self._yes_level_seq.pop(yes_best, None)
                logger.debug(
                    "[ORDERBOOK-SANITIZE] %s removed stale YES bid %d (seq=%d < no_seq=%d)",
                    self.ticker, yes_best, yes_seq, no_seq,
                )
            else:
                # NO best is older or tied -> remove NO best.
                self.no_levels.pop(no_best, None)
                self._no_level_seq.pop(no_best, None)
                logger.debug(
                    "[ORDERBOOK-SANITIZE] %s removed stale NO bid %d (seq=%d <= yes_seq=%d)",
                    self.ticker, no_best, no_seq, yes_seq,
                )

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
        """Get best YES ask from the best NO bid.

        Kalshi's ``orderbook_fp`` carries YES bids and NO bids.  The best YES
        ask is the complement of the best (highest) NO bid:

            YES_ask = 100 - NO_bid

        This is the cheapest price at which we can buy YES right now.
        """
        if not self.no_levels:
            return None
        # The best NO bid is the highest NO price; its complement is the best YES ask.
        best_no_price = max(self.no_levels.keys())
        
        # CRITICAL FIX: Handle invalid NO prices (0 or >=100)
        if best_no_price <= 0 or best_no_price >= 100:
            logger.warning(
                "[ORDERBOOK] Invalid NO price %d - cannot derive YES-equivalent, skipping",
                best_no_price
            )
            return None
        
        # Convert to YES-equivalent ask
        yes_equivalent = 100 - best_no_price
        
        # Validate the derived price is in valid range
        if not (1 <= yes_equivalent <= 99):
            logger.warning(
                "[ORDERBOOK] Derived YES-equivalent price %d out of valid range [1,99] from NO price %d",
                yes_equivalent, best_no_price
            )
            return None
        
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
            List of (price, size) tuples, sorted by price descending
            (best bid first) on both sides.
        """
        levels = self.yes_levels if side == "yes" else self.no_levels

        # Both yes_levels and no_levels store bids; the best bid is the
        # highest price on each side.
        sorted_levels = sorted(levels.items(), key=lambda x: x[0], reverse=True)

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
        self._yes_level_seq.clear()
        self._no_level_seq.clear()
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
