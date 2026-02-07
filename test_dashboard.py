#!/usr/bin/env python3
"""
Test script for MERID Dashboard APIs
Tests all endpoints to ensure data flows correctly
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Any

class DashboardTester:
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
    
    async def test_endpoint(self, endpoint: str, name: str) -> Dict[str, Any]:
        """Test a single API endpoint"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            async with self.session.get(url) as response:
                elapsed = time.time() - start_time
                
                if response.status == 200:
                    data = await response.json()
                    result = {
                        "endpoint": endpoint,
                        "name": name,
                        "status": "PASS",
                        "status_code": response.status,
                        "response_time": elapsed,
                        "data_keys": list(data.keys()) if isinstance(data, dict) else [],
                        "data_size": len(str(data)),
                        "sample_data": data
                    }
                    print(f"✅ {name}: {response.status} ({elapsed:.2f}s)")
                else:
                    result = {
                        "endpoint": endpoint,
                        "name": name,
                        "status": "FAIL",
                        "status_code": response.status,
                        "response_time": elapsed,
                        "error": f"HTTP {response.status}"
                    }
                    print(f"❌ {name}: {response.status} ({elapsed:.2f}s)")
                
                self.results.append(result)
                return result
                
        except Exception as e:
            elapsed = time.time() - start_time
            result = {
                "endpoint": endpoint,
                "name": name,
                "status": "ERROR",
                "response_time": elapsed,
                "error": str(e)
            }
            print(f"💥 {name}: ERROR ({elapsed:.2f}s) - {e}")
            self.results.append(result)
            return result
    
    async def run_tests(self):
        """Run all dashboard tests"""
        print("🧪 Testing MERID Dashboard APIs")
        print("=" * 50)
        
        # Test prediction markets endpoints
        await self.test_endpoint("/api/v1/institutional/predictions/markets", "Prediction Markets")
        await self.test_endpoint("/api/v1/institutional/predictions/drift", "Drift Signals")
        await self.test_endpoint("/api/v1/institutional/predictions/arbitrage", "Arbitrage Opportunities")
        
        # Test system endpoints
        await self.test_endpoint("/api/v1/institutional/systems/status", "Systems Status")
        await self.test_endpoint("/api/v1/institutional/risk/summary", "Risk Summary")
        await self.test_endpoint("/api/v1/institutional/shadow/divergence", "Shadow Divergence")
        
        # Test intelligence endpoints
        await self.test_endpoint("/api/v1/intelligence/news?limit=5", "Intelligence News")
        
        # Test agent endpoints
        await self.test_endpoint("/api/v1/agents/status", "Agent Status")
        
        # Test consensus endpoints
        await self.test_endpoint("/api/v1/governance/consensus/status", "Consensus Status")
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 50)
        print("📊 TEST SUMMARY")
        print("=" * 50)
        
        total = len(self.results)
        passed = len([r for r in self.results if r["status"] == "PASS"])
        failed = len([r for r in self.results if r["status"] == "FAIL"])
        errors = len([r for r in self.results if r["status"] == "ERROR"])
        
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {failed}")
        print(f"💥 Errors: {errors}")
        print(f"Success Rate: {(passed/total*100):.1f}%")
        
        if failed > 0 or errors > 0:
            print("\n❌ FAILED TESTS:")
            for result in self.results:
                if result["status"] in ["FAIL", "ERROR"]:
                    print(f"  - {result['name']}: {result.get('error', 'Unknown error')}")
        
        # Show data samples for successful tests
        print("\n📄 DATA SAMPLES:")
        for result in self.results:
            if result["status"] == "PASS" and "sample_data" in result:
                print(f"\n{result['name']}:")
                sample = result["sample_data"]
                if isinstance(sample, dict):
                    if "markets" in sample:
                        markets = sample["markets"]
                        print(f"  Markets: {len(markets)}")
                        if markets:
                            print(f"  Sample Market: {markets[0].get('question', 'N/A')[:50]}...")
                    if "signals" in sample:
                        signals = sample["signals"]
                        print(f"  Drift Signals: {len(signals)}")
                    if "opportunities" in sample:
                        opportunities = sample["opportunities"]
                        print(f"  Arbitrage Ops: {len(opportunities)}")
                print(f"  Response Time: {result['response_time']:.2f}s")
        
        return passed == total

async def main():
    """Main test function"""
    async with DashboardTester() as tester:
        success = await tester.run_tests()
        return success

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
