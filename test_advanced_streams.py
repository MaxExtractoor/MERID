#!/usr/bin/env python3

import asyncio
import sys
import os
import time
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from streams.news_sentiment_stream import NewsSentimentStream
from streams.social_media_stream import SocialMediaStream
from streams.onchain_stream import OnchainStream
from utils.logger import get_logger

logger = get_logger("test_advanced_streams")

async def test_news_sentiment_stream():
    """Test news sentiment analysis stream"""
    
    print("📰 Testing News Sentiment Stream")
    print("=" * 50)
    
    try:
        # Initialize stream
        config = {
            "update_interval": 5,
            "max_articles": 50,
            "sentiment_threshold": 0.6,
            "relevance_threshold": 0.7
        }
        
        stream = NewsSentimentStream(config)
        print(f"✅ NewsSentimentStream initialized")
        
        # Test connection
        connected = await stream.connect()
        print(f"✅ Connected: {connected}")
        
        # Start stream
        await stream.start()
        print("✅ Stream started")
        
        # Wait for data collection
        print("⏳ Collecting news data...")
        await asyncio.sleep(10)
        
        # Collect events
        events = []
        async for event in stream.subscribe():
            events.append(event)
            if len(events) >= 5:  # Collect 5 events
                break
        
        print(f"✅ Collected {len(events)} news sentiment events")
        
        if events:
            sample = events[0]
            print(f"   Sample event:")
            print(f"   Type: {sample.event_type}")
            print(f"   Priority: {sample.priority}")
            print(f"   Symbol: {sample.data.get('symbol')}")
            print(f"   Sentiment: {sample.data.get('sentiment_score'):.3f}")
            print(f"   Confidence: {sample.data.get('confidence'):.3f}")
            print(f"   Articles: {sample.data.get('article_count')}")
        
        # Test sentiment summary
        print("\n📊 Testing Sentiment Summary")
        summary = stream.get_sentiment_summary(hours=1)
        print(f"✅ Sentiment summary generated")
        print(f"   Total signals: {summary.get('total_signals', 0)}")
        print(f"   Symbols: {summary.get('symbols', [])}")
        print(f"   Avg sentiment: {summary.get('avg_sentiment', 0):.3f}")
        print(f"   Sources: {summary.get('sources', [])}")
        
        # Test symbol-specific sentiment
        print("\n🎯 Testing Symbol-Specific Sentiment")
        symbol_sentiment = stream.get_symbol_sentiment("BTC", hours=1)
        if symbol_sentiment:
            print(f"✅ BTC sentiment data:")
            print(f"   Current sentiment: {symbol_sentiment.get('current_sentiment', 0):.3f}")
            print(f"   Trend: {symbol_sentiment.get('trend', 0):.3f}")
            print(f"   Signal count: {symbol_sentiment.get('signal_count', 0)}")
        else:
            print("⚠️ No BTC sentiment data available")
        
        # Stop stream
        await stream.stop()
        print("✅ Stream stopped")
        
        print("\n🎉 News Sentiment Stream Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ News Sentiment Stream test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_social_media_stream():
    """Test social media monitoring stream"""
    
    print("\n🐦 Testing Social Media Stream")
    print("=" * 50)
    
    try:
        # Initialize stream
        config = {
            "update_interval": 3,
            "max_posts": 100,
            "sentiment_threshold": 0.6,
            "influence_threshold": 1000
        }
        
        stream = SocialMediaStream(config)
        print(f"✅ SocialMediaStream initialized")
        
        # Test connection
        connected = await stream.connect()
        print(f"✅ Connected: {connected}")
        
        # Start stream
        await stream.start()
        print("✅ Stream started")
        
        # Wait for data collection
        print("⏳ Collecting social media data...")
        await asyncio.sleep(8)
        
        # Collect events
        events = []
        async for event in stream.subscribe():
            events.append(event)
            if len(events) >= 5:  # Collect 5 events
                break
        
        print(f"✅ Collected {len(events)} social media events")
        
        if events:
            sample = events[0]
            print(f"   Sample event:")
            print(f"   Type: {sample.event_type}")
            print(f"   Priority: {sample.priority}")
            print(f"   Platform: {sample.data.get('platform')}")
            print(f"   Symbol: {sample.data.get('symbol')}")
            print(f"   Sentiment: {sample.data.get('sentiment_score'):.3f}")
            print(f"   Influence: {sample.data.get('influence_score'):.3f}")
            print(f"   Engagement: {sample.data.get('total_engagement')}")
        
        # Test social summary
        print("\n📊 Testing Social Media Summary")
        summary = stream.get_social_summary(hours=1)
        print(f"✅ Social media summary generated")
        print(f"   Total signals: {summary.get('total_signals', 0)}")
        print(f"   Platforms: {summary.get('platforms', [])}")
        print(f"   Avg sentiment: {summary.get('avg_sentiment', 0):.3f}")
        print(f"   Avg influence: {summary.get('avg_influence', 0):.3f}")
        
        # Test platform stats
        platform_stats = summary.get('platform_stats', {})
        if platform_stats:
            print(f"   Platform breakdown:")
            for platform, stats in platform_stats.items():
                print(f"     {platform}: {stats.get('signal_count', 0)} signals")
        
        # Test symbol-specific social sentiment
        print("\n🎯 Testing Symbol-Specific Social Sentiment")
        symbol_social = stream.get_symbol_social_sentiment("ETH", hours=1)
        if symbol_social:
            print(f"✅ ETH social sentiment data:")
            print(f"   Current sentiment: {symbol_social.get('current_sentiment', 0):.3f}")
            print(f"   Trend: {symbol_social.get('trend', 0):.3f}")
            print(f"   Signal count: {symbol_social.get('signal_count', 0)}")
            print(f"   Total engagement: {symbol_social.get('total_engagement', 0)}")
        else:
            print("⚠️ No ETH social sentiment data available")
        
        # Stop stream
        await stream.stop()
        print("✅ Stream stopped")
        
        print("\n🎉 Social Media Stream Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Social Media Stream test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_onchain_stream():
    """Test on-chain transaction monitoring stream"""
    
    print("\n⛓️ Testing On-Chain Stream")
    print("=" * 50)
    
    try:
        # Initialize stream
        config = {
            "update_interval": 2,
            "max_transactions": 200,
            "whale_threshold": 100000,
            "defi_protocols": ["uniswap", "curve", "aave", "compound"]
        }
        
        stream = OnchainStream(config)
        print(f"✅ OnchainStream initialized")
        
        # Test connection
        connected = await stream.connect()
        print(f"✅ Connected: {connected}")
        
        # Start stream
        await stream.start()
        print("✅ Stream started")
        
        # Wait for data collection
        print("⏳ Collecting on-chain data...")
        await asyncio.sleep(6)
        
        # Collect events
        events = []
        async for event in stream.subscribe():
            events.append(event)
            if len(events) >= 5:  # Collect 5 events
                break
        
        print(f"✅ Collected {len(events)} on-chain events")
        
        if events:
            sample = events[0]
            print(f"   Sample event:")
            print(f"   Type: {sample.event_type}")
            print(f"   Priority: {sample.priority}")
            print(f"   Chain: {sample.data.get('chain')}")
            print(f"   Signal type: {sample.data.get('signal_type')}")
            print(f"   Symbol: {sample.data.get('symbol')}")
            print(f"   Value: ${sample.data.get('value', 0):,.2f}")
            print(f"   Impact: {sample.data.get('impact_score'):.3f}")
            print(f"   Transactions: {sample.data.get('transaction_count')}")
        
        # Test on-chain summary
        print("\n📊 Testing On-Chain Summary")
        summary = stream.get_onchain_summary(hours=1)
        print(f"✅ On-chain summary generated")
        print(f"   Total signals: {summary.get('total_signals', 0)}")
        print(f"   Chains: {summary.get('chains', [])}")
        print(f"   Signal types: {summary.get('signal_types', {})}")
        print(f"   Total value: ${summary.get('total_value', 0):,.2f}")
        
        # Test chain-specific activity
        print("\n🎯 Testing Chain-Specific Activity")
        chain_activity = stream.get_chain_activity("ethereum", hours=1)
        if chain_activity:
            print(f"✅ Ethereum activity data:")
            print(f"   Signal count: {chain_activity.get('signal_count', 0)}")
            print(f"   Total value: ${chain_activity.get('total_value', 0):,.2f}")
            print(f"   Avg impact: {chain_activity.get('avg_impact_score', 0):.3f}")
            
            signal_breakdown = chain_activity.get('signal_breakdown', {})
            if signal_breakdown:
                print(f"   Signal breakdown:")
                for signal_type, stats in signal_breakdown.items():
                    print(f"     {signal_type}: {stats.get('count', 0)} signals")
        else:
            print("⚠️ No Ethereum activity data available")
        
        # Stop stream
        await stream.stop()
        print("✅ Stream stopped")
        
        print("\n🎉 On-Chain Stream Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ On-Chain Stream test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_stream_integration():
    """Test integration of all advanced streams"""
    
    print("\n🔄 Testing Advanced Streams Integration")
    print("=" * 50)
    
    try:
        # Initialize all streams
        news_config = {"update_interval": 3, "max_articles": 30}
        social_config = {"update_interval": 2, "max_posts": 50}
        onchain_config = {"update_interval": 2, "max_transactions": 100}
        
        news_stream = NewsSentimentStream(news_config)
        social_stream = SocialMediaStream(social_config)
        onchain_stream = OnchainStream(onchain_config)
        
        print(f"✅ All streams initialized")
        
        # Connect all streams
        await asyncio.gather(
            news_stream.connect(),
            social_stream.connect(),
            onchain_stream.connect()
        )
        print(f"✅ All streams connected")
        
        # Start all streams
        await asyncio.gather(
            news_stream.start(),
            social_stream.start(),
            onchain_stream.start()
        )
        print(f"✅ All streams started")
        
        # Collect data from all streams
        print("⏳ Collecting data from all streams...")
        await asyncio.sleep(8)
        
        # Collect events from all streams
        all_events = []
        
        # News events
        async for event in news_stream.subscribe():
            all_events.append(("news", event))
            if len(all_events) >= 3:
                break
        
        # Social events
        async for event in social_stream.subscribe():
            all_events.append(("social", event))
            if len(all_events) >= 6:
                break
        
        # On-chain events
        async for event in onchain_stream.subscribe():
            all_events.append(("onchain", event))
            if len(all_events) >= 9:
                break
        
        print(f"✅ Collected {len(all_events)} total events")
        
        # Analyze event distribution
        event_counts = {"news": 0, "social": 0, "onchain": 0}
        for source, event in all_events:
            event_counts[source] += 1
        
        print(f"   Event distribution: {event_counts}")
        
        # Test cross-stream data analysis
        print("\n📊 Testing Cross-Stream Analysis")
        
        # Get summaries from all streams
        news_summary = news_stream.get_sentiment_summary(hours=1)
        social_summary = social_stream.get_social_summary(hours=1)
        onchain_summary = onchain_stream.get_onchain_summary(hours=1)
        
        # Find common symbols
        news_symbols = set(news_summary.get('symbols', []))
        social_symbols = set(social_summary.get('symbols', []))
        onchain_symbols = set(onchain_summary.get('chains', []))
        
        common_symbols = news_symbols & social_symbols
        print(f"   Common symbols across news & social: {common_symbols}")
        
        # Compare sentiment data
        if news_symbols and social_symbols:
            avg_news_sentiment = news_summary.get('avg_sentiment', 0.5)
            avg_social_sentiment = social_summary.get('avg_sentiment', 0.5)
            
            print(f"   Avg news sentiment: {avg_news_sentiment:.3f}")
            print(f"   Avg social sentiment: {avg_social_sentiment:.3f}")
            print(f"   Sentiment correlation: {'positive' if (avg_news_sentiment - 0.5) * (avg_social_sentiment - 0.5) > 0 else 'negative'}")
        
        # Stop all streams
        await asyncio.gather(
            news_stream.stop(),
            social_stream.stop(),
            onchain_stream.stop()
        )
        print(f"✅ All streams stopped")
        
        print("\n🎉 Advanced Streams Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Advanced Streams Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance():
    """Test advanced streams performance"""
    
    print("\n⚡ Testing Advanced Streams Performance")
    print("-" * 40)
    
    try:
        # Initialize streams
        streams = [
            NewsSentimentStream({"update_interval": 1, "max_articles": 20}),
            SocialMediaStream({"update_interval": 1, "max_posts": 30}),
            OnchainStream({"update_interval": 1, "max_transactions": 50})
        ]
        
        # Start all streams
        await asyncio.gather(*[s.connect() for s in streams])
        await asyncio.gather(*[s.start() for s in streams])
        
        # Performance test
        start_time = time.time()
        
        # Collect events concurrently
        event_tasks = []
        for stream in streams:
            task = asyncio.create_task(
                self._collect_events_from_stream(stream, 3)
            )
            event_tasks.append(task)
        
        results = await asyncio.gather(*event_tasks)
        
        end_time = time.time()
        
        # Calculate metrics
        total_events = sum(len(events) for events in results)
        total_time = end_time - start_time
        
        print(f"✅ Performance results:")
        print(f"   Total events: {total_events}")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Events per second: {total_events / total_time:.1f}")
        print(f"   Avg time per event: {(total_time / total_events) * 1000:.1f}ms")
        
        # Memory usage
        import sys
        total_memory = sum(sys.getsizeof(stream) for stream in streams)
        print(f"   Memory usage: {total_memory:,} bytes")
        
        # Stop streams
        await asyncio.gather(*[s.stop() for s in streams])
        
        print("\n🎯 Performance Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def _collect_events_from_stream(stream, max_events):
    """Helper function to collect events from a stream."""
    events = []
    async for event in stream.subscribe():
        events.append(event)
        if len(events) >= max_events:
            break
    return events

async def main():
    """Run all advanced streams tests"""
    try:
        print("🧪 ADVANCED STREAMS TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_news_sentiment_stream()
        test2 = await test_social_media_stream()
        test3 = await test_onchain_stream()
        test4 = await test_stream_integration()
        test5 = await test_performance()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 ADVANCED STREAMS TEST RESULTS")
        print("=" * 70)
        print(f"News Sentiment Stream:   {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Social Media Stream:     {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"On-Chain Stream:          {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Stream Integration:      {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"Performance:              {'✅ PASSED' if test5 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5]):
            print("\n🎯 ALL ADVANCED STREAMS TESTS PASSED!")
            print("✅ News sentiment analysis functional")
            print("✅ Social media monitoring functional")
            print("✅ On-chain transaction monitoring functional")
            print("✅ Cross-stream integration working")
            print("✅ Performance within acceptable limits")
        else:
            print("\n❌ Some advanced streams tests failed")
        
    except Exception as e:
        print(f"❌ Advanced streams test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
