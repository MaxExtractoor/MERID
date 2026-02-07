"""
MERID OPS - Signal Generator

Production implementation of OPS's signal generation and intent proposal.
Connects to the inter-system API to propose trading intents to GOV.

Authority:
- OPS can signal but cannot execute
- OPS cannot move capital
- OPS cannot veto
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("ops.signal_generator")


class SignalType(Enum):
    """Types of trading signals."""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    TREND_FOLLOWING = "trend_following"
    ARBITRAGE = "arbitrage"
    SENTIMENT = "sentiment"
    COMPOSITE = "composite"


class SignalStrength(Enum):
    """Signal strength levels."""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


@dataclass
class TradingSignal:
    """A trading signal from OPS."""
    signal_id: str
    signal_type: SignalType
    asset: str
    direction: str  # LONG or SHORT
    strength: SignalStrength
    confidence: float
    
    # Context
    regime: str
    regime_confidence: float
    epistemic_confidence: float
    
    # Risk metrics
    expected_return: float
    max_drawdown: float
    sharpe_estimate: float
    p_loss: float
    
    # Sources
    sources: List[str] = field(default_factory=list)
    
    # Timing
    generated_at: float = field(default_factory=time.time)
    valid_until: float = 0.0
    
    # Status
    proposed: bool = False
    intent_id: Optional[str] = None
    
    def __post_init__(self):
        if self.valid_until == 0.0:
            self.valid_until = self.generated_at + 3600  # 1 hour default
    
    def is_valid(self) -> bool:
        return time.time() < self.valid_until
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "signal_type": self.signal_type.value,
            "asset": self.asset,
            "direction": self.direction,
            "strength": self.strength.value,
            "confidence": round(self.confidence, 4),
            "regime": self.regime,
            "regime_confidence": round(self.regime_confidence, 4),
            "epistemic_confidence": round(self.epistemic_confidence, 4),
            "expected_return": round(self.expected_return, 6),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_estimate": round(self.sharpe_estimate, 2),
            "p_loss": round(self.p_loss, 4),
            "sources": self.sources,
            "generated_at": self.generated_at,
            "valid_until": self.valid_until,
            "proposed": self.proposed,
            "intent_id": self.intent_id,
        }


@dataclass
class SignalGeneratorConfig:
    """Configuration for signal generator."""
    min_confidence: float = 0.5
    min_regime_confidence: float = 0.6
    min_epistemic_confidence: float = 0.5
    max_p_loss: float = 0.4
    min_sharpe: float = 0.5
    max_drawdown: float = 0.10
    default_notional: float = 10000.0
    max_notional: float = 100000.0
    signal_ttl_seconds: float = 3600.0


class SignalGenerator:
    """
    OPS's signal generation and intent proposal system.
    
    Responsibilities:
    - Aggregate signals from multiple sources
    - Apply regime and epistemic filters
    - Generate trading signals
    - Propose intents to GOV via inter-system API
    """
    
    def __init__(self, config: Optional[SignalGeneratorConfig] = None):
        self._config = config or SignalGeneratorConfig()
        self._signals: Dict[str, TradingSignal] = {}
        self._proposed_intents: Dict[str, str] = {}  # signal_id -> intent_id
        
        # OPS component integrations
        self._regime_detector = None
        self._anomaly_detector = None
        self._epistemic_engine = None
        self._conflict_detector = None
        self._entropy_tracker = None
        
        # Inter-system API
        self._intersystem_api = None
        
        # Callbacks
        self._on_signal_generated: Optional[Callable[[TradingSignal], None]] = None
        self._on_intent_proposed: Optional[Callable[[TradingSignal, str], None]] = None
        
        # Statistics
        self._signals_generated = 0
        self._intents_proposed = 0
        self._signals_filtered = 0
        
        logger.info("Signal generator initialized")
    
    def initialize_components(self) -> None:
        """Initialize OPS component integrations."""
        try:
            from ops.regime_detection import get_regime_detector
            self._regime_detector = get_regime_detector()
        except Exception as e:
            logger.warning("Could not initialize regime detector: %s", e)
        
        try:
            from ops.anomaly_detection import get_anomaly_detection
            self._anomaly_detector = get_anomaly_detection()
        except Exception as e:
            logger.warning("Could not initialize anomaly detector: %s", e)
        
        try:
            from ops.epistemic_confidence import get_epistemic_engine
            self._epistemic_engine = get_epistemic_engine()
        except Exception as e:
            logger.warning("Could not initialize epistemic engine: %s", e)
        
        try:
            from ops.conflict_detector import get_conflict_detector
            self._conflict_detector = get_conflict_detector()
        except Exception as e:
            logger.warning("Could not initialize conflict detector: %s", e)
        
        try:
            from ops.signal_entropy import get_entropy_tracker
            self._entropy_tracker = get_entropy_tracker()
        except Exception as e:
            logger.warning("Could not initialize entropy tracker: %s", e)
        
        try:
            from core.intersystem_api import get_intersystem_api
            self._intersystem_api = get_intersystem_api()
        except Exception as e:
            logger.warning("Could not initialize inter-system API: %s", e)
    
    def generate_signal(
        self,
        signal_type: SignalType,
        asset: str,
        direction: str,
        raw_confidence: float,
        expected_return: float,
        sources: Optional[List[str]] = None,
    ) -> Optional[TradingSignal]:
        """
        Generate a trading signal.
        
        Applies regime, epistemic, and risk filters.
        Returns None if signal is filtered out.
        """
        import uuid
        
        # Get current regime
        regime = "UNKNOWN"
        regime_confidence = 0.5
        if self._regime_detector:
            state = self._regime_detector.get_current_state()
            if state:
                regime = state.regime.value
                regime_confidence = state.confidence
        
        # Get epistemic confidence
        epistemic_confidence = 0.5
        if self._epistemic_engine:
            snapshot = self._epistemic_engine.get_snapshot()
            if snapshot:
                epistemic_confidence = snapshot.overall_confidence
        
        # Apply confidence adjustments
        adjusted_confidence = raw_confidence * regime_confidence * epistemic_confidence
        
        # Check minimum thresholds
        if adjusted_confidence < self._config.min_confidence:
            self._signals_filtered += 1
            logger.debug(
                "Signal filtered: confidence %.2f < %.2f",
                adjusted_confidence, self._config.min_confidence
            )
            return None
        
        if regime_confidence < self._config.min_regime_confidence:
            self._signals_filtered += 1
            logger.debug(
                "Signal filtered: regime_confidence %.2f < %.2f",
                regime_confidence, self._config.min_regime_confidence
            )
            return None
        
        if epistemic_confidence < self._config.min_epistemic_confidence:
            self._signals_filtered += 1
            logger.debug(
                "Signal filtered: epistemic_confidence %.2f < %.2f",
                epistemic_confidence, self._config.min_epistemic_confidence
            )
            return None
        
        # Estimate risk metrics
        max_drawdown = self._estimate_drawdown(expected_return, regime)
        sharpe_estimate = self._estimate_sharpe(expected_return, max_drawdown)
        p_loss = self._estimate_p_loss(expected_return, regime)
        
        # Check risk thresholds
        if max_drawdown > self._config.max_drawdown:
            self._signals_filtered += 1
            logger.debug(
                "Signal filtered: max_drawdown %.2f > %.2f",
                max_drawdown, self._config.max_drawdown
            )
            return None
        
        if sharpe_estimate < self._config.min_sharpe:
            self._signals_filtered += 1
            logger.debug(
                "Signal filtered: sharpe %.2f < %.2f",
                sharpe_estimate, self._config.min_sharpe
            )
            return None
        
        if p_loss > self._config.max_p_loss:
            self._signals_filtered += 1
            logger.debug(
                "Signal filtered: p_loss %.2f > %.2f",
                p_loss, self._config.max_p_loss
            )
            return None
        
        # Check for anomalies
        if self._anomaly_detector:
            anomalies = self._anomaly_detector.get_recent_anomalies(minutes=5)
            critical_anomalies = [a for a in anomalies if a.severity.value in ["high", "critical"]]
            if critical_anomalies:
                self._signals_filtered += 1
                logger.warning(
                    "Signal filtered: %d critical anomalies detected",
                    len(critical_anomalies)
                )
                return None
        
        # Check for conflicts
        if self._conflict_detector:
            conflicts = self._conflict_detector.get_active_conflicts()
            severe_conflicts = [c for c in conflicts if c.severity.value in ["high", "critical"]]
            if severe_conflicts:
                self._signals_filtered += 1
                logger.warning(
                    "Signal filtered: %d severe conflicts detected",
                    len(severe_conflicts)
                )
                return None
        
        # Determine signal strength
        strength = self._determine_strength(adjusted_confidence)
        
        # Create signal
        signal = TradingSignal(
            signal_id=str(uuid.uuid4()),
            signal_type=signal_type,
            asset=asset,
            direction=direction,
            strength=strength,
            confidence=adjusted_confidence,
            regime=regime,
            regime_confidence=regime_confidence,
            epistemic_confidence=epistemic_confidence,
            expected_return=expected_return,
            max_drawdown=max_drawdown,
            sharpe_estimate=sharpe_estimate,
            p_loss=p_loss,
            sources=sources or [],
            valid_until=time.time() + self._config.signal_ttl_seconds,
        )
        
        self._signals[signal.signal_id] = signal
        self._signals_generated += 1
        
        # Trigger callback
        if self._on_signal_generated:
            self._on_signal_generated(signal)
        
        logger.info(
            "Signal generated: %s %s %s confidence=%.2f strength=%s",
            signal.signal_id[:8], signal.asset, signal.direction,
            signal.confidence, signal.strength.value
        )
        
        return signal
    
    async def propose_intent(
        self,
        signal: TradingSignal,
        notional_usd: Optional[float] = None,
        leverage: float = 1.0,
    ) -> Optional[str]:
        """
        Propose an intent to GOV based on a signal.
        
        Returns intent_id if successful, None otherwise.
        """
        if not self._intersystem_api:
            logger.error("Inter-system API not initialized")
            return None
        
        if signal.proposed:
            logger.warning("Signal %s already proposed", signal.signal_id[:8])
            return signal.intent_id
        
        if not signal.is_valid():
            logger.warning("Signal %s expired", signal.signal_id[:8])
            return None
        
        # Calculate notional
        if notional_usd is None:
            notional_usd = self._calculate_notional(signal)
        
        notional_usd = min(notional_usd, self._config.max_notional)
        
        try:
            from core.intersystem_api import RiskPreview, ShadowSimulation, PositionRequest
            
            # Create risk preview
            risk_preview = RiskPreview(
                max_drawdown_pct=signal.max_drawdown,
                corr_exposure=0.3,  # Conservative estimate
                var_95=signal.max_drawdown * 0.5,
                cvar_95=signal.max_drawdown * 0.7,
            )
            
            # Create shadow simulation
            shadow_sim = ShadowSimulation(
                expected_return=signal.expected_return,
                p_loss=signal.p_loss,
                sharpe_ratio=signal.sharpe_estimate,
                max_adverse_excursion=signal.max_drawdown * 1.5,
            )
            
            # Create position request
            position = PositionRequest(
                asset=signal.asset,
                side=signal.direction,
                notional_usd=notional_usd,
                leverage=leverage,
            )
            
            # Propose intent
            result = await self._intersystem_api.propose_intent(
                strategy_id=f"{signal.signal_type.value}_{signal.asset}",
                regime=signal.regime,
                confidence=signal.confidence,
                risk_preview=risk_preview,
                shadow_simulation=shadow_sim,
                position_request=position,
                expiry_ts=signal.valid_until,
                signal_sources=signal.sources,
                epistemic_confidence=signal.epistemic_confidence,
                regime_confidence=signal.regime_confidence,
            )
            
            intent_id = result.get("intent_id")
            if intent_id:
                signal.proposed = True
                signal.intent_id = intent_id
                self._proposed_intents[signal.signal_id] = intent_id
                self._intents_proposed += 1
                
                # Trigger callback
                if self._on_intent_proposed:
                    self._on_intent_proposed(signal, intent_id)
                
                logger.info(
                    "Intent proposed: %s from signal %s",
                    intent_id[:8], signal.signal_id[:8]
                )
                
                return intent_id
            
        except Exception as e:
            logger.error("Failed to propose intent: %s", e)
        
        return None
    
    def _estimate_drawdown(self, expected_return: float, regime: str) -> float:
        """Estimate max drawdown based on return and regime."""
        base_drawdown = abs(expected_return) * 2
        
        # Adjust for regime
        regime_multipliers = {
            "TRENDING_BULL": 0.8,
            "TRENDING_BEAR": 1.2,
            "MEAN_REVERTING": 0.9,
            "HIGH_VOLATILITY": 1.5,
            "CRISIS": 2.0,
            "UNKNOWN": 1.0,
        }
        
        multiplier = regime_multipliers.get(regime, 1.0)
        return min(base_drawdown * multiplier, 0.20)  # Cap at 20%
    
    def _estimate_sharpe(self, expected_return: float, max_drawdown: float) -> float:
        """Estimate Sharpe ratio."""
        if max_drawdown == 0:
            return 0.0
        
        # Rough estimate: return / volatility proxy
        volatility_proxy = max_drawdown / 2
        return expected_return / volatility_proxy if volatility_proxy > 0 else 0.0
    
    def _estimate_p_loss(self, expected_return: float, regime: str) -> float:
        """Estimate probability of loss."""
        # Base probability from expected return
        if expected_return > 0.05:
            base_p = 0.2
        elif expected_return > 0.02:
            base_p = 0.3
        elif expected_return > 0:
            base_p = 0.4
        else:
            base_p = 0.6
        
        # Adjust for regime
        regime_adjustments = {
            "TRENDING_BULL": -0.1,
            "TRENDING_BEAR": 0.1,
            "MEAN_REVERTING": 0.0,
            "HIGH_VOLATILITY": 0.15,
            "CRISIS": 0.25,
            "UNKNOWN": 0.05,
        }
        
        adjustment = regime_adjustments.get(regime, 0.0)
        return max(0.1, min(0.9, base_p + adjustment))
    
    def _determine_strength(self, confidence: float) -> SignalStrength:
        """Determine signal strength from confidence."""
        if confidence >= 0.85:
            return SignalStrength.VERY_STRONG
        elif confidence >= 0.70:
            return SignalStrength.STRONG
        elif confidence >= 0.55:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK
    
    def _calculate_notional(self, signal: TradingSignal) -> float:
        """Calculate appropriate notional for signal."""
        base_notional = self._config.default_notional
        
        # Scale by confidence
        confidence_factor = signal.confidence / 0.7  # Normalize around 0.7
        
        # Scale by strength
        strength_factors = {
            SignalStrength.WEAK: 0.5,
            SignalStrength.MODERATE: 0.75,
            SignalStrength.STRONG: 1.0,
            SignalStrength.VERY_STRONG: 1.25,
        }
        strength_factor = strength_factors.get(signal.strength, 1.0)
        
        # Scale by regime
        regime_factors = {
            "TRENDING_BULL": 1.1,
            "TRENDING_BEAR": 0.9,
            "MEAN_REVERTING": 1.0,
            "HIGH_VOLATILITY": 0.7,
            "CRISIS": 0.5,
            "UNKNOWN": 0.8,
        }
        regime_factor = regime_factors.get(signal.regime, 1.0)
        
        return base_notional * confidence_factor * strength_factor * regime_factor
    
    def get_signal(self, signal_id: str) -> Optional[TradingSignal]:
        """Get a signal by ID."""
        return self._signals.get(signal_id)
    
    def get_active_signals(self) -> List[TradingSignal]:
        """Get all active (valid, not proposed) signals."""
        return [s for s in self._signals.values() if s.is_valid() and not s.proposed]
    
    def get_proposed_signals(self) -> List[TradingSignal]:
        """Get all proposed signals."""
        return [s for s in self._signals.values() if s.proposed]
    
    def cleanup_expired(self) -> int:
        """Remove expired signals. Returns count removed."""
        expired = [sid for sid, s in self._signals.items() if not s.is_valid()]
        for sid in expired:
            del self._signals[sid]
        return len(expired)
    
    def on_signal_generated(self, callback: Callable[[TradingSignal], None]) -> None:
        """Register callback for signal generation."""
        self._on_signal_generated = callback
    
    def on_intent_proposed(self, callback: Callable[[TradingSignal, str], None]) -> None:
        """Register callback for intent proposal."""
        self._on_intent_proposed = callback
    
    def get_stats(self) -> Dict[str, Any]:
        """Get signal generator statistics."""
        signals = list(self._signals.values())
        
        return {
            "total_signals": len(signals),
            "active_signals": len(self.get_active_signals()),
            "proposed_signals": len(self.get_proposed_signals()),
            "signals_generated": self._signals_generated,
            "intents_proposed": self._intents_proposed,
            "signals_filtered": self._signals_filtered,
            "filter_rate": self._signals_filtered / (self._signals_generated + self._signals_filtered) if (self._signals_generated + self._signals_filtered) > 0 else 0,
            "proposal_rate": self._intents_proposed / self._signals_generated if self._signals_generated > 0 else 0,
            "config": {
                "min_confidence": self._config.min_confidence,
                "max_drawdown": self._config.max_drawdown,
                "default_notional": self._config.default_notional,
            },
        }


# Singleton instance
_signal_generator: Optional[SignalGenerator] = None


def get_signal_generator() -> SignalGenerator:
    """Get the singleton signal generator."""
    global _signal_generator
    if _signal_generator is None:
        _signal_generator = SignalGenerator()
        _signal_generator.initialize_components()
    return _signal_generator
