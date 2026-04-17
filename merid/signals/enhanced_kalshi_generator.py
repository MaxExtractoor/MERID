"""
Enhanced Kalshi Signal Generator

Integrates composite features from crypto, debate, and sentiment sources
to generate more sophisticated Kalshi signals with cross-domain context
using the new market wiring layer for explicit mappings and safety.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from merid.signals.unified_manager import get_unified_signal_manager
from merid.signals.crypto_features import get_crypto_feature_processor
from merid.signals.debate_integration import get_debate_signal_integrator
from merid.signals.sentiment_integration import get_sentiment_signal_integrator
from merid.signals.store import get_signal_store
from merid.signals.enhanced_kalshi_integration import get_enhanced_kalshi_integration
from utils.logger import get_logger

logger = get_logger("signals.enhanced_kalshi")


class SignalDecision(Enum):
    """Signal generation decision"""
    GENERATE = "generate"
    SUPPRESSED = "suppressed"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class SignalThresholds:
    """Configurable thresholds for signal generation"""
    min_edge_bps: float = 5.0
    min_volume_z: float = 1.0
    min_debate_confidence: float = 0.6
    min_sentiment_intensity: float = 0.3
    max_risk_score: float = 0.8
    min_liquidity_score: float = 0.5
    
    # Fear & greed bands for different strategies
    fg_bullish_min: float = 0.6
    fg_bearish_max: float = 0.4
    fg_neutral_min: float = 0.4
    fg_neutral_max: float = 0.6


@dataclass
class CompositeFeatures:
    """Composite features from all domains for a symbol"""
    symbol: str
    kalshi_edge_bps: Optional[float]
    liquidity_score: Optional[float]
    risk_score: Optional[float]
    
    # Crypto features
    volume_z_score: Optional[float]
    fear_greed_score: Optional[float]
    price_momentum: Optional[float]
    
    # Debate features
    debate_health: Optional[float]
    debate_confidence: Optional[float]
    debate_multiplier: Optional[float]
    debate_status: Optional[str]
    
    # Sentiment features
    news_sentiment: Optional[float]
    social_sentiment: Optional[float]
    sentiment_intensity: Optional[float]
    
    # Metadata
    timestamp: float
    data_completeness: float  # 0-1, how much data we have


class EnhancedKalshiSignalGenerator:
    """Enhanced Kalshi signal generator with composite feature integration"""
    
    def __init__(self, thresholds: Optional[SignalThresholds] = None):
        self._thresholds = thresholds or SignalThresholds()
        self._unified_manager = get_unified_signal_manager()
        self._signal_store = get_signal_store()
        
        # Feature processors
        self._crypto_processor = get_crypto_feature_processor()
        self._debate_integrator = get_debate_signal_integrator()
        self._sentiment_integrator = get_sentiment_signal_integrator()
        
        # Cache for composite features
        self._feature_cache: Dict[str, CompositeFeatures] = {}
        self._cache_ttl = 300  # 5 minutes
    
    async def generate_all_signals(self, markets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Generate Kalshi signals for the provided catalog markets and store them."""
        signals: List[Dict[str, Any]] = []
        suppressed = 0
        errors = 0

        try:
            integration = get_enhanced_kalshi_integration()
            await integration.initialize()

            # Use provided markets or fall back to the integration layer's own selection
            if markets:
                for mkt in markets:
                    ticker = mkt.get("ticker", "")
                    if not ticker:
                        continue
                    try:
                        sig = integration.generate_signal_for_market(ticker)
                        if sig:
                            signals.append(sig)
                        else:
                            suppressed += 1
                    except Exception as exc:
                        logger.debug("Signal generation skipped for %s: %s", ticker, exc)
                        suppressed += 1
            else:
                raw = integration.generate_all_signals()
                if isinstance(raw, list):
                    signals = raw
                elif isinstance(raw, dict):
                    signals = raw.get("signals", [])

            # Store all generated signals
            stored = 0
            if signals:
                try:
                    stored = integration.store_signals(signals)
                except Exception as exc:
                    logger.warning("store_signals failed: %s", exc)

            logger.info(
                "Kalshi signal generation complete: %d generated, %d stored, %d suppressed",
                len(signals), stored, suppressed,
            )
            return {
                "generated": len(signals),
                "stored": stored,
                "suppressed": suppressed,
                "insufficient_data": 0,
                "errors": errors,
                "signals": signals,
            }

        except Exception as e:
            logger.error("Failed to generate Kalshi signals: %s", e)
            return {
                "generated": 0,
                "stored": 0,
                "suppressed": 0,
                "insufficient_data": 0,
                "errors": 1,
                "signals": [],
                "error": str(e),
            }
    
    # ============================================================================
    # DEPRECATED LEGACY METHODS
    # ============================================================================
    # These methods are kept for experimentation and backward compatibility.
    # All production signal generation should use generate_all_signals() above.
    # ============================================================================
    
    def _generate_signal_for_context(self, context) -> Optional[Dict[str, Any]]:
        """[DEPRECATED] Generate signal for a specific market context
        
        This method is deprecated. Use the wiring-aware integration layer
        via generate_all_signals() for production signal generation.
        """
        logger.warning("_generate_signal_for_context is deprecated - use wiring integration layer")
        try:
            mapping = context.market_mapping
            market = context.kalshi_market
            
            # Gather features using the mapping
            features = self._gather_features_from_context(context)
            if not features:
                logger.debug(f"Insufficient features for {market.market_ticker}")
                return None
            
            # Calculate signal components
            signal_components = self._calculate_signal_components_from_features(features, mapping.risk_profile)
            
            # Calculate proposed notional from edge
            proposed_notional = self._calculate_notional_from_edge(signal_components["edge_bps"])
            
            # Build the signal with complete wiring metadata
            signal = {
                "signal_id": f"kalshi_edge_{market.market_ticker}_{int(time.time())}",
                "symbol": mapping.merid_symbol,
                "domain": "prediction",
                "signal_type": "kalshi_edge",
                "source": "enhanced_kalshi_generator",
                "generated_at": time.time(),
                "market_ticker": market.market_ticker,
                "underlying_symbol": mapping.underlying_symbol,
                "risk_profile": mapping.risk_profile.value,
                "confidence": signal_components["confidence"],
                "strength": signal_components["strength"],
                "edge_bps": signal_components["edge_bps"],
                "direction": signal_components["direction"],
                "notional": proposed_notional,  # Will be adjusted by safety layer
                "features": features,
                "meta": {
                    "market_ticker": market.market_ticker,
                    "underlying_symbol": mapping.underlying_symbol,
                    "risk_profile": mapping.risk_profile.value,
                    "context_complete": context.context_complete,
                    "effective_limits": {
                        "max_notional": context.effective_max_notional,
                        "max_daily": context.effective_daily_notional,
                        "max_open_risk": context.effective_open_risk,
                    },
                    # Full market record for execution bridge
                    "market_record": {
                        "max_notional_per_trade": market.max_notional_per_trade,
                        "max_daily_notional": market.max_daily_notional,
                        "max_open_risk": market.max_open_risk,
                        "enabled_for_merid": market.enabled_for_merid,
                        "status": market.status.value,
                    },
                    # Full mapping for execution bridge
                    "mapping": {
                        "requires_crypto_context": mapping.requires_crypto_context,
                        "requires_debate_context": mapping.requires_debate_context,
                        "requires_sentiment_context": mapping.requires_sentiment_context,
                        "sentiment_symbols": mapping.sentiment_symbols,
                        "debate_symbol": mapping.debate_symbol,
                        "enabled": mapping.enabled,
                    }
                }
            }
            
            return signal
            
        except Exception as e:
            logger.error(f"Error generating signal for context {context.market_mapping.market_ticker}: {e}")
            return None
    
    def _calculate_notional_from_edge(self, edge_bps: float) -> float:
        """Calculate proposed notional from edge in basis points"""
        # Base notional scaled by edge strength
        base_notional = 100.0  # $100 base
        
        # Scale by edge (0.1 bps = $10, 10 bps = $1000)
        edge_multiplier = max(0.1, min(10.0, edge_bps / 10.0))
        
        return base_notional * edge_multiplier
    
    # ============================================================================
    # ADDITIONAL LEGACY METHODS (DEPRECATED)
    # ============================================================================
    # These methods are kept for experimentation and backward compatibility.
    # All production signal generation should use generate_all_signals() above.
    # ============================================================================
    
    # Additional legacy methods can be added here if needed for experimentation
    
    def _gather_features_from_context(self, context) -> Optional[Dict[str, Any]]:
        """Gather features from market context"""
        try:
            features = {}
            mapping = context.market_mapping
            
            # Gather crypto features if required and available
            if (mapping.requires_crypto_context and 
                context.crypto_context_available and 
                context.crypto_fresh):
                
                crypto_features = self._crypto_processor.get_features_for_symbol(mapping.underlying_symbol)
                if crypto_features:
                    features["crypto"] = crypto_features
                else:
                    logger.debug(f"Failed to get crypto features for {mapping.underlying_symbol}")
                    return None
            elif mapping.requires_crypto_context:
                logger.debug(f"Required crypto context not available for {mapping.market_ticker}")
                return None
            
            # Gather sentiment features if required and available
            if (mapping.requires_sentiment_context and 
                context.sentiment_context_available and 
                context.sentiment_fresh):
                
                sentiment_features = {}
                for symbol in mapping.sentiment_symbols:
                    symbol_sentiment = self._sentiment_integrator.get_sentiment_for_symbol(symbol)
                    if symbol_sentiment:
                        sentiment_features[symbol] = symbol_sentiment
                
                if sentiment_features:
                    features["sentiment"] = sentiment_features
                else:
                    logger.debug(f"Failed to get sentiment features for {mapping.sentiment_symbols}")
                    return None
            elif mapping.requires_sentiment_context:
                logger.debug(f"Required sentiment context not available for {mapping.market_ticker}")
                return None
            
            # Gather debate features if required and available
            if (mapping.requires_debate_context and 
                context.debate_context_available and 
                context.debate_fresh and 
                mapping.debate_symbol):
                
                debate_features = self._debate_integrator.get_debate_context_for_symbol(mapping.debate_symbol)
                if debate_features:
                    features["debate"] = debate_features
                else:
                    logger.debug(f"Failed to get debate features for {mapping.debate_symbol}")
                    return None
            elif mapping.requires_debate_context:
                logger.debug(f"Required debate context not available for {mapping.market_ticker}")
                return None
            
            return features if features else None
            
        except Exception as e:
            logger.error(f"Error gathering features from context: {e}")
            return None
    
    def _calculate_signal_components_from_features(self, features: Dict[str, Any], risk_profile) -> Dict[str, Any]:
        """Calculate signal components from gathered features"""
        confidence = 0.5  # Base confidence
        strength = 0.5    # Base strength
        edge_bps = 0.0    # Base edge in basis points
        direction = "neutral"
        
        # Crypto context contribution
        crypto = features.get("crypto", {})
        if crypto:
            fear_greed = crypto.get("fear_greed", {})
            fg_score = fear_greed.get("score", 0.5)
            
            # Adjust based on fear/greed (extreme values increase confidence)
            if fg_score < 0.2 or fg_score > 0.8:
                confidence += 0.2
                strength += 0.1
            
            # Volume anomaly contributes to edge
            volume_anomaly = crypto.get("volume_z", {})
            if volume_anomaly.get("anomaly", False):
                edge_bps += abs(volume_anomaly.get("z_score", 0)) * 5  # Scale z-score to bps
                confidence += 0.1
            
            # Price momentum contributes to direction and edge
            price_momentum = crypto.get("price_momentum", {})
            momentum_score = price_momentum.get("score", 0)
            if momentum_score > 0.1:
                direction = "bullish"
                edge_bps += momentum_score * 10
            elif momentum_score < -0.1:
                direction = "bearish"
                edge_bps += abs(momentum_score) * 10
        
        # Sentiment context contribution
        sentiment = features.get("sentiment", {})
        if sentiment:
            # Aggregate sentiment across symbols
            sentiments = list(sentiment.values())
            avg_sentiment = sum(s.get("combined_sentiment", 0.5) for s in sentiments) / len(sentiments)
            
            # Strong sentiment increases confidence
            if avg_sentiment > 0.7 or avg_sentiment < 0.3:
                confidence += 0.15
                strength += 0.1
            
            # Sentiment bias affects direction
            if avg_sentiment > 0.6:
                if direction == "neutral":
                    direction = "bullish"
                edge_bps += (avg_sentiment - 0.5) * 15
            elif avg_sentiment < 0.4:
                if direction == "neutral":
                    direction = "bearish"
                edge_bps += (0.5 - avg_sentiment) * 15
        
        # Debate context contribution (risk adjustment)
        debate = features.get("debate", {})
        if debate:
            risk_multiplier = debate.get("risk_multiplier", 1.0)
            health_score = debate.get("health_score", 0.5)
            
            # Poor debate health reduces confidence
            if health_score < 0.5:
                confidence *= health_score
                strength *= health_score
            
            # Apply risk multiplier to edge
            edge_bps *= risk_multiplier
        
        # Adjust based on risk profile
        if risk_profile == RiskProfile.CRYPTO_LINKED:
            confidence *= 1.1  # Slightly higher confidence for crypto
        elif risk_profile == RiskProfile.MACRO_ELECTION:
            confidence *= 0.9  # More conservative for elections
        elif risk_profile == RiskProfile.IDIOSYNCRATIC:
            confidence *= 0.7  # Most conservative for idiosyncratic
        
        # Clamp values to reasonable ranges
        confidence = max(0.1, min(0.95, confidence))
        strength = max(0.1, min(0.9, strength))
        edge_bps = max(-50, min(50, edge_bps))  # Cap edge at ±50 bps
        
        return {
            "confidence": confidence,
            "strength": strength,
            "edge_bps": edge_bps,
            "direction": direction,
        }
    
    def _generate_signal_for_market(self, symbol: str, market: Dict[str, Any]) -> Tuple[SignalDecision, Optional[Dict[str, Any]]]:
        """Generate signal for a specific market"""
        try:
            # Get composite features
            features = self._get_composite_features(symbol)
            if not features:
                return SignalDecision.INSUFFICIENT_DATA, None
            
            # Evaluate signal conditions
            decision, reason = self._evaluate_signal_conditions(features)
            
            if decision == SignalDecision.GENERATE:
                signal = self._create_enhanced_signal(features, market)
                return SignalDecision.GENERATE, signal
            else:
                # Create suppressed signal for analysis
                suppressed_signal = self._create_suppressed_signal(features, market, reason)
                return SignalDecision.SUPPRESSED, suppressed_signal
                
        except Exception as e:
            logger.warning(f"Failed to generate signal for {symbol}: {e}")
            return SignalDecision.INSUFFICIENT_DATA, None
    
    def _get_composite_features(self, symbol: str) -> Optional[CompositeFeatures]:
        """Get composite features for a symbol from all sources"""
        # Check cache first
        cached = self._feature_cache.get(symbol)
        if cached and (time.time() - cached.timestamp) < self._cache_ttl:
            return cached
        
        try:
            # Get base Kalshi features
            kalshi_features = self._get_kalshi_features(symbol)
            
            # Get crypto features
            crypto_features = self._get_crypto_features(symbol)
            
            # Get debate features
            debate_features = self._get_debate_features(symbol)
            
            # Get sentiment features
            sentiment_features = self._get_sentiment_features(symbol)
            
            # Calculate data completeness
            completeness = self._calculate_data_completeness(
                kalshi_features, crypto_features, debate_features, sentiment_features
            )
            
            features = CompositeFeatures(
                symbol=symbol,
                kalshi_edge_bps=kalshi_features.get("edge_bps"),
                liquidity_score=kalshi_features.get("liquidity_score"),
                risk_score=kalshi_features.get("risk_score"),
                
                volume_z_score=crypto_features.get("volume_z_score"),
                fear_greed_score=crypto_features.get("fear_greed_score"),
                price_momentum=crypto_features.get("price_momentum"),
                
                debate_health=debate_features.get("health_score"),
                debate_confidence=debate_features.get("confidence_level"),
                debate_multiplier=debate_features.get("debate_multiplier"),
                debate_status=debate_features.get("debate_status"),
                
                news_sentiment=sentiment_features.get("news_sentiment"),
                social_sentiment=sentiment_features.get("social_sentiment"),
                # Intensity should be overall activity, not direction
                sentiment_intensity=(sentiment_features.get("news_intensity", 0.0)
                                     + sentiment_features.get("social_intensity", 0.0)) / 2.0,
                
                timestamp=time.time(),
                data_completeness=completeness
            )
            
            # Cache the result
            self._feature_cache[symbol] = features
            
            return features
            
        except Exception as e:
            logger.warning(f"Failed to get composite features for {symbol}: {e}")
            return None
    
    def _get_kalshi_features(self, symbol: str) -> Dict[str, Any]:
        """Get Kalshi-specific features for a symbol"""
        # This would integrate with existing Kalshi signal generation
        # For now, return placeholder data
        return {
            "edge_bps": 0.0,  # Would come from Kalshi edge endpoint
            "liquidity_score": 0.5,  # Would come from liquidity analysis
            "risk_score": 0.3,  # Would come from risk analysis
        }
    
    def _get_crypto_features(self, symbol: str) -> Dict[str, Any]:
        """Get crypto features for a symbol"""
        try:
            # Map Kalshi symbol to crypto symbol
            crypto_symbol = self._map_to_crypto_symbol(symbol)
            if not crypto_symbol:
                return {}
            
            # Get latest features from signal store
            latest_features = self._signal_store.get_latest_features(crypto_symbol, "crypto")
            
            if latest_features:
                # Return the most recent feature set
                return latest_features[0].get("features", {})
            else:
                return {}
                
        except Exception as e:
            logger.debug(f"Failed to get crypto features for {symbol}: {e}")
            return {}
    
    def _get_debate_features(self, symbol: str) -> Dict[str, Any]:
        """Get debate features for a symbol"""
        try:
            debate_context = self._debate_integrator.get_debate_context_for_symbol(symbol)
            if debate_context:
                return debate_context.to_dict()
            else:
                return {}
                
        except Exception as e:
            logger.debug(f"Failed to get debate features for {symbol}: {e}")
            return {}
    
    def _get_sentiment_features(self, symbol: str) -> Dict[str, Any]:
        """Get sentiment features for a symbol"""
        try:
            sentiment_metrics = self._sentiment_integrator.get_sentiment_metrics(symbol)
            if sentiment_metrics:
                return sentiment_metrics.to_dict()
            else:
                return {}
                
        except Exception as e:
            logger.debug(f"Failed to get sentiment features for {symbol}: {e}")
            return {}
    
    def _calculate_data_completeness(self, *feature_dicts) -> float:
        """Calculate how complete the feature data is (0-1)"""
        total_fields = 0
        present_fields = 0
        
        for features in feature_dicts:
            if features:
                for key, value in features.items():
                    total_fields += 1
                    if value is not None:
                        present_fields += 1
        
        return present_fields / total_fields if total_fields > 0 else 0.0
    
    def _evaluate_signal_conditions(self, features: CompositeFeatures) -> Tuple[SignalDecision, str]:
        """Evaluate whether to generate a signal based on composite features"""
        
        # Check basic Kalshi edge
        if not features.kalshi_edge_bps or features.kalshi_edge_bps < self._thresholds.min_edge_bps:
            return SignalDecision.SUPPRESSED, "Insufficient Kalshi edge"
        
        # Check volume anomaly
        if features.volume_z_score and features.volume_z_score < self._thresholds.min_volume_z:
            return SignalDecision.SUPPRESSED, "Low volume anomaly"
        
        # Check debate health
        if features.debate_health and features.debate_health < 0.5:
            return SignalDecision.SUPPRESSED, "Poor debate health"
        
        # Check sentiment intensity for directional strategies
        if abs(features.sentiment_intensity or 0) < self._thresholds.min_sentiment_intensity:
            return SignalDecision.SUPPRESSED, "Low sentiment intensity"
        
        # Check risk score
        if features.risk_score and features.risk_score > self._thresholds.max_risk_score:
            return SignalDecision.SUPPRESSED, "High risk score"
        
        # Check data completeness
        if features.data_completeness < 0.5:
            return SignalDecision.INSUFFICIENT_DATA, "Insufficient feature data"
        
        # Strategy-specific checks
        fg_score = features.fear_greed_score or 0.5
        
        # Bullish strategy: need greed and positive sentiment
        if fg_score > self._thresholds.fg_bullish_min:
            if (features.news_sentiment or 0) < -0.2 or (features.social_sentiment or 0) < -0.2:
                return SignalDecision.SUPPRESSED, "Contradictory sentiment (bullish FG vs negative sentiment)"
        
        # Bearish strategy: need fear and negative sentiment
        elif fg_score < self._thresholds.fg_bearish_max:
            if (features.news_sentiment or 0) > 0.2 or (features.social_sentiment or 0) > 0.2:
                return SignalDecision.SUPPRESSED, "Contradictory sentiment (bearish FG vs positive sentiment)"
        
        return SignalDecision.GENERATE, "All conditions met"
    
    def _create_enhanced_signal(self, features: CompositeFeatures, market: Dict[str, Any]) -> Dict[str, Any]:
        """Create an enhanced Kalshi signal with composite features"""
        signal = self._unified_manager.create_kalshi_signal(
            ticker=features.symbol,
            edge_bps=features.kalshi_edge_bps or 0.0,
            features={
                # Base Kalshi features
                "kalshi_edge_bps": features.kalshi_edge_bps,
                "liquidity_score": features.liquidity_score,
                "risk_score": features.risk_score,
                
                # Crypto features
                "volume_z_score": features.volume_z_score,
                "fear_greed_score": features.fear_greed_score,
                "price_momentum": features.price_momentum,
                
                # Debate features
                "debate_health": features.debate_health,
                "debate_confidence": features.debate_confidence,
                "debate_multiplier": features.debate_multiplier,
                "debate_status": features.debate_status,
                
                # Sentiment features
                "news_sentiment": features.news_sentiment,
                "social_sentiment": features.social_sentiment,
                "sentiment_intensity": features.sentiment_intensity,
                
                # Composite metrics
                "data_completeness": features.data_completeness,
                "strategy_alignment": self._calculate_strategy_alignment(features),
            },
            confidence=features.data_completeness,
            source="enhanced_kalshi_generator",
            alignment_score=self._calculate_strategy_alignment(features),
        )
        return signal

    def _calculate_strategy_alignment(self, features: CompositeFeatures) -> float:
        """Calculate alignment score between fear/greed, sentiment, and debate health.

        Returns 0.0-1.0 alignment score where higher = better alignment.
        """
        # Average news and social sentiment
        sentiment = ((features.news_sentiment or 0.0) +
                     (features.social_sentiment or 0.0)) / 2.0

        # Check alignment between fear/greed and sentiment
        fg_score = features.fear_greed_score or 0.5
        if fg_score > 0.6 and sentiment > 0.2:
            alignment_score = 0.9  # Bullish alignment
        elif fg_score < 0.4 and sentiment < -0.2:
            alignment_score = 0.9  # Bearish alignment
        elif 0.4 <= fg_score <= 0.6 and abs(sentiment) < 0.2:
            alignment_score = 0.8  # Neutral alignment
        else:
            alignment_score = 0.3  # Misaligned

        # Factor in debate health
        if features.debate_health:
            alignment_score *= features.debate_health

        return max(0.0, min(1.0, alignment_score))
    
    def _create_suppressed_signal(self, features: CompositeFeatures, market: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """Create a suppressed signal for analysis"""
        signal = self._unified_manager.create_kalshi_signal(
            ticker=features.symbol,
            edge_bps=features.kalshi_edge_bps or 0.0,
            features={
                "suppressed_reason": reason,
                "original_edge_bps": features.kalshi_edge_bps,
                "data_completeness": features.data_completeness,
            },
            confidence=0.1,
            source="enhanced_kalshi_generator",
            suppressed=True
        )
        
        # Log suppressed signal explicitly for post-mortem analysis
        logger.info(
            f"Suppressed Kalshi signal for {features.symbol}: {reason}, "
            f"edge_bps={features.kalshi_edge_bps}, completeness={features.data_completeness:.2f}"
        )
        
        return signal
    
    def _map_to_crypto_symbol(self, kalshi_symbol: str) -> Optional[str]:
        """Map Kalshi symbol to crypto symbol for feature lookup"""
        # Simple mapping for common symbols
        if "BTC" in kalshi_symbol:
            return "BTC"
        elif "ETH" in kalshi_symbol:
            return "ETH"
        elif "SOL" in kalshi_symbol:
            return "SOL"
        else:
            return None


# Singleton instance
_generator: Optional[EnhancedKalshiSignalGenerator] = None


def get_enhanced_kalshi_generator(thresholds: Optional[SignalThresholds] = None) -> EnhancedKalshiSignalGenerator:
    """Get the singleton enhanced Kalshi signal generator"""
    global _generator
    if _generator is None:
        _generator = EnhancedKalshiSignalGenerator(thresholds)
    return _generator


def run_enhanced_kalshi_generation(markets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run enhanced Kalshi signal generation (sync entry point)."""
    import asyncio
    generator = get_enhanced_kalshi_generator()
    coro = generator.generate_all_signals(markets)
    try:
        loop = asyncio.get_running_loop()
        # Already inside an event loop — schedule as a task and block
        import concurrent.futures
        future = concurrent.futures.Future()

        async def _run():
            try:
                future.set_result(await coro)
            except Exception as exc:
                future.set_exception(exc)

        loop.create_task(_run())
        # Can't block inside async context; return empty placeholder so the
        # caller's sync pipeline proceeds; results arrive on the next tick.
        return {"generated": 0, "stored": 0, "suppressed": 0, "insufficient_data": 0, "errors": 0, "signals": []}
    except RuntimeError:
        # No running event loop — safe to use asyncio.run()
        return asyncio.run(coro)
