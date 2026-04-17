"""
Test script for Twitter and Telegram bot functionality.

This script verifies that the social media bots are properly configured
and can post messages/tweets.
"""

import asyncio
import os
from agents.twitter_agent import get_twitter_agent
from agents.telegram_agent import get_telegram_agent
from utils.logger import get_logger

logger = get_logger("test_social_bots")


async def test_twitter_bot():
    """Test Twitter bot functionality."""
    print("\n" + "=" * 60)
    print("TESTING TWITTER BOT")
    print("=" * 60)
    
    twitter_agent = get_twitter_agent()
    
    # Check if enabled
    if not twitter_agent.enabled:
        print("❌ Twitter bot is DISABLED")
        print("   Check that X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET are in .env")
        return False
    
    print("✅ Twitter bot is ENABLED")
    print(f"   Client: {twitter_agent.client}")
    
    # Test posting a system status tweet
    print("\n📤 Attempting to post test tweet...")
    tweet = twitter_agent.post_system_status(
        blocks_mined=42,
        agents_active=8,
        consensus_rate=0.95
    )
    
    if tweet:
        print(f"✅ Tweet posted successfully!")
        print(f"   Tweet ID: {tweet.tweet_id}")
        print(f"   Text: {tweet.text}")
        return True
    else:
        print("❌ Failed to post tweet")
        print("   Check Twitter API credentials and rate limits")
        return False


async def test_telegram_bot():
    """Test Telegram bot functionality."""
    print("\n" + "=" * 60)
    print("TESTING TELEGRAM BOT")
    print("=" * 60)
    
    telegram_agent = get_telegram_agent()
    
    # Check if enabled
    if not telegram_agent.enabled:
        print("❌ Telegram bot is DISABLED")
        print("   Check that TELEGRAM_TOKEN and TELEGRAM_CHAT_ID are in .env")
        return False
    
    print("✅ Telegram bot is ENABLED")
    print(f"   Bot: {telegram_agent._bot}")
    print(f"   Chat ID: {telegram_agent.chat_id}")
    
    # Test sending a message
    print("\n📤 Attempting to send test message...")
    message = await telegram_agent.send_message(
        text="<b>🤖 MERID System Test</b>\n\n"
             "This is a test message from the MERID trading engine.\n\n"
             "<i>System Status: OPERATIONAL</i>",
        parse_mode="HTML"
    )
    
    if message:
        print(f"✅ Message sent successfully!")
        print(f"   Message ID: {message.message_id}")
        print(f"   Chat ID: {message.chat_id}")
        return True
    else:
        print("❌ Failed to send message")
        print("   Check Telegram bot token and chat ID")
        return False


async def test_market_alert_integration():
    """Test market alert functionality through both channels."""
    print("\n" + "=" * 60)
    print("TESTING MARKET ALERT INTEGRATION")
    print("=" * 60)
    
    twitter_agent = get_twitter_agent()
    telegram_agent = get_telegram_agent()
    
    # Simulate a market alert
    asset = "BTC"
    price = 67850.00
    change_pct = 5.2
    volume = 28500000000
    
    results = []
    
    # Post to Twitter
    if twitter_agent.enabled:
        print("\n📤 Posting market update to Twitter...")
        tweet = twitter_agent.post_tweet(
            f"📊 {asset} Market Update: ${price:,.2f} (+{change_pct:.1f}%) "
            f"Vol ${volume/1e9:.1f}B #Kalshi #PredictionMarkets"
        )
        if tweet:
            print(f"✅ Twitter alert posted: {tweet.tweet_id}")
            results.append(True)
        else:
            print("❌ Twitter alert failed")
            results.append(False)
    
    # Post to Telegram
    if telegram_agent.enabled:
        print("\n📤 Sending market update to Telegram...")
        message_text = (
            f"<b>🟢 ${asset} Market Update</b>\n\n"
            f"Price: ${price:,.2f}\n"
            f"24h Change: +{change_pct:.2f}%\n"
            f"Volume: ${volume:,.0f}\n\n"
            f"#MERID #Crypto #{asset}"
        )
        message = await telegram_agent.send_message(message_text, parse_mode="HTML")
        if message:
            print(f"✅ Telegram alert sent: {message.message_id}")
            results.append(True)
        else:
            print("❌ Telegram alert failed")
            results.append(False)
    
    return all(results) if results else False


async def main():
    """Run all bot tests."""
    print("\n" + "=" * 60)
    print("MERID SOCIAL BOTS TEST SUITE")
    print("=" * 60)
    print("\nThis script will test both Twitter and Telegram bots.")
    print("Make sure your .env file has the correct credentials.\n")
    
    # Test Twitter
    twitter_ok = await test_twitter_bot()
    
    # Test Telegram
    telegram_ok = await test_telegram_bot()
    
    # Test integrated alerts
    if twitter_ok or telegram_ok:
        integration_ok = await test_market_alert_integration()
    else:
        integration_ok = False
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Twitter Bot:    {'✅ PASSED' if twitter_ok else '❌ FAILED'}")
    print(f"Telegram Bot:   {'✅ PASSED' if telegram_ok else '❌ FAILED'}")
    print(f"Integration:    {'✅ PASSED' if integration_ok else '❌ FAILED'}")
    print("=" * 60)
    
    if twitter_ok and telegram_ok and integration_ok:
        print("\n🎉 ALL TESTS PASSED - Social bots are fully operational!")
    elif twitter_ok or telegram_ok:
        print("\n⚠️  PARTIAL SUCCESS - Some bots are working")
    else:
        print("\n❌ ALL TESTS FAILED - Check your .env configuration")
    
    print("\n")


if __name__ == "__main__":
    asyncio.run(main())
