"""
Market Mapping Builder

Creates explicit mappings between Kalshi markets and MERID symbols
with automatic rules and manual override support.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass

from merid.event_venues.kalshi.market_wiring.models import (
    MarketMapping,
    RiskProfile,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_wiring.mapping")


@dataclass
class MappingRule:
    """Rule for automatic market mapping"""
    # Matching criteria
    category_patterns: List[str]
    title_patterns: List[str]
    tag_patterns: List[str]
    series_patterns: List[str]
    
    # Mapping result
    underlying_symbol: str
    merid_symbol: str
    sentiment_symbols: List[str]
    debate_symbol: Optional[str]
    
    # Context requirements
    requires_crypto_context: bool
    requires_debate_context: bool
    requires_sentiment_context: bool
    
    # Risk profile
    risk_profile: RiskProfile


class MarketMappingBuilder:
    """Builds and maintains market mappings"""
    
    def __init__(self, manual_overrides_file: Optional[str] = None):
        self._store = get_kalshi_market_store()
        self._manual_overrides_file = manual_overrides_file
        self._manual_overrides: Dict[str, Dict[str, Any]] = {}
        
        # Load manual overrides
        self._load_manual_overrides()
        
        # Define automatic mapping rules
        self._mapping_rules = self._define_mapping_rules()
    
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
    
    def _define_mapping_rules(self) -> List[MappingRule]:
        """Define automatic mapping rules"""
        rules = []
        
        # Bitcoin mappings
        rules.append(MappingRule(
            category_patterns=["crypto"],
            title_patterns=["bitcoin", "btc"],
            tag_patterns=["bitcoin", "btc"],
            series_patterns=["btc"],
            underlying_symbol="BTC",
            merid_symbol="BTC",
            sentiment_symbols=["BTC", "BTC-USD"],
            debate_symbol="BTC",
            requires_crypto_context=True,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.CRYPTO_LINKED,
        ))
        
        # Ethereum mappings
        rules.append(MappingRule(
            category_patterns=["crypto"],
            title_patterns=["ethereum", "eth"],
            tag_patterns=["ethereum", "eth"],
            series_patterns=["eth"],
            underlying_symbol="ETH",
            merid_symbol="ETH",
            sentiment_symbols=["ETH", "ETH-USD"],
            debate_symbol="ETH",
            requires_crypto_context=True,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.CRYPTO_LINKED,
        ))
        
        # Solana mappings
        rules.append(MappingRule(
            category_patterns=["crypto"],
            title_patterns=["solana", "sol"],
            tag_patterns=["solana", "sol"],
            series_patterns=["sol"],
            underlying_symbol="SOL",
            merid_symbol="SOL",
            sentiment_symbols=["SOL", "SOL-USD"],
            debate_symbol="SOL",
            requires_crypto_context=True,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.CRYPTO_LINKED,
        ))
        
        # XRP mappings
        rules.append(MappingRule(
            category_patterns=["crypto"],
            title_patterns=["xrp", "ripple"],
            tag_patterns=["xrp", "ripple"],
            series_patterns=["xrp"],
            underlying_symbol="XRP",
            merid_symbol="XRP",
            sentiment_symbols=["XRP", "XRP-USD"],
            debate_symbol="XRP",
            requires_crypto_context=True,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.CRYPTO_LINKED,
        ))
        
        # DOGE mappings
        rules.append(MappingRule(
            category_patterns=["crypto"],
            title_patterns=["doge", "dogecoin"],
            tag_patterns=["doge", "dogecoin"],
            series_patterns=["doge"],
            underlying_symbol="DOGE",
            merid_symbol="DOGE",
            sentiment_symbols=["DOGE", "DOGE-USD"],
            debate_symbol="DOGE",
            requires_crypto_context=True,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.CRYPTO_LINKED,
        ))
        
        # General crypto mappings (fallback)
        rules.append(MappingRule(
            category_patterns=["crypto"],
            title_patterns=["crypto", "cryptocurrency"],
            tag_patterns=["crypto"],
            series_patterns=["crypto"],
            underlying_symbol="BTC",  # Default to BTC for general crypto
            merid_symbol="BTC",
            sentiment_symbols=["BTC", "ETH"],
            debate_symbol=None,
            requires_crypto_context=True,
            requires_debate_context=False,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.CRYPTO_LINKED,
        ))
        
        # Election mappings
        rules.append(MappingRule(
            category_patterns=["elections", "politics"],
            title_patterns=["election", "president", "vote"],
            tag_patterns=["election", "politics"],
            series_patterns=["election"],
            underlying_symbol="US_ELECTION",
            merid_symbol="US_ELECTION",
            sentiment_symbols=["US", "POLITICS"],
            debate_symbol="US_ELECTION",
            requires_crypto_context=False,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.MACRO_ELECTION,
        ))
        
        # Macro economic mappings
        rules.append(MappingRule(
            category_patterns=["economics", "macro"],
            title_patterns=["inflation", "cpi", "fed", "interest rate", "gdp"],
            tag_patterns=["economics", "macro"],
            series_patterns=["economics"],
            underlying_symbol="US_MACRO",
            merid_symbol="US_MACRO",
            sentiment_symbols=["US", "ECONOMY"],
            debate_symbol="US_MACRO",
            requires_crypto_context=False,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.MACRO_ELECTION,
        ))
        
        # Equity index mappings
        rules.append(MappingRule(
            category_patterns=["equity", "stock"],
            title_patterns=["sp500", "s&p", "nasdaq", "dow"],
            tag_patterns=["equity", "stock"],
            series_patterns=["equity"],
            underlying_symbol="US_EQUITY",
            merid_symbol="SPY",
            sentiment_symbols=["SPY", "QQQ"],
            debate_symbol="US_EQUITY",
            requires_crypto_context=False,
            requires_debate_context=True,
            requires_sentiment_context=True,
            risk_profile=RiskProfile.EQUITY_LINKED,
        ))
        
        return rules
    
    def _matches_rule(self, market_data: Dict[str, Any], rule: MappingRule) -> bool:
        """Check if market data matches a mapping rule"""
        # Check category
        category = market_data.get("category", "").lower()
        if not any(pattern in category for pattern in rule.category_patterns):
            return False
        
        # Check title
        title = market_data.get("title", "").lower()
        if not any(pattern in title for pattern in rule.title_patterns):
            return False
        
        # Check tags
        tags = [tag.lower() for tag in market_data.get("tags", [])]
        if rule.tag_patterns and not any(pattern in tags for pattern in rule.tag_patterns):
            return False
        
        # Check series
        series = market_data.get("series_ticker", "").lower()
        if rule.series_patterns and not any(pattern in series for pattern in rule.series_patterns):
            return False
        
        return True
    
    def _apply_rule(self, market_data: Dict[str, Any], rule: MappingRule) -> MarketMapping:
        """Apply a mapping rule to create a MarketMapping"""
        return MarketMapping(
            market_ticker=market_data["market_ticker"],
            event_ticker=market_data["event_ticker"],
            series_ticker=market_data["series_ticker"],
            category=rule.risk_profile.value,
            risk_profile=rule.risk_profile,
            underlying_symbol=rule.underlying_symbol,
            merid_symbol=rule.merid_symbol,
            sentiment_symbols=rule.sentiment_symbols,
            debate_symbol=rule.debate_symbol,
            enabled=True,  # Auto-mapped markets are enabled by default
            requires_crypto_context=rule.requires_crypto_context,
            requires_debate_context=rule.requires_debate_context,
            requires_sentiment_context=rule.requires_sentiment_context,
        )
    
    def _apply_manual_override(self, market_data: Dict[str, Any]) -> Optional[MarketMapping]:
        """Apply manual override if available"""
        market_ticker = market_data["market_ticker"]
        
        if market_ticker in self._manual_overrides:
            override = self._manual_overrides[market_ticker]
            
            try:
                return MarketMapping(
                    market_ticker=market_ticker,
                    event_ticker=market_data["event_ticker"],
                    series_ticker=market_data["series_ticker"],
                    category=override.get("category", "idiosyncratic"),
                    risk_profile=RiskProfile(override.get("risk_profile", "idiosyncratic")),
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
                logger.error(f"Failed to apply manual override for {market_ticker}: {e}")
        
        return None
    
    def _create_disabled_mapping(self, market_data: Dict[str, Any], reason: str) -> MarketMapping:
        """Create a disabled mapping for unmapped markets"""
        return MarketMapping(
            market_ticker=market_data["market_ticker"],
            event_ticker=market_data["event_ticker"],
            series_ticker=market_data["series_ticker"],
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
    
    def build_mapping_for_market(self, market_data: Dict[str, Any]) -> MarketMapping:
        """Build mapping for a single market"""
        # Check manual overrides first
        manual_mapping = self._apply_manual_override(market_data)
        if manual_mapping:
            logger.info(f"Applied manual override for {market_data['market_ticker']}")
            return manual_mapping
        
        # Try automatic rules
        for rule in self._mapping_rules:
            if self._matches_rule(market_data, rule):
                logger.info(f"Applied automatic rule for {market_data['market_ticker']}: {rule.underlying_symbol}")
                return self._apply_rule(market_data, rule)
        
        # No match found - create disabled mapping
        logger.warning(f"No mapping found for {market_data['market_ticker']}, creating disabled mapping")
        return self._create_disabled_mapping(market_data, "no_rule_match")
    
    async def build_all_mappings(self) -> Dict[str, Any]:
        """Build mappings for all markets"""
        start_time = time.time()
        
        # Get all markets from store
        all_markets = self._store.get_open_markets()
        
        results = {
            "total_markets": len(all_markets),
            "mapped_markets": 0,
            "enabled_markets": 0,
            "disabled_markets": 0,
            "manual_overrides": 0,
            "automatic_mappings": 0,
            "errors": [],
            "duration_seconds": 0.0,
        }
        
        for market in all_markets:
            try:
                market_data = {
                    "market_ticker": market.market_ticker,
                    "event_ticker": market.event_ticker,
                    "series_ticker": market.series_ticker,
                    "category": market.category,
                    "title": market.title,
                    "tags": market.tags,
                }
                
                # Check if manual override exists
                if market.market_ticker in self._manual_overrides:
                    results["manual_overrides"] += 1
                
                # Build mapping
                mapping = self.build_mapping_for_market(market_data)
                
                # Store mapping
                if self._store.upsert_mapping(mapping):
                    results["mapped_markets"] += 1
                    if mapping.enabled:
                        results["enabled_markets"] += 1
                    else:
                        results["disabled_markets"] += 1
                    
                    # Count automatic mappings
                    if market.market_ticker not in self._manual_overrides:
                        results["automatic_mappings"] += 1
                else:
                    results["errors"].append(f"Failed to store mapping for {market.market_ticker}")
                
            except Exception as e:
                results["errors"].append(f"Error building mapping for {market.market_ticker}: {e}")
        
        # Update sync timestamp
        self._store.update_sync_timestamp("mapping", start_time)
        
        results["duration_seconds"] = time.time() - start_time
        
        logger.info(
            f"Mapping build completed: "
            f"total={results['total_markets']}, mapped={results['mapped_markets']}, "
            f"enabled={results['enabled_markets']}, disabled={results['disabled_markets']}, "
            f"manual={results['manual_overrides']}, auto={results['automatic_mappings']}, "
            f"errors={len(results['errors'])}"
        )
        
        return results
    
    def get_market_context_config(self, market_ticker: str) -> Optional[Dict[str, Any]]:
        """Get complete context configuration for a market"""
        try:
            # Get mapping
            mapping = self._store.get_mapping(market_ticker)
            if not mapping:
                return None
            
            # Get market record
            market = self._store.get_market(market_ticker)
            if not market:
                return None
            
            return {
                "market_ticker": market_ticker,
                "mapping": mapping.to_dict(),
                "market": market.to_dict(),
                "enabled": mapping.enabled and market.enabled_for_merid,
                "risk_profile": mapping.risk_profile.value,
                "underlying_symbol": mapping.underlying_symbol,
                "context_requirements": {
                    "crypto": mapping.requires_crypto_context,
                    "debate": mapping.requires_debate_context,
                    "sentiment": mapping.requires_sentiment_context,
                },
                "staleness_limits": {
                    "crypto": mapping.max_crypto_staleness,
                    "debate": mapping.max_debate_staleness,
                    "sentiment": mapping.max_sentiment_staleness,
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get context config for {market_ticker}: {e}")
            return None


# Singleton instance
_mapping_builder: Optional[MarketMappingBuilder] = None


def get_market_mapping_builder() -> MarketMappingBuilder:
    """Get singleton market mapping builder instance"""
    global _mapping_builder
    if _mapping_builder is None:
        overrides_file = os.path.join(
            os.path.dirname(__file__), 
            "manual_overrides.json"
        )
        _mapping_builder = MarketMappingBuilder(overrides_file)
    return _mapping_builder
