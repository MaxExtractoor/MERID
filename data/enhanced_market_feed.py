"""
Enhanced Market Feed with US-Compliant Sources

Replaces Binance/Hyperliquid with US-compliant free APIs.
Integrates with existing MERID architecture.
"""

import threading
import asyncio
import time
from typing import Dict, List, Optional, Callable, Any, Union
from dataclasses import dataclass
from datetime import datetime

from data.us_compliant_data_sources import USCompliantDataAggregator, PredictionMarketsAggregator, MarketData
from utils.logger import get_logger

logger = get_logger("data.enhanced_market_feed")


@dataclass
class EnhancedMarketData:
    """Enhanced market data with additional fields."""
    symbol: str
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume_24h: float = 0
    change_24h_pct: float = 0
    timestamp: datetime = None
    source: str = ""
    market_cap: Optional[float] = None
    circulating_supply: Optional[float] = None
    liquidity_score: float = 0  # 0-1 based on volume and market cap
    confidence_score: float = 0  # 0-1 based on source reliability


class EnhancedMarketFeed:
    """
    Enhanced market feed using US-compliant data sources.
    
    Replaces Binance/Hyperliquid with:
    - CoinGecko (primary)
    - Kraken (backup)
    - CryptoCompare (backup)
    - Poloniex (backup)
    - Coinbase (backup)
    - Blockchain.info (Bitcoin only)
    """
    
    def __init__(self, symbols: List[str] = None):
        """
        Initialize enhanced market feed.
        
        Args:
            symbols: List of symbols to track (e.g., ['BTC/USDT', 'ETH/USDT'])
        """
        self.symbols = symbols or ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT']
        self.aggregator = None
        self.prediction_aggregator = None
        self.market_data_cache: Dict[str, EnhancedMarketData] = {}
        self.prediction_data_cache: List[Dict[str, Any]] = []
        self.subscribers: List[Callable] = []
        
        self.running = False
        self.update_interval = 5.0  # Update every 5 seconds
        self.prediction_update_interval = 30.0  # Update predictions every 30 seconds
        
        # Source reliability scores
        self.source_reliability = {
            'coingecko': 1.0,
            'kraken': 0.9,
            'cryptocompare': 0.8,
            'poloniex': 0.7,
            'coinbase': 0.8,
            'blockchain': 0.9
        }
        
        logger.info(f"Enhanced market feed initialized for {len(self.symbols)} symbols")
    
    async def start(self):
        """Start the enhanced market feed."""
        self.aggregator = USCompliantDataAggregator()
        self.prediction_aggregator = PredictionMarketsAggregator()
        
        await self.aggregator.__aenter__()
        await self.prediction_aggregator.__aenter__()
        
        self.running = True
        
        # Start background tasks
        asyncio.create_task(self._market_data_loop())
        asyncio.create_task(self._prediction_data_loop())
        
        logger.info("Enhanced market feed started")
    
    async def stop(self):
        """Stop the enhanced market feed."""
        self.running = False
        
        if self.aggregator:
            await self.aggregator.__aexit__(None, None, None)
        
        if self.prediction_aggregator:
            await self.prediction_aggregator.__aexit__(None, None, None)
        
        logger.info("Enhanced market feed stopped")
    
    def _calculate_liquidity_score(self, market_data: MarketData) -> float:
        """Calculate liquidity score based on volume and market cap."""
        if market_data.volume_24h <= 0:
            return 0.0
        
        # Normalize volume (log scale for better distribution)
        volume_score = min(1.0, (market_data.volume_24h / 1000000) ** 0.5)
        
        # Add market cap bonus if available
        cap_bonus = 0.0
        if market_data.market_cap and market_data.market_cap > 0:
            cap_bonus = min(0.3, (market_data.market_cap / 1000000000) ** 0.3)
        
        return min(1.0, volume_score + cap_bonus)
    
    def _calculate_confidence_score(self, market_data: MarketData) -> float:
        """Calculate confidence score based on source reliability."""
        return self.source_reliability.get(market_data.source, 0.5)
    
    def _enhance_market_data(self, market_data: MarketData) -> EnhancedMarketData:
        """Convert basic market data to enhanced format."""
        return EnhancedMarketData(
            symbol=market_data.symbol,
            price=market_data.price,
            bid=None,  # Not available in free APIs
            ask=None,  # Not available in free APIs
            volume_24h=market_data.volume_24h,
            change_24h_pct=market_data.change_24h_pct,
            timestamp=market_data.timestamp,
            source=market_data.source,
            market_cap=market_data.market_cap,
            circulating_supply=market_data.circulating_supply,
            liquidity_score=self._calculate_liquidity_score(market_data),
            confidence_score=self._calculate_confidence_score(market_data)
        )
    
    async def _market_data_loop(self):
        """Background loop for market data updates."""
        while self.running:
            try:
                # Fetch fresh data
                raw_data = await self.aggregator.get_cached_data(self.symbols)
                
                # Enhance and cache data
                enhanced_data = {}
                for symbol, data in raw_data.items():
                    enhanced_data[symbol] = self._enhance_market_data(data)
                
                self.market_data_cache = enhanced_data
                
                # Notify subscribers
                for subscriber in self.subscribers:
                    try:
                        await subscriber(enhanced_data)
                    except Exception as e:
                        logger.error(f"Subscriber notification error: {e}")
                
                logger.debug(f"Updated {len(enhanced_data)} market data points")
                
            except Exception as e:
                logger.error(f"Market data loop error: {e}")
            
            await asyncio.sleep(self.update_interval)
    
    async def _prediction_data_loop(self):
        """Background loop for prediction markets data."""
        while self.running:
            try:
                # Fetch prediction markets data
                prediction_data = await self.prediction_aggregator.aggregate_prediction_data()
                self.prediction_data_cache = prediction_data
                
                logger.debug(f"Updated {len(prediction_data)} prediction markets")
                
            except Exception as e:
                logger.error(f"Prediction data loop error: {e}")
            
            await asyncio.sleep(self.prediction_update_interval)
    
    def subscribe(self, callback: Callable[[Dict[str, EnhancedMarketData]], None]):
        """Subscribe to market data updates."""
        self.subscribers.append(callback)
        logger.info(f"Added subscriber (total: {len(self.subscribers)})")
    
    def get_market_data(self, symbol: str = None) -> Union[EnhancedMarketData, Dict[str, EnhancedMarketData]]:
        """Get current market data."""
        if symbol:
            return self.market_data_cache.get(symbol)
        return self.market_data_cache.copy()
    
    def get_prediction_data(self) -> List[Dict[str, Any]]:
        """Get current prediction markets data."""
        return self.prediction_data_cache.copy()
    
    def get_top_liquid_symbols(self, count: int = 10) -> List[EnhancedMarketData]:
        """Get top symbols by liquidity score."""
        sorted_data = sorted(
            self.market_data_cache.values(),
            key=lambda x: x.liquidity_score,
            reverse=True
        )
        return sorted_data[:count]
    
    def get_high_confidence_data(self, min_confidence: float = 0.8) -> Dict[str, EnhancedMarketData]:
        """Get market data with high confidence scores."""
        return {
            symbol: data for symbol, data in self.market_data_cache.items()
            if data.confidence_score >= min_confidence
        }


# Integration with existing MERID architecture
class MarketFeedAdapter:
    """
    Adapter to integrate enhanced market feed with existing MERID components.
    
    Provides the same interface as the original market feed but uses US-compliant sources.
    """
    
    def __init__(self):
        self.enhanced_feed = EnhancedMarketFeed()
        self.running = False
    
    async def start(self):
        """Start the market feed adapter."""
        await self.enhanced_feed.start()
        self.running = True
        logger.info("Market feed adapter started")
    
    async def stop(self):
        """Stop the market feed adapter."""
        await self.enhanced_feed.stop()
        self.running = False
        logger.info("Market feed adapter stopped")
    
    def get_price_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get price data in legacy format."""
        market_data = self.enhanced_feed.get_market_data(symbol)
        if not market_data:
            return None
        
        return {
            'symbol': market_data.symbol,
            'price': market_data.price,
            'bid': market_data.bid,
            'ask': market_data.ask,
            'volume_24h': market_data.volume_24h,
            'change_24h_pct': market_data.change_24h_pct,
            'timestamp': market_data.timestamp.isoformat(),
            'source': market_data.source,
            'liquidity_score': market_data.liquidity_score,
            'confidence_score': market_data.confidence_score
        }
    
    def get_all_prices(self) -> Dict[str, Dict[str, Any]]:
        """Get all price data in legacy format."""
        market_data = self.enhanced_feed.get_market_data()
        return {
            symbol: self.get_price_data(symbol)
            for symbol in market_data
        }
    
    def get_prediction_markets(self) -> List[Dict[str, Any]]:
        """Get prediction markets data."""
        return self.enhanced_feed.get_prediction_data()


# Global instance for easy access
_market_feed_adapter = None
_market_feed_adapter_lock = threading.Lock()

async def get_market_feed() -> MarketFeedAdapter:
    """Get the global market feed adapter instance."""
    global _market_feed_adapter
    
    if _market_feed_adapter is None:
        with _market_feed_adapter_lock:
            if _market_feed_adapter is None:
                _market_feed_adapter = MarketFeedAdapter()
                await _market_feed_adapter.start()
    
    return _market_feed_adapter


# Testing and validation
async def test_enhanced_feed():
    """Test the enhanced market feed."""
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    
    adapter = MarketFeedAdapter()
    await adapter.start()
    
    try:
        # Test price data
        print("Testing price data:")
        for symbol in symbols:
            data = adapter.get_price_data(symbol)
            if data:
                print(f"{symbol}: ${data['price']:.2f} ({data['source']})")
        
        # Test prediction markets
        print("\nTesting prediction markets:")
        predictions = adapter.get_prediction_markets()
        print(f"Found {len(predictions)} prediction markets")
        
        # Wait for some updates
        await asyncio.sleep(10)
        
        # Test enhanced features
        print("\nTesting enhanced features:")
        top_liquid = adapter.enhanced_feed.get_top_liquid_symbols(3)
        for data in top_liquid:
            print(f"{data.symbol}: liquidity={data.liquidity_score:.2f}, confidence={data.confidence_score:.2f}")
        
    finally:
        await adapter.stop()


if __name__ == "__main__":
    asyncio.run(test_enhanced_feed())
