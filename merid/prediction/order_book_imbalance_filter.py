"""
Order Book Imbalance (OBI) Filter for 15m Kalshi Crypto Trading

2026 Industry Best Practice Implementation:
- OBI is the strongest simple microstructure feature for short-horizon price prediction
- Predictive horizon: 1-60 seconds (IC ~0.11-0.13 at 1-5s, decays fast)
- Signal lives in tails: heavily lopsided books predict, balanced books do not
- Directional consistency filter: require 60%+ agreement in rolling window
- Expected win rate boost: 5-7 percentage points when combined with momentum

Reference:
- https://algos.pro/posts/2026-03-16-order-book-imbalance-alpha-signals/
- https://aligrithm.com/order-book-imbalance-the-first-microstructure-feature-to-test/
- https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/full

Usage:
    from merid.prediction.order_book_imbalance_filter import get_obi_filter
    
    obi_filter = get_obi_filter()
    signal = obi_filter.compute_obi(bid_depth, ask_depth)
    if obi_filter.should_trade(signal, direction):
        # Execute trade
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.prediction.order_book_imbalance_filter")


class OBISignal(str, Enum):
    """Order book imbalance signal direction."""
    STRONG_BUY = "strong_buy"  # OBI > 0.7 (heavily stacked bids)
    BUY = "buy"  # OBI > 0.3 (moderate bid pressure)
    NEUTRAL = "neutral"  # OBI between -0.3 and 0.3 (balanced)
    SELL = "sell"  # OBI < -0.3 (moderate ask pressure)
    STRONG_SELL = "strong_sell"  # OBI < -0.7 (heavily stacked asks)


@dataclass
class OBIConfig:
    """Configuration for order book imbalance filter."""
    
    # OBI calculation thresholds
    strong_threshold: float = 0.85  # Threshold for strong signal (tails) - 2026-07-03: increased for crypto volatility
    moderate_threshold: float = 0.3  # Threshold for moderate signal
    
    # Per-asset strong thresholds (crypto volatility varies by asset)
    per_asset_strong_threshold: Dict[str, float] = None  # Asset-specific overrides
    
    # Directional consistency filter
    consistency_window_size: int = 20  # Number of snapshots in rolling window
    min_consistency_pct: float = 0.60  # Minimum 60% agreement to trade
    
    # Staleness
    max_staleness_ms: int = 5000  # Max 5 seconds staleness for OBI data
    
    # Depth levels to include
    top_levels: int = 5  # Use top 5 levels (most predictive for fast moves)
    
    def __post_init__(self):
        if self.per_asset_strong_threshold is None:
            self.per_asset_strong_threshold = {}
    
    def get_strong_threshold(self, asset: str) -> float:
        """Get asset-specific strong threshold, or default if not configured."""
        return self.per_asset_strong_threshold.get(asset, self.strong_threshold)


@dataclass
class OBIMeasurement:
    """Single OBI measurement with metadata."""
    obi_value: float  # -1.0 to 1.0
    signal: OBISignal
    timestamp_ms: int
    bid_depth: float
    ask_depth: float


@dataclass
class OBIContext:
    """Context for OBI filtering decision."""
    current_obi: float
    current_signal: OBISignal
    directional_consistency: float  # 0.0 to 1.0 (percentage agreeing)
    window_size: int
    is_fresh: bool  # True if data within staleness threshold
    recommendation: str  # "TRADE", "FILTER", "HOLD"
    size_multiplier: float = 1.0  # Size multiplier based on OBI confidence (0.0 to 1.0)


class OrderBookImbalanceFilter:
    """
    Order book imbalance filter for short-horizon directional alpha.
    
    Key insights from 2026 research:
    1. OBI predicts 1-60 second price moves (useless for multi-day, useful for intraday)
    2. Signal lives in tails: heavily lopsided books predict, balanced books do not
    3. Directional consistency filter eliminates noisy/indeterminate books
    4. Combined with momentum signals, improves win rate by 5-7 percentage points
    """
    
    def __init__(self, config: Optional[OBIConfig] = None):
        self.config = config or OBIConfig()
        
        # Rolling window for directional consistency tracking
        self._history: Dict[str, deque] = {}  # Per-market OBI history
        self._last_update: Dict[str, int] = {}  # Per-market last update timestamp
        
        logger.info(
            "[OBI-FILTER-INIT] strong_threshold=%.2f moderate_threshold=%.2f "
            "consistency_window=%d min_consistency=%.0f%%",
            self.config.strong_threshold,
            self.config.moderate_threshold,
            self.config.consistency_window_size,
            self.config.min_consistency_pct * 100
        )
    
    def compute_obi(self, bid_depth: float, ask_depth: float) -> float:
        """
        Compute order book imbalance.
        
        Formula: (bid_depth - ask_depth) / (bid_depth + ask_depth)
        Result: -1.0 (all asks) to +1.0 (all bids), 0.0 = balanced
        
        Args:
            bid_depth: Total resting bid liquidity
            ask_depth: Total resting ask liquidity
            
        Returns:
            OBI value between -1.0 and 1.0
        """
        total_depth = bid_depth + ask_depth
        if total_depth == 0:
            return 0.0  # No liquidity = neutral
        
        obi = (bid_depth - ask_depth) / total_depth
        return obi
    
    def classify_signal(self, obi: float, asset: str = None) -> OBISignal:
        """Classify OBI value into signal category.
        
        Args:
            obi: OBI value between -1.0 and 1.0
            asset: Asset identifier for per-asset thresholds (optional)
        """
        strong_threshold = self.config.get_strong_threshold(asset) if asset else self.config.strong_threshold
        
        if obi >= strong_threshold:
            return OBISignal.STRONG_BUY
        elif obi >= self.config.moderate_threshold:
            return OBISignal.BUY
        elif obi <= -strong_threshold:
            return OBISignal.STRONG_SELL
        elif obi <= -self.config.moderate_threshold:
            return OBISignal.SELL
        else:
            return OBISignal.NEUTRAL
    
    def _get_or_create_history(self, market_id: str) -> deque:
        """Get or create rolling window for a market."""
        if market_id not in self._history:
            self._history[market_id] = deque(
                maxlen=self.config.consistency_window_size
            )
        return self._history[market_id]
    
    def update_measurement(
        self,
        market_id: str,
        bid_depth: float,
        ask_depth: float,
        timestamp_ms: Optional[int] = None,
        asset: str = None
    ) -> OBIMeasurement:
        """
        Update OBI measurement for a market.
        
        Args:
            market_id: Market identifier
            bid_depth: Total resting bid liquidity
            ask_depth: Total resting ask liquidity
            timestamp_ms: Timestamp in milliseconds (default: current time)
            asset: Asset identifier for per-asset thresholds (optional)
            
        Returns:
            OBIMeasurement with computed OBI and signal
        """
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        
        obi = self.compute_obi(bid_depth, ask_depth)
        signal = self.classify_signal(obi, asset)
        
        measurement = OBIMeasurement(
            obi_value=obi,
            signal=signal,
            timestamp_ms=timestamp_ms,
            bid_depth=bid_depth,
            ask_depth=ask_depth
        )
        
        # Update rolling window
        history = self._get_or_create_history(market_id)
        history.append(measurement)
        self._last_update[market_id] = timestamp_ms
        
        logger.debug(
            "[OBI-MEASUREMENT] market=%s asset=%s obi=%.3f signal=%s bid=%.0f ask=%.0f",
            market_id, asset or "N/A", obi, signal.value, bid_depth, ask_depth
        )
        
        return measurement
    
    def compute_directional_consistency(self, market_id: str, direction: str) -> float:
        """
        Compute directional consistency for a market.
        
        Directional consistency: what % of snapshots in the rolling window
        agree with the current direction.
        
        Args:
            market_id: Market identifier
            direction: "buy" or "sell"
            
        Returns:
            Consistency percentage (0.0 to 1.0)
        """
        history = self._history.get(market_id)
        if not history or len(history) < 5:
            return 0.0  # Not enough data
        
        # Count how many agree with the direction
        agree_count = 0
        for measurement in history:
            if direction == "buy":
                if measurement.signal in [OBISignal.BUY, OBISignal.STRONG_BUY]:
                    agree_count += 1
            else:  # sell
                if measurement.signal in [OBISignal.SELL, OBISignal.STRONG_SELL]:
                    agree_count += 1
        
        consistency = agree_count / len(history)
        return consistency
    
    def is_fresh(self, market_id: str, timestamp_ms: Optional[int] = None) -> bool:
        """Check if OBI data is fresh enough to use."""
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        
        last_update = self._last_update.get(market_id, 0)
        staleness = timestamp_ms - last_update
        
        is_fresh = staleness <= self.config.max_staleness_ms
        
        if not is_fresh:
            logger.debug(
                "[OBI-STALE] market=%s staleness=%dms threshold=%dms",
                market_id, staleness, self.config.max_staleness_ms
            )
        
        return is_fresh
    
    def should_trade(
        self,
        market_id: str,
        bid_depth: float,
        ask_depth: float,
        direction: str,
        timestamp_ms: Optional[int] = None,
        asset: str = None
    ) -> OBIContext:
        """
        Determine if we should trade based on OBI filter.
        
        Args:
            market_id: Market identifier
            bid_depth: Total resting bid liquidity
            ask_depth: Total resting ask liquidity
            direction: Proposed trade direction ("buy" or "sell")
            timestamp_ms: Timestamp in milliseconds (default: current time)
            asset: Asset identifier for per-asset thresholds (optional)
            
        Returns:
            OBIContext with recommendation and reasoning
        """
        # Update measurement
        measurement = self.update_measurement(
            market_id, bid_depth, ask_depth, timestamp_ms, asset
        )
        
        # Check freshness
        is_fresh = self.is_fresh(market_id, timestamp_ms)
        
        # Compute directional consistency
        consistency = self.compute_directional_consistency(market_id, direction)
        
        # Make recommendation and size multiplier based on 2026 research
        # Research: "OBI doesn't replace momentum signals. it filters and sizes them"
        # Use size multiplier instead of hard gate to allow more trades
        if not is_fresh:
            recommendation = "HOLD"  # Data too stale
            size_multiplier = 0.0
        elif consistency == 0.0:
            # Not enough data for consistency calculation (warmup)
            recommendation = "REDUCED"  # Insufficient data, reduce size
            size_multiplier = 0.50  # Warmup -> 50% size
        elif measurement.signal == OBISignal.NEUTRAL:
            recommendation = "REDUCED"  # Balanced book, reduce size
            size_multiplier = 0.70  # Neutral book -> 70% size
        elif consistency < self.config.min_consistency_pct:
            recommendation = "REDUCED"  # Inconsistent direction, reduce size
            size_multiplier = 0.55  # Low consistency -> 55% size
        else:
            recommendation = "TRADE"  # All checks passed
            size_multiplier = 1.0  # Full size
        
        context = OBIContext(
            current_obi=measurement.obi_value,
            current_signal=measurement.signal,
            directional_consistency=consistency,
            window_size=len(self._history.get(market_id, [])),
            is_fresh=is_fresh,
            recommendation=recommendation,
            size_multiplier=size_multiplier
        )
        
        logger.info(
            "[OBI-DECISION] market=%s asset=%s obi=%.3f signal=%s consistency=%.0f%% "
            "fresh=%s recommendation=%s",
            market_id,
            asset or "N/A",
            context.current_obi,
            context.current_signal.value,
            context.directional_consistency * 100,
            context.is_fresh,
            context.recommendation
        )
        
        return context


# Global OBI filter instance
_obi_filter: Optional[OrderBookImbalanceFilter] = None


def get_obi_filter() -> OrderBookImbalanceFilter:
    """Get or create the global OBI filter instance.
    
    Loads configuration from profile (kalshi_crypto_15m_v2.yaml) if available.
    """
    global _obi_filter
    if _obi_filter is None:
        # Try to load config from profile
        config = OBIConfig()
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                # Load OBI filter config from profile
                obi_filter_config = profile.raw.get('order_book_imbalance_filter', {})
                
                # Load thresholds
                config.strong_threshold = obi_filter_config.get('strong_threshold', 0.70)
                config.moderate_threshold = obi_filter_config.get('moderate_threshold', 0.3)
                config.consistency_window_size = obi_filter_config.get('consistency_window_size', 20)
                config.min_consistency_pct = obi_filter_config.get('min_consistency_pct', 0.60)
                config.max_staleness_ms = obi_filter_config.get('max_staleness_ms', 5000)
                config.top_levels = obi_filter_config.get('top_levels', 5)
                
                # Load per-asset thresholds
                per_asset = obi_filter_config.get('per_asset_strong_threshold', {})
                config.per_asset_strong_threshold = per_asset
                
                logger.info(
                    "[OBI-FILTER-INIT] Loaded config from profile: strong_threshold=%.2f per_asset=%s",
                    config.strong_threshold,
                    list(config.per_asset_strong_threshold.keys())
                )
        except Exception as e:
            logger.warning("[OBI-FILTER-INIT] Failed to load config from profile: %s, using defaults", e)
        
        _obi_filter = OrderBookImbalanceFilter(config)
    return _obi_filter
