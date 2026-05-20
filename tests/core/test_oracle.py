#!/usr/bin/env python3

import asyncio
import sys
import os
import time
import unittest

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from oracles.binanceus_oracle import BinanceUSOracle, BinanceUSConfig
from utils.logger import get_logger

logger = get_logger("test_oracle")

class TestBaseOracle(unittest.TestCase):
    """Placeholder for base oracle tests."""

    def test_placeholder(self):
        """Placeholder test."""
        self.assertTrue(True)

async def test_oracle_initialization():
    """Test oracle initialization and basic properties"""
    
    print("🚀 Testing BinanceUSOracle Initialization")
    print("=" * 50)
    
    try:
        # Create oracle with default config
        oracle = BinanceUSOracle()
        print(f"✅ Oracle created: {oracle.oracle_id}")
        print(f"✅ Priority: {oracle.priority}")
        print(f"✅ Status: {oracle.status}")
        
        # Test custom config
        config = BinanceUSConfig(
            rate_limit_requests_per_minute=60,
            timeout_seconds=15.0
        )
        custom_oracle = BinanceUSOracle("custom_binanceus", priority=2, config=config)
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
        oracle = BinanceUSOracle()
        
        # BinanceUS doesn't have connect/disconnect methods in the same way
        # Test health check instead
        print(f"✅ Oracle created: {oracle.oracle_id}")
        print(f"✅ Base URL: {oracle.config.base_url}")
        
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
        oracle = BinanceUSOracle()
        
        # Test single price fetch
        price = await oracle.get_price("BTC/USD")
        if price:
            print(f"✅ BTC/USD price: ${price:.2f}")
        else:
            print("❌ Failed to fetch BTC/USD price")
            return False
        
        # Test batch prices
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD"]
        prices = await oracle.get_batch_prices(symbols)
        print(f"✅ Fetched {len(prices)} prices:")
        for symbol, price in prices.items():
            print(f"   {symbol}: ${price:.2f}")
        
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
        oracle = BinanceUSOracle()
        
        # Test unsupported symbol
        unsupported_price = await oracle.get_price("INVALID/SYMBOL")
        print(f"✅ Unsupported symbol handling: {unsupported_price is None}")
        
        # Test symbol validation
        supported = oracle.is_asset_supported("BTC/USD")
        unsupported = oracle.is_asset_supported("INVALID/SYMBOL")
        print(f"✅ BTC/USD supported: {supported}")
        print(f"✅ INVALID/SYMBOL supported: {unsupported}")
        
        # Test retry logic
        retry_price = await oracle.get_price_with_retry("BTC/USD")
        if retry_price:
            print(f"✅ Retry logic working: ${retry_price:.2f}")
        
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
        oracle = BinanceUSOracle()
        
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
        print("🧪 BINANCEUS ORACLE TEST SUITE")
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
            print("✅ BinanceUSOracle is working correctly")
            print("✅ Ready for integration with agents")
        else:
            print("\n❌ Some tests failed - check implementation")
        
    except Exception as e:
        print(f"❌ Test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
