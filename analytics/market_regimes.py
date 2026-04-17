"""
Market Regime Detection for MERID Predictive Analytics

Provides comprehensive market regime classification and analysis with
machine learning models and US-compliant configuration.

Features:
- Market regime classification (bull/bear/sideways/volatile)
- Regime transition detection
- Market state analysis
- Risk assessment based on regime
- US-compliant market data handling
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

from utils.logger import get_logger

logger = get_logger("analytics.market_regimes")

@dataclass
class MarketState:
    """Current market state snapshot."""
    timestamp: float
    price: float
    volume: float
    volatility: float
    momentum: float
    trend_strength: float
    market_sentiment: float
    social_sentiment: float
    onchain_activity: float
    liquidity_index: float
    fear_greed_index: float
    market_breadth: float
    sector_rotation: float
    macro_indicators: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RegimeTransition:
    """Market regime transition information."""
    from_regime: str
    to_regime: str
    transition_time: float
    confidence: float
    transition_duration: float
    trigger_factors: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RegimeClassification:
    """Market regime classification result."""
    regime: str
    confidence: float
    probability: Dict[str, float]
    risk_level: str
    volatility_level: str
    momentum_level: str
    timestamp: float
    features: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

class MarketRegimeClassifier:
    """
    Market regime classification system for MERID.
    
    Provides intelligent market state detection and regime classification
    with multiple model support and US-compliant data handling.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Model configurations
        self.model_configs: Dict[str, Any] = {}
        
        # Model registry
        self.models: Dict[str, Any] = {}
        
        # Regime definitions
        self.regime_definitions = {
            "bull_market": {
                "description": "Strong uptrend with high confidence",
                "characteristics": ["price_trend > 0.02", "volume_increasing", "sentiment_positive"],
                "risk_level": "low",
                "volatility_range": (0.1, 0.3),
                "momentum_range": (0.05, 0.2)
            },
            "bear_market": {
                "description": "Strong downtrend with high confidence",
                "characteristics": ["price_trend < -0.02", "volume_increasing", "sentiment_negative"],
                "risk_level": "high",
                "volatility_range": (0.2, 0.5),
                "momentum_range": (-0.2, -0.05)
            },
            "sideways": {
                "description": "Consolidation phase with low volatility",
                "characteristics": ["abs(price_trend) < 0.01", "volume_stable", "sentiment_neutral"],
                "risk_level": "medium",
                "volatility_range": (0.05, 0.2),
                "momentum_range": (-0.05, 0.05)
            },
            "volatile": {
                "description": "High volatility with unclear direction",
                "characteristics": ["abs(price_trend) > 0.05", "volume_spiking", "sentiment_extreme"],
                "risk_level": "high",
                "volatility_range": (0.3, 0.8),
                "momentum_range": (-0.3, 0.3)
            }
        }
        
        # Feature weights
        self.feature_weights = config.get("feature_weights", {
            "price_momentum": 0.25,
            "volume_trend": 0.20,
            "volatility": 0.15,
            "market_sentiment": 0.15,
            "social_sentiment": 0.10,
            "onchain_activity": 0.10,
            "liquidity_index": 0.05,
            "fear_greed_index": 0.05,
            "market_breadth": 0.05,
            "sector_rotation": 0.05
        })
        
        # Classification history
        self.classification_history: deque = deque(maxlen=1000)
        self.transition_history: deque = deque(maxlen=500)
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "market_data_privacy": True,
            "model_transparency": True,
            "risk_assessment": True,
            "audit_regime_classifications": True
        })
        
        logger.info("MarketRegimeClassifier initialized")
    
    async def classify_regime(self, market_state: MarketState) -> Optional[RegimeClassification]:
        """Classify current market regime."""
        try:
            # Extract features
            features = self._extract_features(market_state)
            
            # Calculate regime probabilities
            probabilities = self._calculate_regime_probabilities(features)
            
            # Determine best regime
            best_regime = max(probabilities, key=probabilities.get)
            confidence = probabilities[best_regime]
            
            # Determine risk and volatility levels
            risk_level = self._determine_risk_level(best_regime, features)
            volatility_level = self._determine_volatility_level(features)
            momentum_level = self._determine_momentum_level(features)
            
            # Create classification result
            result = RegimeClassification(
                regime=best_regime,
                confidence=confidence,
                probability=probabilities,
                risk_level=risk_level,
                volatility_level=volatility_level,
                momentum_level=momentum_level,
                timestamp=market_state.timestamp,
                features=features,
                metadata={
                    "model_type": "rule_based",
                    "feature_weights": self.feature_weights
                }
            )
            
            # Store classification
            self.classification_history.append(result)
            
            logger.info(f"Market regime classified: {best_regime} (confidence: {confidence:.3f})")
            return result
            
        except Exception as e:
            logger.error(f"Failed to classify market regime: {e}")
            return None
    
    async def detect_transition(self, current_state: MarketState, 
                               previous_state: MarketState) -> Optional[RegimeTransition]:
        """Detect market regime transition."""
        try:
            # Classify both states
            current_classification = await self.classify_regime(current_state)
            previous_classification = await self.classify_regime(previous_state)
            
            if not current_classification or not previous_classification:
                return None
            
            # Check for regime change
            if current_classification.regime != previous_classification.regime:
                # Calculate transition confidence
                transition_confidence = min(
                    current_classification.confidence,
                    previous_classification.confidence
                )
                
                # Determine transition duration (mock)
                transition_duration = current_state.timestamp - previous_state.timestamp
                
                # Identify trigger factors
                trigger_factors = self._identify_trigger_factors(
                    previous_state, current_state,
                    previous_classification.regime,
                    current_classification.regime
                )
                
                transition = RegimeTransition(
                    from_regime=previous_classification.regime,
                    to_regime=current_classification.regime,
                    transition_time=current_state.timestamp,
                    confidence=transition_confidence,
                    transition_duration=transition_duration,
                    trigger_factors=trigger_factors,
                    metadata={
                        "previous_confidence": previous_classification.confidence,
                        "current_confidence": current_classification.confidence
                    }
                )
                
                # Store transition
                self.transition_history.append(transition)
                
                logger.info(f"Regime transition detected: {previous_classification.regime} → {current_classification.regime}")
                return transition
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to detect regime transition: {e}")
            return None
    
    def _extract_features(self, market_state: MarketState) -> Dict[str, float]:
        """Extract features from market state."""
        features = {}
        
        # Price momentum (20-period)
        features["price_momentum"] = market_state.momentum
        
        # Volume trend (20-period)
        features["volume_trend"] = market_state.volume / 1000000  # Normalized volume
        
        # Volatility (20-period)
        features["volatility"] = market_state.volatility
        
        # Market sentiment
        features["market_sentiment"] = market_state.market_sentiment
        
        # Social sentiment
        features["social_sentiment"] = market_state.social_sentiment
        
        # On-chain activity
        features["onchain_activity"] = market_state.onchain_activity
        
        # Liquidity index
        features["liquidity_index"] = market_state.liquidity_index
        
        # Fear & Greed index
        features["fear_greed_index"] = market_state.fear_greed_index
        
        # Market breadth
        features["market_breadth"] = market_state.market_breadth
        
        # Sector rotation
        features["sector_rotation"] = market_state.sector_rotation
        
        # Macro indicators
        for key, value in market_state.macro_indicators.items():
            features[f"macro_{key}"] = value
        
        return features
    
    def _calculate_regime_probabilities(self, features: Dict[str, float]) -> Dict[str, float]:
        """Calculate regime probabilities based on features."""
        probabilities = {}
        
        for regime, definition in self.regime_definitions.items():
            score = 0.0
            
            # Check each characteristic
            for characteristic in definition["characteristics"]:
                if ">" in characteristic:
                    # Range check (e.g., "price_trend > 0.02")
                    parts = characteristic.split(">")
                    field = parts[0]
                    operator = parts[1]
                    value = float(parts[2])
                    
                    if field in features:
                        feature_value = features[field]
                        if operator == ">" and feature_value > value:
                            score += self.feature_weights.get(field, 0.1)
                        elif operator == "<" and feature_value < value:
                            score += self.feature_weights.get(field, 0.1)
                elif "<" in characteristic:
                    # Range check (e.g., "abs(price_trend) < 0.01")
                    parts = characteristic.split("<")
                    field = parts[0]
                    value = float(parts[1])
                    
                    if field in features:
                        feature_value = features[field]
                        if abs(feature_value) < value:
                            score += self.feature_weights.get(field, 0.1)
                elif "==" in characteristic:
                    # Equality check (e.g., "sentiment_positive")
                    field = parts[0]
                    value = parts[1]
                    
                    if field in features:
                        feature_value = features[field]
                        if feature_value == value:
                            score += self.feature_weights.get(field, 0.1)
            
            # Normalize score
            probabilities[regime] = score / len(definition["characteristics"])
        
        # Normalize all probabilities
        total_score = sum(probabilities.values())
        if total_score > 0:
            probabilities = {regime: prob/total_score for regime, prob in probabilities.items()}
        
        return probabilities
    
    def _determine_risk_level(self, regime: str, features: Dict[str, float]) -> str:
        """Determine risk level based on regime and features."""
        regime_def = self.regime_definitions.get(regime, {})
        return regime_def.get("risk_level", "medium")
    
    def _determine_volatility_level(self, features: Dict[str, float]) -> str:
        """Determine volatility level based on features."""
        volatility = features.get("volatility", 0.2)
        
        if volatility < 0.1:
            return "low"
        elif volatility < 0.3:
            return "medium"
        elif volatility < 0.5:
            return "high"
        else:
            return "critical"
    
    def _determine_momentum_level(self, features: Dict[str, float]) -> str:
        """Determine momentum level based on features."""
        momentum = features.get("price_momentum", 0.0)
        
        if momentum > 0.1:
            return "strong"
        elif momentum > 0.05:
            return "moderate"
        elif momentum > -0.05:
            return "weak"
        elif momentum > -0.1:
            return "negative"
        else:
            return "neutral"
    
    def _identify_trigger_factors(self, previous_state: MarketState, 
                                     current_state: MarketState,
                                     from_regime: str, to_regime: str) -> List[str]:
        """Identify factors that triggered the regime transition."""
        triggers = []
        
        # Price change
        price_change = (current_state.price - previous_state.price) / previous_state.price
        if abs(price_change) > 0.05:
            triggers.append(f"price_change_{price_change:.2f}")
        
        # Volume change
        volume_change = (current_state.volume - previous_state.volume) / previous_state.volume
        if abs(volume_change) > 0.2:
            triggers.append(f"volume_change_{volume_change:.2f}")
        
        # Volatility change
        volatility_change = current_state.volatility - previous_state.volatility
        if abs(volatility_change) > 0.1:
            triggers.append(f"volatility_change_{volatility_change:.2f}")
        
        # Sentiment change
        sentiment_change = current_state.market_sentiment - previous_state.market_sentiment
        if abs(sentiment_change) > 0.3:
            triggers.append(f"sentiment_change_{sentiment_change:.2f}")
        
        # Fear & Greed index change
        fg_change = current_state.fear_greed_index - previous_state.fear_greed_index
        if abs(fg_change) > 10:
            triggers.append(f"fear_greed_change_{fg_change:.1f}")
        
        return triggers
    
    def get_regime_summary(self) -> Dict[str, Any]:
        """Get comprehensive regime analysis summary."""
        if not self.classification_history:
            return {"status": "no_data"}
        
        # Recent classifications
        recent_classifications = list(self.classification_history)[-100:]
        
        # Regime distribution
        regime_counts = {}
        for classification in recent_classifications:
            regime = classification.regime
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
        
        # Transition statistics
        recent_transitions = list(self.transition_history)[-50:]
        transition_matrix = {}
        
        for transition in recent_transitions:
            key = f"{transition.from_regime} → {transition.to_regime}"
            transition_matrix[key] = transition_matrix.get(key, 0) + 1
        
        # Average confidence by regime
        regime_confidence = {}
        for regime in regime_counts:
            regime_classifications = [c for c in recent_classifications if c.regime == regime]
            if regime_classifications:
                avg_confidence = sum(c.confidence for c in regime_classifications) / len(regime_classifications)
                regime_confidence[regime] = avg_confidence
        
        return {
            "total_classifications": len(self.classification_history),
            "recent_classifications": len(recent_classifications),
            "regime_distribution": regime_counts,
            "transition_matrix": transition_matrix,
            "regime_confidence": regime_confidence,
            "regime_definitions": self.regime_definitions,
            "us_compliance": self.us_compliance
        }
    
    def get_regime_history(self, limit: int = 100) -> List[RegimeClassification]:
        """Get regime classification history."""
        return list(self.classification_history)[-limit:]
    
    def get_transition_history(self, limit: int = 50) -> List[RegimeTransition]:
        """Get regime transition history."""
        return list(self.transition_history)[-limit:]
    
    def get_regime_statistics(self, regime: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed statistics for a specific regime."""
        if not self.classification_history:
            return {"status": "no_data"}
        
        classifications = [c for c in self.classification if regime is None or c.regime == regime]
        
        if not classifications:
            return {"status": "no_data"}
        
        # Calculate statistics
        confidences = [c.confidence for c in classifications]
        probabilities = [c.probability.get(regime, 0) for c in classifications for regime in [regime]]
        
        return {
            "total_classifications": len(classifications),
            "avg_confidence": np.mean(confidences) if confidences else 0,
            "max_confidence": max(confidences) if confidences else 0,
            "min_confidence": min(confidences) if confidences else 0,
            "avg_probability": np.mean(probabilities) if probabilities else 0,
            "timestamp_range": {
                "earliest": min(c.timestamp for c in classifications),
                "latest": max(c.timestamp for c in classifications)
            }
        }
    
    def update_regime_definitions(self, new_definitions: Dict[str, Dict[str, Any]]):
        """Update regime definitions."""
        self.regime_definitions.update(new_definitions)
        logger.info(f"Updated {len(new_definitions)} regime definitions")
    
    def update_feature_weights(self, new_weights: Dict[str, float]):
        """Update feature weights for classification."""
        self.feature_weights.update(new_weights)
        logger.info(f"Updated {len(new_weights)} feature weights")

class MarketRegimeAnalyzer:
    """
    Advanced market regime analysis system for MERID.
    
    Provides comprehensive regime analysis, transition detection, and
    market intelligence with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Initialize classifier
        self.classifier = MarketRegimeClassifier(config)
        
        # Analysis history
        self.analysis_history: deque = deque(maxlen=1000)
        
        # Regime performance tracking
        self.regime_performance: Dict[str, Dict[str, float]] = {}
        
        # Market cycle tracking
        self.market_cycles: deque = deque(maxlen=100)
        
        # US compliance
        self.us_compliance = config.get("us_compliance", {
            "market_data_privacy": True,
            "regime_analysis_logging": True,
            "risk_assessment": True
        })
        
        logger.info("MarketRegimeAnalyzer initialized")
    
    async def start_analysis(self):
        """Start continuous market regime analysis."""
        logger.info("Starting market regime analysis")
        
        # Start analysis loop
        asyncio.create_task(self._analysis_loop())
        
        logger.info("Market regime analysis started")
    
    async def _analysis_loop(self):
        """Continuous market regime analysis loop."""
        while True:
            try:
                # In production, fetch real market data
                market_state = await self._fetch_market_state()
                
                if market_state:
                    # Classify current regime
                    classification = await self.classifier.classify_regime(market_state)
                    
                    # Analyze regime performance
                    await self._analyze_regime_performance(classification)
                    
                    # Detect transitions
                    if len(self.classifier.classification_history) > 1:
                        previous_state = await self._fetch_market_state()
                        transition = await self.classifier.detect_transition(market_state, previous_state)
                        
                        if transition:
                            await self._analyze_transition(transition)
                    
                    # Store analysis
                    analysis_entry = {
                        "timestamp": market_state.timestamp,
                        "regime": classification.regime if classification else "unknown",
                        "confidence": classification.confidence if classification else 0,
                        "features": classification.features if classification else {},
                        "metadata": classification.metadata if classification else {}
                    }
                    
                    self.analysis_history.append(analysis_entry)
                
                # Sleep for next analysis
                await asyncio.sleep(60)  # Analyze every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Analysis loop error: {e}")
                await asyncio.sleep(10)
    
    async def _fetch_market_state(self) -> Optional[MarketState]:
        """Fetch current market state (mock implementation)."""
        # In production, this would fetch real market data
        try:
            # Mock market data generation
            current_time = time.time()
            
            # Generate realistic market data
            base_price = 3000.0 + np.sin(current_time / 1000) * 100
            base_volume = 1000000 + np.random.normal(0, 200000, 10000)
            base_volatility = 0.2 + np.random.normal(0, 0.1, 0.05)
            
            # Market momentum
            momentum = np.sin(current_time / 500) * 0.02
            
            # Market sentiment (mock)
            market_sentiment = np.random.normal(0, 0.3, 0.1)
            
            # Social sentiment (mock)
            social_sentiment = np.random.normal(0, 0.2, 0.1)
            
            # On-chain activity (mock)
            onchain_activity = np.random.exponential(1000, 5000, 10000)
            
            # Liquidity index (mock)
            liquidity_index = np.random.uniform(0.8, 1.0)
            
            # Fear & Greed index (mock)
            fear_greed_index = 50 + np.random.normal(0, 15, 5)
            
            # Market breadth (mock)
            market_breadth = np.random.uniform(0.3, 0.7)
            
            # Sector rotation (mock)
            sector_rotation = np.random.uniform(0.0, 1.0)
            
            # Macro indicators (mock)
            macro_indicators = {
                "interest_rate": 0.05 + np.random.normal(0, 0.01, 0.002),
                "inflation_rate": 0.02 + np.random.normal(0, 0.005, 0.001),
                "gdp_growth": 0.03 + np.random.normal(0, 0.01, 0.002)
            }
            
            market_state = MarketState(
                timestamp=current_time,
                price=base_price,
                volume=base_volume,
                volatility=base_volatility,
                momentum=momentum,
                trend_strength=abs(momentum),
                market_sentiment=market_sentiment,
                social_sentiment=social_sentiment,
                onchain_activity=onchain_activity,
                liquidity_index=liquidity_index,
                fear_greed_index=fear_greed_index,
                market_breadth=market_breadth,
                sector_rotation=sector_rotation,
                macro_indicators=macro_indicators,
                metadata={"mock": True}
            )
            
            return market_state
            
        except Exception as e:
            logger.error(f"Failed to fetch market state: {e}")
            return None
    
    async def _analyze_regime_performance(self, classification: RegimeClassification):
        """Analyze regime performance."""
        try:
            # Get historical performance for this regime
            regime_classifications = [
                c for c in self.classifier.classification_history 
                if c.regime == classification.regime
            ]
            
            if len(regime_classifications) < 2:
                return
            
            # Calculate performance metrics
            confidences = [c.confidence for c in regime_classifications]
            avg_confidence = np.mean(confidences)
            max_confidence = max(confidences)
            
            # Update performance tracking
            if classification.regime not in self.regime_performance:
                self.regime_performance[classification.regime] = {}
            
            self.regime_performance[classification.regime].update({
                "avg_confidence": avg_confidence,
                "max_confidence": max_confidence,
                "total_classifications": len(regime_classifications),
                "last_updated": time.time()
            })
            
            logger.debug(f"Regime performance updated for {classification.regime}")
            
        except Exception as e:
            logger.error(f"Failed to analyze regime performance: {e}")
    
    async def _analyze_transition(self, transition: RegimeTransition):
        """Analyze regime transition."""
        try:
            # Store transition analysis
            analysis_entry = {
                "timestamp": transition.transition_time,
                "from_regime": transition.from_regime,
                "to_regime": transition.to_regime,
                "confidence": transition.confidence,
                "duration": transition.transition_duration,
                "trigger_factors": transition.trigger_factors
            }
            
            self.transition_history.append(analysis_entry)
            
            logger.info(f"Regime transition analyzed: {transition.from_regime} → {transition.to_regime}")
            
        except Exception as e:
            logger.error(f"Failed to analyze transition: {e}")
    
    def get_regime_analysis_summary(self) -> Dict[str, Any]:
        """Get comprehensive regime analysis summary."""
        if not self.analysis_history:
            return {"status": "no_data"}
        
        # Recent classifications
        recent_classifications = list(self.analysis_history)[-100:]
        
        # Regime distribution
        regime_counts = {}
        for analysis in recent_classifications:
            regime = analysis["regime"]
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
        
        # Transition matrix
        transition_matrix = {}
        for analysis in self.transition_history:
            key = f"{analysis['from_regime']} → {analysis['to_regime']}"
            transition_matrix[key] = transition_matrix.get(key, 0) + 1
        
        # Performance metrics
        performance_summary = {}
        for regime, metrics in self.regime_performance.items():
            performance_summary[regime] = {
                "avg_confidence": metrics["avg_confidence"],
                "max_confidence": metrics["max_confidence"],
                "total_classifications": metrics["total_classifications"]
            }
        
        # Market cycles
        recent_cycles = list(self.market_cycles)[-20:]
        
        return {
            "total_analyses": len(self.analysis_history),
            "recent_analyses": len(recent_classifications),
            "regime_distribution": regime_counts,
            "transition_matrix": transition_matrix,
            "performance_summary": performance_summary,
            "market_cycles": len(recent_cycles),
            "regime_definitions": self.classifier.regime_definitions,
            "us_compliance": self.us_compliance
        }
    
    def get_regime_performance(self, regime: Optional[str] = None) -> Dict[str, Any]:
        """Get performance metrics for a specific regime."""
        if regime and regime in self.regime_performance:
            return self.regime_performance[regime]
        
        return self.regime_performance
    
    def get_market_cycles(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get market cycle history."""
        return list(self.market_cycles)[-limit:]
    
    def update_regime_definitions(self, new_definitions: Dict[str, Dict[str, Any]]):
        """Update regime definitions."""
        self.classifier.update_regime_definitions(new_definitions)
    
    def update_feature_weights(self, new_weights: Dict[str, float]):
        """Update feature weights for classification."""
        self.classifier.update_feature_weights(new_weights)
    
    def get_available_regimes(self) -> List[str]:
        """Get list of available regime types."""
        return list(self.classifier.regime_definitions.keys())
