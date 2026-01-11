"""
Integration tests for Twitter, Telegram, and News agents.
Validates configuration and connectivity before production launch.
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Import agents with correct paths
try:
    from lib.merid.twitter_agent import MERIDTwitterAgent
except ImportError:
    MERIDTwitterAgent = None

from notifications.telegram_client import TelegramAlertClient
from monitoring.news_agent import NewsSentinel

load_dotenv()


def test_twitter_agent():
    """Test Twitter agent configuration and connectivity."""
    print("\n=== Testing Twitter Agent ===")
    
    if MERIDTwitterAgent is None:
        print("⚠️  Twitter agent module not found - skipping")
        print("   Expected location: lib/merid/twitter_agent.py")
        return False
    
    # Check environment variables
    required_vars = [
        "X_BEARER_TOKEN",
        "X_API_KEY",
        "X_API_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET"
    ]
    
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        print("⚠️  Twitter agent will not function without credentials")
        print("   Add these to your .env file:")
        for var in missing:
            print(f"   {var}=your_value_here")
        return False
    
    print("✅ All Twitter credentials configured")
    
    try:
        agent = MERIDTwitterAgent()
        print("✅ Twitter agent initialized successfully")
        
        # Test market sentiment fetch
        result = agent.get_market_sentiment("Bitcoin")
        if isinstance(result, str) and "Error" in result:
            print(f"❌ Twitter API test failed: {result}")
            return False
        
        print(f"✅ Twitter API working - fetched {len(result) if isinstance(result, list) else 0} tweets")
        return True
        
    except Exception as exc:
        print(f"❌ Twitter agent error: {exc}")
        return False


def test_telegram_agent():
    """Test Telegram agent configuration and connectivity."""
    print("\n=== Testing Telegram Agent ===")
    
    bot_token = os.getenv("MERID_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("MERID_TELEGRAM_CHAT_ID")
    
    if not bot_token:
        print("❌ MERID_TELEGRAM_BOT_TOKEN not configured")
        print("⚠️  Telegram alerts will be disabled")
        return False
    
    print("✅ Telegram bot token configured")
    
    if not chat_id:
        print("⚠️  MERID_TELEGRAM_CHAT_ID not set, using default: @merid_alerts")
    else:
        print(f"✅ Telegram chat ID: {chat_id}")
    
    try:
        client = TelegramAlertClient(enabled=True)
        
        # Test message send
        test_message = "🧪 MERID Test Alert - System Initialization Check"
        success = client.send_alert(test_message)
        
        if success:
            print("✅ Telegram alert sent successfully")
            print(f"   Check your Telegram channel: {chat_id or '@merid_alerts'}")
            return True
        else:
            print("❌ Telegram alert failed to send")
            return False
            
    except Exception as exc:
        print(f"❌ Telegram agent error: {exc}")
        return False


def test_news_agent():
    """Test News agent functionality."""
    print("\n=== Testing News Agent ===")
    
    try:
        sentinel = NewsSentinel()
        print("✅ News sentinel initialized")
        
        headlines = sentinel.fetch_headlines(limit=5)
        
        if not headlines:
            print("❌ No headlines fetched")
            return False
        
        print(f"✅ Fetched {len(headlines)} news items")
        
        for idx, item in enumerate(headlines[:3], 1):
            print(f"   {idx}. [{item.source}] {item.headline}")
            print(f"      Importance: {item.importance}")
        
        print("\n⚠️  NOTE: News agent currently using mock data")
        print("   For production, integrate live feeds:")
        print("   - CoinDesk API")
        print("   - CoinTelegraph RSS")
        print("   - Binance Announcements API")
        
        return True
        
    except Exception as exc:
        print(f"❌ News agent error: {exc}")
        return False


def main():
    """Run all agent integration tests."""
    print("=" * 60)
    print("MERID AGENT INTEGRATION TESTS")
    print("=" * 60)
    
    results = {
        "Twitter": test_twitter_agent(),
        "Telegram": test_telegram_agent(),
        "News": test_news_agent()
    }
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for agent, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{agent:15} {status}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\nTotal: {passed}/{total} agents operational")
    
    if passed == total:
        print("\n🎉 All agents ready for production!")
        return 0
    else:
        print("\n⚠️  Some agents need configuration - check .env file")
        return 1


if __name__ == "__main__":
    exit(main())
