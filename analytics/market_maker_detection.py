"""Market Maker Detection for Adverse Selection Avoidance.

Detects market maker presence in orderbook to avoid adverse selection and
being picked off by informed traders. Identifies toxic flow patterns and
provides recommendations for order timing and sizing.

Key Features:
- Orderbook imbalance analysis
- Spread analysis for market maker presence
- Trade timing recommendations
- Toxic flow detection
- Adverse selection risk scoring

Usage:
    from analytics.market_maker_detection import get_market_maker_detector
    
    detector = get_market_maker_detector()
    
    # Analyze market for market maker presence
    result = detector.analyze_market(
        ticker="KXBTC15M-26MAY092115-15",
        orderbook=orderbook_data
    )
    
    # Check if it's safe to trade
    if result.risk_score > 0.7:
        logger.warning("High adverse selection risk")
        return
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math

from utils.logger import get_logger

logger = get_logger("analytics.market_maker_detection")


class RiskLevel(str, Enum):
    """Adverse selection risk level."""
    LOW = "low"           # Low risk, safe to trade
    MEDIUM = "medium"     # Moderate risk, proceed with caution
    HIGH = "high"         # High risk, avoid trading
    CRITICAL = "critical"  # Critical risk, do not trade


@dataclass
class OrderbookSnapshot:
    """Snapshot of orderbook at a point in time."""
    ticker: str
    timestamp: datetime
    bids: List[Tuple[int, int]]  # List of (price_cents, quantity)
    asks: List[Tuple[int, int]]  # List of (price_cents, quantity)
    spread_cents: int = 0
    mid_cents: int = 0
    
    def __post_init__(self):
        if self.bids and self.asks:
            self.spread_cents = self.asks[0][0] - self.bids[0][0]
            self.mid_cents = (self.bids[0][0] + self.asks[0][0]) // 2


@dataclass
class MarketMakerDetectionResult:
    """Result of market maker detection analysis."""
    ticker: str
    timestamp: datetime
    
    # Risk assessment
    risk_level: RiskLevel
    risk_score: float  # 0-1, higher = more risky
    
    # Market maker indicators
    market_maker_present: bool
    market_maker_confidence: float  # 0-1
    imbalance_score: float  # -1 to 1, negative = bid-heavy, positive = ask-heavy
    
    # Spread analysis
    spread_cents: int
    spread_pct: float
    spread_compression: bool  # Is spread unusually tight?
    
    # Flow analysis
    toxic_flow_detected: bool
    toxic_flow_score: float  # 0-1
    
    # Recommendations
    should_trade: bool
    recommended_action: str
    reason: str
    
    # Additional metrics
    bid_depth: int
    ask_depth: int
    depth_ratio: float


@dataclass
class MarketMakerDetectionConfig:
    """Market maker detection configuration."""
    min_spread_threshold_pct: float = 0.5  # Minimum spread to consider tight
    max_imbalance_threshold: float = 0.7  # Maximum imbalance before warning
    toxic_flow_threshold: float = 0.6  # Threshold for toxic flow detection
    risk_score_threshold: float = 0.7  # Threshold for avoiding trades
    depth_levels_to_analyze: int = 5  # Number of price levels to analyze
    enable_adaptive_thresholds: bool = True  # Enable adaptive thresholds


class MarketMakerDetector:
    """Market maker detection engine.
    
    Detects market maker presence and adverse selection risk to avoid
    being picked off by informed traders.
    """
    
    _instance: Optional["MarketMakerDetector"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize the market maker detector."""
        self._config = MarketMakerDetectionConfig()
        self._historical_spreads: Dict[str, List[float]] = {}
        self._historical_lock = threading.Lock()
        self._detection_history: List[MarketMakerDetectionResult] = []
        self._history_lock = threading.Lock()
        logger.info("MarketMakerDetector initialized")
    
    def get_config(self) -> MarketMakerDetectionConfig:
        """Get the market maker detection configuration."""
        return self._config
    
    def set_config(self, config: MarketMakerDetectionConfig):
        """Update the market maker detection configuration."""
        self._config = config
        logger.info("Market maker detection configuration updated")
    
    def analyze_market(
        self,
        ticker: str,
        orderbook: Optional[OrderbookSnapshot] = None,
        bids: Optional[List[Tuple[int, int]]] = None,
        asks: Optional[List[Tuple[int, int]]] = None
    ) -> MarketMakerDetectionResult:
        """Analyze market for market maker presence and adverse selection risk.
        
        Args:
            ticker: Market ticker
            orderbook: Orderbook snapshot (or provide bids/asks separately)
            bids: List of (price_cents, quantity) for bids
            asks: List of (price_cents, quantity) for asks
            
        Returns:
            MarketMakerDetectionResult
        """
        timestamp = datetime.now(timezone.utc)
        
        # Create orderbook snapshot if not provided
        if orderbook is None:
            if bids is None or asks is None:
                return self._create_default_result(ticker, timestamp, "No orderbook data")
            orderbook = OrderbookSnapshot(
                ticker=ticker,
                timestamp=timestamp,
                bids=bids,
                asks=asks
            )
        
        # Analyze spread
        spread_cents = orderbook.spread_cents
        spread_pct = self._calculate_spread_pct(spread_cents, orderbook.mid_cents)
        spread_compression = spread_pct < self._config.min_spread_threshold_pct
        
        # Analyze orderbook imbalance
        imbalance_score, bid_depth, ask_depth, depth_ratio = self._analyze_orderbook_imbalance(
            orderbook.bids, orderbook.asks
        )
        
        # Detect market maker presence
        market_maker_present, mm_confidence = self._detect_market_maker(
            orderbook, spread_compression, imbalance_score
        )
        
        # Detect toxic flow
        toxic_flow_detected, toxic_flow_score = self._detect_toxic_flow(
            ticker, orderbook, imbalance_score
        )
        
        # Calculate overall risk score
        risk_score = self._calculate_risk_score(
            market_maker_present, mm_confidence,
            spread_compression, imbalance_score,
            toxic_flow_detected, toxic_flow_score
        )
        
        # Determine risk level
        risk_level = self._determine_risk_level(risk_score)
        
        # Generate recommendation
        should_trade, recommended_action, reason = self._generate_recommendation(
            risk_level, market_maker_present, spread_compression, toxic_flow_detected
        )
        
        result = MarketMakerDetectionResult(
            ticker=ticker,
            timestamp=timestamp,
            risk_level=risk_level,
            risk_score=risk_score,
            market_maker_present=market_maker_present,
            market_maker_confidence=mm_confidence,
            imbalance_score=imbalance_score,
            spread_cents=spread_cents,
            spread_pct=spread_pct,
            spread_compression=spread_compression,
            toxic_flow_detected=toxic_flow_detected,
            toxic_flow_score=toxic_flow_score,
            should_trade=should_trade,
            recommended_action=recommended_action,
            reason=reason,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            depth_ratio=depth_ratio
        )
        
        # Store in history
        with self._history_lock:
            self._detection_history.append(result)
            if len(self._detection_history) > 1000:
                self._detection_history = self._detection_history[-1000:]
        
        # Update historical spread data
        self._update_historical_spreads(ticker, spread_pct)
        
        return result
    
    def _create_default_result(
        self,
        ticker: str,
        timestamp: datetime,
        reason: str
    ) -> MarketMakerDetectionResult:
        """Create a default result when analysis cannot be performed."""
        return MarketMakerDetectionResult(
            ticker=ticker,
            timestamp=timestamp,
            risk_level=RiskLevel.MEDIUM,
            risk_score=0.5,
            market_maker_present=False,
            market_maker_confidence=0.0,
            imbalance_score=0.0,
            spread_cents=0,
            spread_pct=0.0,
            spread_compression=False,
            toxic_flow_detected=False,
            toxic_flow_score=0.0,
            should_trade=False,
            recommended_action="WAIT",
            reason=reason,
            bid_depth=0,
            ask_depth=0,
            depth_ratio=0.0
        )
    
    def _calculate_spread_pct(self, spread_cents: int, mid_cents: int) -> float:
        """Calculate spread as percentage of mid price.
        
        Args:
            spread_cents: Spread in cents
            mid_cents: Mid price in cents
            
        Returns:
            Spread percentage
        """
        if mid_cents == 0:
            return 0.0
        return (spread_cents / mid_cents) * 100
    
    def _analyze_orderbook_imbalance(
        self,
        bids: List[Tuple[int, int]],
        asks: List[Tuple[int, int]]
    ) -> Tuple[float, int, int, float]:
        """Analyze orderbook imbalance.
        
        Args:
            bids: List of (price_cents, quantity) for bids
            asks: List of (price_cents, quantity) for asks
            
        Returns:
            Tuple of (imbalance_score, bid_depth, ask_depth, depth_ratio)
        """
        # Calculate total depth at top N levels
        n_levels = self._config.depth_levels_to_analyze
        bid_depth = sum(q for _, q in bids[:n_levels])
        ask_depth = sum(q for _, q in asks[:n_levels])
        
        # Calculate imbalance score (-1 to 1)
        total_depth = bid_depth + ask_depth
        if total_depth == 0:
            imbalance_score = 0.0
            depth_ratio = 1.0
        else:
            imbalance_score = (ask_depth - bid_depth) / total_depth
            depth_ratio = ask_depth / bid_depth if bid_depth > 0 else float('inf')
        
        return imbalance_score, bid_depth, ask_depth, depth_ratio
    
    def _detect_market_maker(
        self,
        orderbook: OrderbookSnapshot,
        spread_compression: bool,
        imbalance_score: float
    ) -> Tuple[bool, float]:
        """Detect market maker presence in orderbook.
        
        Args:
            orderbook: Orderbook snapshot
            spread_compression: Whether spread is compressed
            imbalance_score: Orderbook imbalance score
            
        Returns:
            Tuple of (market_maker_present, confidence)
        """
        confidence = 0.0
        indicators = 0
        
        # Indicator 1: Tight spread (market makers maintain tight spreads)
        if spread_compression:
            confidence += 0.4
            indicators += 1
        
        # Indicator 2: Balanced orderbook (market makers provide liquidity on both sides)
        if abs(imbalance_score) < 0.3:
            confidence += 0.3
            indicators += 1
        
        # Indicator 3: Deep orderbook (market makers provide depth)
        total_depth = sum(q for _, q in orderbook.bids[:5]) + sum(q for _, q in orderbook.asks[:5])
        if total_depth > 100:
            confidence += 0.3
            indicators += 1
        
        # Market maker present if at least 2 indicators detected
        market_maker_present = indicators >= 2
        
        return market_maker_present, min(confidence, 1.0)
    
    def _detect_toxic_flow(
        self,
        ticker: str,
        orderbook: OrderbookSnapshot,
        imbalance_score: float
    ) -> Tuple[bool, float]:
        """Detect toxic flow patterns.
        
        Args:
            ticker: Market ticker
            orderbook: Orderbook snapshot
            imbalance_score: Current imbalance score
            
        Returns:
            Tuple of (toxic_flow_detected, toxic_flow_score)
        """
        toxic_indicators = 0
        toxic_score = 0.0
        
        # Indicator 1: Extreme imbalance (could signal informed trading)
        if abs(imbalance_score) > self._config.max_imbalance_threshold:
            toxic_score += 0.4
            toxic_indicators += 1
        
        # Indicator 2: Rapid spread widening (could signal adverse selection)
        historical_spreads = self._get_historical_spreads(ticker)
        if len(historical_spreads) >= 5:
            recent_avg = sum(historical_spreads[-5:]) / 5
            current_spread_pct = self._calculate_spread_pct(orderbook.spread_cents, orderbook.mid_cents)
            if current_spread_pct > recent_avg * 1.5:
                toxic_score += 0.3
                toxic_indicators += 1
        
        # Indicator 3: Shallow depth (could indicate market maker pulling liquidity)
        total_depth = sum(q for _, q in orderbook.bids[:3]) + sum(q for _, q in orderbook.asks[:3])
        if total_depth < 50:
            toxic_score += 0.3
            toxic_indicators += 1
        
        toxic_flow_detected = toxic_score > self._config.toxic_flow_threshold
        
        return toxic_flow_detected, min(toxic_score, 1.0)
    
    def _calculate_risk_score(
        self,
        market_maker_present: bool,
        mm_confidence: float,
        spread_compression: bool,
        imbalance_score: float,
        toxic_flow_detected: bool,
        toxic_flow_score: float
    ) -> float:
        """Calculate overall adverse selection risk score.
        
        Args:
            market_maker_present: Whether market maker is present
            mm_confidence: Confidence in market maker detection
            spread_compression: Whether spread is compressed
            imbalance_score: Orderbook imbalance score
            toxic_flow_detected: Whether toxic flow is detected
            toxic_flow_score: Toxic flow score
            
        Returns:
            Risk score (0-1)
        """
        risk_score = 0.0
        
        # Market maker presence reduces risk (they provide liquidity)
        if market_maker_present:
            risk_score -= 0.2 * mm_confidence
        
        # Spread compression is good (indicates healthy market)
        if spread_compression:
            risk_score -= 0.1
        
        # Extreme imbalance increases risk
        if abs(imbalance_score) > self._config.max_imbalance_threshold:
            risk_score += 0.3 * abs(imbalance_score)
        
        # Toxic flow significantly increases risk
        if toxic_flow_detected:
            risk_score += 0.5 * toxic_flow_score
        
        # Normalize to 0-1 range
        risk_score = max(0.0, min(1.0, risk_score + 0.5))
        
        return risk_score
    
    def _determine_risk_level(self, risk_score: float) -> RiskLevel:
        """Determine risk level from risk score.
        
        Args:
            risk_score: Risk score (0-1)
            
        Returns:
            RiskLevel
        """
        if risk_score < 0.3:
            return RiskLevel.LOW
        elif risk_score < 0.5:
            return RiskLevel.MEDIUM
        elif risk_score < 0.7:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL
    
    def _generate_recommendation(
        self,
        risk_level: RiskLevel,
        market_maker_present: bool,
        spread_compression: bool,
        toxic_flow_detected: bool
    ) -> Tuple[bool, str, str]:
        """Generate trading recommendation.
        
        Args:
            risk_level: Risk level
            market_maker_present: Whether market maker is present
            spread_compression: Whether spread is compressed
            toxic_flow_detected: Whether toxic flow is detected
            
        Returns:
            Tuple of (should_trade, recommended_action, reason)
        """
        if risk_level == RiskLevel.CRITICAL:
            return False, "AVOID", "Critical adverse selection risk detected"
        
        if risk_level == RiskLevel.HIGH:
            if toxic_flow_detected:
                return False, "WAIT", "Toxic flow detected, wait for conditions to improve"
            return False, "REDUCE", "Reduce position size due to elevated risk"
        
        if risk_level == RiskLevel.MEDIUM:
            if not market_maker_present:
                return True, "CAUTION", "Proceed with caution, no market maker present"
            return True, "PROCEED", "Conditions acceptable for trading"
        
        # LOW risk
        return True, "PROCEED", "Low risk, favorable conditions for trading"
    
    def _update_historical_spreads(self, ticker: str, spread_pct: float):
        """Update historical spread data for a ticker.
        
        Args:
            ticker: Market ticker
            spread_pct: Current spread percentage
        """
        with self._historical_lock:
            if ticker not in self._historical_spreads:
                self._historical_spreads[ticker] = []
            
            self._historical_spreads[ticker].append(spread_pct)
            
            # Keep last 100 observations
            if len(self._historical_spreads[ticker]) > 100:
                self._historical_spreads[ticker] = self._historical_spreads[ticker][-100:]
    
    def _get_historical_spreads(self, ticker: str) -> List[float]:
        """Get historical spread data for a ticker.
        
        Args:
            ticker: Market ticker
            
        Returns:
            List of historical spread percentages
        """
        with self._historical_lock:
            return self._historical_spreads.get(ticker, []).copy()
    
    def get_detection_history(self, ticker: Optional[str] = None, limit: int = 100) -> List[MarketMakerDetectionResult]:
        """Get detection history.
        
        Args:
            ticker: Filter by ticker (optional)
            limit: Maximum number of results to return
            
        Returns:
            List of detection results
        """
        with self._history_lock:
            history = self._detection_history
            
            if ticker:
                history = [r for r in history if r.ticker == ticker]
            
            return history[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of market maker detection activity.
        
        Returns:
            Summary dictionary
        """
        with self._history_lock:
            total_detections = len(self._detection_history)
            
            # Calculate risk distribution
            risk_distribution = {
                "low": 0,
                "medium": 0,
                "high": 0,
                "critical": 0
            }
            
            for result in self._detection_history:
                risk_distribution[result.risk_level.value] += 1
            
            # Calculate market maker presence rate
            mm_present_count = sum(1 for r in self._detection_history if r.market_maker_present)
            mm_present_rate = mm_present_count / total_detections if total_detections > 0 else 0
        
        with self._historical_lock:
            tracked_tickers = list(self._historical_spreads.keys())
        
        return {
            "total_detections": total_detections,
            "tracked_tickers": len(tracked_tickers),
            "risk_distribution": risk_distribution,
            "market_maker_present_rate": mm_present_rate,
            "tickers": tracked_tickers
        }


# Singleton accessor
_market_maker_detector: Optional[MarketMakerDetector] = None
_market_maker_detector_lock = threading.Lock()


def get_market_maker_detector() -> MarketMakerDetector:
    """Get the singleton MarketMakerDetector instance."""
    global _market_maker_detector
    if _market_maker_detector is None:
        with _market_maker_detector_lock:
            if _market_maker_detector is None:
                _market_maker_detector = MarketMakerDetector()
    return _market_maker_detector
