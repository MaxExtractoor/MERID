"""FVG (Fair Value Gap) Detector for Hedge Timing (P1-7)

Detects price imbalances (3-candle gaps) to provide optimal hedge entry zones.
Used by hedge engine to time entries at FVG fills rather than market orders.

Fair Value Gap definition:
- Bullish FVG: Low[candle2] > High[candle0] (gap up)
- Bearish FVG: High[candle2] < Low[candle0] (gap down)
- Zone remains "active" until price returns to fill it
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum
import time


class FVGType(Enum):
    """Fair Value Gap type."""
    BULLISH = "bullish"   # Gap up (buy zone)
    BEARISH = "bearish"  # Gap down (sell zone)


@dataclass
class FVGZone:
    """Single FVG zone with metadata."""
    
    asset: str
    timeframe: str
    fvg_type: FVGType
    top: float       # Top of zone (high of candle 0 for bearish, low of candle 2 for bullish)
    bottom: float    # Bottom of zone
    created_at: float
    volume_at_creation: float = 0.0
    filled: bool = False
    
    @property
    def mid(self) -> float:
        """Midpoint of FVG zone."""
        return (self.top + self.bottom) / 2
    
    @property
    def height(self) -> float:
        """Zone height in price units."""
        return abs(self.top - self.bottom)
    
    def is_price_in_zone(self, price: float) -> bool:
        """Check if price is within the FVG zone."""
        return min(self.top, self.bottom) <= price <= max(self.top, self.bottom)


@dataclass
class FVGSnapshot:
    """Snapshot of all active FVG zones for an asset/timeframe."""
    
    asset: str
    timeframe: str
    zones: List[FVGZone] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    
    def get_nearest_zone(self, price: float, fvg_type: Optional[FVGType] = None) -> Optional[FVGZone]:
        """Get nearest FVG zone to given price."""
        candidates = self.zones
        if fvg_type:
            candidates = [z for z in candidates if z.fvg_type == fvg_type and not z.filled]
        
        if not candidates:
            return None
        
        return min(candidates, key=lambda z: abs(z.mid - price))
    
    def has_active_bullish_zone(self) -> bool:
        """Check if any active bullish (buy) zones exist."""
        return any(z.fvg_type == FVGType.BULLISH and not z.filled for z in self.zones)
    
    def has_active_bearish_zone(self) -> bool:
        """Check if any active bearish (sell) zones exist."""
        return any(z.fvg_type == FVGType.BEARISH and not z.filled for z in self.zones)


def detect_fvg_zones(
    ohlcv: List[Tuple[float, float, float, float, float]],  # (open, high, low, close, volume)
    asset: str,
    timeframe: str,
    min_gap_pct: float = 0.001,  # Minimum 0.1% gap
) -> FVGSnapshot:
    """Detect FVG zones from OHLCV data.
    
    Args:
        ohlcv: List of (open, high, low, close, volume) tuples, oldest first
        asset: Asset symbol
        timeframe: Timeframe string
        min_gap_pct: Minimum gap percentage to qualify as FVG
        
    Returns:
        FVGSnapshot with detected zones
    """
    zones: List[FVGZone] = []
    
    # Need at least 3 candles
    if len(ohlcv) < 3:
        return FVGSnapshot(asset=asset, timeframe=timeframe, zones=zones)
    
    for i in range(len(ohlcv) - 2):
        c0 = ohlcv[i]    # Candle 0 (oldest)
        c1 = ohlcv[i+1]  # Candle 1 (middle)
        c2 = ohlcv[i+2]  # Candle 2 (newest)
        
        o0, h0, l0, close0, v0 = c0
        o1, h1, l1, close1, v1 = c1
        o2, h2, l2, close2, v2 = c2
        
        # Calculate average price for percentage
        avg_price = (close0 + close1 + close2) / 3
        
        # Bullish FVG: Low[c2] > High[c0]
        if l2 > h0:
            gap_size = l2 - h0
            gap_pct = gap_size / avg_price
            
            if gap_pct >= min_gap_pct:
                zone = FVGZone(
                    asset=asset,
                    timeframe=timeframe,
                    fvg_type=FVGType.BULLISH,
                    top=l2,
                    bottom=h0,
                    created_at=time.time(),
                    volume_at_creation=v0 + v1 + v2,
                )
                zones.append(zone)
        
        # Bearish FVG: High[c2] < Low[c0]
        elif h2 < l0:
            gap_size = l0 - h2
            gap_pct = gap_size / avg_price
            
            if gap_pct >= min_gap_pct:
                zone = FVGZone(
                    asset=asset,
                    timeframe=timeframe,
                    fvg_type=FVGType.BEARISH,
                    top=l0,
                    bottom=h2,
                    created_at=time.time(),
                    volume_at_creation=v0 + v1 + v2,
                )
                zones.append(zone)
    
    return FVGSnapshot(
        asset=asset,
        timeframe=timeframe,
        zones=zones,
        timestamp=time.time(),
    )


def get_hedge_fvg_price(
    asset: str,
    timeframe: str,
    hedge_side: str,  # "yes" (bullish) or "no" (bearish)
    current_price: float,
    ohlcv_data: Optional[List[Tuple]] = None,
) -> Optional[float]:
    """Get optimal hedge price based on FVG zones (P1-7).
    
    If FVG zone exists in hedge direction, return zone midpoint.
    Otherwise return None (use market price).
    
    Args:
        asset: Asset to hedge
        timeframe: Timeframe for FVG detection
        hedge_side: "yes" for bullish hedge, "no" for bearish
        current_price: Current market price
        ohlcv_data: Optional OHLCV data (if None, returns None)
        
    Returns:
        Optimal FVG-based price or None
    """
    if ohlcv_data is None or len(ohlcv_data) < 3:
        return None
    
    snapshot = detect_fvg_zones(ohlcv_data, asset, timeframe)
    
    # Map hedge side to FVG type
    # Hedge "yes" = bullish position = buy at bearish FVG (discount)
    # Hedge "no" = bearish position = buy at bullish FVG (premium)
    target_type = FVGType.BEARISH if hedge_side == "yes" else FVGType.BULLISH
    
    # Find nearest unfilled zone of target type
    zone = snapshot.get_nearest_zone(current_price, target_type)
    
    if zone and not zone.filled:
        # Return zone midpoint as optimal entry
        return zone.mid
    
    return None
