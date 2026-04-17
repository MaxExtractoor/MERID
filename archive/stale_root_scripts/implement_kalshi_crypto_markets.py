#!/usr/bin/env python3
"""
IMPLEMENT KALSHI CRYPTO MARKETS CORRECTLY

Following official Kalshi API documentation to:
1. Use proper credentials from .env
2. Discover and classify crypto markets correctly  
3. Implement BTC trading scaffolding
"""

import asyncio
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

class KalshiCryptoMarkets:
    """Proper Kalshi API integration for crypto markets."""
    
    def __init__(self):
        self.api_key_id = os.getenv('KALSHI_API_KEY_ID')
        self.private_key_path = os.getenv('KALSHI_PRIVATE_KEY_PATH')
        self.use_demo = os.getenv('KALSHI_USE_DEMO', 'true').lower() == 'true'  # Force demo for testing
        
        if not self.api_key_id:
            raise ValueError("KALSHI_API_KEY_ID not found in environment")
        if not self.private_key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not found in environment")
        
        # Determine base URL based on environment (using working endpoints)
        if self.use_demo:
            self.base_url = "https://demo-api.kalshi.co"
        else:
            self.base_url = "https://api.elections.kalshi.com"  # Use working elections API
        
        print(f"🔧 Kalshi Crypto Markets initialized")
        print(f"  Environment: {'DEMO' if self.use_demo else 'PRODUCTION'}")
        print(f"  API Key ID: {self.api_key_id[:8]}...")
        print(f"  Private Key: {self.private_key_path}")
        print(f"  Base URL: {self.base_url}")
    
    async def fetch_all_markets(self) -> List[Dict[str, Any]]:
        """
        Fetch ALL markets from Kalshi API with proper pagination.
        
        Returns:
            List of all market objects from Kalshi
        """
        print(f"\n📡 FETCHING ALL MARKETS FROM KALSHI API")
        print(f"  Using endpoint: {self.base_url}/trade-api/v2/markets")
        
        try:
            import httpx
            
            all_markets = []
            cursor = None
            page_count = 0
            total_fetched = 0
            
            async with httpx.AsyncClient() as client:
                while True:
                    page_count += 1
                    
                    # Build request parameters
                    params = {"limit": 1000}  # Max per page
                    if cursor:
                        params["cursor"] = cursor
                    
                    print(f"  📄 Fetching page {page_count}...")
                    
                    # Make authenticated request
                    response = await client.get(
                        f"{self.base_url}/trade-api/v2/markets",
                        params=params,
                        headers=self._get_auth_headers(),
                        timeout=30.0
                    )
                    
                    if response.status_code != 200:
                        print(f"  ❌ API Error: {response.status_code} - {response.text}")
                        break
                    
                    data = response.json()
                    markets = data.get("markets", [])
                    cursor = data.get("next_cursor")
                    
                    page_market_count = len(markets)
                    total_fetched += page_market_count
                    
                    print(f"    ✅ Page {page_count}: {page_market_count} markets")
                    print(f"    📊 Total so far: {total_fetched} markets")
                    
                    all_markets.extend(markets)
                    
                    # Stop if no more pages
                    if not cursor:
                        print(f"  🏁 Reached end of market list")
                        break
                    
                    # Safety limit
                    if page_count >= 10:  # Max 10 pages
                        print(f"  ⚠️  Reached page limit, stopping")
                        break
            
            print(f"\n📊 MARKET FETCH SUMMARY:")
            print(f"  Total pages: {page_count}")
            print(f"  Total markets: {len(all_markets)}")
            
            # Log sample of raw fields
            if all_markets:
                sample_market = all_markets[0]
                print(f"\n📋 SAMPLE MARKET FIELDS:")
                for key, value in sample_market.items():
                    if isinstance(value, str) and len(value) > 100:
                        value = value[:100] + "..."
                    print(f"  {key}: {value}")
            
            return all_markets
            
        except Exception as e:
            print(f"  ❌ Error fetching markets: {e}")
            return []
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for Kalshi API."""
        import base64
        import time
        import hashlib
        import hmac
        
        # Read private key
        try:
            with open(self.private_key_path, 'r') as f:
                private_key = f.read().strip()
        except Exception as e:
            raise ValueError(f"Failed to read private key: {e}")
        
        # Create signature
        timestamp = str(int(time.time()))
        message = f"{timestamp}"
        
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
    
    def is_crypto_market(self, market: Dict[str, Any]) -> bool:
        """
        Determine if a market is a crypto market.
        
        Args:
            market: Market object from Kalshi API
            
        Returns:
            True if this is a crypto market
        """
        # Get market text fields
        title = market.get("title", "").lower()
        subtitle = market.get("subtitle", "").lower()
        ticker = market.get("ticker", "").lower()
        description = market.get("description", "").lower()
        
        # Crypto keywords
        crypto_keywords = [
            "bitcoin", "btc", "ether", "ethereum", "crypto", 
            "solana", "sol", "dogecoin", "doge", "cardano", "ada",
            "polygon", "matic", "polkadot", "dot", "avalanche", "avax"
        ]
        
        # CF Benchmarks crypto indices
        crypto_indices = [
            "brti", "ethusd_rti", "btcusd_rti", "cfb", "cme", "cf benchmarks"
        ]
        
        # Check all text fields for crypto indicators
        all_text = f"{title} {subtitle} {ticker} {description}"
        
        # Direct crypto keyword matches
        for keyword in crypto_keywords:
            if keyword in all_text:
                return True
        
        # CF Benchmarks indices
        for index in crypto_indices:
            if index in all_text:
                return True
        
        # Check underlying field
        underlying = market.get("underlying", "").lower()
        if underlying:
            for keyword in crypto_keywords + crypto_indices:
                if keyword in underlying:
                    return True
        
        # Check series_ticker
        series_ticker = market.get("series_ticker", "").lower()
        if series_ticker:
            for keyword in crypto_keywords + crypto_indices:
                if keyword in series_ticker:
                    return True
        
        # Check tags
        tags = market.get("tags", [])
        if tags:
            for tag in tags:
                tag_lower = str(tag).lower()
                for keyword in crypto_keywords:
                    if keyword in tag_lower:
                        return True
        
        return False
    
    def classify_market_type(self, market: Dict[str, Any]) -> str:
        """
        Classify market into type categories.
        
        Args:
            market: Market object from Kalshi API
            
        Returns:
            Market type: crypto, sports, politics, economics, weather, other
        """
        # Check crypto first (most specific)
        if self.is_crypto_market(market):
            return "crypto"
        
        # Get text for classification
        title = market.get("title", "").lower()
        subtitle = market.get("subtitle", "").lower()
        ticker = market.get("ticker", "").lower()
        all_text = f"{title} {subtitle} {ticker}"
        
        # Sports keywords
        sports_keywords = [
            "nba", "nfl", "mlb", "nhl", "soccer", "tennis", "golf",
            "player", "points", "goals", "wins", "game", "match", "team"
        ]
        if any(keyword in all_text for keyword in sports_keywords):
            return "sports"
        
        # Politics keywords  
        politics_keywords = [
            "election", "president", "senate", "congress", "vote", "trump", "biden",
            "politics", "democrat", "republican", "party", "campaign"
        ]
        if any(keyword in all_text for keyword in politics_keywords):
            return "politics"
        
        # Economics keywords
        economics_keywords = [
            "cpi", "gdp", "fed", "inflation", "unemployment", "jobs", "rate",
            "economy", "economic", "financial", "market", "stock", "index"
        ]
        if any(keyword in all_text for keyword in economics_keywords):
            return "economics"
        
        # Weather keywords
        weather_keywords = [
            "weather", "temperature", "rain", "snow", "hurricane", "climate",
            "degrees", "fahrenheit", "celsius", "forecast"
        ]
        if any(keyword in all_text for keyword in weather_keywords):
            return "weather"
        
        return "other"
    
    def build_catalog_summary(self, markets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build catalog summary with market type counts.
        
        Args:
            markets: List of market objects
            
        Returns:
            Catalog summary with counts per market type
        """
        summary = {
            "total_markets": len(markets),
            "crypto": 0,
            "sports": 0,
            "politics": 0,
            "economics": 0,
            "weather": 0,
            "other": 0
        }
        
        crypto_examples = []
        
        for market in markets:
            market_type = self.classify_market_type(market)
            summary[market_type] += 1
            
            # Collect crypto examples
            if market_type == "crypto" and len(crypto_examples) < 5:
                crypto_examples.append({
                    "ticker": market.get("ticker", ""),
                    "title": market.get("title", ""),
                    "subtitle": market.get("subtitle", "")
                })
        
        summary["crypto_examples"] = crypto_examples
        
        return summary
    
    def discover_btc_markets(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Discover BTC markets for trading.
        
        Args:
            markets: List of market objects
            
        Returns:
            List of BTC markets
        """
        btc_markets = []
        
        for market in markets:
            if not self.is_crypto_market(market):
                continue
            
            # Check if it's BTC-specific
            title = market.get("title", "").lower()
            subtitle = market.get("subtitle", "").lower()
            ticker = market.get("ticker", "").lower()
            
            btc_indicators = ["bitcoin", "btc"]
            if any(indicator in title or indicator in subtitle or indicator in ticker 
                   for indicator in btc_indicators):
                
                # Check for high/range/close patterns
                market_type = "unknown"
                if "high" in title or "high" in subtitle:
                    market_type = "high"
                elif "range" in title or "range" in subtitle or "between" in title:
                    market_type = "range"
                elif "close" in title or "close" in subtitle:
                    market_type = "close"
                
                btc_markets.append({
                    **market,
                    "btc_market_type": market_type,
                    "expiry_date": market.get("end_date"),
                    "active": market.get("active", True)
                })
        
        return btc_markets
    
    def select_target_market(self, btc_markets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Select the best BTC market for trading.
        
        Args:
            btc_markets: List of BTC markets
            
        Returns:
            Selected market or None
        """
        if not btc_markets:
            return None
        
        # Sort by expiry date (nearest first)
        active_markets = [m for m in btc_markets if m.get("active", True)]
        
        if not active_markets:
            return None
        
        # Prefer high markets, then range, then close
        priority_order = {"high": 1, "range": 2, "close": 3, "unknown": 4}
        
        sorted_markets = sorted(
            active_markets,
            key=lambda m: (
                priority_order.get(m.get("btc_market_type", "unknown"), 4),
                m.get("expiry_date", "")
            )
        )
        
        return sorted_markets[0]

async def main():
    """Main function to implement Kalshi crypto markets."""
    print("🚀 IMPLEMENTING KALSHI CRYPTO MARKETS")
    print("=" * 70)
    print("Following official Kalshi API documentation")
    print("Using credentials from .env file")
    print("=" * 70)
    
    try:
        # Initialize Kalshi client
        kalshi = KalshiCryptoMarkets()
        
        # Fetch all markets
        all_markets = await kalshi.fetch_all_markets()
        
        if not all_markets:
            print("❌ No markets fetched - check credentials and permissions")
            return
        
        # Build catalog summary
        summary = kalshi.build_catalog_summary(all_markets)
        
        print(f"\n📊 MARKET CATALOG SUMMARY:")
        print(f"  Total markets: {summary['total_markets']}")
        print(f"  Crypto markets: {summary['crypto']}")
        print(f"  Sports markets: {summary['sports']}")
        print(f"  Politics markets: {summary['politics']}")
        print(f"  Economics markets: {summary['economics']}")
        print(f"  Weather markets: {summary['weather']}")
        print(f"  Other markets: {summary['other']}")
        
        # Show crypto examples
        if summary['crypto_examples']:
            print(f"\n💰 CRYPTO MARKET EXAMPLES:")
            for example in summary['crypto_examples']:
                print(f"  - {example['ticker']}")
                print(f"    Title: {example['title']}")
                print(f"    Subtitle: {example['subtitle']}")
        else:
            print(f"\n❌ NO CRYPTO MARKETS FOUND")
            print(f"  This indicates a permissions or configuration issue")
            print(f"  Environment: {'DEMO' if kalshi.use_demo else 'PRODUCTION'}")
            print(f"  API Key: {kalshi.api_key_id[:8]}...")
        
        # Discover BTC markets
        btc_markets = kalshi.discover_btc_markets(all_markets)
        
        print(f"\n₿ BTC MARKETS DISCOVERED: {len(btc_markets)}")
        
        if btc_markets:
            print(f"\n₿ BTC MARKET TYPES:")
            btc_types = {}
            for market in btc_markets:
                market_type = market.get("btc_market_type", "unknown")
                btc_types[market_type] = btc_types.get(market_type, 0) + 1
            
            for market_type, count in btc_types.items():
                print(f"  - {market_type}: {count}")
            
            # Select target market
            target_market = kalshi.select_target_market(btc_markets)
            if target_market:
                print(f"\n🎯 SELECTED BTC MARKET:")
                print(f"  Ticker: {target_market.get('ticker')}")
                print(f"  Title: {target_market.get('title')}")
                print(f"  Type: {target_market.get('btc_market_type')}")
                print(f"  Expiry: {target_market.get('expiry_date')}")
                print(f"  Active: {target_market.get('active')}")
        
        # Generate report
        report = {
            "timestamp": datetime.now().isoformat(),
            "environment": "demo" if kalshi.use_demo else "production",
            "api_key_id": kalshi.api_key_id[:8] + "...",
            "catalog_summary": summary,
            "btc_markets_count": len(btc_markets),
            "btc_market_types": list(set(m.get("btc_market_type", "unknown") for m in btc_markets)),
            "target_market": {
                "ticker": kalshi.select_target_market(btc_markets).get("ticker") if btc_markets else None,
                "type": kalshi.select_target_market(btc_markets).get("btc_market_type") if btc_markets else None
            } if btc_markets else None,
            "implementation_status": "success" if summary['crypto'] > 0 else "no_crypto_markets"
        }
        
        # Save report
        with open('kalshi_crypto_implementation.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n📋 Implementation report saved to: kalshi_crypto_implementation.json")
        
        if summary['crypto'] == 0:
            print(f"\n⚠️  DEBUGGING NEEDED:")
            print(f"  - Verify credentials in .env file")
            print(f"  - Check if account has crypto market permissions")
            print(f"  - Confirm environment (demo vs production)")
            print(f"  - Contact Kalshi support if needed")
        
        return summary['crypto'] > 0
        
    except Exception as e:
        print(f"❌ Implementation failed: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(main())
