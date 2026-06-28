"""
LEGACY - DO NOT USE IN PRODUCTION 15m STACK

Composite spot price calculation from multi-exchange data.

This module is NOT used by the Kalshi 15m crypto trading stack.
The 15m stack uses UnifiedSpotService (data/unified_spot_service.py) as the
single canonical spot provider via the parity helper system.

Aggregates normalized per-exchange tick data and computes:
- Volume-weighted mid price (VWAP) over a short window (preferred when volume available)
- Median mid price across exchanges (fallback when volume unreliable)

Emits canonical "MERID_SPOT" price per asset with metadata:
- Contributing exchanges
- Per-exchange prices and volumes
- Method used (VWAP/median)
- Health/quality flags (healthy, degraded, insufficient_data)

Integrates with existing LivePriceFeed to avoid duplication.

Production 15m stack path:
- data/unified_spot_service.py (UnifiedSpotService with parity helpers)
- merid/core/spot_parity_helpers.py (symmetric fetch across Coinbase/Kraken/BinanceUS)
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from data.spot_models import Asset, CompositeHealth, CompositeSpot, ExchangeName, ExchangeTick
from utils.logger import get_logger

logger = get_logger("data.spot_composite")

# Assets supported
SUPPORTED_ASSETS = [Asset.BTC, Asset.ETH, Asset.SOL, Asset.XRP, Asset.DOGE]

# Window for VWAP calculation (seconds)
# Use recent window to ensure composite reflects current market conditions
VWAP_WINDOW_SECONDS = 60.0

# Maximum age for a tick to be considered fresh (seconds)
FRESH_TICK_MAX_AGE_SECONDS = 10.0

# Minimum number of exchanges required for healthy composite
MIN_EXCHANGES_HEALTHY = 2
MIN_EXCHANGES_DEGRADED = 1

# Volume weight exponent for VWAP
# Higher = more weight to high-volume exchanges
VOLUME_WEIGHT_EXPONENT = 0.5


@dataclass
class ExchangeTickBuffer:
    """Buffer of recent ticks from a single exchange."""
    exchange: ExchangeName
    asset: Asset
    ticks: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def add_tick(self, tick: ExchangeTick):
        """Add a tick to the buffer."""
        self.ticks.append(tick)
    
    def get_fresh_ticks(self, max_age_seconds: float = FRESH_TICK_MAX_AGE_SECONDS) -> List[ExchangeTick]:
        """Get fresh ticks from the buffer."""
        now = datetime.now(timezone.utc)
        fresh = []
        for tick in self.ticks:
            age = (now - tick.ts_received).total_seconds()
            if age <= max_age_seconds:
                fresh.append(tick)
        return fresh
    
    def get_latest_tick(self) -> Optional[ExchangeTick]:
        """Get the most recent tick."""
        if not self.ticks:
            return None
        return self.ticks[-1]
    
    def get_average_volume(self) -> float:
        """Get average 24h volume across ticks in buffer."""
        if not self.ticks:
            return 0.0
        volumes = [t.volume_24h or 0.0 for t in self.ticks]
        return sum(volumes) / len(volumes) if volumes else 0.0


class SpotComposite:
    """Aggregates multi-exchange tick data into composite spot prices.
    
    Maintains per-exchange tick buffers and computes composite spot prices
    using either VWAP (preferred) or median (fallback) methods.
    
    Usage:
        composite = SpotComposite()
        
        # Feed ticks from exchanges
        composite.add_tick(ExchangeTick(...))
        
        # Get composite spot for an asset
        spot = composite.get_composite_spot(Asset.BTC)
        if spot.is_healthy:
            print(f"BTC composite: ${spot.price:.2f}")
    """
    
    def __init__(self, vwap_window_seconds: float = VWAP_WINDOW_SECONDS):
        """
        Initialize SpotComposite.
        
        Args:
            vwap_window_seconds: Window for VWAP calculation in seconds
        """
        self.vwap_window_seconds = vwap_window_seconds
        
        # Per-exchange tick buffers: (exchange, asset) -> ExchangeTickBuffer
        self._buffers: Dict[tuple, ExchangeTickBuffer] = {}
        
        # Latest composite per asset
        self._latest_composite: Dict[Asset, CompositeSpot] = {}
        
        logger.info(f"SpotComposite initialized: vwap_window={vwap_window_seconds}s")
    
    def add_tick(self, tick: ExchangeTick):
        """Add a tick from an exchange to the composite buffer.
        
        Args:
            tick: ExchangeTick to add
        """
        key = (tick.exchange, tick.asset)
        
        if key not in self._buffers:
            self._buffers[key] = ExchangeTickBuffer(exchange=tick.exchange, asset=tick.asset)
        
        self._buffers[key].add_tick(tick)
        
        # Recompute composite for this asset
        self._recompute_composite(tick.asset)
    
    def get_composite_spot(self, asset: Asset) -> CompositeSpot:
        """Get the latest composite spot price for an asset.
        
        Args:
            asset: Crypto asset
        
        Returns:
            CompositeSpot with latest price and metadata
        """
        return self._latest_composite.get(asset, CompositeSpot(asset=asset, method="none"))
    
    def get_all_composite_spots(self) -> Dict[Asset, CompositeSpot]:
        """Get all latest composite spot prices."""
        return self._latest_composite.copy()
    
    def _recompute_composite(self, asset: Asset):
        """Recompute composite spot for an asset from fresh exchange ticks.
        
        Args:
            asset: Crypto asset
        """
        # Collect fresh ticks from all exchanges for this asset
        fresh_ticks: List[ExchangeTick] = []
        per_exchange_data: Dict[str, dict] = {}
        
        for (exchange, a), buffer in self._buffers.items():
            if a != asset:
                continue
            
            latest = buffer.get_latest_tick()
            if latest and latest.is_fresh(FRESH_TICK_MAX_AGE_SECONDS):
                fresh_ticks.append(latest)
                
                # Store per-exchange data for metadata
                per_exchange_data[exchange.value] = {
                    "mid": latest.mid,
                    "volume_24h": latest.volume_24h or 0.0,
                }
        
        # Determine health and compute composite
        if len(fresh_ticks) >= MIN_EXCHANGES_HEALTHY:
            health = CompositeHealth.HEALTHY
        elif len(fresh_ticks) >= MIN_EXCHANGES_DEGRADED:
            health = CompositeHealth.DEGRADED
        else:
            health = CompositeHealth.INSUFFICIENT_DATA
        
        # Compute composite price
        price = None
        method = "none"
        contributing_exchanges = []
        per_exchange_mids = {}
        per_exchange_weights = {}
        
        if fresh_ticks:
            # Try VWAP first (preferred when volume data available)
            vwap_result = self._compute_vwap(fresh_ticks, per_exchange_data)
            if vwap_result is not None:
                price, weights = vwap_result
                method = "vwap"
                per_exchange_weights = weights
            else:
                # Fallback to median
                median_result = self._compute_median(fresh_ticks)
                if median_result is not None:
                    price = median_result
                    method = "median"
            
            # Populate metadata
            contributing_exchanges = [t.exchange.value for t in fresh_ticks]
            per_exchange_mids = {t.exchange.value: t.mid for t in fresh_ticks if t.mid is not None}
        
        # Create composite spot
        composite = CompositeSpot(
            asset=asset,
            price=price,
            method=method,
            contributing_exchanges=contributing_exchanges,
            per_exchange_mids=per_exchange_mids,
            per_exchange_weights=per_exchange_weights,
            health=health,
            ts=datetime.now(timezone.utc),
        )
        
        self._latest_composite[asset] = composite
        
        if health == CompositeHealth.HEALTHY:
            logger.debug(
                f"[SPOT-COMPOSITE] {asset} composite: ${price:.2f} "
                f"(method={method}, exchanges={len(contributing_exchanges)})"
            )
        elif health == CompositeHealth.DEGRADED:
            logger.warning(
                f"[SPOT-COMPOSITE] {asset} degraded: ${price:.2f} "
                f"(method={method}, exchanges={len(contributing_exchanges)})"
            )
        else:
            logger.warning(
                f"[SPOT-COMPOSITE] {asset} insufficient data "
                f"(exchanges={len(contributing_exchanges)})"
            )
    
    def _compute_vwap(
        self,
        ticks: List[ExchangeTick],
        per_exchange_data: Dict[str, dict],
    ) -> Optional[tuple]:
        """Compute volume-weighted average price (VWAP).
        
        Args:
            ticks: List of fresh ExchangeTick
            per_exchange_data: Per-exchange metadata
        
        Returns:
            Tuple of (vwap_price, weights_dict) or None if insufficient data
        """
        # Filter ticks with valid mid and volume
        valid_ticks = [t for t in ticks if t.mid is not None and t.volume_24h and t.volume_24h > 0]
        
        if len(valid_ticks) < MIN_EXCHANGES_DEGRADED:
            return None
        
        # Compute volume weights
        volumes = [t.volume_24h for t in valid_ticks]
        total_volume = sum(volumes)
        
        if total_volume <= 0:
            return None
        
        # Apply exponent to volume weights (reduce dominance of very high volume exchanges)
        weights = [(v / total_volume) ** VOLUME_WEIGHT_EXPONENT for v in volumes]
        weight_sum = sum(weights)
        normalized_weights = [w / weight_sum for w in weights]
        
        # Compute VWAP
        vwap = sum(t.mid * w for t, w in zip(valid_ticks, normalized_weights))
        
        # Build weights dict
        weights_dict = {
            t.exchange.value: w
            for t, w in zip(valid_ticks, normalized_weights)
        }
        
        return vwap, weights_dict
    
    def _compute_median(self, ticks: List[ExchangeTick]) -> Optional[float]:
        """Compute median mid price across exchanges.
        
        Args:
            ticks: List of fresh ExchangeTick
        
        Returns:
            Median price or None if insufficient data
        """
        # Filter ticks with valid mid
        mids = [t.mid for t in ticks if t.mid is not None]
        
        if len(mids) < MIN_EXCHANGES_DEGRADED:
            return None
        
        # Sort and compute median
        mids_sorted = sorted(mids)
        n = len(mids_sorted)
        
        if n % 2 == 0:
            median = (mids_sorted[n // 2 - 1] + mids_sorted[n // 2]) / 2.0
        else:
            median = mids_sorted[n // 2]
        
        return median
    
    def get_stats(self) -> Dict:
        """Get composite statistics."""
        return {
            "buffers_count": len(self._buffers),
            "latest_composites": {
                asset.value: {
                    "price": spot.price,
                    "health": spot.health.value,
                    "method": spot.method,
                    "exchanges": len(spot.contributing_exchanges),
                }
                for asset, spot in self._latest_composite.items()
            },
        }


# Singleton instance
_composite: Optional[SpotComposite] = None


def get_spot_composite() -> SpotComposite:
    """Get or create the singleton SpotComposite instance."""
    global _composite
    if _composite is None:
        _composite = SpotComposite()
    return _composite
