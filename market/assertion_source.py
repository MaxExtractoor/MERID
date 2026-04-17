"""
Market Data Assertion Source

Provides market domain assertions to reduce blind spots in the reality system.
"""

import time
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass

from core.reality_registry import (
    get_reality_registry,
    AssertionDomain,
    AssertionProvenance,
    RealityAssertion,
    AssertionStatus
)
from utils.logger import get_logger

logger = get_logger("market.assertion_source")


@dataclass
class MarketAssertion:
    """Market data assertion for reality system."""
    symbol: str
    price: float
    volume: float
    timestamp: float
    source: str
    confidence: float = 0.8


class MarketAssertionSource:
    """
    Market data assertion source for reality system.
    
    Periodically registers market data assertions to reduce blind spots
    in the market domain.
    """
    
    def __init__(self):
        self.registry = get_reality_registry()
        self.last_assertion_time = 0.0
        self.assertion_interval = 60.0  # 1 minute
        self.market_data_cache: Dict[str, MarketAssertion] = {}
    
    def update_market_data(self, symbol: str, price: float, volume: float, source: str = "bootstrap"):
        """Update market data and register assertion if needed."""
        current_time = time.time()
        
        # Cache the market data
        self.market_data_cache[symbol] = MarketAssertion(
            symbol=symbol,
            price=price,
            volume=volume,
            timestamp=current_time,
            source=source,
            confidence=0.8
        )
        
        # Register assertion if interval has passed
        if current_time - self.last_assertion_time >= self.assertion_interval:
            self._register_market_assertion(symbol)
            self.last_assertion_time = current_time
    
    def _register_market_assertion(self, symbol: str):
        """Register a market data assertion."""
        try:
            market_data = self.market_data_cache.get(symbol)
            if not market_data:
                logger.warning(f"No market data available for {symbol}")
                return
            
            # Create assertion
            assertion_id = self.registry.register_assertion(
                domain=AssertionDomain.MARKET,
                description=f"Market data for {symbol}: price=${market_data.price}, volume={market_data.volume}",
                confidence=market_data.confidence,
                provenance_score=0.7,
                regime_compatibility=1.0,
                decay_rate=0.05,  # Market data decays faster
                validity_window=300.0,  # 5 minutes
                sources=[
                    AssertionProvenance(
                        source_id="market_feed",
                        module_id="market_assertion_source",
                        evidence_hash=f"market_{symbol}_{market_data.timestamp}",
                        weight=1.0,
                        timestamp=market_data.timestamp
                    )
                ]
            )
            
            logger.info(f"Registered market assertion: {symbol} - {assertion_id}")
            
        except Exception as e:
            logger.error(f"Error registering market assertion for {symbol}: {e}")
    
    def register_batch_market_data(self, market_data_list: List[Dict]):
        """Register multiple market data assertions at once."""
        for market_data in market_data_list:
            symbol = market_data.get("symbol")
            price = market_data.get("price")
            volume = market_data.get("volume")
            source = market_data.get("source", "batch")
            
            if symbol and price is not None and volume is not None:
                # Cache the market data
                current_time = time.time()
                self.market_data_cache[symbol] = MarketAssertion(
                    symbol=symbol,
                    price=price,
                    volume=volume,
                    timestamp=current_time,
                    source=source,
                    confidence=0.8
                )
                
                # Register assertion immediately for demo data (bypass interval check)
                if source == "demo":
                    self._register_market_assertion(symbol)
                else:
                    self.update_market_data(symbol, price, volume, source)
    
    def get_market_assertions(self) -> List[Dict]:
        """Get all market assertions from the registry."""
        try:
            assertions = self.registry.get_assertions_by_domain(AssertionDomain.MARKET)
            
            # Get auditor for regime_entropy
            from core.reality_auditor import get_reality_auditor
            auditor = get_reality_auditor()
            current_time = time.time()
            
            return [
                {
                    "assertion_id": a.assertion_id,
                    "symbol": a.description.split(":")[0].strip(),
                    "description": a.description,
                    "confidence_score": a.confidence_score,
                    "provenance_score": a.provenance_score,
                    "status": a.status.value,
                    "created_at": a.created_at,
                    "effective_confidence": a.effective_confidence(current_time, auditor.regime_entropy),
                    "is_usable": a.is_usable(current_time, auditor.regime_entropy)
                }
                for a in assertions
            ]
        except Exception as e:
            logger.error(f"Error getting market assertions: {e}")
            return []


# Singleton instance
_market_source: Optional[MarketAssertionSource] = None


def get_market_assertion_source() -> MarketAssertionSource:
    """Get the global market assertion source."""
    global _market_source
    if _market_source is None:
        _market_source = MarketAssertionSource()
    return _market_source


# Example usage
if __name__ == "__main__":
    # Create market assertion source
    source = get_market_assertion_source()
    
    # Update some market data
    source.update_market_data("BTC", 45000.0, 1234567.89, "coinbase")
    source.update_market_data("ETH", 3200.0, 987654.32, "kraken")
    source.update_market_data("SOL", 150.0, 234567.89, "bootstrap")
    
    # Get market assertions
    assertions = source.get_market_assertions()
    print(f"Market assertions: {len(assertions)}")
    for assertion in assertions:
        print(f"  - {assertion['symbol']}: {assertion['status']}")
    
    print("Market assertion source is ready!")
