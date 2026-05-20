"""Dynamic Max Price Calculator — Real-time WebSocket-Driven Pricing

DYNAMIC PRICING v10 (2026-04-26):
- Real-time WebSocket orderbook data (sub-200ms latency)
- ATR-based volatility scaling from indicator stacks
- Time-to-expiration linear decay
- Spread-based market efficiency adjustment
- Asset-specific ranges: BTC/ETH $0.92-0.95, SOL $0.88-0.92, XRP/DOGE $0.80-0.85

PRO TIP: Use Kalshi WebSocket API instead of REST. Even 200ms delay can turn 
a $.95 "sure thing" into a loss during trend reversal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.pricing.dynamic_max_price")


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Base price ranges per asset (cents) — adjusted dynamically
DYNAMIC_PRICE_RANGES: Dict[str, Tuple[int, int]] = {
    "BTC":  (85, 95),   # Low volatility, high efficiency → 85¢-95¢
    "ETH":  (85, 95),   # Low volatility, high efficiency → 85¢-95¢
    "SOL":  (80, 92),   # Medium volatility → 80¢-92¢
    "XRP":  (75, 85),   # High volatility → 75¢-85¢
    "DOGE": (75, 85),   # High volatility → 75¢-85¢
}

# Volatility profiles for ATR-based scaling
VOLATILITY_PROFILES: Dict[str, Dict[str, float]] = {
    "BTC":  {"atr_threshold": 0.015, "efficiency": 0.95, "base_max": 95},
    "ETH":  {"atr_threshold": 0.020, "efficiency": 0.93, "base_max": 95},
    "SOL":  {"atr_threshold": 0.035, "efficiency": 0.88, "base_max": 92},
    "XRP":  {"atr_threshold": 0.050, "efficiency": 0.82, "base_max": 85},
    "DOGE": {"atr_threshold": 0.080, "efficiency": 0.78, "base_max": 85},
}

# Time-to-expiration decay factors (linear scaling)
TIME_DECAY_FACTORS: Dict[str, float] = {
    "15m":     0.95,  # 5% reduction (very short horizon)
    "1h":      0.98,  # 2% reduction
    "4h":      0.99,  # 1% reduction
    "daily":   1.00,  # No adjustment
    "weekly":  1.02,  # 2% boost (more time for edge)
    "monthly": 1.03,  # 3% boost
    "annual":  1.05,  # 5% boost
}

# Spread-based efficiency penalties
SPREAD_PENALTIES: Dict[str, Tuple[int, float]] = {
    # (max_acceptable_spread_cents, penalty_factor_if_exceeded)
    "BTC":  (3, 0.95),
    "ETH":  (3, 0.95),
    "SOL":  (5, 0.92),
    "XRP":  (6, 0.90),
    "DOGE": (8, 0.88),
}


@dataclass
class WSOrderbookSnapshot:
    """WebSocket orderbook snapshot for real-time pricing."""
    ticker: str
    bid_cents: int
    ask_cents: int
    timestamp_ms: float
    
    @property
    def mid_cents(self) -> int:
        return (self.bid_cents + self.ask_cents) // 2
    
    @property
    def spread_cents(self) -> int:
        return self.ask_cents - self.bid_cents


class DynamicMaxPriceCalculator:
    """Real-time dynamic max price calculator using WebSocket data.
    
    Uses sub-200ms WebSocket orderbook feeds to calculate volatility-adjusted
    max contract prices that account for ATR, time decay, and spread efficiency.
    """
    
    def __init__(self):
        self._ws_cache: Dict[str, WSOrderbookSnapshot] = {}
        self._indicator_stacks: Optional[Dict[str, Any]] = None
        self._last_calc: Dict[str, Tuple[int, float]] = {}  # ticker -> (price, ts)
    
    def set_indicator_stacks(self, stacks: Dict[str, Any]) -> None:
        """Set indicator stacks for ATR access."""
        self._indicator_stacks = stacks
    
    def update_ws_orderbook(self, ticker: str, bid_cents: int, ask_cents: int) -> None:
        """Update WebSocket orderbook (call on every WS message)."""
        self._ws_cache[ticker] = WSOrderbookSnapshot(
            ticker=ticker,
            bid_cents=bid_cents,
            ask_cents=ask_cents,
            timestamp_ms=time.time() * 1000,
        )
    
    def _get_atr_data(self, asset: str) -> Tuple[float, float]:
        """Get ATR and price from indicator stack. Returns (atr_pct, efficiency)."""
        if self._indicator_stacks is None:
            return 0.02, 0.90  # Default
        
        stack = self._indicator_stacks.get(asset)
        if stack is None:
            return 0.02, 0.90
        
        try:
            snap = stack.snapshot()
            atr = getattr(snap, 'atr', 0)
            price = getattr(snap, 'price', 0)
            
            if price > 0 and atr > 0:
                atr_pct = atr / price
                # Efficiency score based on volatility regime
                profile = VOLATILITY_PROFILES.get(asset, {})
                threshold = profile.get("atr_threshold", 0.02)
                
                if atr_pct <= threshold * 0.8:
                    efficiency = 1.0  # Very stable
                elif atr_pct <= threshold:
                    efficiency = 0.95
                elif atr_pct <= threshold * 1.5:
                    efficiency = 0.85
                else:
                    efficiency = 0.75
                
                return atr_pct, efficiency
        except Exception as e:
            logger.debug(f"[DYNAMIC_PRICE] ATR fetch failed for {asset}: {e}")
        
        return 0.02, 0.90
    
    def _parse_expiry_hours(self, ticker: str) -> float:
        """Extract hours to expiry from Kalshi ticker format."""
        try:
            # Format: KXBTC-15M-26APR271200-T90000 or KXBTC-26APR271200-T90000
            parts = ticker.split("-")
            if len(parts) >= 3:
                expiry_str = parts[2] if "M" not in parts[1] else parts[2]
                
                # Parse DDMMMYYHHMM
                if len(expiry_str) >= 9:
                    day = int(expiry_str[0:2])
                    month_str = expiry_str[2:5]
                    year = 2000 + int(expiry_str[5:7])
                    hour = int(expiry_str[7:9])
                    minute = int(expiry_str[9:11]) if len(expiry_str) >= 11 else 0
                    
                    months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                             "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
                    month = months.get(month_str.upper(), 1)
                    
                    expiry = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
                    hours = max(0.01, (expiry - datetime.now(timezone.utc)).total_seconds() / 3600)
                    return hours
        except Exception:
            pass
        return 24.0
    
    def calculate(
        self,
        asset: str,
        ticker: str,
        timeframe: str,
    ) -> int:
        """Calculate dynamic max price in cents.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            ticker: Full Kalshi ticker
            timeframe: Timeframe bucket (15m, 1h, daily, etc.)
        
        Returns:
            int: Max acceptable contract price in cents
        """
        asset_upper = asset.upper()
        
        # Get base parameters
        min_cap, max_cap = DYNAMIC_PRICE_RANGES.get(asset_upper, (75, 95))
        profile = VOLATILITY_PROFILES.get(asset_upper, {"atr_threshold": 0.02, "efficiency": 0.90, "base_max": 90})
        
        # 1. Volatility adjustment (ATR-based)
        atr_pct, vol_efficiency = self._get_atr_data(asset_upper)
        atr_threshold = profile["atr_threshold"]
        
        if atr_pct > atr_threshold * 1.5:
            # High volatility - aggressive reduction
            vol_factor = max(0.80, 1.0 - ((atr_pct - atr_threshold) / atr_threshold) * 0.2)
        elif atr_pct > atr_threshold:
            # Moderate volatility - slight reduction
            vol_factor = max(0.90, 1.0 - ((atr_pct - atr_threshold) / atr_threshold) * 0.1)
        else:
            # Low volatility - can go toward max
            vol_factor = min(1.05, 1.0 + ((atr_threshold - atr_pct) / atr_threshold) * 0.05)
        
        # 2. Time decay adjustment
        hours = self._parse_expiry_hours(ticker)
        time_factor = TIME_DECAY_FACTORS.get(timeframe, 1.0)
        
        # Extra decay for very short time
        if hours < 0.25:  # < 15 min
            time_factor *= 0.90
        elif hours < 1.0:  # < 1 hour
            time_factor *= 0.95
        
        # 3. Spread efficiency adjustment (from WebSocket data)
        spread_factor = 1.0
        ws_data = self._ws_cache.get(ticker)
        if ws_data:
            spread_cents = ws_data.spread_cents
            max_spread, penalty = SPREAD_PENALTIES.get(asset_upper, (5, 0.95))
            
            if spread_cents > max_spread:
                spread_factor = penalty
            elif spread_cents > max_spread // 2:
                # Moderate spread - slight penalty
                spread_factor = 0.98
        
        # 4. Calculate final max price
        base_max = profile["base_max"]
        adjusted_max = base_max * vol_factor * time_factor * spread_factor
        
        # Clamp to asset range
        final_max = int(max(min_cap, min(max_cap, adjusted_max)))
        
        # Log calculation details occasionally
        now = time.time()
        last_calc = self._last_calc.get(ticker, (0, 0))
        if now - last_calc[1] > 60:  # Log once per minute per ticker
            logger.info(
                "[DYNAMIC_PRICE] %s | base=%d vol=%.3f time=%.3f spread=%.3f → max=%d¢ "
                "(atr=%.2f%% hrs=%.1f)",
                ticker, base_max, vol_factor, time_factor, spread_factor,
                final_max, atr_pct * 100, hours
            )
            self._last_calc[ticker] = (final_max, now)
        
        return final_max


# Singleton instance
_dynamic_calculator: Optional[DynamicMaxPriceCalculator] = None


def get_dynamic_max_price_calculator() -> DynamicMaxPriceCalculator:
    """Get singleton calculator instance."""
    global _dynamic_calculator
    if _dynamic_calculator is None:
        _dynamic_calculator = DynamicMaxPriceCalculator()
    return _dynamic_calculator


def calculate_dynamic_max_price(asset: str, ticker: str, timeframe: str) -> int:
    """Convenience function to calculate dynamic max price."""
    calc = get_dynamic_max_price_calculator()
    return calc.calculate(asset, ticker, timeframe)
