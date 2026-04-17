"""
Market Mapping Registry

Manages explicit mappings between Kalshi markets and MERID symbols
with automatic building and manual override support.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Any

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

from merid.event_venues.kalshi.market_wiring.models import (
    KalshiMarketRecord,
    MarketMapping,
    RiskProfile,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from merid.event_venues.kalshi.market_classifier import MarketClassifier
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_mapping")


class MarketMappingRegistry:
    """Registry for market mappings with automatic building and persistence"""
    
    def __init__(self, manual_overrides_file: Optional[str] = None):
        self._store = get_kalshi_market_store()
        self._classifier = MarketClassifier()
        self._manual_overrides_file = manual_overrides_file
        self._manual_overrides: Dict[str, Dict[str, Any]] = {}
        
        # Load manual overrides
        self._load_manual_overrides()
    
    def _load_manual_overrides(self):
        """Load manual override mappings from file"""
        if not self._manual_overrides_file or not os.path.exists(self._manual_overrides_file):
            logger.info("No manual overrides file found, using automatic rules only")
            return
        
        try:
            with open(self._manual_overrides_file, 'r') as f:
                self._manual_overrides = json.load(f)
            logger.info(f"Loaded {len(self._manual_overrides)} manual overrides")
        except Exception as e:
            logger.error(f"Failed to load manual overrides: {e}")
            self._manual_overrides = {}
    
    def get_mapping(self, market_ticker: str) -> Optional[MarketMapping]:
        """Get market mapping by ticker"""
        try:
            mapping = self._store.get_mapping(market_ticker)
            if mapping:
                return mapping
            return None
        except Exception as e:
            logger.error(f"Failed to get mapping for {market_ticker}: {e}")
            return None
    
    def upsert_mapping(self, mapping: MarketMapping) -> bool:
        """Insert or update a market mapping"""
        try:
            success = self._store.upsert_mapping(mapping)
            if success:
                logger.debug(f"Upserted mapping for {mapping.market_ticker}")
            return success
        except Exception as e:
            logger.error(f"Failed to upsert mapping for {mapping.market_ticker}: {e}")
            return False
    
    def auto_build_mapping(self, market: KalshiMarketRecord) -> MarketMapping:
        """Auto-build a mapping using classifier and market data"""
        try:
            # Get series metadata for consistency with classifier
            series_info = self._store.get_series(market.series_ticker) or {}
            
            # Use classifier to infer mappings
            risk_profile = self._classifier.classify_market(
                {
                    "title": market.title,
                    "subtitle": market.subtitle,
                    "tags": market.tags,
                    "series_ticker": market.series_ticker,
                },
                series_info
            )
            
            # Get normalized category
            category = self._classifier.get_normalized_category(
                {
                    "title": market.title,
                    "subtitle": market.subtitle,
                    "tags": market.tags,
                },
                series_info
            )
            
            # Infer symbols
            underlying = self._classifier.infer_underlying_symbol(
                {
                    "title": market.title,
                    "subtitle": market.subtitle,
                    "tags": market.tags,
                    "series_ticker": market.series_ticker,
                },
                series_info
            )
            
            sentiment_symbols = self._classifier.get_sentiment_symbols(
                {
                    "title": market.title,
                    "subtitle": market.subtitle,
                    "tags": market.tags,
                },
                series_info,
                risk_profile
            )
            
            debate_symbol = self._classifier.get_debate_symbol(
                {
                    "title": market.title,
                    "subtitle": market.subtitle,
                    "tags": market.tags,
                },
                series_info,
                risk_profile
            )
            
            # Determine context requirements based on risk profile
            requires_crypto = risk_profile == RiskProfile.CRYPTO_LINKED
            requires_debate = risk_profile in [RiskProfile.MACRO_ELECTION, RiskProfile.CRYPTO_LINKED]
            requires_sentiment = risk_profile in [RiskProfile.MACRO_ELECTION, RiskProfile.EQUITY_LINKED]
            
            # Auto-enable based on risk profile (aligned with universe sync defaults)
            enabled = risk_profile in [RiskProfile.CRYPTO_LINKED, RiskProfile.MACRO_ELECTION]
            
            # Create mapping
            mapping = MarketMapping(
                market_ticker=market.market_ticker,
                event_ticker=market.event_ticker,
                series_ticker=market.series_ticker,
                category=category,
                risk_profile=risk_profile,
                underlying_symbol=underlying or "UNMAPPED",
                merid_symbol=underlying or "UNMAPPED",
                sentiment_symbols=sentiment_symbols or [],
                debate_symbol=debate_symbol,
                enabled=enabled,
                requires_crypto_context=requires_crypto,
                requires_debate_context=requires_debate,
                requires_sentiment_context=requires_sentiment,
                max_crypto_staleness=300,  # 5 minutes
                max_sentiment_staleness=600,  # 10 minutes
                max_debate_staleness=900,  # 15 minutes
            )
            
            logger.debug(f"Auto-built mapping for {market.market_ticker}: {risk_profile.value}, enabled={enabled}")
            return mapping
            
        except Exception as e:
            logger.error(f"Error auto-building mapping for {market.market_ticker}: {e}")
            # Return disabled mapping as fallback
            return MarketMapping(
                market_ticker=market.market_ticker,
                event_ticker=market.event_ticker,
                series_ticker=market.series_ticker,
                category="idiosyncratic",
                risk_profile=RiskProfile.IDIOSYNCRATIC,
                underlying_symbol="UNMAPPED",
                merid_symbol="UNMAPPED",
                sentiment_symbols=[],
                debate_symbol=None,
                enabled=False,
                requires_crypto_context=False,
                requires_debate_context=False,
                requires_sentiment_context=False,
            )
    
    def _apply_manual_override(self, market) -> MarketMapping:
        """Apply manual override for a market"""
        override = self._manual_overrides[market.market_ticker]
        
        try:
            return MarketMapping(
                market_ticker=market.market_ticker,
                event_ticker=market.event_ticker,
                series_ticker=market.series_ticker,
                category=override.get("category", market.category),
                risk_profile=RiskProfile(override.get("risk_profile", market.risk_profile.value)),
                underlying_symbol=override.get("underlying_symbol", "UNKNOWN"),
                merid_symbol=override.get("merid_symbol", "UNKNOWN"),
                sentiment_symbols=override.get("sentiment_symbols", []),
                debate_symbol=override.get("debate_symbol"),
                enabled=override.get("enabled", False),
                requires_crypto_context=override.get("requires_crypto_context", False),
                requires_debate_context=override.get("requires_debate_context", False),
                requires_sentiment_context=override.get("requires_sentiment_context", False),
                max_crypto_staleness=override.get("max_crypto_staleness", 300.0),
                max_sentiment_staleness=override.get("max_sentiment_staleness", 600.0),
                max_debate_staleness=override.get("max_debate_staleness", 900.0),
            )
        except Exception as e:
            logger.error(f"Failed to apply manual override for {market.market_ticker}: {e}")
            return self._create_disabled_mapping(market, "override_error")
    
    def _determine_merid_symbol(self, underlying_symbol: str, risk_profile: RiskProfile) -> str:
        """Determine MERID symbol from underlying symbol and risk profile"""
        # For crypto, use the underlying symbol directly
        if risk_profile == RiskProfile.CRYPTO_LINKED:
            return underlying_symbol
        
        # For equity, use common ETF symbols
        if risk_profile == RiskProfile.EQUITY_LINKED:
            equity_mappings = {
                "SP500": "SPY",
                "NASDAQ": "QQQ",
                "NASDAQ100": "QQQ",
                "DOW": "DIA",
            }
            return equity_mappings.get(underlying_symbol, underlying_symbol)
        
        # For macro/elections, use descriptive symbols
        if risk_profile == RiskProfile.MACRO_ELECTION:
            macro_mappings = {
                "US_ELECTION_2024": "US_ELECTION",
                "US_MACRO": "US_MACRO",
            }
            return macro_mappings.get(underlying_symbol, underlying_symbol)
        
        # Default to underlying symbol
        return underlying_symbol
    
    def _should_auto_enable(self, risk_profile: RiskProfile, underlying_symbol: str) -> bool:
        """Determine if mapping should be auto-enabled"""
        # Auto-enable rules by risk profile
        auto_enable_rules = {
            RiskProfile.CRYPTO_LINKED: True,      # Crypto markets are well-understood
            RiskProfile.MACRO_ELECTION: True,    # Macro/elections are important
            RiskProfile.EQUITY_LINKED: False,    # Equity markets need manual review
            RiskProfile.IDIOSYNCRATIC: False,    # Idiosyncratic markets need manual review
        }
        
        base_rule = auto_enable_rules.get(risk_profile, False)
        
        # Additional checks for specific symbols
        if risk_profile == RiskProfile.CRYPTO_LINKED:
            # Enable for all canonical crypto assets (was BTC/ETH/SOL only — missing XRP, DOGE)
            return base_rule and underlying_symbol in ACTIVE_CRYPTO_ASSETS
        
        return base_rule
    
    def _create_disabled_mapping(self, market, reason: str) -> MarketMapping:
        """Create a disabled mapping with clear reason"""
        return MarketMapping(
            market_ticker=market.market_ticker,
            event_ticker=market.event_ticker,
            series_ticker=market.series_ticker,
            category="idiosyncratic",
            risk_profile=RiskProfile.IDIOSYNCRATIC,
            underlying_symbol="UNMAPPED",
            merid_symbol="UNMAPPED",
            sentiment_symbols=[],
            debate_symbol=None,
            enabled=False,
            requires_crypto_context=False,
            requires_debate_context=False,
            requires_sentiment_context=False,
        )
    
    def build_all_mappings(self) -> Dict[str, Any]:
        """Build mappings for all markets"""
        try:
            # Get all markets
            all_markets = self._store.get_open_markets()
            
            results = {
                "total_markets": len(all_markets),
                "mapped_markets": 0,
                "enabled_markets": 0,
                "disabled_markets": 0,
                "manual_overrides": 0,
                "automatic_mappings": 0,
                "errors": [],
            }
            
            for market in all_markets:
                try:
                    # Check if manual override exists
                    is_manual = market.market_ticker in self._manual_overrides
                    if is_manual:
                        results["manual_overrides"] += 1
                    
                    # Build mapping
                    mapping = self.auto_build_mapping(market)
                    
                    if mapping:
                        # Store mapping
                        if self.upsert_mapping(mapping):
                            results["mapped_markets"] += 1
                            if mapping.enabled:
                                results["enabled_markets"] += 1
                            else:
                                results["disabled_markets"] += 1
                            
                            # Count automatic mappings
                            if not is_manual:
                                results["automatic_mappings"] += 1
                        else:
                            results["errors"].append(f"Failed to store mapping for {market.market_ticker}")
                    else:
                        results["errors"].append(f"Failed to build mapping for {market.market_ticker}")
                
                except Exception as e:
                    results["errors"].append(f"Error processing {market.market_ticker}: {e}")
            
            logger.info(
                f"Mapping build completed: "
                f"total={results['total_markets']}, mapped={results['mapped_markets']}, "
                f"enabled={results['enabled_markets']}, disabled={results['disabled_markets']}, "
                f"manual={results['manual_overrides']}, auto={results['automatic_mappings']}, "
                f"errors={len(results['errors'])}"
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to build all mappings: {e}")
            return {
                "total_markets": 0,
                "mapped_markets": 0,
                "enabled_markets": 0,
                "disabled_markets": 0,
                "manual_overrides": 0,
                "automatic_mappings": 0,
                "errors": [str(e)],
            }
    
    def get_enabled_mappings(self) -> List[MarketMapping]:
        """Get all enabled mappings"""
        try:
            return self._store.get_enabled_mappings()
        except Exception as e:
            logger.error(f"Failed to get enabled mappings: {e}")
            return []
    
    def get_mappings_by_underlying(self, underlying_symbol: str) -> List[MarketMapping]:
        """Get mappings by underlying symbol"""
        try:
            return self._store.get_mappings_by_underlying(underlying_symbol)
        except Exception as e:
            logger.error(f"Failed to get mappings for {underlying_symbol}: {e}")
            return []
    
    def get_mappings_by_risk_profile(self, risk_profile: RiskProfile) -> List[MarketMapping]:
        """Get mappings by risk profile"""
        try:
            return self._store.get_mappings_by_risk_profile(risk_profile)
        except Exception as e:
            logger.error(f"Failed to get mappings for {risk_profile}: {e}")
            return []


# Singleton instance
_mapping_registry: Optional[MarketMappingRegistry] = None


def get_market_mapping_registry() -> MarketMappingRegistry:
    """Get singleton market mapping registry instance"""
    global _mapping_registry
    if _mapping_registry is None:
        overrides_file = os.path.join(
            os.path.dirname(__file__), 
            "manual_overrides.json"
        )
        _mapping_registry = MarketMappingRegistry(overrides_file)
    return _mapping_registry
