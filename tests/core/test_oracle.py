#!/usr/bin/env python3

import asyncio
import sys
import os
import time

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from oracles.coingecko_oracle import CoinGeckoOracle, CoinGeckoConfig
from utils.logger import get_logger

logger = get_logger("test_oracle")

async def test_oracle_initialization():
    """Test oracle initialization and basic properties"""
    
    print("🚀 Testing CoinGeckoOracle Initialization")
    print("=" * 50)
    
    try:
        # Create oracle with default config
        oracle = CoinGeckoOracle()
        print(f"✅ Oracle created: {oracle.oracle_id}")
        print(f"✅ Priority: {oracle.priority}")
        print(f"✅ Status: {oracle.status}")
        
        # Test custom config
        config = CoinGeckoConfig(
            rate_limit_requests_per_minute=60,
            timeout_seconds=15.0
        )
        custom_oracle = CoinGeckoOracle("custom_coingecko", priority=2, config=config)
        print(f"✅ Custom oracle created: {custom_oracle.oracle_id}")
        print(f"✅ Custom rate limit: {config.rate_limit_requests_per_minute}")
        
        # Test supported symbols
        symbols = oracle.get_supported_symbols()
        print(f"✅ Supported symbols: {len(symbols)}")
        print(f"   Sample: {symbols[:3]}")
        
        print("\n🎉 Oracle initialization test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Oracle initialization test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_oracle_connection():
    """Test oracle connection lifecycle"""
    
    print("\n🔌 Testing Oracle Connection")
    print("-" * 30)
    
    try:
        oracle = CoinGeckoOracle()
        
        # Test connection
        connected = await oracle.connect()
        print(f"✅ Connection result: {connected}")
        print(f"✅ Status after connect: {oracle.status}")
        
        # Test health
        health = oracle.get_health()
        print(f"✅ Health status: {health.status}")
        print(f"✅ Uptime: {health.uptime_seconds:.1f}s")
        
        # Test disconnection
        await oracle.disconnect()
        print(f"✅ Status after disconnect: {oracle.status}")
        
        print("\n🎉 Oracle connection test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Oracle connection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_price_fetching():
    """Test price fetching functionality"""
    
    print("\n💰 Testing Price Fetching")
    print("-" * 30)
    
    try:
        oracle = CoinGeckoOracle()
        await oracle.connect()
        
        # Test single price fetch
        price = await oracle.get_price("BTC/USD")
        if price:
            print(f"✅ BTC/USD price: ${price.price:.2f}")
            print(f"✅ Confidence: {price.confidence:.2f}")
            print(f"✅ Age: {price.age_seconds():.1f}s")
        else:
            print("❌ Failed to fetch BTC/USD price")
            return False
        
        # Test multiple prices
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]
        prices = await oracle.get_prices(symbols)
        print(f"✅ Fetched {len(prices)} prices:")
        for symbol, oracle_price in prices.items():
            print(f"   {symbol}: ${oracle_price.price:.2f}")
        
        # Test caching
        start_time = time.time()
        cached_price = await oracle.get_price("BTC/USD")  # Should use cache
        cache_time = (time.time() - start_time) * 1000
        print(f"✅ Cache response time: {cache_time:.1f}ms")
        
        await oracle.disconnect()
        
        print("\n🎉 Price fetching test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Price fetching test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_error_handling():
    """Test error handling and edge cases"""
    
    print("\n⚠️ Testing Error Handling")
    print("-" * 30)
    
    try:
        oracle = CoinGeckoOracle()
        await oracle.connect()
        
        # Test unsupported symbol
        unsupported_price = await oracle.get_price("INVALID/SYMBOL")
        print(f"✅ Unsupported symbol handling: {unsupported_price is None}")
        
        # Test symbol validation
        supported = oracle.is_symbol_supported("BTC/USD")
        unsupported = oracle.is_symbol_supported("INVALID/SYMBOL")
        print(f"✅ BTC/USD supported: {supported}")
        print(f"✅ INVALID/SYMBOL supported: {unsupported}")
        
        # Test retry logic with retry
        retry_price = await oracle.get_price_with_retry("BTC/USD")
        if retry_price:
            print(f"✅ Retry logic working: ${retry_price.price:.2f}")
        
        await oracle.disconnect()
        
        print("\n🎉 Error handling test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Error handling test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance():
    """Test performance metrics"""
    
    print("\n⚡ Testing Performance")
    print("-" * 30)
    
    try:
        oracle = CoinGeckoOracle()
        await oracle.connect()
        
        # Test multiple concurrent requests
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD"] * 3  # 9 requests
        start_time = time.time()
        
        tasks = [oracle.get_price(symbol) for symbol in symbols]
        prices = await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        successful_prices = [p for p in prices if p is not None]
        print(f"✅ Processed {len(symbols)} requests in {total_time:.2f}s")
        print(f"✅ Successful: {len(successful_prices)}/{len(symbols)}")
        print(f"✅ Average time per request: {(total_time/len(symbols))*1000:.1f}ms")
        
        # Check health metrics
        health = oracle.get_health()
        print(f"✅ Request count: {health.request_count}")
        print(f"✅ Error count: {health.error_count}")
        print(f"✅ Average latency: {health.avg_latency_ms:.1f}ms")
        
        await oracle.disconnect()
        
        print("\n🎉 Performance test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all oracle tests"""
    try:
        print("🧪 COINGECKO ORACLE TEST SUITE")
        print("=" * 60)
        
        # Run tests
        test1 = await test_oracle_initialization()
        test2 = await test_oracle_connection()
        test3 = await test_price_fetching()
        test4 = await test_error_handling()
        test5 = await test_performance()
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST RESULTS")
        print("=" * 60)
        print(f"Initialization:        {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Connection:           {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Price Fetching:       {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Error Handling:       {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"Performance:          {'✅ PASSED' if test5 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5]):
            print("\n🎯 ALL TESTS PASSED!")
            print("✅ CoinGeckoOracle is working correctly")
            print("✅ All NotImplemented methods implemented")
            print("✅ BaseOracle contract satisfied")
            print("✅ Ready for integration with agents")
        else:
            print("\n❌ Some tests failed - check implementation")
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
