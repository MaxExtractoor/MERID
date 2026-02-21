"""
Forex & Fiat Currency Data Feed for MERID.

Real-time foreign exchange rates using multiple providers:
- Alpha Vantage (forex)
- Polygon.io (forex)
- Finnhub (forex)
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from utils.logger import get_logger

logger = get_logger("data.forex_feed")


@dataclass
class ForexRate:
    """Forex rate data structure."""
    pair: str
    rate: float
    bid: float
    ask: float
    timestamp: datetime
    source: str


class ForexFeed:
    """
    Live forex and fiat currency data feed.
    
    Tracks major currency pairs and USD conversions.
    """
    
    def __init__(self, pairs: List[str] = None):
        """
        Initialize forex feed.
        
        Args:
            pairs: List of currency pairs (e.g., ['EUR/USD', 'GBP/USD'])
        """
        # Major currency pairs
        self.pairs = pairs or [
            # Majors against USD
            'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF', 'AUD/USD', 'NZD/USD', 'USD/CAD',
            # Crosses
            'EUR/GBP', 'EUR/JPY', 'GBP/JPY', 'EUR/CHF', 'AUD/JPY', 'NZD/JPY',
            # Emerging markets
            'USD/CNY', 'USD/INR', 'USD/BRL', 'USD/MXN', 'USD/ZAR', 'USD/TRY',
            # Crypto-related fiat
            'USD/KRW', 'USD/SGD', 'USD/HKD',
        ]
        
        self.alpha_vantage_key = os.getenv('ALPHA_VANTAGE_API_KEY')
        self.polygon_key = os.getenv('POLYGON_API_KEY')
        self.finnhub_key = os.getenv('FINNHUB_API_KEY')
        
        self.rate_cache: Dict[str, ForexRate] = {}
        self.subscribers: List[Callable] = []
        self.running = False
        self.update_interval = 10.0  # 10 seconds for forex
        
        self.client = httpx.AsyncClient(timeout=30.0)
        
        logger.info(f"Forex feed initialized for {len(self.pairs)} pairs")
    
    async def start_streaming(self):
        """Start streaming forex rate updates."""
        self.running = True
        logger.info("Forex rate streaming started")
        
        while self.running:
            try:
                await self.fetch_and_broadcast_rates()
                await asyncio.sleep(self.update_interval)
            except Exception as exc:
                logger.error(f"Error in forex streaming loop: {exc}")
                await asyncio.sleep(self.update_interval)
    
    def stop_streaming(self):
        """Stop forex rate streaming."""
        self.running = False
        logger.info("Forex rate streaming stopped")
    
    async def fetch_and_broadcast_rates(self):
        """Fetch latest forex rates from all providers."""
        # Try Polygon first
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
                await subscriber(self.rate_cache)
            except Exception as exc:
                logger.error(f"Error notifying subscriber: {exc}")
    
    async def _fetch_from_polygon(self):
        """Fetch from Polygon.io."""
        try:
            for pair in self.pairs:
                try:
                    # Convert EUR/USD to C:EURUSD format
                    symbol = f"C:{pair.replace('/', '')}"
                    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev"
                    params = {"apiKey": self.polygon_key}
                    
                    response = await self.client.get(url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('results'):
                            result = data['results'][0]
                            
                            self.rate_cache[pair] = ForexRate(
                                pair=pair,
                                rate=result['c'],
                                bid=result['l'],
                                ask=result['h'],
                                timestamp=datetime.now(),
                                source='polygon'
                            )
                    
                    await asyncio.sleep(0.2)
                    
                except Exception as exc:
                    logger.debug(f"Failed to fetch {pair} from Polygon: {exc}")
                    
        except Exception as exc:
            logger.error(f"Polygon forex fetch error: {exc}")
    
    async def _fetch_from_finnhub(self):
        """Fetch from Finnhub."""
        try:
            for pair in self.pairs:
                try:
                    # Convert EUR/USD to OANDA:EUR_USD format
                    symbol = f"OANDA:{pair.replace('/', '_')}"
                    url = f"https://finnhub.io/api/v1/quote"
                    params = {"symbol": symbol, "token": self.finnhub_key}
                    
                    response = await self.client.get(url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if data.get('c'):
                            self.rate_cache[pair] = ForexRate(
                                pair=pair,
                                rate=data['c'],
                                bid=data.get('l', data['c']),
                                ask=data.get('h', data['c']),
                                timestamp=datetime.now(),
                                source='finnhub'
                            )
                    
                    await asyncio.sleep(0.2)
                    
                except Exception as exc:
                    logger.debug(f"Failed to fetch {pair} from Finnhub: {exc}")
                    
        except Exception as exc:
            logger.error(f"Finnhub forex fetch error: {exc}")
    
    async def _fetch_from_alphavantage(self):
        """Fetch from Alpha Vantage."""
        try:
            for pair in self.pairs[:3]:  # Rate limited
                try:
                    from_currency, to_currency = pair.split('/')
                    url = f"https://www.alphavantage.co/query"
                    params = {
                        "function": "CURRENCY_EXCHANGE_RATE",
                        "from_currency": from_currency,
                        "to_currency": to_currency,
                        "apikey": self.alpha_vantage_key
                    }
                    
                    response = await self.client.get(url, params=params)
                    
                    if response.status_code == 200:
                        data = response.json()
                        rate_data = data.get('Realtime Currency Exchange Rate', {})
                        
                        if rate_data:
                            rate = float(rate_data.get('5. Exchange Rate', 0))
                            self.rate_cache[pair] = ForexRate(
                                pair=pair,
                                rate=rate,
                                bid=rate * 0.9999,  # Approximate spread
                                ask=rate * 1.0001,
                                timestamp=datetime.now(),
                                source='alphavantage'
                            )
                    
                    await asyncio.sleep(12)  # Rate limit
                    
                except Exception as exc:
                    logger.debug(f"Failed to fetch {pair} from Alpha Vantage: {exc}")
                    
        except Exception as exc:
            logger.error(f"Alpha Vantage forex fetch error: {exc}")
    
    def subscribe(self, callback: Callable):
        """Subscribe to forex rate updates."""
        self.subscribers.append(callback)
        logger.info(f"New forex subscriber added (total: {len(self.subscribers)})")
    
    def get_latest_rates(self) -> Dict[str, ForexRate]:
        """Get latest cached rates."""
        return self.rate_cache.copy()


# Global singleton
_forex_feed: Optional[ForexFeed] = None


def get_forex_feed() -> ForexFeed:
    """Get or create forex feed singleton."""
    global _forex_feed
    if _forex_feed is None:
        _forex_feed = ForexFeed()
    return _forex_feed
