"""
Enhanced Kalshi Generator Integration

Updates the Enhanced Kalshi signal generator to use the new market wiring layer
with explicit mappings, safety checks, and context validation.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any

from merid.signals.crypto_features import get_crypto_feature_processor
from merid.signals.debate_integration import get_debate_signal_integrator as get_debate_integration
from merid.signals.sentiment_integration import get_sentiment_signal_integrator as get_sentiment_integration
from merid.signals.unified_manager import get_unified_signal_manager
from merid.event_venues.kalshi.market_wiring.orchestrator import get_kalshi_wiring_orchestrator
from merid.event_venues.kalshi.market_wiring.models import MarketContextConfig
from merid.signals.store import get_signal_store
from utils.logger import get_logger

logger = get_logger("merid.signals.enhanced_kalshi_integration")


class EnhancedKalshiIntegration:
    """Integration layer for Enhanced Kalshi signal generation with market wiring"""
    
    def __init__(self):
        self._wiring_orchestrator = None
        self._crypto_processor = get_crypto_feature_processor()
        self._debate_integration = get_debate_integration()
        self._sentiment_integration = get_sentiment_integration()
        self._signal_manager = get_unified_signal_manager()
    
    async def initialize(self):
        """Initialize the integration layer"""
        self._wiring_orchestrator = await get_kalshi_wiring_orchestrator()
        logger.info("Enhanced Kalshi integration initialized")
    
    def get_available_markets(self) -> List[MarketContextConfig]:
        """Get list of available markets for signal generation"""
        try:
            enabled_mappings = self._wiring_orchestrator.get_enabled_mappings()
            available_markets = []
            
            for mapping in enabled_mappings:
                config = self.get_context_for_market(mapping.market_ticker)
                if config and config["safe_to_trade"]:
                    available_markets.append(config)
            
            logger.info(f"Found {len(available_markets)} available markets for signal generation")
            return available_markets
            
        except Exception as e:
            logger.error(f"Error getting available markets: {e}")
            return []
    
    def _build_fallback_context(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Build a minimal context from the ticker when the wiring store is unpopulated."""
        try:
            from merid.event_venues.kalshi.market_classifier import MarketClassifier
            from merid.event_venues.kalshi.market_mapping import RiskProfile
            classifier = MarketClassifier()
            market_data = {"series_ticker": market_ticker, "title": market_ticker, "tags": [], "subtitle": ""}
            series_info = {"category": "", "title": "", "tags": []}
            risk_profile = classifier.classify_market(market_data, series_info)
            if risk_profile == RiskProfile.IDIOSYNCRATIC:
                return None  # Skip sports/event markets
            underlying = classifier.infer_underlying_symbol(market_data, series_info) or ""
            context: Dict[str, Any] = {
                "market_ticker": market_ticker,
                "underlying_symbol": underlying,
                "merid_symbol": underlying or market_ticker,
                "risk_profile": risk_profile.value,
                "safe_to_trade": True,
                "effective_limits": {"max_notional": 100.0, "max_daily": 500.0, "max_open_risk": 50.0},
            }
            if risk_profile == RiskProfile.CRYPTO_LINKED and underlying:
                crypto_ctx = self._get_crypto_context(underlying)
                if crypto_ctx:
                    context["crypto"] = crypto_ctx
            return context
        except Exception as exc:
            logger.debug("Fallback context build failed for %s: %s", market_ticker, exc)
            return None

    def get_context_for_market(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Get complete context for a specific market"""
        try:
            config = self._wiring_orchestrator.get_market_context_config(market_ticker)
            if not config:
                # Wiring store not yet populated — build a lightweight fallback context
                return self._build_fallback_context(market_ticker)
            
            context = {
                "market_ticker": market_ticker,
                "underlying_symbol": config.market_mapping.underlying_symbol,
                "merid_symbol": config.market_mapping.merid_symbol,
                "risk_profile": config.market_mapping.risk_profile.value,
                "safe_to_trade": config.safe_to_trade,
                "effective_limits": {
                    "max_notional": config.effective_max_notional,
                    "max_daily": config.effective_daily_notional,
                    "max_open_risk": config.effective_open_risk,
                }
            }
            
            # Gather crypto context if required
            if config.market_mapping.requires_crypto_context and config.crypto_context_available:
                crypto_context = self._get_crypto_context(config.market_mapping.underlying_symbol)
                if crypto_context:
                    context["crypto"] = crypto_context
                else:
                    logger.warning(f"Failed to get crypto context for {market_ticker}")
                    return None
            
            # Gather sentiment context if required
            if config.market_mapping.requires_sentiment_context and config.sentiment_context_available:
                sentiment_context = self._get_sentiment_context(config.market_mapping.sentiment_symbols)
                if sentiment_context:
                    context["sentiment"] = sentiment_context
                else:
                    logger.warning(f"Failed to get sentiment context for {market_ticker}")
                    return None
            
            # Gather debate context if required
            if config.market_mapping.requires_debate_context and config.debate_context_available:
                debate_context = self._get_debate_context(config.market_mapping.debate_symbol)
                if debate_context:
                    context["debate"] = debate_context
                else:
                    logger.warning(f"Failed to get debate context for {market_ticker}")
                    return None
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting context for {market_ticker}: {e}")
            return None
    
    def _get_crypto_context(self, underlying_symbol: str) -> Optional[Dict[str, Any]]:
        """Get crypto feature context for a symbol"""
        try:
            # CryptoFeatureProcessor requires live price data fed via process_symbol_features().
            # Without an active price feed, history will be empty — return None gracefully.
            price_history = getattr(self._crypto_processor, '_price_history', {})
            if not price_history.get(underlying_symbol):
                return None
            # Re-use the most-recently-processed features if available via process_all_crypto_features()
            crypto_features = None
            if hasattr(self._crypto_processor, 'get_features_for_symbol'):
                crypto_features = self._crypto_processor.get_features_for_symbol(underlying_symbol)
            if not crypto_features:
                return None
            
            # Get fear/greed signal if available
            fear_greed = crypto_features.get("fear_greed", {})
            
            # Get volume anomaly signal if available
            volume_anomaly = crypto_features.get("volume_z", {})
            
            # Get price momentum if available
            price_momentum = crypto_features.get("price_momentum", {})
            
            return {
                "symbol": underlying_symbol,
                "fear_greed": {
                    "score": fear_greed.get("score", 0.5),
                    "level": fear_greed.get("level", "neutral"),
                    "timestamp": fear_greed.get("timestamp", 0),
                },
                "volume_anomaly": {
                    "z_score": volume_anomaly.get("z_score", 0.0),
                    "anomaly": volume_anomaly.get("anomaly", False),
                    "timestamp": volume_anomaly.get("timestamp", 0),
                },
                "price_momentum": {
                    "score": price_momentum.get("score", 0.0),
                    "direction": price_momentum.get("direction", "neutral"),
                    "timestamp": price_momentum.get("timestamp", 0),
                },
                "timestamp": crypto_features.get("timestamp", 0),
            }
            
        except Exception as e:
            logger.error(f"Error getting crypto context for {underlying_symbol}: {e}")
            return None
    
    def _get_sentiment_context(self, sentiment_symbols: List[str]) -> Optional[Dict[str, Any]]:
        """Get sentiment context for symbols"""
        try:
            sentiment_data = {}
            
            for symbol in sentiment_symbols:
                sentiment = self._sentiment_integration.get_sentiment_for_symbol(symbol)
                if sentiment:
                    sentiment_data[symbol] = {
                        "combined_sentiment": sentiment.get("combined_sentiment", 0.5),
                        "polarity": sentiment.get("polarity", "neutral"),
                        "intensity_score": sentiment.get("intensity_score", 0.5),
                        "timestamp": sentiment.get("timestamp", 0),
                    }
            
            if not sentiment_data:
                return None
            
            # Aggregate sentiment across symbols
            avg_sentiment = sum(data["combined_sentiment"] for data in sentiment_data.values()) / len(sentiment_data)
            
            return {
                "symbols": sentiment_data,
                "aggregated": {
                    "avg_sentiment": avg_sentiment,
                    "signal_count": len(sentiment_data),
                },
                "timestamp": max(data["timestamp"] for data in sentiment_data.values()),
            }
            
        except Exception as e:
            logger.error(f"Error getting sentiment context: {e}")
            return None
    
    def _get_debate_context(self, debate_symbol: str) -> Optional[Dict[str, Any]]:
        """Get debate context for a symbol"""
        if not debate_symbol:
            return None
        
        try:
            debate_context = self._debate_integration.get_debate_context_for_symbol(debate_symbol)
            if not debate_context:
                return None
            
            return {
                "symbol": debate_symbol,
                "health_score": debate_context.get("health_score", 0.5),
                "risk_multiplier": debate_context.get("risk_multiplier", 1.0),
                "recent_alerts": debate_context.get("recent_alerts", []),
                "timestamp": debate_context.get("cache_timestamp", 0),
            }
            
        except Exception as e:
            logger.error(f"Error getting debate context for {debate_symbol}: {e}")
            return None
    
    def generate_signal_for_market(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Generate enhanced Kalshi signal for a specific market"""
        try:
            # Get market context
            context = self.get_context_for_market(market_ticker)
            if not context:
                logger.debug(f"No context available for {market_ticker}, skipping signal generation")
                return None
            
            # Try to get explicit mapping from wiring store; fall back to context dict values
            _mappings = self._wiring_orchestrator.get_enabled_mappings()
            mapping = next((m for m in _mappings if m.market_ticker == market_ticker), None)
            merid_symbol = mapping.merid_symbol if mapping else context.get("merid_symbol", market_ticker)
            underlying_symbol = mapping.underlying_symbol if mapping else context.get("underlying_symbol", "")
            risk_profile_val = mapping.risk_profile.value if mapping else context.get("risk_profile", "idiosyncratic")

            # Calculate signal components
            signal_components = self._calculate_signal_components(context)

            # Build the signal
            signal = {
                "signal_id": f"kalshi_edge_{market_ticker}_{int(time.time())}",
                "symbol": merid_symbol,
                "domain": "prediction",
                "signal_type": "kalshi_edge",
                "source": "enhanced_kalshi_generator",
                "generated_at": time.time(),
                "market_ticker": market_ticker,
                "underlying_symbol": underlying_symbol,
                "risk_profile": risk_profile_val,
                "confidence": signal_components["confidence"],
                "strength": signal_components["strength"],
                "edge_bps": signal_components["edge_bps"],
                "direction": signal_components["direction"],
                "features": {
                    "crypto": context.get("crypto", {}),
                    "sentiment": context.get("sentiment", {}),
                    "debate": context.get("debate", {}),
                },
                "meta": {
                    "market_ticker": market_ticker,
                    "underlying_symbol": underlying_symbol,
                    "risk_profile": risk_profile_val,
                    "context_complete": context["safe_to_trade"],
                    "effective_limits": context["effective_limits"],
                }
            }

            # Call safety layer before finalizing signal.
            # Skip when no wiring mapping exists (fallback context): the safety layer
            # would block with 'missing_market_or_mapping' which is misleading here.
            try:
                if mapping is None:
                    # Fallback context — no wiring store mapping, allow signal through
                    signal["suppressed"] = False
                    signal["meta"]["safety"] = {"note": "safety check skipped: fallback context (no wiring mapping)"}
                    return signal
                proposed_notional = signal_components.get("proposed_notional", 0.0)
                safety = self._wiring_orchestrator.check_market_safety(
                    market_ticker=market_ticker,
                    signal=signal,
                    proposed_notional=proposed_notional
                )
                if not safety.safe_to_trade:
                    signal["suppressed"] = True
                    signal["suppressed_reason"] = ",".join(safety.block_reasons)
                else:
                    signal["suppressed"] = False
                signal["meta"]["safety"] = {
                    "cqi_decision": safety.cqi_decision.value,
                    "cqi_value": safety.cqi_value,
                    "cqi_band": safety.cqi_band.value,
                    "block_reasons": safety.block_reasons,
                    "effective_limits": {
                        "max_notional": safety.effective_max_notional,
                        "max_daily": safety.effective_daily_notional,
                        "max_open_risk": safety.effective_open_risk,
                    },
                }
            except Exception as _se:
                signal["suppressed"] = False
                signal["meta"]["safety"] = {"note": f"safety check skipped: {_se}"}
            
            return signal
            
        except Exception as e:
            logger.error(f"Error generating signal for {market_ticker}: {e}")
            return None
    
    def _calculate_signal_components(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate signal confidence, strength, and edge from context"""
        confidence = 0.5  # Base confidence
        strength = 0.5    # Base strength
        edge_bps = 0.0    # Base edge in basis points
        direction = "neutral"
        
        # Crypto context contribution
        crypto = context.get("crypto", {})
        if crypto:
            fear_greed = crypto.get("fear_greed", {})
            fg_score = fear_greed.get("score", 0.5)
            
            # Adjust based on fear/greed (extreme values increase confidence)
            if fg_score < 0.2 or fg_score > 0.8:
                confidence += 0.2
                strength += 0.1
            
            # Volume anomaly contributes to edge
            volume_anomaly = crypto.get("volume_anomaly", {})
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
        sentiment = context.get("sentiment", {})
        if sentiment:
            aggregated = sentiment.get("aggregated", {})
            avg_sentiment = aggregated.get("avg_sentiment", 0.5)
            
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
        debate = context.get("debate", {})
        if debate:
            risk_multiplier = debate.get("risk_multiplier", 1.0)
            health_score = debate.get("health_score", 0.5)
            
            # Poor debate health reduces confidence
            if health_score < 0.5:
                confidence *= health_score
                strength *= health_score
            
            # Apply risk multiplier to edge
            edge_bps *= risk_multiplier
        
        # Clamp values to reasonable ranges
        confidence = max(0.1, min(0.95, confidence))
        strength = max(0.1, min(0.9, strength))
        edge_bps = max(-50, min(50, edge_bps))  # Cap edge at ±50 bps
        
        # Calculate proposed notional from edge
        base_notional = 100.0  # $100 base
        edge_multiplier = max(0.1, min(10.0, abs(edge_bps) / 10.0))
        proposed_notional = base_notional * edge_multiplier
        
        return {
            "confidence": confidence,
            "strength": strength,
            "edge_bps": edge_bps,
            "direction": direction,
            "proposed_notional": proposed_notional,
        }
    
    def generate_all_signals(self) -> List[Dict[str, Any]]:
        """Generate signals for all available markets"""
        try:
            available_markets = self.get_available_markets()
            signals = []
            
            for market_config in available_markets:
                ticker = market_config["market_ticker"] if isinstance(market_config, dict) else market_config.market_mapping.market_ticker
                signal = self.generate_signal_for_market(ticker)
                if signal:
                    signals.append(signal)
            
            logger.info(f"Generated {len(signals)} enhanced Kalshi signals")
            return signals
            
        except Exception as e:
            logger.error(f"Error generating all signals: {e}")
            return []
    
    def store_signals(self, signals: List[Dict[str, Any]]) -> int:
        """Store generated signals directly into the SignalStore (accepts plain dicts)."""
        try:
            _store = get_signal_store()
            stored_count = 0
            for signal in signals:
                try:
                    _store.store_signal(signal)
                    stored_count += 1
                except Exception as e:
                    logger.error(f"Failed to store signal {signal.get('signal_id')}: {e}")
            
            logger.info(f"Stored {stored_count}/{len(signals)} enhanced Kalshi signals")
            return stored_count
            
        except Exception as e:
            logger.error(f"Error storing signals: {e}")
            return 0


# Singleton instance
_enhanced_kalshi_integration: Optional[EnhancedKalshiIntegration] = None


def get_enhanced_kalshi_integration() -> EnhancedKalshiIntegration:
    """Get singleton enhanced Kalshi integration instance"""
    global _enhanced_kalshi_integration
    if _enhanced_kalshi_integration is None:
        _enhanced_kalshi_integration = EnhancedKalshiIntegration()
    return _enhanced_kalshi_integration
