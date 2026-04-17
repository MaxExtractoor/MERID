"""
Stocks & Equities Data Feed for MERID.

Real-time stock market data using multiple providers:
- Alpha Vantage (US stocks, indices)
- Polygon.io (stocks, options, forex)
- Finnhub (stocks, forex, crypto)
"""

from __future__ import annotations

import asyncio
import threading
import os
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from utils.logger import get_logger

logger = get_logger("data.stocks_feed")


@dataclass
class StockPrice:
    """Stock price data structure."""
    symbol: str
    price: float
    bid: float
    ask: float
    volume: float
    change_pct: float
    timestamp: datetime
    source: str
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None


class StocksFeed:
    """
    Live stocks and equities data feed.
    
    Aggregates from multiple providers for redundancy.
    """
    
    def __init__(self, symbols: List[str] = None):
        """
        Initialize stocks feed.
        
        Args:
            symbols: List of stock symbols (e.g., ['AAPL', 'TSLA', 'NVDA'])
        """
        # Major tech, finance, and market movers
        self.symbols = symbols or [
            # FAANG + Microsoft
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA',
            # Crypto-related stocks
            'COIN', 'MSTR', 'MARA', 'RIOT', 'CLSK', 'HUT',
            # Major indices (as individual stocks for simplicity)
            'SPY', 'QQQ', 'DIA', 'IWM',  # S&P 500, Nasdaq, Dow, Russell 2000
            # Banking & Finance
            'JPM', 'BAC', 'GS', 'MS', 'C', 'WFC',
            # AI/Tech
            'AMD', 'INTC', 'ARM', 'PLTR', 'SNOW', 'NET',
            # Payment processors
            'V', 'MA', 'PYPL', 'SQ',
            # Energy
            'XOM', 'CVX',
            # Meme stocks
            'GME', 'AMC', 'BBBY'
        ]
        
        self.alpha_vantage_key = os.getenv('ALPHA_VANTAGE_API_KEY')
        self.polygon_key = os.getenv('POLYGON_API_KEY')
        self.finnhub_key = os.getenv('FINNHUB_API_KEY')
        
        self.price_cache: Dict[str, StockPrice] = {}
        self.subscribers: List[Callable] = []
        self.running = False
        self.update_interval = 5.0  # 5 seconds for stocks
        
        self.client = httpx.AsyncClient(timeout=30.0)
        
        logger.info(f"Stocks feed initialized for {len(self.symbols)} symbols")
    
    async def start_streaming(self):
        """Start streaming stock price updates."""
        self.running = True
        logger.info("Stock price streaming started")
        
        while self.running:
            try:
                await self.fetch_and_broadcast_prices()
                await asyncio.sleep(self.update_interval)
            except Exception as exc:
                logger.error(f"Error in stock streaming loop: {exc}")
                await asyncio.sleep(self.update_interval)
    
    def stop_streaming(self):
        """Stop stock price streaming."""
        self.running = False
        logger.info("Stock price streaming stopped")
    
    async def fetch_and_broadcast_prices(self):
        """Fetch latest stock prices from all providers."""
        # Try Polygon first (best real-time data)
        if self.polygon_key and self.polygon_key != 'change_me':
            await self._fetch_from_polygon()
        
        # Fallback to Finnhub
        elif self.finnhub_key and self.finnhub_key != 'change_me':
            await self._fetch_from_finnhub()
        
        # Final fallback to Alpha Vantage
        elif self.alpha_vantage_key and self.alpha_vantage_key != 'change_me':
            await self._fetch_from_alphavantage()
        
        # Broadcast to subscribers
        for subscriber in self.subscribers:
            try:
                await subscriber(self.price_cache)
            except Exception as exc:
                logger.error(f"Error notifying subscriber: {exc}")
    
    async def _fetch_from_polygon(self):
        """Fetch from Polygon.io - Best real-time data."""
        try:
            for symbol in self.symbols:
                try:
                    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev"
                    params = {"apiKey": self.polygon_key}
                    
                    response = await self.client.get(url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('results'):
                            result = data['results'][0]
                            
                            self.price_cache[symbol] = StockPrice(
                                symbol=symbol,
                                price=result['c'],  # close
                                bid=result['l'],    # low as bid approximation
                                ask=result['h'],    # high as ask approximation
                                volume=result['v'],
                                change_pct=((result['c'] - result['o']) / result['o']) * 100,
                                timestamp=datetime.now(),
                                source='polygon'
                            )
                    
                    await asyncio.sleep(0.1)  # Rate limiting
                    
                except Exception as exc:
                    logger.debug(f"Failed to fetch {symbol} from Polygon: {exc}")
                    
        except Exception as exc:
            logger.error(f"Polygon fetch error: {exc}")
    
    async def _fetch_from_finnhub(self):
        """Fetch from Finnhub."""
        try:
            for symbol in self.symbols:
                try:
                    url = f"https://finnhub.io/api/v1/quote"
                    params = {"symbol": symbol, "token": self.finnhub_key}
                    
                    response = await self.client.get(url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if data.get('c'):  # current price
                            self.price_cache[symbol] = StockPrice(
                                symbol=symbol,
                                price=data['c'],
                                bid=data.get('l', data['c']),  # low
                                ask=data.get('h', data['c']),  # high
                                volume=0,  # Finnhub doesn't provide volume in quote
                                change_pct=data.get('dp', 0),  # percent change
                                timestamp=datetime.now(),
                                source='finnhub'
                            )
                    
                    await asyncio.sleep(0.1)
                    
                except Exception as exc:
                    logger.debug(f"Failed to fetch {symbol} from Finnhub: {exc}")
                    
        except Exception as exc:
            logger.error(f"Finnhub fetch error: {exc}")
    
    async def _fetch_from_alphavantage(self):
        """Fetch from Alpha Vantage - slowest but most reliable."""
        try:
            for symbol in self.symbols[:5]:  # Alpha Vantage has strict rate limits
                try:
                    url = f"https://www.alphavantage.co/query"
                    params = {
                        "function": "GLOBAL_QUOTE",
                        "symbol": symbol,
                        "apikey": self.alpha_vantage_key
                    }
                    
                    response = await self.client.get(url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        quote = data.get('Global Quote', {})
                        
                        if quote:
                            self.price_cache[symbol] = StockPrice(
                                symbol=symbol,
                                price=float(quote.get('05. price', 0)),
                                bid=float(quote.get('04. low', 0)),
                                ask=float(quote.get('03. high', 0)),
                                volume=float(quote.get('06. volume', 0)),
                                change_pct=float(quote.get('10. change percent', '0%').rstrip('%')),
                                timestamp=datetime.now(),
                                source='alphavantage'
                            )
                    
                    await asyncio.sleep(12)  # Alpha Vantage: 5 calls/min limit
                    
                except Exception as exc:
                    logger.debug(f"Failed to fetch {symbol} from Alpha Vantage: {exc}")
                    
        except Exception as exc:
            logger.error(f"Alpha Vantage fetch error: {exc}")
    
    def subscribe(self, callback: Callable):
        """Subscribe to stock price updates."""
        self.subscribers.append(callback)
        logger.info(f"New subscriber added (total: {len(self.subscribers)})")
    
    def get_latest_prices(self) -> Dict[str, StockPrice]:
        """Get latest cached prices."""
        return self.price_cache.copy()


# Global singleton
_stocks_feed: Optional[StocksFeed] = None
_stocks_feed_lock = threading.Lock()


def get_stocks_feed() -> StocksFeed:
    """Get or create stocks feed singleton."""
    global _stocks_feed
    if _stocks_feed is None:
        with _stocks_feed_lock:
            if _stocks_feed is None:
                _stocks_feed = StocksFeed()
    return _stocks_feed
