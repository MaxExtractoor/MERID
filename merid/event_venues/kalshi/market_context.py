"""
Market Context Resolver

Resolves complete market context including freshness checks and risk caps
for safe Kalshi market operations.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any

from merid.event_venues.kalshi.market_wiring.models import (
    MarketMapping,
    KalshiMarketRecord,
    MarketContextConfig,
    RiskProfile,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from merid.event_venues.kalshi.market_mapping import get_market_mapping_registry
from merid.signals.store import get_signal_store
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_context")


class MarketContextResolver:
    """Resolves complete market context with freshness and safety validation"""
    
    def __init__(self):
        self._market_store = get_kalshi_market_store()
        self._mapping_registry = get_market_mapping_registry()
        self._unified_store = get_signal_store()
    
    def get_context(self, market_ticker: str) -> Optional[MarketContextConfig]:
        """Return full context config for a market, including freshness and risk caps"""
        try:
            # Load market and mapping
            market = self._market_store.get_market(market_ticker)
            mapping = self._mapping_registry.get_mapping(market_ticker)
            
            if not market or not mapping:
                logger.debug(f"No market or mapping found for {market_ticker}")
                return self._create_disabled_context(market_ticker, "missing_market_or_mapping")
            
            # Check if enabled
            if not mapping.enabled or not market.enabled_for_merid:
                logger.debug(f"Market {market_ticker} is disabled")
                return self._create_disabled_context(market_ticker, "market_disabled")
            
            # Check context availability and freshness
            crypto_context = self._check_crypto_context(mapping)
            sentiment_context = self._check_sentiment_context(mapping)
            debate_context = self._check_debate_context(mapping)
            
            # Compute effective risk caps
            effective_caps = self._compute_effective_caps(
                market, mapping, crypto_context, sentiment_context, debate_context
            )
            
            # Create context config
            config = MarketContextConfig(
                market_mapping=mapping,
                kalshi_market=market,
                crypto_context_available=crypto_context["available"],
                sentiment_context_available=sentiment_context["available"],
                debate_context_available=debate_context["available"],
                crypto_fresh=crypto_context["fresh"],
                sentiment_fresh=sentiment_context["fresh"],
                debate_fresh=debate_context["fresh"],
                effective_max_notional=effective_caps["max_notional"],
                effective_daily_notional=effective_caps["max_daily"],
                effective_open_risk=effective_caps["max_open_risk"],
            )
            
            logger.debug(f"Context for {market_ticker}: safe_to_trade={config.safe_to_trade}")
            return config
            
        except Exception as e:
            logger.error(f"Error getting context for {market_ticker}: {e}")
            return self._create_disabled_context(market_ticker, "context_error")
    
    def _check_crypto_context(self, mapping: MarketMapping) -> Dict[str, Any]:
        """Check crypto context availability and freshness"""
        if not mapping.requires_crypto_context:
            return {"available": True, "fresh": True, "age_seconds": None}
        
        try:
            # Get latest crypto features for underlying symbol
            crypto_features = self._unified_store.get_latest_features(
                symbol=mapping.underlying_symbol,
                domain="crypto"
            )
            
            if not crypto_features:
                return {"available": False, "fresh": False, "age_seconds": None}
            
            # Check freshness
            current_time = time.time()
            feature_time = crypto_features.get("timestamp", 0)
            age_seconds = current_time - feature_time
            
            is_fresh = age_seconds <= mapping.max_crypto_staleness
            
            return {
                "available": True,
                "fresh": is_fresh,
                "age_seconds": age_seconds,
                "max_staleness": mapping.max_crypto_staleness,
            }
            
        except Exception as e:
            logger.error(f"Error checking crypto context for {mapping.underlying_symbol}: {e}")
            return {"available": False, "fresh": False, "age_seconds": None}
    
    def _check_sentiment_context(self, mapping: MarketMapping) -> Dict[str, Any]:
        """Check sentiment context availability and freshness"""
        if not mapping.requires_sentiment_context or not mapping.sentiment_symbols:
            return {"available": True, "fresh": True, "age_seconds": None}
        
        try:
            current_time = time.time()
            youngest_age = None
            any_available = False
            
            # Check each sentiment symbol
            for symbol in mapping.sentiment_symbols:
                sentiment_features = self._unified_store.get_latest_features(
                    symbol=symbol,
                    domain="sentiment"
                )
                
                if sentiment_features:
                    any_available = True
                    age = current_time - sentiment_features.get("timestamp", 0)
                    if youngest_age is None or age < youngest_age:
                        youngest_age = age
            
            if not any_available:
                return {"available": False, "fresh": False, "age_seconds": None}
            
            # Check freshness
            is_fresh = youngest_age <= mapping.max_sentiment_staleness
            
            return {
                "available": True,
                "fresh": is_fresh,
                "age_seconds": youngest_age,
                "max_staleness": mapping.max_sentiment_staleness,
            }
            
        except Exception as e:
            logger.error(f"Error checking sentiment context: {e}")
            return {"available": False, "fresh": False, "age_seconds": None}
    
    def _check_debate_context(self, mapping: MarketMapping) -> Dict[str, Any]:
        """Check debate context availability and freshness"""
        if not mapping.requires_debate_context or not mapping.debate_symbol:
            return {"available": True, "fresh": True, "age_seconds": None}
        
        try:
            # Get latest debate features
            debate_features = self._unified_store.get_latest_features(
                symbol=mapping.debate_symbol,
                domain="debate"
            )
            
            if not debate_features:
                return {"available": False, "fresh": False, "age_seconds": None}
            
            # Check freshness
            current_time = time.time()
            feature_time = debate_features.get("timestamp", 0)
            age_seconds = current_time - feature_time
            
            is_fresh = age_seconds <= mapping.max_debate_staleness
            
            return {
                "available": True,
                "fresh": is_fresh,
                "age_seconds": age_seconds,
                "max_staleness": mapping.max_debate_staleness,
            }
            
        except Exception as e:
            logger.error(f"Error checking debate context for {mapping.debate_symbol}: {e}")
            return {"available": False, "fresh": False, "age_seconds": None}
    
    def _compute_effective_caps(
        self,
        market: KalshiMarketRecord,
        mapping: MarketMapping,
        crypto_context: Dict[str, Any],
        sentiment_context: Dict[str, Any],
        debate_context: Dict[str, Any],
    ) -> Dict[str, float]:
        """Compute effective risk caps based on context availability"""
        
        # Start with base caps
        base_caps = {
            "max_notional": market.max_notional_per_trade,
            "max_daily": market.max_daily_notional,
            "max_open_risk": market.max_open_risk,
        }
        
        # Calculate context completeness factor (0.0 to 1.0)
        required_contexts = []
        if mapping.requires_crypto_context:
            required_contexts.append(crypto_context)
        if mapping.requires_sentiment_context:
            required_contexts.append(sentiment_context)
        if mapping.requires_debate_context:
            required_contexts.append(debate_context)
        
        if not required_contexts:
            return base_caps  # No context requirements
        
        # Calculate completeness factor
        available_count = sum(1 for ctx in required_contexts if ctx["available"])
        fresh_count = sum(1 for ctx in required_contexts if ctx["fresh"])
        
        # Factor based on availability (more important) and freshness
        availability_factor = available_count / len(required_contexts)
        freshness_factor = fresh_count / len(required_contexts) if required_contexts else 1.0
        
        # Weight availability more heavily than freshness
        completeness_factor = (availability_factor * 0.7) + (freshness_factor * 0.3)
        
        # Apply factor to caps (with minimum of 20% to allow some trading)
        min_factor = 0.2
        applied_factor = max(min_factor, completeness_factor)
        
        effective_caps = {
            "max_notional": base_caps["max_notional"] * applied_factor,
            "max_daily": base_caps["max_daily"] * applied_factor,
            "max_open_risk": base_caps["max_open_risk"] * applied_factor,
        }
        
        logger.debug(
            f"Effective caps for {market.market_ticker}: "
            f"factor={applied_factor:.2f}, "
            f"notional={effective_caps['max_notional']:.2f} (base={base_caps['max_notional']:.2f})"
        )
        
        return effective_caps
    
    def _create_disabled_context(self, market_ticker: str, reason: str) -> MarketContextConfig:
        """Create a disabled context configuration"""
        # Create dummy market and mapping for disabled context
        dummy_mapping = MarketMapping(
            market_ticker=market_ticker,
            event_ticker="",
            series_ticker="",
            category="idiosyncratic",
            risk_profile=RiskProfile.IDIOSYNCRATIC,
            underlying_symbol="DISABLED",
            merid_symbol="DISABLED",
            sentiment_symbols=[],
            debate_symbol=None,
            enabled=False,
            requires_crypto_context=False,
            requires_debate_context=False,
            requires_sentiment_context=False,
        )
        
        dummy_market = KalshiMarketRecord(
            market_ticker=market_ticker,
            event_ticker="",
            series_ticker="",
            category="idiosyncratic",
            tags=[],
            title="Disabled Market",
            subtitle=reason,
            close_ts=0.0,
            status="closed",
            enabled_for_merid=False,
            risk_profile=RiskProfile.IDIOSYNCRATIC,
            max_notional_per_trade=0.0,
            max_daily_notional=0.0,
            max_open_risk=0.0,
        )
        
        return MarketContextConfig(
            market_mapping=dummy_mapping,
            kalshi_market=dummy_market,
            crypto_context_available=False,
            sentiment_context_available=False,
            debate_context_available=False,
            crypto_fresh=False,
            sentiment_fresh=False,
            debate_fresh=False,
            effective_max_notional=0.0,
            effective_daily_notional=0.0,
            effective_open_risk=0.0,
        )
    
    def get_contexts_for_symbol(self, underlying_symbol: str) -> List[MarketContextConfig]:
        """Get all context configs for a given underlying symbol"""
        try:
            mappings = self._mapping_registry.get_mappings_by_underlying(underlying_symbol)
            contexts = []
            
            for mapping in mappings:
                context = self.get_context(mapping.market_ticker)
                if context:
                    contexts.append(context)
            
            return contexts
            
        except Exception as e:
            logger.error(f"Error getting contexts for {underlying_symbol}: {e}")
            return []
    
    def get_safe_contexts(self) -> List[MarketContextConfig]:
        """Get all safe-to-trade contexts"""
        try:
            enabled_mappings = self._mapping_registry.get_enabled_mappings()
            safe_contexts = []
            
            for mapping in enabled_mappings:
                context = self.get_context(mapping.market_ticker)
                if context and context.safe_to_trade:
                    safe_contexts.append(context)
            
            return safe_contexts
            
        except Exception as e:
            logger.error(f"Error getting safe contexts: {e}")
            return []
    
    def validate_context_for_signal(self, market_ticker: str) -> Dict[str, Any]:
        """Validate context for signal generation"""
        context = self.get_context(market_ticker)
        
        if not context:
            return {
                "valid": False,
                "reason": "no_context",
                "safe_to_trade": False,
            }
        
        if not context.safe_to_trade:
            return {
                "valid": False,
                "reason": "unsafe_to_trade",
                "safe_to_trade": False,
                "context_issues": self._get_context_issues(context),
            }
        
        return {
            "valid": True,
            "reason": "context_valid",
            "safe_to_trade": True,
            "effective_caps": {
                "max_notional": context.effective_max_notional,
                "max_daily": context.effective_daily_notional,
                "max_open_risk": context.effective_open_risk,
            }
        }
    
    def _get_context_issues(self, context: MarketContextConfig) -> List[str]:
        """Get list of context issues"""
        issues = []
        
        if not context.crypto_context_available and context.market_mapping.requires_crypto_context:
            issues.append("crypto_context_missing")
        elif not context.crypto_fresh and context.market_mapping.requires_crypto_context:
            issues.append("crypto_context_stale")
        
        if not context.sentiment_context_available and context.market_mapping.requires_sentiment_context:
            issues.append("sentiment_context_missing")
        elif not context.sentiment_fresh and context.market_mapping.requires_sentiment_context:
            issues.append("sentiment_context_stale")
        
        if not context.debate_context_available and context.market_mapping.requires_debate_context:
            issues.append("debate_context_missing")
        elif not context.debate_fresh and context.market_mapping.requires_debate_context:
            issues.append("debate_context_stale")
        
        return issues


# Singleton instance
_context_resolver: Optional[MarketContextResolver] = None


def get_market_context_resolver() -> MarketContextResolver:
    """Get singleton market context resolver instance"""
    global _context_resolver
    if _context_resolver is None:
        _context_resolver = MarketContextResolver()
    return _context_resolver
