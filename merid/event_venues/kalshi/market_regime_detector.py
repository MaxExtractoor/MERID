"""
Market Regime Detector for Prediction Markets

Classifies markets into maker-dominated, taker-dominated, or neutral regimes
based on orderbook state (spread, depth, trade tape, refresh rate).

Research source: https://simplefunctions.dev/concepts/maker-taker-regime-in-pms
"""

import logging
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime classification"""
    MAKER_DOMINATED = "maker_dominated"
    TAKER_DOMINATED = "taker_dominated"
    NEUTRAL = "neutral"


class ExecutionMode(Enum):
    """Execution mode based on regime"""
    MAKER = "maker"  # Passive limit order
    TAKER = "taker"  # Aggressive market order
    STAGED_IOC = "staged_ioc"  # Immediate-or-cancel with splitting
    PASSIVE_QUOTE = "passive_quote"  # Quote inside spread


@dataclass
class RegimeMetrics:
    """Metrics used for regime classification"""
    spread_cents: float
    bid_depth: float
    ask_depth: float
    trade_frequency: float  # trades per minute
    refresh_rate: float  # quote refreshes per second
    mid_price: float


@dataclass
class RegimeClassification:
    """Regime classification result"""
    regime: MarketRegime
    execution_mode: ExecutionMode
    metrics: RegimeMetrics
    confidence: float  # 0.0 to 1.0
    liquidity_availability_score: float = 0.0  # LAS: (bid_depth + ask_depth) / (1 + spread_cents)


class MarketRegimeDetector:
    """
    Detects market regime from orderbook state and trade tape.
    
    Regime classification logic (from SimpleFunctions research):
    - Maker-dominated: Wide spread + thick depth + slow refresh + low trade frequency
    - Taker-dominated: Tight spread + thin depth + fast refresh + high trade frequency
    - Neutral: Mixed signals
    """
    
    # Thresholds for regime classification
    WIDE_SPREAD_THRESHOLD_CENTS = 4.0  # Spread > 4c = wide
    THICK_DEPTH_THRESHOLD = 200.0  # Depth > 200 contracts = thick
    SLOW_REFRESH_THRESHOLD = 0.5  # Refresh < 0.5/s = slow
    LOW_TRADE_FREQUENCY_THRESHOLD = 1.0  # < 1 trade/min = low
    
    TIGHT_SPREAD_THRESHOLD_CENTS = 2.0  # Spread < 2c = tight
    THIN_DEPTH_THRESHOLD = 50.0  # Depth < 50 contracts = thin
    FAST_REFRESH_THRESHOLD = 2.0  # Refresh > 2/s = fast
    HIGH_TRADE_FREQUENCY_THRESHOLD = 5.0  # > 5 trades/min = high
    
    def __init__(self):
        self._trade_history: Dict[str, list] = {}  # ticker -> list of trade timestamps
        self._quote_refresh_history: Dict[str, list] = {}  # ticker -> list of refresh timestamps
        
    def classify_regime(
        self,
        ticker: str,
        spread_cents: float,
        bid_depth: float,
        ask_depth: float,
        mid_price: float,
        trade_timestamps: Optional[list] = None,
        quote_refresh_timestamps: Optional[list] = None
    ) -> RegimeClassification:
        """
        Classify market regime from orderbook state.
        
        Args:
            ticker: Market ticker
            spread_cents: Bid-ask spread in cents
            bid_depth: Total depth at bid
            ask_depth: Total depth at ask
            mid_price: Mid price in cents
            trade_timestamps: List of recent trade timestamps (optional)
            quote_refresh_timestamps: List of recent quote refresh timestamps (optional)
            
        Returns:
            RegimeClassification with regime, execution mode, and metrics
        """
        # Calculate trade frequency (trades per minute)
        if trade_timestamps and len(trade_timestamps) > 1:
            time_window = (trade_timestamps[-1] - trade_timestamps[0]) / 60.0  # minutes
            trade_frequency = len(trade_timestamps) / max(time_window, 0.1)
        else:
            trade_frequency = 0.0
            
        # Calculate refresh rate (refreshes per second)
        if quote_refresh_timestamps and len(quote_refresh_timestamps) > 1:
            time_window = quote_refresh_timestamps[-1] - quote_refresh_timestamps[0]  # seconds
            refresh_rate = len(quote_refresh_timestamps) / max(time_window, 1.0)
        else:
            refresh_rate = 0.0
            
        # Create metrics
        metrics = RegimeMetrics(
            spread_cents=spread_cents,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            trade_frequency=trade_frequency,
            refresh_rate=refresh_rate,
            mid_price=mid_price
        )
        
        # Classify regime
        regime = self._classify_from_metrics(metrics)
        
        # Select execution mode based on regime
        execution_mode = self._select_execution_mode(regime, metrics)
        
        # Calculate confidence (how strongly signals align)
        confidence = self._calculate_confidence(regime, metrics)
        
        # Calculate Liquidity Availability Score (LAS)
        # Formula from SimpleFunctions: LAS = (bid_depth + ask_depth) / (1 + spread_cents)
        # This combines depth and spread into a single liquidity metric
        liquidity_availability_score = self._calculate_liquidity_availability_score(metrics)
        
        return RegimeClassification(
            regime=regime,
            execution_mode=execution_mode,
            metrics=metrics,
            confidence=confidence,
            liquidity_availability_score=liquidity_availability_score
        )
    
    def _classify_from_metrics(self, metrics: RegimeMetrics) -> MarketRegime:
        """Classify regime from metrics"""
        # Check for maker-dominated signals
        maker_signals = 0
        if metrics.spread_cents > self.WIDE_SPREAD_THRESHOLD_CENTS:
            maker_signals += 1
        if metrics.bid_depth > self.THICK_DEPTH_THRESHOLD and metrics.ask_depth > self.THICK_DEPTH_THRESHOLD:
            maker_signals += 1
        if metrics.refresh_rate < self.SLOW_REFRESH_THRESHOLD:
            maker_signals += 1
        if metrics.trade_frequency < self.LOW_TRADE_FREQUENCY_THRESHOLD:
            maker_signals += 1
            
        # Check for taker-dominated signals
        taker_signals = 0
        if metrics.spread_cents < self.TIGHT_SPREAD_THRESHOLD_CENTS:
            taker_signals += 1
        if metrics.bid_depth < self.THIN_DEPTH_THRESHOLD or metrics.ask_depth < self.THIN_DEPTH_THRESHOLD:
            taker_signals += 1
        if metrics.refresh_rate > self.FAST_REFRESH_THRESHOLD:
            taker_signals += 1
        if metrics.trade_frequency > self.HIGH_TRADE_FREQUENCY_THRESHOLD:
            taker_signals += 1
            
        # Classify based on signal strength
        if maker_signals >= 3:
            return MarketRegime.MAKER_DOMINATED
        elif taker_signals >= 3:
            return MarketRegime.TAKER_DOMINATED
        else:
            return MarketRegime.NEUTRAL
    
    def _select_execution_mode(self, regime: MarketRegime, metrics: RegimeMetrics) -> ExecutionMode:
        """
        Select execution mode based on regime.
        
        Key insight from SimpleFunctions:
        - Maker-dominated: Use taker (cross spread, makers are defensive)
        - Taker-dominated: Use maker (provide liquidity, makers withdrew)
        - Neutral: Use thesis-based (default to taker for now)
        
        ENHANCEMENT (2026-08-01): Add spread percentage guard for extreme spreads
        - Even in maker-dominated regimes, if spread is > 100% of price, use maker mode
        - This prevents crossing massive spreads that would destroy edge
        """
        # Calculate spread percentage first (used in multiple conditions)
        spread_pct = (metrics.spread_cents / metrics.mid_price) * 100 if metrics.mid_price > 0 else 0
        
        # CRITICAL FIX: Guard against extreme spreads regardless of regime
        # If spread > 100% of contract value, never cross as taker
        if spread_pct > 100:
            logger.warning(
                "[REGIME-EXECUTION-OVERRIDE] regime=%s spread_pct=%.2f%% > 100%% - forcing MAKER mode to avoid spread destruction",
                regime.value, spread_pct
            )
            return ExecutionMode.MAKER
        
        if regime == MarketRegime.MAKER_DOMINATED:
            # Makers are providing liquidity - use maker execution by default
            # Only cross as taker if spread is extremely tight (< 5%)
            if spread_pct < 5:
                logger.info(
                    "[REGIME-EXECUTION-ADJUST] regime=maker_dominated spread_pct=%.2f%% < 5%% - using TAKER instead of MAKER",
                    spread_pct
                )
                return ExecutionMode.TAKER
            return ExecutionMode.MAKER
        elif regime == MarketRegime.TAKER_DOMINATED:
            # Makers withdrew - provide liquidity with passive quote
            return ExecutionMode.MAKER
        else:
            # Neutral - use adaptive routing based on spread percentage
            if spread_pct > 30:  # Very wide spread - use maker
                return ExecutionMode.MAKER
            elif spread_pct > 10:  # Moderate spread - use staged IOC
                return ExecutionMode.STAGED_IOC
            else:  # Tight spread - use taker
                return ExecutionMode.TAKER
    
    def _calculate_liquidity_availability_score(self, metrics: RegimeMetrics) -> float:
        """
        Calculate Liquidity Availability Score (LAS).
        
        Formula from SimpleFunctions research:
        LAS = (bid_depth + ask_depth) / (1 + spread_cents)
        
        This metric combines depth and spread into a single score:
        - Higher depth = better liquidity
        - Higher spread = worse liquidity (penalized)
        
        A higher LAS indicates better liquidity availability for execution.
        
        Args:
            metrics: RegimeMetrics containing spread and depth information
            
        Returns:
            Liquidity availability score (higher is better)
        """
        total_depth = metrics.bid_depth + metrics.ask_depth
        spread_penalty = 1.0 + metrics.spread_cents
        
        las = total_depth / spread_penalty if spread_penalty > 0 else 0.0
        
        logger.debug(
            "[LAS-CALC] bid_depth=%.0f ask_depth=%.0f spread_cents=%.2f LAS=%.2f",
            metrics.bid_depth, metrics.ask_depth, metrics.spread_cents, las
        )
        
        return las
    
    def _calculate_confidence(self, regime: MarketRegime, metrics: RegimeMetrics) -> float:
        """Calculate confidence in regime classification (0.0 to 1.0)"""
        if regime == MarketRegime.NEUTRAL:
            return 0.5  # Low confidence for neutral
            
        # Count how many signals align with the regime
        aligned_signals = 0
        total_signals = 4
        
        if regime == MarketRegime.MAKER_DOMINATED:
            if metrics.spread_cents > self.WIDE_SPREAD_THRESHOLD_CENTS:
                aligned_signals += 1
            if metrics.bid_depth > self.THICK_DEPTH_THRESHOLD and metrics.ask_depth > self.THICK_DEPTH_THRESHOLD:
                aligned_signals += 1
            if metrics.refresh_rate < self.SLOW_REFRESH_THRESHOLD:
                aligned_signals += 1
            if metrics.trade_frequency < self.LOW_TRADE_FREQUENCY_THRESHOLD:
                aligned_signals += 1
        elif regime == MarketRegime.TAKER_DOMINATED:
            if metrics.spread_cents < self.TIGHT_SPREAD_THRESHOLD_CENTS:
                aligned_signals += 1
            if metrics.bid_depth < self.THIN_DEPTH_THRESHOLD or metrics.ask_depth < self.THIN_DEPTH_THRESHOLD:
                aligned_signals += 1
            if metrics.refresh_rate > self.FAST_REFRESH_THRESHOLD:
                aligned_signals += 1
            if metrics.trade_frequency > self.HIGH_TRADE_FREQUENCY_THRESHOLD:
                aligned_signals += 1
                
        return aligned_signals / total_signals


# Singleton instance
_regime_detector: Optional[MarketRegimeDetector] = None


def get_regime_detector() -> MarketRegimeDetector:
    """Get singleton regime detector instance"""
    global _regime_detector
    if _regime_detector is None:
        _regime_detector = MarketRegimeDetector()
    return _regime_detector
