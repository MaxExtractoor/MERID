"""
LagTracker: Measures spot-to-book lag for Kalshi 15m crypto markets.

This module tracks the delay between spot price moves and Kalshi orderbook updates,
providing per-asset lag statistics (mean, median, p95) for edge/lag ratio computation.

Key concepts:
- Spot-to-book lag: Time between a spot price move and the first book update reflecting it
- Move threshold: Filters micro-noise (default 1 bps)
- Directional correlation: Book must move in same direction as spot for valid lag sample
- Rolling window: Maintains last N samples for statistics (default 5000)

Usage:
    from merid.market_data.lag_tracker import LagTracker

    lag_tracker = LagTracker(move_threshold_bps=1.0, window_size=5000)

    # In spot data handler
    lag_tracker.on_spot_update(asset="BTC", ts=time.time(), price=74800.0)

    # In Kalshi book handler
    lag_tracker.on_book_update(asset="BTC", ts=time.time(), best_bid=0.52, best_ask=0.53)

    # Get statistics
    stats = lag_tracker.get_stats("BTC")
    # Returns: {"count": 1234, "mean_ms": 150.5, "median_ms": 145.0, "p95_ms": 280.0}

    # Get effective lag for decision
    lag_ms = lag_tracker.get_effective_lag_ms("BTC", quantile=0.5)
"""

from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Dict, Optional
import math
import time
import logging

logger = logging.getLogger(__name__)

# Local price formatting function (replaces utils.logger.format_price to avoid import issues)
def format_price(asset: str, price: float) -> str:
    """Format price with appropriate decimal places based on asset."""
    if asset in ["BTC", "ETH"]:
        return f"{price:.2f}"
    elif asset in ["SOL", "XRP"]:
        return f"{price:.4f}"
    elif asset == "DOGE":
        return f"{price:.6f}"
    else:
        return f"{price:.4f}"


@dataclass
class LagSample:
    """Single lag measurement sample."""
    ts_spot: float
    ts_book: float

    @property
    def lag_ms(self) -> float:
        """Lag in milliseconds."""
        return max(0.0, (self.ts_book - self.ts_spot) * 1000.0)


@dataclass
class AssetLagState:
    """Per-asset lag tracking state."""
    # Recent lag samples for statistics
    samples: Deque[LagSample] = field(default_factory=lambda: deque(maxlen=5000))
    # Last observed spot price
    last_spot_ts: Optional[float] = None
    last_spot_price: Optional[float] = None
    # Last observed book mid
    last_book_ts: Optional[float] = None
    last_book_mid: Optional[float] = None


class LagTracker:
    """
    Tracks spot-to-book lag per asset for edge/lag ratio computation.

    Measures the delay between spot price moves and Kalshi orderbook updates,
    providing rolling statistics (mean, median, p95) for each asset.
    """

    def __init__(self, move_threshold_bps: float = 1.0, window_size: int = 5000):
        """
        Initialize LagTracker.

        Args:
            move_threshold_bps: Minimum spot move in basis points to trigger lag measurement
                                (default 1.0 bps = 0.01%)
            window_size: Maximum number of lag samples to keep per asset (default 5000)
        """
        self._assets: Dict[str, AssetLagState] = {}
        self._move_threshold_bps = move_threshold_bps
        self._window_size = window_size
        
        # Per-asset move thresholds (higher for smaller, noisier coins)
        self._move_thresholds_per_asset: Dict[str, float] = {
            "BTC": 1.0,
            "ETH": 1.0,
            "SOL": 2.0,
            "XRP": 2.0,
            "DOGE": 3.0,
        }

        logger.info(
            "[LAG-TRACKER] Initialized with move_threshold_bps=%.2f, window_size=%d",
            move_threshold_bps,
            window_size
        )

    def _state(self, asset: str) -> AssetLagState:
        """Get or create asset state."""
        if asset not in self._assets:
            self._assets[asset] = AssetLagState(samples=deque(maxlen=self._window_size))
            logger.debug("[LAG-TRACKER] Created state for asset=%s", asset)
        return self._assets[asset]

    def on_spot_update(self, asset: str, ts: float, price: float) -> None:
        """
        Record a spot price update.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
            ts: Timestamp in seconds (Unix epoch)
            price: Spot price in USD
        """
        # CRITICAL FIX: Handle sentinel values and missing spot data gracefully
        if price <= 0 or price is None:
            logger.debug("[LAG-TRACKER] Invalid or sentinel spot price=%s for asset=%s, skipping", price, asset)
            return
            
        if ts <= 0 or ts is None:
            logger.debug("[LAG-TRACKER] Invalid or sentinel timestamp=%s for asset=%s, skipping", ts, asset)
            return

        st = self._state(asset)
        st.last_spot_ts = ts
        st.last_spot_price = price

        logger.debug("[LAG-TRACKER] Spot update: asset=%s ts=%.3f price=%s", asset, ts, format_price(asset, price))

    def on_book_update(self, asset: str, ts: float, best_bid: float, best_ask: float) -> None:
        """
        Record a Kalshi orderbook update and potentially create a lag sample.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
            ts: Timestamp in seconds (Unix epoch)
            best_bid: Best bid price in cents (Kalshi contract price)
            best_ask: Best ask price in cents (Kalshi contract price)
        """
        # CRITICAL FIX: Handle sentinel values and missing book data gracefully
        if best_bid <= 0 or best_bid is None or best_ask <= 0 or best_ask is None:
            logger.debug("[LAG-TRACKER] Invalid or sentinel book prices for asset=%s (bid=%s, ask=%s), skipping", asset, best_bid, best_ask)
            return
            
        if ts <= 0 or ts is None:
            logger.debug("[LAG-TRACKER] Invalid or sentinel timestamp=%s for asset=%s book update, skipping", ts, asset)
            return

        st = self._state(asset)
        mid = 0.5 * (best_bid + best_ask)

        # Initialize book state if needed
        if st.last_book_mid is None:
            st.last_book_mid = mid
            st.last_book_ts = ts
            logger.debug("[LAG-TRACKER] Initialized book state for asset=%s mid=%.2f", asset, mid)
            return

        # Only measure lag if we have a recent spot sample
        if st.last_spot_ts is None or st.last_spot_price is None:
            st.last_book_mid = mid
            st.last_book_ts = ts
            logger.debug("[LAG-TRACKER] No spot sample for asset=%s, skipping lag measurement", asset)
            return

        # Check if this book move is meaningfully reacting to the prior spot move
        pct_book = (mid - st.last_book_mid) / st.last_book_mid if st.last_book_mid != 0 else 0.0
        pct_spot = (st.last_spot_price - st.last_book_mid) / st.last_book_mid if st.last_book_mid != 0 else 0.0

        # Require that spot has moved at least X bps and book is moving in same direction
        spot_move_bps = abs(pct_spot) * 1e4
        spot_direction = math.copysign(1.0, pct_spot or 1.0)
        book_direction = math.copysign(1.0, pct_book or 1.0)
        
        # Use per-asset move threshold (higher for noisier coins)
        move_threshold = self._move_thresholds_per_asset.get(asset, self._move_threshold_bps)

        if spot_move_bps >= move_threshold and spot_direction == book_direction:
            # Ensure ts_book >= ts_spot to avoid negative lag (Kalshi leading spot)
            if ts >= st.last_spot_ts:
                sample = LagSample(ts_spot=st.last_spot_ts, ts_book=ts)
                st.samples.append(sample)
                logger.debug(
                    "[LAG-TRACKER] Lag sample: asset=%s lag_ms=%.2f spot_move_bps=%.2f threshold=%.2f",
                    asset,
                    sample.lag_ms,
                    spot_move_bps,
                    move_threshold
                )
            else:
                # Book timestamp is before spot timestamp - skip this sample
                logger.debug(
                    "[LAG-TRACKER] Skipping lag sample for asset=%s: ts_book=%.3f < ts_spot=%.3f (possible clock skew or Kalshi leading spot)",
                    asset, ts, st.last_spot_ts
                )

        st.last_book_mid = mid
        st.last_book_ts = ts

    def get_stats(self, asset: str) -> Optional[Dict[str, float]]:
        """
        Get lag statistics for an asset.

        Args:
            asset: Asset symbol

        Returns:
            Dict with keys: count, mean_ms, median_ms, p95_ms
            Returns None if no samples available
        """
        st = self._assets.get(asset)
        if not st or not st.samples:
            return None

        lags = [s.lag_ms for s in st.samples]
        lags_sorted = sorted(lags)
        n = len(lags_sorted)

        mean = sum(lags_sorted) / n
        median = lags_sorted[n // 2] if n % 2 == 1 else 0.5 * (lags_sorted[n // 2 - 1] + lags_sorted[n // 2])

        p95_idx = min(n - 1, int(math.ceil(0.95 * n)) - 1)
        p95 = lags_sorted[p95_idx]

        return {
            "count": float(n),
            "mean_ms": mean,
            "median_ms": median,
            "p95_ms": p95,
        }

    def get_effective_lag_ms(self, asset: str, quantile: float = 0.5) -> Optional[float]:
        """
        Get effective lag for decision-making.

        Args:
            asset: Asset symbol
            quantile: Quantile to use (0.5 = median, 0.95 = p95, default 0.5)

        Returns:
            Lag in milliseconds, or None if no samples available
        """
        stats = self.get_stats(asset)
        if not stats:
            return None

        if quantile <= 0.5:
            return stats["median_ms"]
        elif quantile >= 0.95:
            return stats["p95_ms"]
        else:
            # For intermediate quantiles, use mean as approximation
            return stats["mean_ms"]

    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Get lag statistics for all assets.

        Returns:
            Dict mapping asset -> stats dict
        """
        result = {}
        for asset in self._assets:
            stats = self.get_stats(asset)
            if stats:
                result[asset] = stats
        return result

    def reset(self, asset: Optional[str] = None) -> None:
        """
        Reset lag tracking for an asset or all assets.

        Args:
            asset: Asset to reset, or None to reset all
        """
        if asset:
            if asset in self._assets:
                self._assets[asset].samples.clear()
                self._assets[asset].last_spot_ts = None
                self._assets[asset].last_spot_price = None
                self._assets[asset].last_book_ts = None
                self._assets[asset].last_book_mid = None
                logger.info("[LAG-TRACKER] Reset asset=%s", asset)
        else:
            self._assets.clear()
            logger.info("[LAG-TRACKER] Reset all assets")


# Global singleton instance
_lag_tracker_instance: Optional[LagTracker] = None


def get_lag_tracker() -> LagTracker:
    """Get the global LagTracker singleton instance."""
    global _lag_tracker_instance
    if _lag_tracker_instance is None:
        _lag_tracker_instance = LagTracker()
    return _lag_tracker_instance


def reset_lag_tracker() -> None:
    """Reset the global LagTracker singleton instance."""
    global _lag_tracker_instance
    _lag_tracker_instance = None
    logger.info("[LAG-TRACKER] Global instance reset")
