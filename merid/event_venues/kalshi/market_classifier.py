"""
Market Classifier

Classifies Kalshi markets by risk profile and category using series metadata
and market content analysis.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
from merid.event_venues.kalshi.market_wiring.models import RiskProfile
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_classifier")


class MarketClassifier:
    """Classifies Kalshi markets by risk profile and normalized category"""
    
    def __init__(self, default_debate_symbol: str = "US_ELECTION_2024"):
        # Classification patterns
        self._crypto_patterns = {
            "categories": ["crypto", "cryptocurrency", "digital assets"],
            "tags": ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "ripple", "doge", "dogecoin", "crypto"],
            "title_keywords": ["bitcoin", "ethereum", "btc", "eth", "sol", "xrp", "doge", "crypto"],
            "series_patterns": ["btc", "eth", "sol", "xrp", "doge", "crypto"],
        }
        
        self._equity_patterns = {
            "categories": ["equity", "stocks", "indices", "etfs"],
            "tags": ["spy", "qqq", "ndx", "sp500", "nasdaq", "dow", "index"],
            "title_keywords": ["sp500", "s&p", "nasdaq", "dow jones", "spy", "qqq", "ndx"],
            "series_patterns": ["spy", "qqq", "ndx", "equity", "index"],
        }
        
        self._macro_patterns = {
            "categories": ["economics", "macro", "finance", "monetary policy"],
            "tags": ["cpi", "inflation", "fed", "fomc", "interest rates", "gdp", "employment"],
            "title_keywords": ["inflation", "cpi", "federal reserve", "fed", "fomc", "interest rate", "gdp", "unemployment"],
            "series_patterns": ["economics", "macro", "cpi", "fed", "inflation"],
        }
        
        self._election_patterns = {
            "categories": ["politics", "elections", "government"],
            "tags": ["election", "president", "vote", "politics", "congress", "senate"],
            "title_keywords": ["election", "president", "vote", "congress", "senate", "politics"],
            "series_patterns": ["election", "politics", "president", "vote"],
        }
        
        # Symbol mappings
        self._crypto_symbol_mappings = {
            "bitcoin": "BTC",
            "btc": "BTC",
            "ethereum": "ETH",
            "eth": "ETH",
            "solana": "SOL",
            "sol": "SOL",
            "xrp": "XRP",
            "ripple": "XRP",
            "doge": "DOGE",
            "dogecoin": "DOGE",
        }
        
        self._equity_symbol_mappings = {
            "sp500": "SPY",
            "s&p": "SPY",
            "spy": "SPY",
            "nasdaq": "QQQ",
            "ndx": "QQQ",
            "qqq": "QQQ",
            "dow jones": "DIA",
            "dow": "DIA",
        }
    
    def _matches_patterns(self, text: str, patterns: Dict[str, List[str]]) -> bool:
        """Check if text matches any of the provided patterns"""
        text_lower = text.lower()
        
        # Check categories
        for pattern in patterns.get("categories", []):
            if pattern.lower() in text_lower:
                return True
        
        # Check tags
        for pattern in patterns.get("tags", []):
            if pattern.lower() in text_lower:
                return True
        
        # Check title keywords
        for pattern in patterns.get("title_keywords", []):
            if pattern.lower() in text_lower:
                return True
        
        return False
    
    def _matches_series_pattern(self, series_ticker: str, patterns: List[str]) -> bool:
        """Check if series ticker matches any pattern"""
        series_lower = series_ticker.lower()
        for pattern in patterns:
            if pattern.lower() in series_lower:
                return True
        return False
    
    def classify_market(self, market_data: Dict[str, Any], series_info: Dict[str, Any]) -> RiskProfile:
        """Classify market by risk profile using market and series data"""
        # Combine market and series information
        combined_text = " ".join([
            market_data.get("title", ""),
            market_data.get("subtitle", ""),
            " ".join(market_data.get("tags", [])),
            series_info.get("category", ""),
            series_info.get("title", ""),
            " ".join(series_info.get("tags", [])),
        ])
        
        series_ticker = market_data.get("series_ticker", "")
        
        # Check crypto patterns first (most specific)
        if (self._matches_patterns(combined_text, self._crypto_patterns) or
            self._matches_series_pattern(series_ticker, self._crypto_patterns["series_patterns"])):
            return RiskProfile.CRYPTO_LINKED
        
        # Check equity patterns
        if (self._matches_patterns(combined_text, self._equity_patterns) or
            self._matches_series_pattern(series_ticker, self._equity_patterns["series_patterns"])):
            return RiskProfile.EQUITY_LINKED
        
        # Check election patterns (more specific than general macro)
        if (self._matches_patterns(combined_text, self._election_patterns) or
            self._matches_series_pattern(series_ticker, self._election_patterns["series_patterns"])):
            return RiskProfile.MACRO_ELECTION
        
        # Check macro patterns (general case)
        if (self._matches_patterns(combined_text, self._macro_patterns) or
            self._matches_series_pattern(series_ticker, self._macro_patterns["series_patterns"])):
            return RiskProfile.MACRO_ELECTION
        
        # Default to idiosyncratic
        return RiskProfile.IDIOSYNCRATIC
    
    def get_normalized_category(self, market_data: Dict[str, Any], series_info: Dict[str, Any]) -> str:
        """Get normalized category string"""
        # Use series category if available
        series_category = series_info.get("category", "").lower()
        
        # Normalize common categories
        category_mapping = {
            "crypto": "crypto",
            "cryptocurrency": "crypto",
            "digital assets": "crypto",
            "equity": "equity",
            "stocks": "equity",
            "indices": "equity",
            "etfs": "equity",
            "economics": "macro",
            "macro": "macro",
            "finance": "macro",
            "politics": "elections",
            "elections": "elections",
            "government": "elections",
            "sports": "idiosyncratic",
            "weather": "idiosyncratic",
            "entertainment": "idiosyncratic",
        }
        
        # Try to map series category
        normalized = category_mapping.get(series_category)
        if normalized:
            return normalized
        
        # Fall back to risk profile-based categorization
        risk_profile = self.classify_market(market_data, series_info)
        profile_to_category = {
            RiskProfile.CRYPTO_LINKED: "crypto",
            RiskProfile.EQUITY_LINKED: "equity",
            RiskProfile.MACRO_ELECTION: "macro",  # Could be "elections" for specific cases
            RiskProfile.IDIOSYNCRATIC: "idiosyncratic",
        }
        
        return profile_to_category.get(risk_profile, "idiosyncratic")
    
    def infer_underlying_symbol(self, market_data: Dict[str, Any], series_info: Dict[str, Any]) -> Optional[str]:
        """Infer underlying symbol from market and series data"""
        combined_text = " ".join([
            market_data.get("title", ""),
            market_data.get("subtitle", ""),
            series_info.get("title", ""),
        ]).lower()
        
        # Check crypto symbols
        for keyword, symbol in self._crypto_symbol_mappings.items():
            if keyword in combined_text:
                return symbol
        
        # Check equity symbols
        for keyword, symbol in self._equity_symbol_mappings.items():
            if keyword in combined_text:
                return symbol
        
        # Check series ticker for direct symbol mapping
        series_ticker = market_data.get("series_ticker", "").upper()
        _direct_symbols = set(ACTIVE_CRYPTO_ASSETS) | {"SPY", "QQQ", "NDX"}
        if series_ticker in _direct_symbols:
            return series_ticker
        
        return None
    
    def get_sentiment_symbols(self, underlying_symbol: Optional[str], risk_profile: RiskProfile) -> List[str]:
        """Get sentiment symbols for a market based on underlying symbol and risk profile"""
        if not underlying_symbol:
            return []
        
        symbols = []
        
        # Add primary symbol
        symbols.append(underlying_symbol)
        
        # Add common variations for crypto
        if risk_profile == RiskProfile.CRYPTO_LINKED:
            if underlying_symbol == "BTC":
                symbols.append("BTC-USD")
            elif underlying_symbol == "ETH":
                symbols.append("ETH-USD")
            elif underlying_symbol == "SOL":
                symbols.append("SOL-USD")
        
        # Add common variations for equity
        elif risk_profile == RiskProfile.EQUITY_LINKED:
            if underlying_symbol == "SPY":
                symbols.append("SP500")
            elif underlying_symbol == "QQQ":
                symbols.append("NASDAQ")
            elif underlying_symbol == "NDX":
                symbols.append("NASDAQ100")
        
        # Add macro symbols
        elif risk_profile == RiskProfile.MACRO_ELECTION:
            symbols.extend(["US", "USA", "ECONOMY"])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_symbols = []
        for symbol in symbols:
            if symbol not in seen:
                seen.add(symbol)
                unique_symbols.append(symbol)
        
        return unique_symbols
    
    def get_debate_symbol(self, market_data: Dict[str, Any], series_info: Dict[str, Any], risk_profile: RiskProfile) -> Optional[str]:
        """Get debate symbol for a market"""
        if risk_profile not in [RiskProfile.MACRO_ELECTION, RiskProfile.CRYPTO_LINKED]:
            return None
        
        combined_text = " ".join([
            market_data.get("title", ""),
            market_data.get("subtitle", ""),
            series_info.get("title", ""),
        ]).lower()
        
        # Election-related debate symbols
        if "election" in combined_text or "president" in combined_text:
            return self._default_debate_symbol
        
        # Macro debate symbols
        if any(keyword in combined_text for keyword in ["fed", "fomc", "inflation", "cpi"]):
            return "US_MACRO"
        
        # Crypto debate symbols
        if risk_profile == RiskProfile.CRYPTO_LINKED:
            underlying = self.infer_underlying_symbol(market_data, series_info)
            if underlying:
                return underlying
        
        return None
