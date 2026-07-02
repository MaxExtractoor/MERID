"""FVG Integration — Connects Kalshi market data to FVG detection.

This module integrates Fair Value Gap detection with Kalshi market data feeds:
- Updates FVG store from orderbook mid-price changes
- Provides FVG-based signal overlay for trading decisions
- Tracks FVG fill events for post-trade analysis

Production Integration Points:
1. KalshiMarketStateStore — feeds price updates to FVG store
2. TradingAgent — queries FVG signals for edge calculation
3. Strategy — uses FVG fill proximity for entry/exit timing

Usage::

    from merid.prediction.fvg_integration import (
        get_fvg_integrator,
        update_price_from_orderbook,
        get_fvg_signal_for_market,
    )
    
    # Called from market state updates
    update_price_from_orderbook(ticker, bid, ask, timestamp)
    
    # Called from strategy
    signal = get_fvg_signal_for_market(ticker, current_price)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from merid.prediction.forecasters.fvg import (
    FVGForecaster,
    FVGStore,
    get_fvg_forecaster,
    get_fvg_store,
)
from utils.logger import get_logger

logger = get_logger("merid.prediction.fvg_integration")

# ═══════════════════════════════════════════════════════════════════════════════
# FVG Production Configuration
# ═══════════════════════════════════════════════════════════════════════════════

_FVG_ENABLED = os.getenv("MERID_FVG_ENABLED", "true").lower() in ("true", "1", "yes")
_FVG_MIN_PRICE_CHANGE_CENTS = float(os.getenv("MERID_FVG_MIN_PRICE_CHANGE", "0.5"))

# Signal calibration
_FVG_BASE_CONFIDENCE = float(os.getenv("MERID_FVG_BASE_CONFIDENCE", "0.85"))
_FVG_PROXIMITY_BOOST = float(os.getenv("MERID_FVG_PROXIMITY_BOOST", "0.15"))
_FVG_MAX_EDGE_PCT = float(os.getenv("MERID_FVG_MAX_EDGE_PCT", "0.08"))
_FVG_MIN_CONFLUENCE_SCORE = float(os.getenv("MERID_FVG_MIN_CONFLUENCE_SCORE", "0.30"))

# Position sizing impact
_FVG_SIZE_MULTIPLIER = float(os.getenv("MERID_FVG_SIZE_MULTIPLIER", "1.25"))
_FVG_MAX_POSITION_BOOST = float(os.getenv("MERID_FVG_MAX_POSITION_BOOST", "1.5"))
_FVG_FILLED_ZONE_SIZE_FACTOR = float(os.getenv("MERID_FVG_FILLED_ZONE_SIZE_FACTOR", "0.75"))

# Entry/exit timing
_FVG_ENTRY_TIMING_ENABLED = os.getenv("MERID_FVG_ENTRY_TIMING_ENABLED", "true").lower() in ("true", "1", "yes")
_FVG_ENTRY_PROXIMITY_CENTS = float(os.getenv("MERID_FVG_ENTRY_PROXIMITY_CENTS", "3.0"))
_FVG_EXIT_TIMING_ENABLED = os.getenv("MERID_FVG_EXIT_TIMING_ENABLED", "true").lower() in ("true", "1", "yes")
_FVG_EXIT_PROXIMITY_CENTS = float(os.getenv("MERID_FVG_EXIT_PROXIMITY_CENTS", "2.0"))
_FVG_HOLD_ON_CONFLUENCE_THRESHOLD = float(os.getenv("MERID_FVG_HOLD_ON_CONFLUENCE_THRESHOLD", "0.60"))

# Risk management
_FVG_MAX_TRADES_PER_HOUR = int(os.getenv("MERID_FVG_MAX_TRADES_PER_HOUR", "4"))
_FVG_ENTRY_DEBOUNCE_SECONDS = float(os.getenv("MERID_FVG_ENTRY_DEBOUNCE_SECONDS", "900"))
_FVG_OPPOSING_FVG_CANCEL_CENTS = float(os.getenv("MERID_FVG_OPPOSING_FVG_CANCEL_CENTS", "5.0"))

# Monitoring
_FVG_LOG_SIGNALS = os.getenv("MERID_FVG_LOG_SIGNALS", "true").lower() in ("true", "1", "yes")
_FVG_LARGE_GAP_ALERT_CENTS = float(os.getenv("MERID_FVG_LARGE_GAP_ALERT_CENTS", "10.0"))


def _get_asset_config(asset: str) -> Dict[str, float]:
    """Get asset-specific FVG configuration."""
    asset = (asset or "BTC").upper()
    return {
        "min_gap_cents": float(os.getenv(f"MERID_FVG_{asset}_MIN_GAP_CENTS", os.getenv("MERID_FVG_MIN_GAP_CENTS", "2.0"))),
        "fill_threshold": float(os.getenv(f"MERID_FVG_{asset}_FILL_THRESHOLD", os.getenv("MERID_FVG_FILL_THRESHOLD", "5.0"))),
    }


@dataclass
class FVGSignal:
    """FVG-based trading signal for a specific market."""
    
    ticker: str
    direction: str  # "bullish", "bearish", or "neutral"
    confidence: float  # 0.0-1.0
    nearest_fvg_distance: float  # cents to nearest FVG
    active_fvgs: int
    confluence_score: float  # -1.0 to 1.0, cross-timeframe alignment
    fill_imminent: bool  # True if price is within fill threshold
    
    # Production extension: entry/exit timing
    entry_timing_score: float = 0.0  # 0.0-1.0, higher = better entry timing
    exit_timing_score: float = 0.0  # 0.0-1.0, higher = better exit timing
    position_size_factor: float = 1.0  # Multiplier for position sizing
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "nearest_fvg_distance": round(self.nearest_fvg_distance, 2),
            "active_fvgs": self.active_fvgs,
            "confluence_score": round(self.confluence_score, 4),
            "fill_imminent": self.fill_imminent,
            "entry_timing_score": round(self.entry_timing_score, 4),
            "exit_timing_score": round(self.exit_timing_score, 4),
            "position_size_factor": round(self.position_size_factor, 4),
        }


@dataclass
class FVGEntryExitTiming:
    """FVG-based entry and exit timing recommendation."""
    
    should_enter: bool
    should_exit: bool
    entry_urgency: float  # 0.0-1.0, higher = enter now
    exit_urgency: float  # 0.0-1.0, higher = exit now
    target_price_cents: Optional[float] = None  # Price to target for exit
    stop_price_cents: Optional[float] = None  # Price to use as stop
    reason: str = ""


class FVGIntegrator:
    """Integrates FVG detection with Kalshi market data.
    
    Maintains price history from orderbook updates and feeds it to the FVG store.
    Provides signal generation for trading agents.
    """
    
    def __init__(self) -> None:
        self._store = get_fvg_store()
        self._forecaster = get_fvg_forecaster()
        self._last_price: Dict[str, float] = {}
        self._price_history: Dict[str, List[Tuple[float, float, float, float, float]]] = {}
        # OHLC tracking per ticker per timeframe bucket
        self._current_candle: Dict[str, Dict[str, Any]] = {}
        self._enabled = _FVG_ENABLED
        
        if self._enabled:
            logger.info("FVGIntegrator initialized - FVG analysis ENABLED")
        else:
            logger.info("FVGIntegrator initialized - FVG analysis DISABLED (MERID_FVG_ENABLED=false)")
    
    def is_enabled(self) -> bool:
        return self._enabled
    
    def update_price(
        self,
        ticker: str,
        bid: float,
        ask: float,
        timestamp: Optional[float] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> None:
        """Update FVG store with price from orderbook.
        
        Args:
            ticker: Kalshi market ticker
            bid: Best bid (0-1)
            ask: Best ask (0-1)
            timestamp: Unix timestamp (default: now)
            asset: Underlying asset (BTC, ETH, etc.) - extracted from ticker if not provided
            timeframe: Market timeframe - extracted from ticker if not provided
        """
        if not self._enabled:
            return
        
        ts = timestamp or time.time()
        mid = ((bid + ask) / 2) * 100  # Convert to cents
        
        # Extract asset/timeframe from ticker if not provided
        asset = asset or self._extract_asset_from_ticker(ticker)
        timeframe = timeframe or self._extract_timeframe_from_ticker(ticker)
        
        if not asset or not timeframe:
            return
        
        # Check if price moved enough to warrant FVG update
        last = self._last_price.get(ticker)
        if last is not None:
            if abs(mid - last) < _FVG_MIN_PRICE_CHANGE_CENTS:
                return  # Skip small changes
        
        self._last_price[ticker] = mid
        
        # Build candle from price movement
        self._update_candle(ticker, asset, timeframe, mid, ts)
    
    def _extract_asset_from_ticker(self, ticker: str) -> Optional[str]:
        """Extract asset from Kalshi ticker like KXBTC-15M-T97000."""
        ticker_upper = ticker.upper()
        if "BTC" in ticker_upper or "BITCOIN" in ticker_upper:
            return "BTC"
        elif "ETH" in ticker_upper or "ETHER" in ticker_upper:
            return "ETH"
        elif "SOL" in ticker_upper or "SOLANA" in ticker_upper:
            return "SOL"
        elif "XRP" in ticker_upper or "RIPPLE" in ticker_upper:
            return "XRP"
        elif "DOGE" in ticker_upper or "DOGECOIN" in ticker_upper:
            return "DOGE"
        return None
    
    def _extract_timeframe_from_ticker(self, ticker: str) -> Optional[str]:
        """Extract timeframe from Kalshi ticker like KXBTC-15M-T97000."""
        ticker_upper = ticker.upper()
        if "15M" in ticker_upper:
            return "15m"
        elif "1H" in ticker_upper or "HOURLY" in ticker_upper:
            return "1h"
        elif "4H" in ticker_upper:
            return "4h"
        elif "DAILY" in ticker_upper or "D1" in ticker_upper or ticker_upper.count("D") > 0:
            return "daily"
        elif "WEEKLY" in ticker_upper or "W1" in ticker_upper:
            return "weekly"
        return "1h"  # Default to hourly
    
    def _update_candle(
        self,
        ticker: str,
        asset: str,
        timeframe: str,
        price: float,
        timestamp: float,
    ) -> None:
        """Build synthetic candles from tick data for FVG detection."""
        key = f"{ticker}:{timeframe}"
        
        # Get or create current candle
        candle = self._current_candle.get(key)
        
        # Determine candle period based on timeframe
        period_seconds = self._timeframe_to_seconds(timeframe)
        
        if candle is None or timestamp - candle["start"] >= period_seconds:
            # Close previous candle and start new one
            if candle is not None:
                self._close_candle(key, asset, timeframe)
            
            # Start new candle
            self._current_candle[key] = {
                "start": timestamp,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
            }
        else:
            # Update current candle
            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price
    
    def _timeframe_to_seconds(self, timeframe: str) -> int:
        """Convert timeframe to seconds for candle building."""
        mapping = {
            "15m": 15 * 60,
            "1h": 60 * 60,
            "4h": 4 * 60 * 60,
            "daily": 24 * 60 * 60,
            "weekly": 7 * 24 * 60 * 60,
        }
        return mapping.get(timeframe, 60 * 60)  # Default 1h
    
    def _close_candle(self, key: str, asset: str, timeframe: str) -> None:
        """Close a candle and feed to FVG store."""
        candle = self._current_candle.get(key)
        if candle is None:
            return
        
        # Add to FVG store
        self._store.add_candle(
            asset=asset,
            timeframe=timeframe,
            open_p=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
            timestamp=candle["start"],
        )
        
        # Check for fills
        self._store.check_fills(asset, timeframe, candle["close"], candle["start"])
    
    def get_signal(
        self,
        ticker: str,
        bid: float,
        ask: float,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Optional[FVGSignal]:
        """Generate FVG signal for a market.
        
        Args:
            ticker: Kalshi market ticker
            bid: Current best bid (0-1)
            ask: Current best ask (0-1)
            asset: Underlying asset (extracted from ticker if not provided)
            timeframe: Market timeframe (extracted from ticker if not provided)
        
        Returns:
            FVGSignal or None if no signal
        """
        if not self._enabled:
            return None
        
        asset = asset or self._extract_asset_from_ticker(ticker)
        timeframe = timeframe or self._extract_timeframe_from_ticker(ticker)
        
        if not asset or not timeframe:
            return None
        
        mid = ((bid + ask) / 2) * 100  # Convert to cents
        
        # Get active FVGs
        active_fvgs = self._store.get_active_fvgs(asset, timeframe)
        
        if not active_fvgs:
            return FVGSignal(
                ticker=ticker,
                direction="neutral",
                confidence=0.0,
                nearest_fvg_distance=float('inf'),
                active_fvgs=0,
                confluence_score=0.0,
                fill_imminent=False,
            )
        
        # Find nearest FVG
        nearest = self._store.get_nearest_fvg(asset, timeframe, mid)
        if nearest is None:
            return FVGSignal(
                ticker=ticker,
                direction="neutral",
                confidence=0.0,
                nearest_fvg_distance=float('inf'),
                active_fvgs=len(active_fvgs),
                confluence_score=0.0,
                fill_imminent=False,
            )
        
        distance = nearest.distance_to_fill(mid)
        is_near = nearest.is_within_fill_distance(mid)
        confluence = self._store.get_fvg_confluence_score(asset, mid)
        
        # Determine signal direction with production calibration
        if nearest.direction == "bullish":
            direction = "bullish" if is_near else "neutral"
            # Production: Use configurable base confidence + proximity boost
            base_conf = _FVG_BASE_CONFIDENCE if is_near else (_FVG_BASE_CONFIDENCE * 0.3)
            proximity_bonus = _FVG_PROXIMITY_BOOST if is_near else 0.0
            size_factor = min(1.0, nearest.size / _FVG_LARGE_GAP_ALERT_CENTS)
            confidence = min(1.0, base_conf * size_factor + proximity_bonus)
        else:
            direction = "bearish" if is_near else "neutral"
            base_conf = _FVG_BASE_CONFIDENCE if is_near else (_FVG_BASE_CONFIDENCE * 0.3)
            proximity_bonus = _FVG_PROXIMITY_BOOST if is_near else 0.0
            size_factor = min(1.0, nearest.size / _FVG_LARGE_GAP_ALERT_CENTS)
            confidence = min(1.0, base_conf * size_factor + proximity_bonus)
        
        # Calculate entry/exit timing scores
        entry_timing = self._calculate_entry_timing(nearest, mid, distance, confluence)
        exit_timing = self._calculate_exit_timing(nearest, mid, distance, confluence, active_fvgs)
        
        # Calculate position size factor based on FVG strength
        size_factor = self._calculate_position_size_factor(nearest, confluence, is_near)
        
        if _FVG_LOG_SIGNALS:
            logger.info(
                "[FVG-SIGNAL] %s | dir=%s conf=%.3f dist=%.1fc fvgs=%d confl=%.2f entry=%.2f exit=%.2f size=%.2f",
                ticker, direction, confidence, distance, len(active_fvgs), 
                confluence, entry_timing, exit_timing, size_factor
            )
        
        return FVGSignal(
            ticker=ticker,
            direction=direction,
            confidence=confidence,
            nearest_fvg_distance=distance,
            active_fvgs=len(active_fvgs),
            confluence_score=confluence,
            fill_imminent=is_near,
            entry_timing_score=entry_timing,
            exit_timing_score=exit_timing,
            position_size_factor=size_factor,
        )
    
    def _calculate_entry_timing(
        self, 
        nearest_fvg: Any, 
        current_price: float, 
        distance: float,
        confluence: float
    ) -> float:
        """Calculate entry timing score (0.0-1.0, higher = better entry)."""
        if not _FVG_ENTRY_TIMING_ENABLED:
            return 0.0
        
        # Best entry when price is near but not at FVG edge
        if nearest_fvg.direction == "bullish":
            # For bullish FVG, enter when price is just above bottom (support)
            ideal_entry = nearest_fvg.bottom + (_FVG_ENTRY_PROXIMITY_CENTS / 2)
            entry_zone_width = _FVG_ENTRY_PROXIMITY_CENTS
        else:
            # For bearish FVG, enter when price is just below top (resistance)
            ideal_entry = nearest_fvg.top - (_FVG_ENTRY_PROXIMITY_CENTS / 2)
            entry_zone_width = _FVG_ENTRY_PROXIMITY_CENTS
        
        # Score based on proximity to ideal entry zone
        price_distance = abs(current_price - ideal_entry)
        if price_distance <= entry_zone_width:
            base_score = 1.0 - (price_distance / entry_zone_width)
        else:
            base_score = max(0.0, 0.5 - (price_distance / (entry_zone_width * 2)))
        
        # Boost by confluence score
        return min(1.0, base_score * (1.0 + confluence))
    
    def _calculate_exit_timing(
        self,
        nearest_fvg: Any,
        current_price: float,
        distance: float,
        confluence: float,
        all_fvgs: List[Any],
    ) -> float:
        """Calculate exit timing score (0.0-1.0, higher = consider exiting)."""
        if not _FVG_EXIT_TIMING_ENABLED:
            return 0.0
        
        # Look for opposing FVGs (counter-trend gaps)
        opposing_fvgs = [f for f in all_fvgs if f.direction != nearest_fvg.direction]
        
        if not opposing_fvgs:
            # No opposing FVGs, check if we're approaching nearest FVG fill
            if distance <= _FVG_EXIT_PROXIMITY_CENTS:
                return 0.7  # Consider taking profit near fill
            return 0.0
        
        # Find nearest opposing FVG
        nearest_opposing = min(opposing_fvgs, key=lambda f: abs(f.midpoint() - current_price))
        opp_distance = nearest_opposing.distance_to_fill(current_price)
        
        # High exit urgency if opposing FVG is close (resistance/support ahead)
        if opp_distance <= _FVG_EXIT_PROXIMITY_CENTS:
            return min(1.0, 0.8 + (_FVG_EXIT_PROXIMITY_CENTS - opp_distance) / _FVG_EXIT_PROXIMITY_CENTS * 0.2)
        
        return 0.3  # Moderate exit consideration
    
    def _calculate_position_size_factor(
        self,
        nearest_fvg: Any,
        confluence: float,
        is_near: bool,
    ) -> float:
        """Calculate position size multiplier based on FVG strength."""
        # Base multiplier from config
        base_multiplier = _FVG_SIZE_MULTIPLIER if is_near else 1.0
        
        # Boost for strong confluence
        if confluence >= _FVG_MIN_CONFLUENCE_SCORE:
            confluence_boost = min(0.25, confluence * 0.3)
        else:
            confluence_boost = 0.0
        
        # Size factor for large gaps
        size_factor = min(1.0, nearest_fvg.size / 10.0)
        
        # Calculate final size factor
        size_mult = 1.0 + ((base_multiplier - 1.0) * size_factor) + confluence_boost
        
        # Cap at max boost
        return min(_FVG_MAX_POSITION_BOOST, size_mult)
    
    def get_entry_exit_timing(
        self,
        ticker: str,
        bid: float,
        ask: float,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Optional[FVGEntryExitTiming]:
        """Get FVG-based entry and exit timing recommendation.
        
        Args:
            ticker: Kalshi market ticker
            bid: Current best bid (0-1)
            ask: Current best ask (0-1)
            asset: Underlying asset (extracted from ticker if not provided)
            timeframe: Market timeframe (extracted from ticker if not provided)
        
        Returns:
            FVGEntryExitTiming with entry/exit recommendations
        """
        if not self._enabled:
            return None
        
        signal = self.get_signal(ticker, bid, ask, asset, timeframe)
        if not signal or signal.direction == "neutral":
            return None
        
        mid = ((bid + ask) / 2) * 100
        
        # Determine entry/exit based on signal
        should_enter = signal.entry_timing_score >= 0.5
        should_exit = signal.exit_timing_score >= 0.7
        
        # Calculate target price based on opposing FVG
        asset = asset or self._extract_asset_from_ticker(ticker)
        timeframe = timeframe or self._extract_timeframe_from_ticker(ticker)
        target_price = None
        stop_price = None
        
        if asset and timeframe:
            active = self._store.get_active_fvgs(asset, timeframe)
            opposing = [f for f in active if f.direction != signal.direction]
            
            if opposing:
                # Target the nearest opposing FVG
                nearest_opp = min(opposing, key=lambda f: abs(f.midpoint() - mid))
                target_price = nearest_opp.midpoint()
                
                # Stop at the far side of nearest FVG
                nearest_same = next((f for f in active if f.direction == signal.direction), None)
                if nearest_same:
                    if signal.direction == "bullish":
                        stop_price = nearest_same.bottom
                    else:
                        stop_price = nearest_same.top
        
        return FVGEntryExitTiming(
            should_enter=should_enter,
            should_exit=should_exit,
            entry_urgency=signal.entry_timing_score,
            exit_urgency=signal.exit_timing_score,
            target_price_cents=target_price,
            stop_price_cents=stop_price,
            reason=f"FVG_{signal.direction}_confl_{signal.confluence_score:.2f}",
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get FVG statistics for monitoring."""
        stats = {
            "enabled": self._enabled,
            "tracked_tickers": len(self._last_price),
            "by_asset": {},
        }
        
        for ticker, price in self._last_price.items():
            asset = self._extract_asset_from_ticker(ticker)
            if asset:
                if asset not in stats["by_asset"]:
                    stats["by_asset"][asset] = {
                        "tickers": 0,
                        "active_fvgs": 0,
                    }
                stats["by_asset"][asset]["tickers"] += 1
        
        # Add FVG counts
        for asset in stats["by_asset"]:
            total_fvgs = 0
            for tf in ["15m", "1h", "4h", "daily"]:
                total_fvgs += len(self._store.get_active_fvgs(asset, tf))
            stats["by_asset"][asset]["active_fvgs"] = total_fvgs
        
        return stats


# ── Singleton ────────────────────────────────────────────────────────────

_integrator: Optional[FVGIntegrator] = None


def get_fvg_integrator() -> FVGIntegrator:
    """Get the global FVG integrator singleton."""
    global _integrator
    if _integrator is None:
        _integrator = FVGIntegrator()
    return _integrator


def update_price_from_orderbook(
    ticker: str,
    bid: float,
    ask: float,
    timestamp: Optional[float] = None,
    asset: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> None:
    """Convenience function to update price from orderbook data.
    
    Call this from WS orderbook handlers or market state updates.
    """
    integrator = get_fvg_integrator()
    integrator.update_price(ticker, bid, ask, timestamp, asset, timeframe)


def get_fvg_signal_for_market(
    ticker: str,
    bid: float,
    ask: float,
    asset: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> Optional[FVGSignal]:
    """Convenience function to get FVG signal for a market.
    
    Call this from strategy or trading agent.
    """
    integrator = get_fvg_integrator()
    return integrator.get_signal(ticker, bid, ask, asset, timeframe)


def is_fvg_enabled() -> bool:
    """Check if FVG analysis is enabled."""
    return _FVG_ENABLED


def get_fvg_entry_exit_timing(
    ticker: str,
    bid: float,
    ask: float,
    asset: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> Optional[FVGEntryExitTiming]:
    """Convenience function to get FVG-based entry/exit timing.
    
    Call this from strategy or position management.
    
    Returns:
        FVGEntryExitTiming with entry/exit recommendations, or None if disabled
    """
    integrator = get_fvg_integrator()
    return integrator.get_entry_exit_timing(ticker, bid, ask, asset, timeframe)


def get_fvg_position_size_factor(
    ticker: str,
    bid: float,
    ask: float,
    asset: Optional[str] = None,
    timeframe: Optional[str] = None,
) -> float:
    """Get FVG-based position size factor (1.0 = no change).
    
    Call this from position sizing logic.
    
    Returns:
        Position size multiplier (e.g., 1.25 = 25% larger position)
    """
    integrator = get_fvg_integrator()
    signal = integrator.get_signal(ticker, bid, ask, asset, timeframe)
    if signal:
        return signal.position_size_factor
    return 1.0
