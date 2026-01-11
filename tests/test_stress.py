"""
Stress test for MERID trading system.

Tests system under load with concurrent requests.
"""

import asyncio
import time
from typing import List

import httpx
import pytest

BASE_URL = "http://127.0.0.1:8001"


class TestStressLoad:
    """Stress test suite."""
    
    @pytest.mark.asyncio
    async def test_concurrent_api_requests(self):
        """Test concurrent API requests."""
        async with httpx.AsyncClient() as client:
            tasks = []
            
            # Create 50 concurrent health check requests
            for _ in range(50):
                tasks.append(client.get(f"{BASE_URL}/api/v1/health"))
            
            start_time = time.time()
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            duration = time.time() - start_time
            
            # Check success rate
            successful = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
            success_rate = successful / len(responses) * 100
            
            print(f"\n✅ Concurrent requests: {len(responses)}")
            print(f"✅ Successful: {successful} ({success_rate:.1f}%)")
            print(f"✅ Duration: {duration:.2f}s")
            print(f"✅ Avg response time: {duration/len(responses)*1000:.2f}ms")
            
            assert success_rate >= 95, f"Success rate too low: {success_rate}%"
    
    @pytest.mark.asyncio
    async def test_paper_trading_stress(self):
        """Test paper trading under load."""
        async with httpx.AsyncClient() as client:
            user_id = "stress_test_user"
            
            # Place 20 concurrent paper trades
            tasks = []
            for i in range(20):
                order_data = {
                    "user_id": user_id,
                    "asset": "BTC" if i % 2 == 0 else "ETH",
                    "side": "long" if i % 2 == 0 else "short",
                    "size_usd": 100.0,
                    "order_type": "market",
                    "leverage": 1,
                    "market_type": "perp"
                }
                tasks.append(client.post(f"{BASE_URL}/api/v1/paper/orders/place", json=order_data))
            
            start_time = time.time()
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            duration = time.time() - start_time
            
            successful = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
            success_rate = successful / len(responses) * 100
            
            print(f"\n✅ Paper trades placed: {len(responses)}")
            print(f"✅ Successful: {successful} ({success_rate:.1f}%)")
            print(f"✅ Duration: {duration:.2f}s")
            
            assert success_rate >= 90, f"Paper trading success rate too low: {success_rate}%"
    
    @pytest.mark.asyncio
    async def test_trading_api_endpoints(self):
        """Test all trading API endpoints."""
        async with httpx.AsyncClient() as client:
            endpoints = [
                "/api/v1/trading/arbitrage/scan",
                "/api/v1/trading/arbitrage/stats",
                "/api/v1/trading/execute/stats",
                "/api/v1/trading/slippage/stats",
                "/api/v1/trading/perps/positions",
                "/api/v1/trading/markets/list",
            ]
            
            tasks = [client.get(f"{BASE_URL}{endpoint}") for endpoint in endpoints]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            successful = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
            
            print(f"\n✅ Trading endpoints tested: {len(endpoints)}")
            print(f"✅ Successful: {successful}/{len(endpoints)}")
            
            for endpoint, response in zip(endpoints, responses):
                if isinstance(response, Exception):
                    print(f"❌ {endpoint}: {response}")
                else:
                    print(f"✅ {endpoint}: {response.status_code}")
            
            assert successful >= len(endpoints) - 1, "Too many endpoint failures"
    
    @pytest.mark.asyncio
    async def test_betting_api_endpoints(self):
        """Test betting API endpoints."""
        async with httpx.AsyncClient() as client:
            endpoints = [
                "/api/v1/betting/pools/active",
                "/api/v1/betting/stats",
                "/api/v1/betting/leaderboard",
            ]
            
            tasks = [client.get(f"{BASE_URL}{endpoint}") for endpoint in endpoints]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            successful = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
            
            print(f"\n✅ Betting endpoints tested: {len(endpoints)}")
            print(f"✅ Successful: {successful}/{len(endpoints)}")
            
            assert successful >= len(endpoints) - 1, "Too many endpoint failures"
    
    @pytest.mark.asyncio
    async def test_paper_trading_portfolio_operations(self):
        """Test paper trading portfolio operations."""
        async with httpx.AsyncClient() as client:
            user_id = "portfolio_test_user"
            
            # Get portfolio
            response = await client.get(f"{BASE_URL}/api/v1/paper/portfolio/{user_id}")
            assert response.status_code == 200
            print(f"\n✅ Portfolio retrieved")
            
            # Get stats
            response = await client.get(f"{BASE_URL}/api/v1/paper/portfolio/{user_id}/stats")
            assert response.status_code == 200
            stats = response.json()
            print(f"✅ Portfolio stats: Balance=${stats['current_balance']:.2f}, ROI={stats['roi_pct']:.2f}%")
            
            # Get positions
            response = await client.get(f"{BASE_URL}/api/v1/paper/portfolio/{user_id}/positions")
            assert response.status_code == 200
            print(f"✅ Positions retrieved")
            
            # Get history
            response = await client.get(f"{BASE_URL}/api/v1/paper/portfolio/{user_id}/history")
            assert response.status_code == 200
            print(f"✅ Trade history retrieved")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
