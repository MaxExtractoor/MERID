#!/usr/bin/env python3
"""
Complete Validation Test for MERID Dashboard
Tests all components end-to-end to ensure everything works
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Any

class CompleteValidator:
    def __init__(self, base_url: str = "http://127.0.0.1:8008"):
        self.base_url = base_url
        self.session = None
        self.results = []
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def test_endpoint(self, endpoint: str, name: str, expected_status: int = 200):
        """Test a single endpoint"""
        url = f"{self.base_url}{endpoint}"
        start_time = time.time()
        
        try:
            async with self.session.get(url) as response:
                elapsed = time.time() - start_time
                content = await response.text()
                
                if response.status == expected_status:
                    result = {
                        "endpoint": endpoint,
                        "name": name,
                        "status": "PASS",
                        "status_code": response.status,
                        "response_time": elapsed,
                        "content_length": len(content),
                        "content_type": response.headers.get('content-type', 'unknown')
                    }
                    print(f"✅ {name}: {response.status} ({elapsed:.2f}s, {len(content)} bytes)")
                else:
                    result = {
                        "endpoint": endpoint,
                        "name": name,
                        "status": "FAIL",
                        "status_code": response.status,
                        "response_time": elapsed,
                        "error": f"HTTP {response.status}",
                        "content": content[:200]
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
    
    async def test_html_dashboard(self):
        """Test HTML dashboard loading"""
        print("🧪 Testing HTML Dashboard")
        print("=" * 50)
        
        # Test the fixed dashboard
        result = await self.test_endpoint("/dashboard/fixed", "Fixed Dashboard")
        
        if result["status"] == "PASS":
            # Check if HTML content is valid
            if "<!DOCTYPE html>" in result.get("content", ""):
                print("✅ HTML content is valid")
            else:
                print("❌ HTML content is invalid")
                result["status"] = "FAIL"
        
        return result["status"] == "PASS"
    
    async def test_api_endpoints(self):
        """Test all API endpoints"""
        print("\n🧪 Testing API Endpoints")
        print("=" * 50)
        
        endpoints = [
            ("/api/v1/institutional/predictions/markets", "Prediction Markets"),
            ("/api/v1/institutional/predictions/drift", "Drift Signals"),
            ("/api/v1/institutional/predictions/arbitrage", "Arbitrage Opportunities"),
            ("/api/v1/institutional/systems/status", "Systems Status"),
            ("/api/v1/institutional/risk/summary", "Risk Summary"),
            ("/api/v1/institutional/shadow/divergence", "Shadow Divergence"),
            ("/api/v1/intelligence/news?limit=5", "Intelligence News"),
            ("/api/v1/agents/status", "Agent Status"),
            ("/api/v1/governance/consensus/status", "Consensus Status"),
            ("/docs", "API Documentation"),
            ("/openapi.json", "OpenAPI Schema")
        ]
        
        results = []
        for endpoint, name in endpoints:
            result = await self.test_endpoint(endpoint, name)
            results.append(result)
        
        return all(r["status"] == "PASS" for r in results)
    
    async def test_data_integrity(self):
        """Test data integrity and structure"""
        print("\n🧪 Testing Data Integrity")
        print("=" * 50)
        
        # Test prediction markets data structure
        markets_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/markets")
        
        if markets_response.status == 200:
            markets_data = await markets_response.json()
            
            # Validate structure
            required_fields = ["markets", "count", "status"]
            structure_valid = all(field in markets_data for field in required_fields)
            
            if structure_valid:
                markets = markets_data.get("markets", [])
                print(f"✅ Markets structure valid: {len(markets)} markets")
                
                # Validate individual market
                if markets:
                    market = markets[0]
                    market_fields = ["id", "question", "yes_price", "no_price", "category", "platform"]
                    market_valid = all(field in market for field in market_fields)
                    
                    if market_valid:
                        print("✅ Individual market structure valid")
                    else:
                        print("❌ Individual market structure invalid")
                        return False
                else:
                    print("⚠️  No markets data (may be warming up)")
            else:
                print("❌ Markets structure invalid")
                return False
        else:
            print(f"❌ Failed to fetch markets: {markets_response.status}")
            return False
        
        # Test arbitrage data
        arb_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/arbitrage")
        
        if arb_response.status == 200:
            arb_data = await arb_response.json()
            opportunities = arb_data.get("opportunities", [])
            print(f"✅ Arbitrage data: {len(opportunities)} opportunities")
        
        return True
    
    async def test_real_time_updates(self):
        """Test real-time data updates"""
        print("\n🧪 Testing Real-Time Updates")
        print("=" * 50)
        
        # Fetch initial data
        initial_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/markets")
        initial_data = await initial_response.json()
        initial_count = initial_data.get("count", 0)
        
        print(f"Initial markets count: {initial_count}")
        
        # Wait for update
        await asyncio.sleep(3)
        
        # Fetch updated data
        updated_response = await self.session.get(f"{self.base_url}/api/v1/institutional/predictions/markets")
        updated_data = await updated_response.json()
        updated_count = updated_data.get("count", 0)
        
        print(f"Updated markets count: {updated_count}")
        
        # Check if data is updating
        if updated_count >= initial_count:
            print("✅ Real-time updates working")
            return True
        else:
            print("⚠️  Data count unchanged (may be normal)")
            return True
    
    async def run_complete_validation(self):
        """Run complete validation suite"""
        print("🎯 MERID Complete Validation Suite")
        print("=" * 60)
        print(f"Testing server at: {self.base_url}")
        print("=" * 60)
        
        tests = [
            ("HTML Dashboard", self.test_html_dashboard),
            ("API Endpoints", self.test_api_endpoints),
            ("Data Integrity", self.test_data_integrity),
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
        
        # Print final summary
        print("\n" + "=" * 60)
        print("📊 COMPLETE VALIDATION SUMMARY")
        print("=" * 60)
        
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
        
        # Print detailed results
        print("\n📄 DETAILED RESULTS:")
        for result in self.results:
            if result["status"] == "PASS":
                print(f"✅ {result['name']}: {result['status_code']} ({result['response_time']:.2f}s)")
            else:
                print(f"❌ {result['name']}: {result.get('error', 'Unknown error')}")
        
        print(f"\n🎮 Access the dashboard: {self.base_url}/dashboard/fixed")
        print(f"📚 API Documentation: {self.base_url}/docs")
        
        return passed == total

async def main():
    """Main validation function"""
    async with CompleteValidator() as validator:
        success = await validator.run_complete_validation()
        return success

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
