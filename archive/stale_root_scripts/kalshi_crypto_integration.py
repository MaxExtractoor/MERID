#!/usr/bin/env python3
"""
COMPLETE KALSHI CRYPTO MARKETS INTEGRATION

Following official Kalshi documentation to implement:
1. Proper API endpoints for crypto markets
2. Correct market classification
3. BTC trading scaffolding
4. UI integration
"""

import asyncio
import json
import os
import re
import base64
import time
import hashlib
import hmac
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

class KalshiOfficialAPI:
    """Official Kalshi API integration following docs.kalshi.com"""
    
    def __init__(self):
        self.api_key_id = os.getenv('KALSHI_API_KEY_ID')
        self.private_key_path = os.getenv('KALSHI_PRIVATE_KEY_PATH')
        self.use_demo = os.getenv('KALSHI_USE_DEMO', 'false').lower() == 'true'
        
        if not self.api_key_id:
            raise ValueError("KALSHI_API_KEY_ID not found in environment")
        if not self.private_key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not found in environment")
        
        # Use correct Kalshi API endpoints from documentation
        if self.use_demo:
            self.base_url = "https://demo-api.kalshi.co"
        else:
            self.base_url = "https://api.kalshi.co"  # Main Kalshi API for crypto markets
        
        print(f"🔧 Kalshi Official API initialized")
        print(f"  Environment: {'DEMO' if self.use_demo else 'PRODUCTION'}")
        print(f"  API Key ID: {self.api_key_id[:8]}...")
        print(f"  Base URL: {self.base_url}")
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Generate Kalshi API authentication headers"""
        try:
            with open(self.private_key_path, 'r') as f:
                private_key = f.read().strip()
        except Exception as e:
            raise ValueError(f"Failed to read private key: {e}")
        
        timestamp = str(int(time.time()))
        message = timestamp
        
        signature = hmac.new(
            private_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        signature_b64 = base64.b64encode(signature).decode('utf-8')
        
        return {
            "KALSHI-API-KEY-ID": self.api_key_id,
            "KALSHI-API-SIGNATURE": signature_b64,
            "KALSHI-API-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }
    
    async def fetch_all_markets(self) -> List[Dict[str, Any]]:
        """Fetch all markets with proper pagination"""
        print(f"\n📡 FETCHING ALL MARKETS FROM KALSHI API")
        print(f"  Endpoint: {self.base_url}/trade-api/v2/markets")
        
        try:
            import httpx
            
            all_markets = []
            cursor = None
            page_count = 0
            
            async with httpx.AsyncClient() as client:
                while True:
                    page_count += 1
                    params = {"limit": 1000}
                    if cursor:
                        params["cursor"] = cursor
                    
                    print(f"  📄 Fetching page {page_count}...")
                    
                    response = await client.get(
                        f"{self.base_url}/trade-api/v2/markets",
                        params=params,
                        headers=self._get_auth_headers(),
                        timeout=30.0
                    )
                    
                    if response.status_code == 401:
                        print(f"  ❌ Authentication failed - check credentials")
                        break
                    elif response.status_code == 403:
                        print(f"  ❌ Access forbidden - may need crypto market permissions")
                        break
                    elif response.status_code != 200:
                        print(f"  ❌ API Error: {response.status_code} - {response.text}")
                        break
                    
                    data = response.json()
                    markets = data.get("markets", [])
                    cursor = data.get("next_cursor")
                    
                    print(f"    ✅ Page {page_count}: {len(markets)} markets")
                    all_markets.extend(markets)
                    
                    if not cursor:
                        print(f"  🏁 Reached end of market list")
                        break
                    
                    if page_count >= 10:  # Safety limit
                        print(f"  ⚠️  Reached page limit")
                        break
            
            print(f"\n📊 FETCHED {len(all_markets)} TOTAL MARKETS")
            return all_markets
            
        except Exception as e:
            print(f"  ❌ Error fetching markets: {e}")
            return []
    
    def is_crypto_market(self, market: Dict[str, Any]) -> bool:
        """Determine if market is a crypto market"""
        title = market.get("title", "").lower()
        subtitle = market.get("subtitle", "").lower()
        ticker = market.get("ticker", "").lower()
        
        # Crypto keywords
        crypto_keywords = [
            "bitcoin", "btc", "ethereum", "eth", "solana", "sol", 
            "dogecoin", "doge", "cardano", "ada", "polygon", "matic",
            "polkadot", "dot", "avalanche", "avax", "chainlink", "link"
        ]
        
        # Price indicators
        price_keywords = ["price", "high", "low", "close", "usd", "$", "settlement"]
        
        # CF Benchmarks indices
        crypto_indices = ["brti", "ethusd_rti", "btcusd_rti", "cfb", "cme cf", "cf benchmarks"]
        
        # Check all text
        all_text = f"{title} {subtitle} {ticker}"
        
        # Must have crypto keyword + price indicator
        has_crypto = any(keyword in all_text for keyword in crypto_keywords)
        has_price = any(keyword in all_text for keyword in price_keywords)
        has_index = any(index in all_text for index in crypto_indices)
        
        return (has_crypto and has_price) or has_index
    
    def classify_market(self, market: Dict[str, Any]) -> str:
        """Classify market type"""
        if self.is_crypto_market(market):
            return "crypto"
        
        title = market.get("title", "").lower()
        subtitle = market.get("subtitle", "").lower()
        all_text = f"{title} {subtitle}"
        
        # Sports
        sports_keywords = ["nba", "nfl", "mlb", "nhl", "player", "points", "wins", "game"]
        if any(keyword in all_text for keyword in sports_keywords):
            return "sports"
        
        # Politics
        politics_keywords = ["election", "president", "senate", "congress", "vote"]
        if any(keyword in all_text for keyword in politics_keywords):
            return "politics"
        
        # Economics
        economics_keywords = ["cpi", "gdp", "fed", "inflation", "unemployment"]
        if any(keyword in all_text for keyword in economics_keywords):
            return "economics"
        
        # Weather
        weather_keywords = ["weather", "temperature", "rain", "snow", "degrees"]
        if any(keyword in all_text for keyword in weather_keywords):
            return "weather"
        
        return "other"
    
    def discover_btc_markets(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Discover BTC-specific markets"""
        btc_markets = []
        
        for market in markets:
            if not self.is_crypto_market(market):
                continue
            
            title = market.get("title", "").lower()
            ticker = market.get("ticker", "").upper()
            
            # Check for BTC-specific
            if "btc" in title or "bitcoin" in title or "BTC" in ticker:
                market_type = "unknown"
                if "high" in title:
                    market_type = "high"
                elif "range" in title or "between" in title:
                    market_type = "range"
                elif "close" in title:
                    market_type = "close"
                
                btc_markets.append({
                    **market,
                    "btc_market_type": market_type
                })
        
        return btc_markets

class KalshiCryptoBot:
    """BTC trading scaffolding"""
    
    def __init__(self, api: KalshiOfficialAPI):
        self.api = api
    
    async def get_btc_market_opportunities(self) -> List[Dict[str, Any]]:
        """Get current BTC market opportunities"""
        markets = await self.api.fetch_all_markets()
        btc_markets = self.api.discover_btc_markets(markets)
        
        # Filter for active markets with good liquidity
        opportunities = []
        for market in btc_markets:
            if market.get("status") == "active":
                # Check order book depth
                orderbook = await self.get_orderbook(market.get("ticker"))
                if orderbook and self.has_sufficient_liquidity(orderbook):
                    opportunities.append({
                        "market": market,
                        "orderbook": orderbook,
                        "confidence": self.calculate_confidence(market, orderbook)
                    })
        
        return sorted(opportunities, key=lambda x: x["confidence"], reverse=True)
    
    async def get_orderbook(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get orderbook for a market"""
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api.base_url}/trade-api/v2/markets/{ticker}/orderbook",
                    headers=self.api._get_auth_headers(),
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"  ❌ Orderbook error for {ticker}: {response.status_code}")
                    return None
        except Exception as e:
            print(f"  ❌ Orderbook fetch error: {e}")
            return None
    
    def has_sufficient_liquidity(self, orderbook: Dict[str, Any]) -> bool:
        """Check if market has sufficient liquidity"""
        yes_bid = orderbook.get("yes_bid", 0)
        no_bid = orderbook.get("no_bid", 0)
        
        # Basic liquidity check
        return yes_bid > 0 and no_bid > 0
    
    def calculate_confidence(self, market: Dict[str, Any], orderbook: Dict[str, Any]) -> float:
        """Calculate trading confidence score"""
        confidence = 0.0
        
        # Market type preference
        market_type = market.get("btc_market_type", "unknown")
        if market_type == "high":
            confidence += 0.3
        elif market_type == "range":
            confidence += 0.2
        elif market_type == "close":
            confidence += 0.1
        
        # Liquidity score
        yes_bid = orderbook.get("yes_bid", 0)
        no_bid = orderbook.get("no_bid", 0)
        liquidity_score = min((yes_bid + no_bid) / 200, 1.0)  # Normalize to 0-1
        confidence += liquidity_score * 0.4
        
        # Time to expiry (prefer nearer expiry)
        close_time = market.get("close_time")
        if close_time:
            try:
                from datetime import datetime
                expiry = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                days_to_expiry = (expiry - datetime.now()).days
                if days_to_expiry < 7:
                    confidence += 0.3
                elif days_to_expiry < 30:
                    confidence += 0.2
            except:
                pass
        
        return min(confidence, 1.0)

async def main():
    """Main implementation function"""
    print("🚀 KALSHI CRYPTO MARKETS - OFFICIAL IMPLEMENTATION")
    print("=" * 70)
    print("Following docs.kalshi.com official documentation")
    print("=" * 70)
    
    try:
        # Initialize API
        api = KalshiOfficialAPI()
        
        # Fetch markets
        markets = await api.fetch_all_markets()
        
        if not markets:
            print("❌ No markets fetched - check credentials and permissions")
            return
        
        # Classify markets
        catalog = {
            "total": len(markets),
            "crypto": 0,
            "sports": 0,
            "politics": 0,
            "economics": 0,
            "weather": 0,
            "other": 0
        }
        
        crypto_markets = []
        
        for market in markets:
            market_type = api.classify_market(market)
            catalog[market_type] += 1
            
            if market_type == "crypto":
                crypto_markets.append(market)
        
        print(f"\n📊 MARKET CATALOG:")
        print(f"  Total: {catalog['total']}")
        print(f"  Crypto: {catalog['crypto']}")
        print(f"  Sports: {catalog['sports']}")
        print(f"  Politics: {catalog['politics']}")
        print(f"  Economics: {catalog['economics']}")
        print(f"  Weather: {catalog['weather']}")
        print(f"  Other: {catalog['other']}")
        
        # Show crypto markets
        if crypto_markets:
            print(f"\n💰 CRYPTO MARKETS FOUND:")
            for market in crypto_markets[:10]:
                print(f"  - {market.get('ticker')}")
                print(f"    Title: {market.get('title')}")
                print(f"    Status: {market.get('status')}")
                print()
        else:
            print(f"\n❌ NO CRYPTO MARKETS FOUND")
            print(f"  This suggests the account doesn't have crypto market access")
            print(f"  Environment: {'DEMO' if api.use_demo else 'PRODUCTION'}")
        
        # BTC trading analysis
        bot = KalshiCryptoBot(api)
        btc_markets = api.discover_btc_markets(markets)
        
        print(f"\n₿ BTC MARKETS: {len(btc_markets)}")
        if btc_markets:
            print(f"\n₿ BTC MARKET TYPES:")
            for market in btc_markets[:5]:
                print(f"  - {market.get('ticker')} ({market.get('btc_market_type')})")
                print(f"    {market.get('title')}")
        
        # Get trading opportunities
        opportunities = await bot.get_btc_market_opportunities()
        
        print(f"\n🎯 TRADING OPPORTUNITIES: {len(opportunities)}")
        for opp in opportunities[:3]:
            market = opp["market"]
            print(f"  - {market.get('ticker')} (confidence: {opp['confidence']:.2f})")
            print(f"    {market.get('title')}")
        
        # Generate implementation report
        report = {
            "timestamp": datetime.now().isoformat(),
            "environment": "demo" if api.use_demo else "production",
            "api_endpoint": api.base_url,
            "catalog": catalog,
            "crypto_markets_count": len(crypto_markets),
            "btc_markets_count": len(btc_markets),
            "trading_opportunities": len(opportunities),
            "crypto_examples": [
                {
                    "ticker": m.get("ticker"),
                    "title": m.get("title"),
                    "status": m.get("status")
                } for m in crypto_markets[:5]
            ],
            "implementation_status": "success" if catalog["crypto"] > 0 else "no_crypto_access"
        }
        
        with open('kalshi_crypto_implementation_report.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n📋 Implementation report saved to: kalshi_crypto_implementation_report.json")
        
        # Final status
        if catalog["crypto"] > 0:
            print(f"\n🎉 SUCCESS! Kalshi crypto markets integration complete")
            print(f"  ✅ Found {catalog['crypto']} crypto markets")
            print(f"  ✅ BTC trading scaffolding ready")
            print(f"  ✅ Market classification working")
        else:
            print(f"\n⚠️  CRYPTO MARKETS NOT ACCESSIBLE")
            print(f"  ❌ Account may need crypto market permissions")
            print(f"  ❌ Try upgrading account or contacting Kalshi support")
            print(f"  ❌ Current markets: sports ({catalog['sports']}), economics ({catalog['economics']})")
        
        return catalog["crypto"] > 0
        
    except Exception as e:
        print(f"❌ Implementation failed: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(main())
