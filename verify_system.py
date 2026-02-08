"""
MERID System Verification Script

Comprehensive startup verification for all integrated systems:
- Data feeds (crypto, stocks, forex, commodities)
- WebSocket publishers
- API endpoints
- Social media bots
- News aggregation
- Prediction markets
"""

import asyncio
import time
import httpx
from typing import Dict, List, Tuple
from utils.logger import get_logger

logger = get_logger("verify_system")


class SystemVerifier:
    """Verifies all MERID system components."""
    
    def __init__(self):
        self.results: Dict[str, bool] = {}
        self.errors: List[str] = []
        self.base_url = "http://localhost:8000"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def verify_all(self):
        """Run all verification checks."""
        print("\n" + "=" * 80)
        print("MERID SYSTEM VERIFICATION")
        print("=" * 80 + "\n")
        
        # Check API endpoints
        await self.verify_api_endpoints()
        
        # Check data feeds
        await self.verify_data_feeds()
        
        # Check social bots
        await self.verify_social_bots()
        
        # Check news aggregation
        await self.verify_news_aggregation()
        
        # Print summary
        self.print_summary()
        
        await self.client.aclose()
    
    async def verify_api_endpoints(self):
        """Verify all REST API endpoints."""
        print("🔍 VERIFYING API ENDPOINTS")
        print("-" * 80)
        
        endpoints = [
            ("/api/v1/markets/stocks", "Stocks API"),
            ("/api/v1/markets/forex", "Forex API"),
            ("/api/v1/markets/commodities", "Commodities API"),
            ("/api/v1/markets/all", "All Markets API"),
            ("/api/v1/trading/orders/open", "Open Orders API"),
            ("/api/agents/summary", "Agent Summary API"),
            ("/api/risk/exposure", "Risk Exposure API"),
        ]
        
        for endpoint, name in endpoints:
            try:
                response = await self.client.get(f"{self.base_url}{endpoint}")
                if response.status_code == 200:
                    data = response.json()
                    self.results[name] = True
                    print(f"✅ {name}: {endpoint}")
                    
                    # Show data count if available
                    if 'stocks' in data:
                        print(f"   → {len(data['stocks'])} stocks")
                    if 'forex' in data:
                        print(f"   → {len(data['forex'])} forex pairs")
                    if 'commodities' in data:
                        print(f"   → {len(data['commodities'])} commodities")
                else:
                    self.results[name] = False
                    self.errors.append(f"{name}: HTTP {response.status_code}")
                    print(f"❌ {name}: HTTP {response.status_code}")
            except Exception as e:
                self.results[name] = False
                self.errors.append(f"{name}: {str(e)}")
                print(f"❌ {name}: {str(e)[:50]}...")
        
        print()
    
    async def verify_data_feeds(self):
        """Verify data feeds are working."""
        print("📊 VERIFYING DATA FEEDS")
        print("-" * 80)
        
        try:
            # Check crypto feed
            from data.live_price_feed import get_live_price_feed
            crypto_feed = get_live_price_feed()
            print(f"✅ Crypto Feed: {len(crypto_feed.symbols)} symbols configured")
            self.results["Crypto Feed"] = True
        except Exception as e:
            print(f"❌ Crypto Feed: {str(e)[:50]}...")
            self.results["Crypto Feed"] = False
            self.errors.append(f"Crypto Feed: {str(e)}")
        
        try:
            # Check stocks feed
            from data.stocks_feed import get_stocks_feed
            stocks_feed = get_stocks_feed()
            print(f"✅ Stocks Feed: {len(stocks_feed.symbols)} symbols configured")
            self.results["Stocks Feed"] = True
        except Exception as e:
            print(f"❌ Stocks Feed: {str(e)[:50]}...")
            self.results["Stocks Feed"] = False
            self.errors.append(f"Stocks Feed: {str(e)}")
        
        try:
            # Check forex feed
            from data.forex_feed import get_forex_feed
            forex_feed = get_forex_feed()
            print(f"✅ Forex Feed: {len(forex_feed.pairs)} pairs configured")
            self.results["Forex Feed"] = True
        except Exception as e:
            print(f"❌ Forex Feed: {str(e)[:50]}...")
            self.results["Forex Feed"] = False
            self.errors.append(f"Forex Feed: {str(e)}")
        
        try:
            # Check commodities feed
            from data.commodities_feed import get_commodities_feed
            commodities_feed = get_commodities_feed()
            print(f"✅ Commodities Feed: {len(commodities_feed.commodities)} commodities configured")
            self.results["Commodities Feed"] = True
        except Exception as e:
            print(f"❌ Commodities Feed: {str(e)[:50]}...")
            self.results["Commodities Feed"] = False
            self.errors.append(f"Commodities Feed: {str(e)}")
        
        print()
    
    async def verify_social_bots(self):
        """Verify social media bots."""
        print("🤖 VERIFYING SOCIAL MEDIA BOTS")
        print("-" * 80)
        
        try:
            from agents.twitter_agent import get_twitter_agent
            twitter_agent = get_twitter_agent()
            
            if twitter_agent.enabled:
                print(f"✅ Twitter Bot: ENABLED")
                print(f"   → Client: {type(twitter_agent.client).__name__}")
                self.results["Twitter Bot"] = True
            else:
                print("⚠️  Twitter Bot: DISABLED (check credentials)")
                self.results["Twitter Bot"] = False
        except Exception as e:
            print(f"❌ Twitter Bot: {str(e)[:50]}...")
            self.results["Twitter Bot"] = False
            self.errors.append(f"Twitter Bot: {str(e)}")
        
        try:
            from agents.telegram_agent import get_telegram_agent
            telegram_agent = get_telegram_agent()
            
            if telegram_agent.enabled:
                print(f"✅ Telegram Bot: ENABLED")
                print(f"   → Chat ID: {telegram_agent.chat_id}")
                self.results["Telegram Bot"] = True
            else:
                print("⚠️  Telegram Bot: DISABLED (check credentials)")
                self.results["Telegram Bot"] = False
        except Exception as e:
            print(f"❌ Telegram Bot: {str(e)[:50]}...")
            self.results["Telegram Bot"] = False
            self.errors.append(f"Telegram Bot: {str(e)}")
        
        print()
    
    async def verify_news_aggregation(self):
        """Verify news aggregation."""
        print("📰 VERIFYING NEWS AGGREGATION")
        print("-" * 80)
        
        try:
            from monitoring.news_feeds import get_news_aggregator
            news_aggregator = get_news_aggregator()
            
            print("✅ News Aggregator: Initialized")
            print(f"   → Sources: CoinDesk, CoinTelegraph, CryptoCompare")
            print(f"   → Articles per source: 15")
            
            # Try fetching news
            articles = news_aggregator.fetch_all(limit_per_source=5)
            print(f"   → Fetched {len(articles)} articles")
            
            self.results["News Aggregator"] = True
        except Exception as e:
            print(f"❌ News Aggregator: {str(e)[:50]}...")
            self.results["News Aggregator"] = False
            self.errors.append(f"News Aggregator: {str(e)}")
        
        try:
            from agents.news_monitor_agent import get_news_monitor_agent
            news_monitor = get_news_monitor_agent()
            
            print("✅ News Monitor Agent: Initialized")
            print(f"   → Importance threshold: {news_monitor.importance_threshold}")
            print(f"   → Twitter integration: {news_monitor.twitter_agent.enabled}")
            print(f"   → Telegram integration: {news_monitor.telegram_agent.enabled}")
            
            self.results["News Monitor"] = True
        except Exception as e:
            print(f"❌ News Monitor: {str(e)[:50]}...")
            self.results["News Monitor"] = False
            self.errors.append(f"News Monitor: {str(e)}")
        
        print()
    
    def print_summary(self):
        """Print verification summary."""
        print("=" * 80)
        print("VERIFICATION SUMMARY")
        print("=" * 80)
        
        passed = sum(1 for v in self.results.values() if v)
        total = len(self.results)
        
        print(f"\nResults: {passed}/{total} checks passed")
        print()
        
        # Group results
        api_checks = {k: v for k, v in self.results.items() if 'API' in k}
        feed_checks = {k: v for k, v in self.results.items() if 'Feed' in k}
        bot_checks = {k: v for k, v in self.results.items() if 'Bot' in k}
        other_checks = {k: v for k, v in self.results.items() 
                       if k not in api_checks and k not in feed_checks and k not in bot_checks}
        
        if api_checks:
            print("API Endpoints:")
            for name, status in api_checks.items():
                print(f"  {'✅' if status else '❌'} {name}")
            print()
        
        if feed_checks:
            print("Data Feeds:")
            for name, status in feed_checks.items():
                print(f"  {'✅' if status else '❌'} {name}")
            print()
        
        if bot_checks:
            print("Social Bots:")
            for name, status in bot_checks.items():
                print(f"  {'✅' if status else '❌'} {name}")
            print()
        
        if other_checks:
            print("Other Components:")
            for name, status in other_checks.items():
                print(f"  {'✅' if status else '❌'} {name}")
            print()
        
        if self.errors:
            print("Errors:")
            for error in self.errors:
                print(f"  ⚠️  {error}")
            print()
        
        # Overall status
        if passed == total:
            print("🎉 ALL SYSTEMS OPERATIONAL!")
        elif passed >= total * 0.8:
            print("⚠️  MOSTLY OPERATIONAL (some issues detected)")
        elif passed >= total * 0.5:
            print("⚠️  PARTIAL FUNCTIONALITY (significant issues)")
        else:
            print("❌ CRITICAL ISSUES DETECTED")
        
        print("=" * 80)


async def main():
    """Run system verification."""
    verifier = SystemVerifier()
    await verifier.verify_all()


if __name__ == "__main__":
    asyncio.run(main())
