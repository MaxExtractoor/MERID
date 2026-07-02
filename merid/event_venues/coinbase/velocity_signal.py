"""Velocity signal generator using Coinbase spot data.

This module generates trading signals for Kalshi 15-minute crypto contracts
based on velocity calculated from Coinbase spot price movements.

Based on Turbine research: Coinbase 1-minute velocity was the top-performing
strategy for Kalshi BTC 15-minute markets (+$19,451 P&L over 30 days).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from utils.logger import get_logger

from merid.event_venues.coinbase.ws_client import (
    CoinbaseWebSocketClient,
    CoinbaseAsset,
    VelocitySignal,
    get_coinbase_client,
)

logger = get_logger("merid.event_venues.coinbase.velocity_signal")


class SignalSide(Enum):
    """Trading signal side."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    NO_TRADE = "no_trade"


@dataclass
class KalshiTradingSignal:
    """Trading signal for Kalshi 15-minute crypto contracts."""
    asset: str
    side: SignalSide
    confidence: float  # 0.0 to 1.0
    velocity: float
    timestamp: float
    source: str = "coinbase_velocity"


class CoinbaseVelocitySignalGenerator:
    """Generate Kalshi trading signals from Coinbase velocity.
    
    This generator uses Coinbase spot price velocity as a lead indicator
    for Kalshi 15-minute crypto contracts.
    
    Based on Turbine research:
    - 1-minute Coinbase velocity was the top-performing strategy
    - Threshold barely mattered (0.0002 to 0.002 both worked)
    - Edge: "when Coinbase spot is moving up right now, Kalshi's 15-minute
      contract still has enough lag to buy YES"
    """
    
    # Velocity thresholds (per asset, aligned with research)
    # Updated 2026-06-29: Reduced by 25% to capture more trades in calm market conditions
    VELOCITY_THRESHOLDS = {
        "BTC-USD": 0.00015,  # 0.015% - reduced by 25% from 0.0002 to capture more trades in calm conditions
        "ETH-USD": 0.00015,  # 0.015% - reduced by 25% from 0.0002 to capture more trades in calm conditions
        "SOL-USD": 0.000225,  # 0.0225% - reduced by 25% from 0.0003 for higher volatility assets
        "XRP-USD": 0.000225,  # 0.0225% - reduced by 25% from 0.0003 for higher volatility assets
        "DOGE-USD": 0.0003,   # 0.03% - reduced by 25% from 0.0004 for highest volatility assets
    }
    
    def __init__(
        self,
        coinbase_client: Optional[CoinbaseWebSocketClient] = None,
        on_signal: Optional[callable[[KalshiTradingSignal], None]] = None,
    ):
        """Initialize velocity signal generator.
        
        Args:
            coinbase_client: Coinbase WebSocket client (uses singleton if None)
            on_signal: Callback for generated trading signals
        """
        self.client = coinbase_client or get_coinbase_client()
        self.on_signal = on_signal
        
        self._running = False
        self._signal_cooldown: Dict[str, float] = {}  # Asset -> last signal time
        self._cooldown_seconds = 30  # Minimum 30 seconds between signals per asset
    
    async def start(self) -> None:
        """Start the signal generator."""
        logger.info("[COINBASE-VELOCITY] Starting signal generator")
        
        # Set up velocity signal callback
        self.client.on_velocity_signal = self._on_velocity_signal
        
        # Connect to Coinbase WebSocket
        await self.client.connect()
        
        # Start listening in background
        self._running = True
        asyncio.create_task(self.client.listen())
        
        logger.info("[COINBASE-VELOCITY] Signal generator started")
    
    def _on_velocity_signal(self, velocity_signal: VelocitySignal) -> None:
        """Handle velocity signal from Coinbase client."""
        asset = velocity_signal.asset
        velocity = velocity_signal.velocity
        
        # Check cooldown
        last_signal_time = self._signal_cooldown.get(asset, 0)
        if time.time() - last_signal_time < self._cooldown_seconds:
            logger.debug(
                f"[COINBASE-VELOCITY] {asset} in cooldown, skipping signal"
            )
            return
        
        # Get velocity threshold for this asset
        threshold = self.VELOCITY_THRESHOLDS.get(asset, 0.0005)
        
        # Generate trading signal based on velocity
        if velocity > threshold:
            # Positive velocity -> BUY YES
            signal = KalshiTradingSignal(
                asset=asset,
                side=SignalSide.BUY_YES,
                confidence=min(0.5 + abs(velocity) / threshold * 0.4, 0.95),
                velocity=velocity,
                timestamp=velocity_signal.timestamp,
            )
            
            logger.info(
                f"[COINBASE-VELOCITY] {asset} velocity={velocity:.6f} > threshold={threshold:.6f} -> BUY YES"
            )
            
        elif velocity < -threshold:
            # Negative velocity -> BUY NO
            signal = KalshiTradingSignal(
                asset=asset,
                side=SignalSide.BUY_NO,
                confidence=min(0.5 + abs(velocity) / threshold * 0.4, 0.95),
                velocity=velocity,
                timestamp=velocity_signal.timestamp,
            )
            
            logger.info(
                f"[COINBASE-VELOCITY] {asset} velocity={velocity:.6f} < -threshold={-threshold:.6f} -> BUY NO"
            )
            
        else:
            # Velocity within threshold -> NO TRADE
            logger.debug(
                f"[COINBASE-VELOCITY] {asset} velocity={velocity:.6f} within ±threshold={threshold:.6f} -> NO TRADE"
            )
            return
        
        # Update cooldown
        self._signal_cooldown[asset] = time.time()
        
        # Callback for signal
        if self.on_signal:
            self.on_signal(signal)
    
    async def stop(self) -> None:
        """Stop the signal generator."""
        logger.info("[COINBASE-VELOCITY] Stopping signal generator")
        
        self._running = False
        await self.client.disconnect()
        
        logger.info("[COINBASE-VELOCITY] Signal generator stopped")
    
    def get_latest_signal(self, asset: str) -> Optional[KalshiTradingSignal]:
        """Get the latest signal for an asset."""
        # This would need to be implemented with signal history tracking
        # For now, return None as signals are fire-and-forget via callback
        return None


# Singleton instance
_signal_generator: Optional[CoinbaseVelocitySignalGenerator] = None


def get_velocity_signal_generator() -> CoinbaseVelocitySignalGenerator:
    """Get singleton velocity signal generator instance."""
    global _signal_generator
    
    if _signal_generator is None:
        _signal_generator = CoinbaseVelocitySignalGenerator()
    
    return _signal_generator


# Import time for cooldown check
import time
