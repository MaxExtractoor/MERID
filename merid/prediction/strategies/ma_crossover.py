"""Fast moving-average crossover strategy for Kalshi 15-minute crypto contracts.

This strategy uses fast EMA over short SMA for confirmation signals.

Based on Turbine research:
- Fast moving-average crossover worked well
- YES strategies using fast EMA over short SMA: 5 of 5 profitable, mean P&L +$4,020
- NO strategies using inverse setup: 5 of 5 profitable, mean P&L +$3,625
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Callable
from utils.logger import get_logger

logger = get_logger("merid.prediction.strategies.ma_crossover")


class SignalSide(Enum):
    """Trading signal side."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    NO_TRADE = "no_trade"


@dataclass
class MACrossoverSignal:
    """MA crossover trading signal."""
    asset: str
    side: SignalSide
    confidence: float
    ema_value: float
    sma_value: float
    timestamp: float
    source: str = "ma_crossover"


class MACrossoverStrategy:
    """Fast moving-average crossover strategy for Kalshi 15-minute crypto contracts.
    
    This strategy uses a fast EMA (Exponential Moving Average) over a short
    SMA (Simple Moving Average) to generate trading signals.
    
    Based on Turbine research:
    - Fast MA crossover was consistently profitable
    - EMA over SMA worked well for confirmation
    - Less explosive than pure velocity but more interpretable
    """
    
    # Default configuration (based on Turbine research)
    DEFAULT_EMA_PERIOD = 9  # 9-period EMA (fast)
    DEFAULT_SMA_PERIOD = 21  # 21-period SMA (short)
    DEFAULT_MIN_CROSSOVER_PCT = 0.001  # 0.1% minimum crossover strength
    
    def __init__(
        self,
        ema_period: int = DEFAULT_EMA_PERIOD,
        sma_period: int = DEFAULT_SMA_PERIOD,
        min_crossover_pct: float = DEFAULT_MIN_CROSSOVER_PCT,
        on_signal: Optional[Callable[[MACrossoverSignal], None]] = None,
    ):
        """Initialize MA crossover strategy.
        
        Args:
            ema_period: EMA period (default 9)
            sma_period: SMA period (default 21)
            min_crossover_pct: Minimum crossover strength to consider (default 0.1%)
            on_signal: Callback for generated signals
        """
        self.ema_period = ema_period
        self.sma_period = sma_period
        self.min_crossover_pct = min_crossover_pct
        self.on_signal = on_signal
        
        # Price tracking
        self._price_history: Dict[str, List[Dict]] = {}
        self._last_signal_time: Dict[str, float] = {}
        self._last_ema: Dict[str, float] = {}
        self._cooldown_seconds = 60  # 1 minute cooldown between signals
    
    def update_price(self, asset: str, price: float, timestamp: float) -> None:
        """Update price history for an asset.
        
        Args:
            asset: Asset identifier (e.g., "BTC-USD")
            price: Current price
            timestamp: Unix timestamp
        """
        if asset not in self._price_history:
            self._price_history[asset] = []
        
        # Add price snapshot
        self._price_history[asset].append({
            "price": price,
            "timestamp": timestamp,
        })
        
        # Keep enough history for SMA calculation
        required_history = max(self.ema_period, self.sma_period) * 2
        cutoff_time = timestamp - (required_history * 60)  # Assume 1-minute intervals
        self._price_history[asset] = [
            p for p in self._price_history[asset]
            if p["timestamp"] > cutoff_time
        ]
        
        # Check for MA crossover
        self._check_ma_crossover(asset, timestamp)
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average.
        
        Args:
            prices: List of prices
            period: EMA period
        
        Returns:
            EMA value
        """
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        
        # Calculate smoothing factor
        multiplier = 2 / (period + 1)
        
        # Start with SMA for first EMA value
        ema = sum(prices[:period]) / period
        
        # Calculate EMA for remaining prices
        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        
        return ema
    
    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Calculate Simple Moving Average.
        
        Args:
            prices: List of prices
            period: SMA period
        
        Returns:
            SMA value
        """
        if len(prices) < period:
            return sum(prices) / len(prices) if prices else 0.0
        
        return sum(prices[-period:]) / period
    
    def _check_ma_crossover(self, asset: str, current_timestamp: float) -> None:
        """Check for MA crossover signals."""
        history = self._price_history.get(asset, [])
        
        if len(history) < max(self.ema_period, self.sma_period):
            return
        
        # Check cooldown
        last_signal_time = self._last_signal_time.get(asset, 0)
        if current_timestamp - last_signal_time < self._cooldown_seconds:
            return
        
        # Extract prices
        prices = [p["price"] for p in history]
        
        # Calculate EMA and SMA
        ema = self._calculate_ema(prices, self.ema_period)
        sma = self._calculate_sma(prices, self.sma_period)
        
        # Get previous EMA
        prev_ema = self._last_ema.get(asset, ema)
        self._last_ema[asset] = ema
        
        # Check for crossover
        crossover_pct = (ema - sma) / sma if sma > 0 else 0
        
        # Bullish crossover: EMA crosses above SMA
        if prev_ema <= sma and ema > sma and abs(crossover_pct) >= self.min_crossover_pct:
            signal = MACrossoverSignal(
                asset=asset,
                side=SignalSide.BUY_YES,
                confidence=min(0.5 + abs(crossover_pct) / self.min_crossover_pct * 0.4, 0.90),
                ema_value=ema,
                sma_value=sma,
                timestamp=current_timestamp,
            )
            
            logger.info(
                f"[MA-CROSSOVER] {asset} bullish crossover: EMA={ema:.2f} > SMA={sma:.2f} -> BUY YES"
            )
            
            # Update cooldown
            self._last_signal_time[asset] = current_timestamp
            
            # Callback for signal
            if self.on_signal:
                self.on_signal(signal)
        
        # Bearish crossover: EMA crosses below SMA
        elif prev_ema >= sma and ema < sma and abs(crossover_pct) >= self.min_crossover_pct:
            signal = MACrossoverSignal(
                asset=asset,
                side=SignalSide.BUY_NO,
                confidence=min(0.5 + abs(crossover_pct) / self.min_crossover_pct * 0.4, 0.90),
                ema_value=ema,
                sma_value=sma,
                timestamp=current_timestamp,
            )
            
            logger.info(
                f"[MA-CROSSOVER] {asset} bearish crossover: EMA={ema:.2f} < SMA={sma:.2f} -> BUY NO"
            )
            
            # Update cooldown
            self._last_signal_time[asset] = current_timestamp
            
            # Callback for signal
            if self.on_signal:
                self.on_signal(signal)
    
    def get_latest_price(self, asset: str) -> Optional[float]:
        """Get latest price for an asset."""
        history = self._price_history.get(asset, [])
        return history[-1]["price"] if history else None


# Singleton instance
_ma_crossover_strategy: Optional[MACrossoverStrategy] = None


def get_ma_crossover_strategy() -> MACrossoverStrategy:
    """Get singleton MA crossover strategy instance."""
    global _ma_crossover_strategy
    
    if _ma_crossover_strategy is None:
        _ma_crossover_strategy = MACrossoverStrategy()
    
    return _ma_crossover_strategy
