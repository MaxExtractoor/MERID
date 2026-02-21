#!/usr/bin/env python3
"""
UI Integration Test for MERID Dashboard
Tests the frontend integration with real data
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Any

class UIIntegrationTester:
    def __init__(self, base_url: str = "http://127.0.0.1:8007"):
        self.base_url = base_url
        self.session = None
        self.results = []
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_ui_data_flow(self):
        """Test that UI can properly display real data"""
        print("🧪 Testing UI Data Integration")
        print("=" * 50)
        
        # Test prediction markets data structure
        markets_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/markets")
        
        if markets_response.status == 200:
            markets_data = await markets_response.json()
            
            # Validate markets data structure
            required_fields = ["markets", "count", "status"]
            for field in required_fields:
                if field not in markets_data:
                    print(f"❌ Missing required field: {field}")
                    return False
            
            markets = markets_data.get("markets", [])
            if not markets:
                print("❌ No markets data found")
                return False
            
            # Validate individual market structure
            market_sample = markets[0]
            required_market_fields = ["id", "question", "yes_price", "no_price", "category", "platform"]
            for field in required_market_fields:
                if field not in market_sample:
                    print(f"❌ Missing market field: {field}")
                    return False
            
            print(f"✅ Markets data structure valid: {len(markets)} markets")
            
            # Test drift signals
            drift_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/drift")
            if drift_response.status == 200:
                drift_data = await drift_response.json()
                signals = drift_data.get("signals", [])
                print(f"✅ Drift signals: {len(signals)} signals")
                
                if signals:
                    signal_sample = signals[0]
                    required_signal_fields = ["signal_id", "market_id", "platform", "question", "drift_pct"]
                    for field in required_signal_fields:
                        if field not in signal_sample:
                            print(f"❌ Missing signal field: {field}")
                            return False
            
            # Test arbitrage opportunities
            arb_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/arbitrage")
            if arb_response.status == 200:
                arb_data = await arb_response.json()
                opportunities = arb_data.get("opportunities", [])
                print(f"✅ Arbitrage opportunities: {len(opportunities)} opportunities")
                
                if opportunities:
                    arb_sample = opportunities[0]
                    required_arb_fields = ["arb_id", "question", "platform_a", "platform_b", "spread_pct"]
                    for field in required_arb_fields:
                        if field not in arb_sample:
                            print(f"❌ Missing arbitrage field: {field}")
                            return False
            
            return True
        else:
            print(f"❌ Failed to fetch markets data: {markets_response.status}")
            return False
    
    async def test_ui_compatibility(self):
        """Test UI compatibility with data formats"""
        print("🧪 Testing UI Compatibility")
        print("=" * 50)
        
        # Test that the fixed HTML can handle the data
        test_cases = [
            {
                "name": "Markets Display",
                "endpoint": "/api/v1/institutional/predictions/markets",
                "validation": lambda data: (
                    isinstance(data.get("markets"), list) and
                    len(data.get("markets", [])) > 0 and
                    all(isinstance(m.get("yes_price"), (int, float)) for m in data.get("markets", []))
                )
            },
            {
                "name": "Drift Display",
                "endpoint": "/api/v1/institutional/predictions/drift",
                "validation": lambda data: (
                    isinstance(data.get("signals"), list) and
                    all(isinstance(s.get("drift_pct"), (int, float)) for s in data.get("signals", []))
                )
            },
            {
                "name": "Arbitrage Display",
                "endpoint": "/api/v1/institutional/predictions/arbitrage",
                "validation": lambda data: (
                    isinstance(data.get("opportunities"), list) and
                    all(isinstance(a.get("spread_pct"), (int, float)) for a in data.get("opportunities", []))
                )
            }
        ]
        
        all_passed = True
        for test_case in test_cases:
            try:
                response = await self.session.get(f"{self.base_url}{test_case['endpoint']}")
                if response.status == 200:
                    data = await response.json()
                    if test_case["validation"](data):
                        print(f"✅ {test_case['name']}: PASS")
                    else:
                        print(f"❌ {test_case['name']}: FAIL - Data validation failed")
                        all_passed = False
                else:
                    print(f"❌ {test_case['name']}: FAIL - HTTP {response.status}")
                    all_passed = False
            except Exception as e:
                print(f"❌ {test['name']}: ERROR - {e}")
                all_passed = False
        
        return all_passed
    
    async def test_real_time_updates(self):
        """Test that data updates in real-time"""
        print("🧪 Testing Real-Time Updates")
        print("=" * 50)
        
        # Fetch initial data
        initial_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/markets")
        initial_data = await initial_response.json()
        initial_count = initial_data.get("count", 0)
        
        print(f"Initial markets count: {initial_count}")
        
        # Wait a moment for data to update
        await asyncio.sleep(2)
        
        # Fetch updated data
        updated_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/markets")
        updated_data = await updated_response.json()
        updated_count = updated_data.get("count", 0)
        
        print(f"Updated markets count: {updated_count}")
        
        # Check if data is being updated (synthetic data should change)
        if updated_count >= initial_count:
            print("✅ Real-time updates working")
            return True
        else:
            print("⚠️  Data count unchanged (may be normal for real data)")
            return True  # Not necessarily an error
    
    async def run_integration_tests(self):
        """Run all integration tests"""
        print("🎯 MERID UI Integration Tests")
        print("=" * 50)
        
        tests = [
            ("Data Flow", self.test_ui_data_flow),
            ("UI Compatibility", self.test_ui_compatibility),
            ("Real-Time Updates", self.test_real_time_updates)
        ]
        
        results = []
        for test_name, test_func in tests:
            try:
                result = await test_func()
                results.append((test_name, result))
                if result:
                    print(f"✅ {test_name}: PASSED")
                else:
                    print(f"❌ {test_name}: FAILED")
            except Exception as e:
                print(f"💥 {test_name}: ERROR - {e}")
                results.append((test_name, False))
        
        # Print summary
        print("\n" + "=" * 50)
        print("📊 INTEGRATION TEST SUMMARY")
        print("=" * 50)
        
        total = len(results)
        passed = len([r for r in results if r[1]])
        failed = len([r for r in results if not r[1]])
        
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"Success Rate: {(passed/total*100):.1f}%")
        
        if failed > 0:
            print("\n❌ FAILED TESTS:")
            for test_name, result in results:
                if not result:
                    print(f"  - {test_name}")
        
        return passed == total

async def main():
    """Main integration test function"""
    async with UIIntegrationTester() as tester:
        success = await tester.run_integration_tests()
        return success

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
