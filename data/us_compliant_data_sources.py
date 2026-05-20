"""
US-Compliant Data Sources for MERID

Free, unrestricted APIs and data sources that work in the United States.
No API keys required, no restrictions, no US limitations.
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import json
import aiohttp
import requests

from utils.logger import get_logger

logger = get_logger("data.us_compliant_sources")


@dataclass
class MarketData:
    """Standardized market data structure."""
    symbol: str
    price: float
    volume_24h: float
    change_24h_pct: float
    timestamp: datetime
    source: str
    market_cap: Optional[float] = None
    circulating_supply: Optional[float] = None


class USCompliantDataAggregator:
    """
    Aggregates free, unrestricted data sources that work in the US.
    
    Sources included:
    1. BinanceUS (public API, no API key required)
    2. CoinMarketCap (free tier, limited but functional)
    3. CryptoCompare (free tier, no API key required)
    4. Kraken (public API, no restrictions)
    5. Poloniex (public API, no restrictions)
    6. CoinBase (public API, limited endpoints)
    7. Gemini (public API, limited endpoints)
    8. Blockchain.info (public API, Bitcoin data)
    """
    
    def __init__(self):
        self.session = None
        self.data_cache: Dict[str, MarketData] = {}
        self.cache_ttl = 60  # 60 seconds cache
        self.last_update: Dict[str, float] = {}
        
        # Symbol mappings for different APIs
        # Keys are our internal USD format (BTC/USD, ETH/USD, etc.)
        # Values are API-specific symbols
        self.symbol_mappings = {
            'binanceus': {
                'BTC/USD': 'BTCUSDT',  # BinanceUS uses USDT pairs internally
                'ETH/USD': 'ETHUSDT',
                'SOL/USD': 'SOLUSDT',
                'XRP/USD': 'XRPUSDT',
                'DOGE/USD': 'DOGEUSDT',
            },
            'coinmarketcap': {
                'BTC': '1',
                'ETH': '1027',
                'SOL': '5426',
                'AVAX': '5805',
                'MATIC': '3890',
                'DOT': '6636',
                'LINK': '1976',
                'UNI': '7083',
                'AAVE': '7278',
                'COMP': '6785'
            }
        }
        
        # Base URLs for APIs
        self.api_endpoints = {
            'binanceus': 'https://api.binance.us/api/v3',
            'coinmarketcap': 'https://pro-api.coinmarketcap.com/v1',
            'cryptocompare': 'https://min-api.cryptocompare.com/data/v2',
            'kraken': 'https://api.kraken.com/0/public',
            'poloniex': 'https://api.poloniex.com/public',
            'coinbase': 'https://api.coinbase.com/v2',
            'gemini': 'https://api.gemini.com/v1',
            'blockchain': 'https://blockchain.info'
        }
        
        logger.info("US-Compliant Data Aggregator initialized")
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'MERID-Data-Aggregator/1.0'}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def fetch_binanceus_data(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Fetch data from BinanceUS (public API, no API key required).
        
        Args:
            symbols: List of symbols in USD format (e.g., BTC/USD, ETH/USD)
        """
        results = {}
        try:
            # Fetch all 24h ticker data from BinanceUS
            url = f"{self.api_endpoints['binanceus']}/ticker/24hr"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Build reverse mapping from BinanceUS symbol to our USD symbol
                    binanceus_to_symbol = {v: k for k, v in self.symbol_mappings['binanceus'].items()}
                    
                    for ticker in data:
                        binanceus_symbol = ticker.get('symbol')
                        if binanceus_symbol in binanceus_to_symbol:
                            usd_symbol = binanceus_to_symbol[binanceus_symbol]
                            if usd_symbol in symbols:
                                price = float(ticker.get('lastPrice', 0))
                                if price > 0:
                                    results[usd_symbol] = MarketData(
                                        symbol=usd_symbol,
                                        price=price,
                                        volume_24h=float(ticker.get('quoteVolume', 0)),
                                        change_24h_pct=float(ticker.get('priceChangePercent', 0)),
                                        timestamp=datetime.now(),
                                        source='binanceus'
                                    )
                    
                    logger.info(f"BinanceUS: fetched {len(results)} symbols")
                    return results
                else:
                    logger.warning(f"BinanceUS API error: {response.status}")
                    return {}
                    
        except Exception as e:
            logger.error(f"BinanceUS fetch error: {e}")
            return {}
    
    async def fetch_cryptocompare_data(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Fetch data from CryptoCompare (free tier, no API key required)."""
        try:
            results = {}
            
            for symbol in symbols:
                # CryptoCompare uses different symbol format
                fsym = symbol.replace('/', '')
                tsym = 'USD'
                
                url = f"{self.api_endpoints['cryptocompare']}/histohour"
                params = {
                    'fsym': fsym,
                    'tsym': tsym,
                    'limit': 1  # Get latest data
                }
                
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('Response') == 'Success':
                            # Get latest price
                            price_url = f"{self.api_endpoints['cryptocompare']}/price"
                            price_params = {'fsym': fsym, 'tsyms': tsym}
                            
                            async with self.session.get(price_url, params=price_params) as price_response:
                                if price_response.status == 200:
                                    price_data = await price_response.json()
                                    if tsym in price_data:
                                        results[symbol] = MarketData(
                                            symbol=symbol,
                                            price=price_data[tsym],
                                            volume_24h=0,  # Not available in this endpoint
                                            change_24h_pct=0,  # Not available in this endpoint
                                            timestamp=datetime.now(),
                                            source='cryptocompare'
                                        )
                    else:
                        logger.warning(f"CryptoCompare API error for {symbol}: {data.get('Message', 'Unknown')}")
            
            logger.info(f"CryptoCompare: fetched {len(results)} symbols")
            return results
            
        except Exception as e:
            logger.error(f"CryptoCompare fetch error: {e}")
            return {}
    
    async def fetch_kraken_data(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Fetch data from Kraken (public API, no restrictions)."""
        try:
            # Kraken uses different symbol format
            kraken_symbols = []
            for symbol in symbols:
                if symbol == 'BTC/USD':
                    kraken_symbols.append('XBTUSD')
                elif symbol == 'ETH/USD':
                    kraken_symbols.append('ETHUSD')
                else:
                    kraken_symbols.append(symbol.replace('/', ''))
            
            if not kraken_symbols:
                return {}
            
            url = f"{self.api_endpoints['kraken']}/Ticker"
            params = {'pair': ','.join(kraken_symbols)}
            
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = {}
                    
                    if 'result' in data:
                        for kraken_symbol, ticker_data in data['result'].items():
                            # Map back to original symbol
                            original_symbol = None
                            for symbol in symbols:
                                if symbol == 'BTC/USD' and kraken_symbol == 'XBTUSD':
                                    original_symbol = symbol
                                    break
                                elif symbol.replace('/', '') == kraken_symbol:
                                    original_symbol = symbol
                                    break
                            
                            if original_symbol:
                                price = float(ticker_data['c'][0])  # Last trade price
                                volume = float(ticker_data['v'][1])  # 24h volume
                                change_pct = float(ticker_data['p']) / price * 100 if price > 0 else 0
                                
                                results[original_symbol] = MarketData(
                                    symbol=original_symbol,
                                    price=price,
                                    volume_24h=volume,
                                    change_24h_pct=change_pct,
                                    timestamp=datetime.now(),
                                    source='kraken'
                                )
                    
                    logger.info(f"Kraken: fetched {len(results)} symbols")
                    return results
                else:
                    logger.warning(f"Kraken API error: {response.status}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Kraken fetch error: {e}")
            return {}
    
    async def fetch_poloniex_data(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Fetch data from Poloniex (public API, no restrictions)."""
        try:
            results = {}
            
            for symbol in symbols:
                url = f"{self.api_endpoints['poloniex']}/ticker"
                params = {'currencyPair': symbol}
                
                async with self.session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and isinstance(data, dict):
                            results[symbol] = MarketData(
                                symbol=symbol,
                                price=float(data.get('last', 0)),
                                volume_24h=float(data.get('baseVolume', 0)),
                                change_24h_pct=float(data.get('percentChange', 0)) * 100,
                                timestamp=datetime.now(),
                                source='poloniex'
                            )
            
            logger.info(f"Poloniex: fetched {len(results)} symbols")
            return results
            
        except Exception as e:
            logger.error(f"Poloniex fetch error: {e}")
            return {}
    
    async def fetch_coinbase_data(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Fetch data from Coinbase (public API, limited endpoints)."""
        try:
            results = {}
            
            for symbol in symbols:
                # Coinbase uses different symbol format
                base, quote = symbol.split('/')
                coinbase_symbol = f"{base.upper()}-{quote.upper()}"
                
                url = f"{self.api_endpoints['coinbase']}/prices/{coinbase_symbol}/spot"
                
                async with self.session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'data' in data:
                            price_data = data['data']
                            results[symbol] = MarketData(
                                symbol=symbol,
                                price=float(price_data.get('amount', 0)),
                                volume_24h=0,  # Not available in this endpoint
                                change_24h_pct=0,  # Not available in this endpoint
                                timestamp=datetime.now(),
                                source='coinbase'
                            )
            
            logger.info(f"Coinbase: fetched {len(results)} symbols")
            return results
            
        except Exception as e:
            logger.error(f"Coinbase fetch error: {e}")
            return {}
    
    async def fetch_blockchain_data(self) -> Dict[str, MarketData]:
        """Fetch Bitcoin data from Blockchain.info (public API)."""
        try:
            url = f"{self.api_endpoints['blockchain']}/stats"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    return {
                        'BTC/USD': MarketData(
                            symbol='BTC/USD',
                            price=float(data.get('market_price_usd', 0)),
                            volume_24h=float(data.get('trade_volume_24h', 0)),
                            change_24h_pct=float(data.get('market_price_usd_change', 0)),
                            timestamp=datetime.now(),
                            source='blockchain'
                        )
                    }
                else:
                    logger.warning(f"Blockchain.info API error: {response.status}")
                    return {}
                    
        except Exception as e:
            logger.error(f"Blockchain.info fetch error: {e}")
            return {}
    
    async def aggregate_all_sources(self, symbols: List[str]) -> Dict[str, MarketData]:
        """
        Aggregate data from all available sources.
        
        Returns the most recent data for each symbol, prioritized by source reliability.
        """
        all_data = {}
        
        # Fetch from all sources concurrently
        tasks = [
            self.fetch_binanceus_data(symbols),
            self.fetch_cryptocompare_data(symbols),
            self.fetch_kraken_data(symbols),
            self.fetch_poloniex_data(symbols),
            self.fetch_coinbase_data(symbols)
        ]
        
        # Add Bitcoin-specific source
        if 'BTC/USD' in symbols:
            tasks.append(self.fetch_blockchain_data())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results with source priority
        source_priority = ['binanceus', 'kraken', 'cryptocompare', 'poloniex', 'coinbase', 'blockchain']
        
        for result in results:
            if isinstance(result, dict):
                for symbol, data in result.items():
                    if symbol not in all_data:
                        all_data[symbol] = data
                    else:
                        # Use data from higher priority source
                        current_priority = source_priority.index(all_data[symbol].source)
                        new_priority = source_priority.index(data.source)
                        if new_priority < current_priority:
                            all_data[symbol] = data
        
        # Update cache
        for symbol, data in all_data.items():
            self.data_cache[symbol] = data
            self.last_update[symbol] = time.time()
        
        logger.info(f"Aggregated {len(all_data)} symbols from {len([r for r in results if isinstance(r, dict)])} sources")
        return all_data
    
    async def get_cached_data(self, symbols: List[str]) -> Dict[str, MarketData]:
        """Get data from cache if fresh, otherwise fetch new data."""
        current_time = time.time()
        cached_data = {}
        
        for symbol in symbols:
            if symbol in self.data_cache and symbol in self.last_update:
                if current_time - self.last_update[symbol] < self.cache_ttl:
                    cached_data[symbol] = self.data_cache[symbol]
        
        # If we have fresh cached data for all requested symbols, return it
        if len(cached_data) == len(symbols):
            return cached_data
        
        # Otherwise fetch fresh data
        return await self.aggregate_all_sources(symbols)
    
    async def start_real_time_feed(self, symbols: List[str], callback):
        """
        Start real-time data feed for given symbols.
        
        Args:
            symbols: List of symbols to track
            callback: Callback function to receive data updates
        """
        logger.info(f"Starting real-time feed for {len(symbols)} symbols")
        
        while True:
            try:
                data = await self.get_cached_data(symbols)
                if data:
                    await callback(data)
                
                await asyncio.sleep(self.cache_ttl)
                
            except Exception as e:
                logger.error(f"Real-time feed error: {e}")
                await asyncio.sleep(10)  # Wait before retrying


# Prediction Markets Data Sources
class PredictionMarketsAggregator:
    """
    Aggregates free prediction markets data sources.
    
    Sources included:
    1. Polymarket (public API, limited data)
    2. Augur (public API, limited data)
    3. Manifold (public API, limited data)
    """
    
    def __init__(self):
        self.session = None
        self.data_cache: Dict[str, Any] = {}
        self.cache_ttl = 120  # 2 minutes cache for prediction markets
        
        # API endpoints
        self.api_endpoints = {
            'polymarket': 'https://api.polymarket.com',
            'augur': 'https://api.augur.net',
            'manifold': 'https://api.manifold.markets'
        }
        
        logger.info("Prediction Markets Aggregator initialized")
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'MERID-Prediction-Aggregator/1.0'}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def fetch_polymarket_data(self) -> List[Dict[str, Any]]:
        """Fetch prediction markets data from Polymarket."""
        try:
            # Polymarket has limited public API access
            # This is a simplified implementation
            url = f"{self.api_endpoints['polymarket']}/markets"
            
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    markets = []
                    
                    for market in data.get('data', []):
                        markets.append({
                            'id': market.get('id'),
                            'question': market.get('question'),
                            'yes_price': market.get('yesPrice', 0),
                            'no_price': market.get('noPrice', 0),
                            'volume': market.get('volume24h', 0),
                            'category': market.get('category', 'unknown'),
                            'source': 'polymarket'
                        })
                    
                    logger.info(f"Polymarket: fetched {len(markets)} markets")
                    return markets
                else:
                    logger.warning(f"Polymarket API error: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Polymarket fetch error: {e}")
            return []
    
    async def aggregate_prediction_data(self) -> List[Dict[str, Any]]:
        """Aggregate data from all prediction market sources."""
        all_markets = []
        
        # Fetch from all sources
        tasks = [
            self.fetch_polymarket_data()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_markets.extend(result)
        
        logger.info(f"Aggregated {len(all_markets)} prediction markets")
        return all_markets
    
    async def start_prediction_feed(self, callback):
        """
        Start real-time prediction markets data feed.
        
        Args:
            callback: Callback function to receive data updates
        """
        logger.info("Starting prediction markets feed")
        
        while True:
            try:
                data = await self.aggregate_prediction_data()
                if data:
                    await callback(data)
                
                await asyncio.sleep(self.cache_ttl)
                
            except Exception as e:
                logger.error(f"Prediction feed error: {e}")
                await asyncio.sleep(30)  # Wait before retrying


# Usage example and testing
async def test_data_sources():
    """Test the US-compliant data sources."""
    symbols = ['BTC/USD', 'ETH/USD', 'SOL/USD']
    
    async with USCompliantDataAggregator() as aggregator:
        # Test single fetch
        data = await aggregator.aggregate_all_sources(symbols)
        print("Market Data:")
        for symbol, market_data in data.items():
            print(f"{symbol}: ${market_data.price:.2f} ({market_data.source})")
        
        # Test real-time feed
        async def data_callback(data):
            print(f"Real-time update: {len(data)} symbols")
        
        await aggregator.start_real_time_feed(symbols, data_callback)


if __name__ == "__main__":
    asyncio.run(test_data_sources())
