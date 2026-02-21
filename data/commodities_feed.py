"""
Commodities & Metals Data Feed for MERID.

Real-time precious metals and commodity prices:
- Gold, Silver, Platinum, Palladium
- Oil (WTI, Brent)
- Natural Gas
- Agricultural commodities
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

logger = get_logger("data.commodities_feed")


@dataclass
class CommodityPrice:
    """Commodity price data structure."""
    symbol: str
    name: str
    price: float
    unit: str  # e.g., 'USD/oz', 'USD/bbl'
    change_pct: float
    timestamp: datetime
    source: str


class CommoditiesFeed:
    """
    Live commodities and precious metals data feed.
    
    Tracks gold, silver, oil, and other commodities.
    """
    
    def __init__(self):
        """Initialize commodities feed."""
        # Commodities mapping: symbol -> (name, unit)
        self.commodities = {
            'XAU/USD': ('Gold', 'USD/oz'),
            'XAG/USD': ('Silver', 'USD/oz'),
            'XPT/USD': ('Platinum', 'USD/oz'),
            'XPD/USD': ('Palladium', 'USD/oz'),
            'WTI': ('Crude Oil WTI', 'USD/bbl'),
            'BRENT': ('Crude Oil Brent', 'USD/bbl'),
            'NG': ('Natural Gas', 'USD/MMBtu'),
            'COPPER': ('Copper', 'USD/lb'),
            'CORN': ('Corn', 'USD/bu'),
            'WHEAT': ('Wheat', 'USD/bu'),
            'SOYBEAN': ('Soybeans', 'USD/bu'),
        }
        
        self.alpha_vantage_key = os.getenv('ALPHA_VANTAGE_API_KEY')
        self.polygon_key = os.getenv('POLYGON_API_KEY')
        self.finnhub_key = os.getenv('FINNHUB_API_KEY')
        
        self.price_cache: Dict[str, CommodityPrice] = {}
        self.subscribers: List[Callable] = []
        self.running = False
        self.update_interval = 30.0  # 30 seconds for commodities
        
        self.client = httpx.AsyncClient(timeout=30.0)
        
        logger.info(f"Commodities feed initialized for {len(self.commodities)} commodities")
    
    async def start_streaming(self):
        """Start streaming commodity price updates."""
        self.running = True
        logger.info("Commodity price streaming started")
        
        while self.running:
            try:
                await self.fetch_and_broadcast_prices()
                await asyncio.sleep(self.update_interval)
            except Exception as exc:
                logger.error(f"Error in commodity streaming loop: {exc}")
                await asyncio.sleep(self.update_interval)
    
    def stop_streaming(self):
        """Stop commodity price streaming."""
        self.running = False
        logger.info("Commodity price streaming stopped")
    
    async def fetch_and_broadcast_prices(self):
        """Fetch latest commodity prices."""
        # Fetch metals from Alpha Vantage (best for commodities)
        if self.alpha_vantage_key and self.alpha_vantage_key != 'change_me':
            await self._fetch_metals_alphavantage()
        
        # Fetch from Polygon for oil/gas
        if self.polygon_key and self.polygon_key != 'change_me':
            await self._fetch_energy_polygon()
        
        # Broadcast to subscribers
        for subscriber in self.subscribers:
            try:
                await subscriber(self.price_cache)
            except Exception as exc:
                logger.error(f"Error notifying subscriber: {exc}")
    
    async def _fetch_metals_alphavantage(self):
        """Fetch precious metals from Alpha Vantage."""
        metal_functions = {
            'XAU/USD': 'XAU',
            'XAG/USD': 'XAG',
            'XPT/USD': 'XPT',
            'XPD/USD': 'XPD',
        }
        
        for symbol, function_code in metal_functions.items():
            try:
                url = "https://www.alphavantage.co/query"
                params = {
                    "function": function_code,
                    "market": "USD",
                    "apikey": self.alpha_vantage_key
                }
                
                response = await self.client.get(url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Alpha Vantage returns data in different formats
                    if 'Realtime Currency Exchange Rate' in data:
                        rate_data = data['Realtime Currency Exchange Rate']
                        price = float(rate_data.get('5. Exchange Rate', 0))
                        
                        name, unit = self.commodities[symbol]
                        self.price_cache[symbol] = CommodityPrice(
                            symbol=symbol,
                            name=name,
                            price=price,
                            unit=unit,
                            change_pct=0.0,  # Would need historical data
                            timestamp=datetime.now(),
                            source='alphavantage'
                        )
                        
                        logger.debug(f"Fetched {name}: ${price:.2f}/{unit.split('/')[1]}")
                
                await asyncio.sleep(12)  # Rate limit
                
            except Exception as exc:
                logger.debug(f"Failed to fetch {symbol}: {exc}")
    
    async def _fetch_energy_polygon(self):
        """Fetch energy commodities from Polygon."""
        # Polygon uses specific ticker formats for commodities
        energy_tickers = {
            'WTI': 'C:CL',      # Crude Oil WTI futures
            'BRENT': 'C:BZ',    # Brent Crude futures
            'NG': 'C:NG',       # Natural Gas futures
        }
        
        for symbol, ticker in energy_tickers.items():
            try:
                url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev"
                params = {"apiKey": self.polygon_key}
                
                response = await self.client.get(url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('results'):
                        result = data['results'][0]
                        
                        name, unit = self.commodities[symbol]
                        price = result['c']
                        open_price = result['o']
                        change_pct = ((price - open_price) / open_price) * 100 if open_price else 0
                        
                        self.price_cache[symbol] = CommodityPrice(
                            symbol=symbol,
                            name=name,
                            price=price,
                            unit=unit,
                            change_pct=change_pct,
                            timestamp=datetime.now(),
                            source='polygon'
                        )
                        
                        logger.debug(f"Fetched {name}: ${price:.2f}/{unit.split('/')[1]}")
                
                await asyncio.sleep(0.2)
                
            except Exception as exc:
                logger.debug(f"Failed to fetch {symbol}: {exc}")
    
    def subscribe(self, callback: Callable):
        """Subscribe to commodity price updates."""
        self.subscribers.append(callback)
        logger.info(f"New commodity subscriber added (total: {len(self.subscribers)})")
    
    def get_latest_prices(self) -> Dict[str, CommodityPrice]:
        """Get latest cached prices."""
        return self.price_cache.copy()


# Global singleton
_commodities_feed: Optional[CommoditiesFeed] = None


def get_commodities_feed() -> CommoditiesFeed:
    """Get or create commodities feed singleton."""
    global _commodities_feed
    if _commodities_feed is None:
        _commodities_feed = CommoditiesFeed()
    return _commodities_feed
