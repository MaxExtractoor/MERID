#!/usr/bin/env python3
"""
MERID Paper Trading Setup Script
Configures paper trading environment and validates connections
"""

import asyncio
import aiohttp
import json
import os
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from dotenv import load_dotenv


# Load paper-trading credentials from .env by default (mirrors backend behavior)
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_PATH = os.getenv("MERID_ENV_FILE", os.path.join(_BASE_DIR, ".env"))
if os.path.exists(_ENV_PATH):
    load_dotenv(_ENV_PATH, override=False)

@dataclass
class PaperTradingConfig:
    """Configuration for paper trading setup"""
    
    # Broker configuration
    broker_type: str = "alpaca"  # alpaca, quantconnect, internal
    paper_api_key: Optional[str] = None
    paper_api_secret: Optional[str] = None
    paper_base_url: str = "https://paper-api.alpaca.markets"
    
    # Data configuration
    data_source: str = "alpaca"  # alpaca, polygon, yahoo
    real_time_data: bool = True
    
    # Risk limits
    max_position_size: float = 10000.0
    max_daily_loss: float = 1000.0
    max_positions: int = 10
    
    # Test symbols
    test_symbols: list = None
    
    def __post_init__(self):
        if self.test_symbols is None:
            self.test_symbols = ["AAPL", "MSFT", "SPY", "QQQ", "GLD"]

class PaperTradingSetup:
    """Paper trading environment setup and validation"""
    
    def __init__(self, config: PaperTradingConfig):
        self.config = config
        self.session = None
        self.results = []
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def log_result(self, test_name: str, success: bool, message: str, details: Dict = None):
        """Log test result"""
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "details": details or {},
            "timestamp": time.time()
        }
        self.results.append(result)
        
        status = "✅" if success else "❌"
        print(f"{status} {test_name}: {message}")
        
        if details and not success:
            print(f"   Details: {json.dumps(details, indent=2)}")
    
    async def test_broker_connection(self) -> bool:
        """Test broker API connection"""
        try:
            if self.config.broker_type == "alpaca":
                return await self._test_alpaca_connection()
            elif self.config.broker_type == "quantconnect":
                return await self._test_quantconnect_connection()
            else:
                self.log_result("broker_connection", False, "Unsupported broker type")
                return False
        except Exception as e:
            self.log_result("broker_connection", False, f"Connection failed: {e}")
            return False
    
    async def _test_alpaca_connection(self) -> bool:
        """Test Alpaca paper trading connection"""
        if not self.config.paper_api_key or not self.config.paper_api_secret:
            self.log_result("alpaca_auth", False, "Missing API credentials")
            return False
        
        headers = {
            "APCA-API-KEY-ID": self.config.paper_api_key,
            "APCA-API-SECRET-KEY": self.config.paper_api_secret
        }
        
        try:
            # Test account info
            async with self.session.get(
                f"{self.config.paper_base_url}/v2/account",
                headers=headers
            ) as response:
                if response.status == 200:
                    account_data = await response.json()
                    self.log_result(
                        "alpaca_account", 
                        True, 
                        f"Connected to paper account: {account_data.get('account_number', 'Unknown')}",
                        {"equity": account_data.get("equity", 0), "buying_power": account_data.get("buying_power", 0)}
                    )
                    return True
                else:
                    error_text = await response.text()
                    self.log_result("alpaca_account", False, f"HTTP {response.status}: {error_text}")
                    return False
        except Exception as e:
            self.log_result("alpaca_account", False, f"Request failed: {e}")
            return False
    
    async def _test_quantconnect_connection(self) -> bool:
        """Test QuantConnect connection"""
        # Placeholder for QuantConnect implementation
        self.log_result("quantconnect", False, "Not implemented yet")
        return False
    
    async def test_market_data(self) -> bool:
        """Test market data connection"""
        try:
            if self.config.data_source == "alpaca":
                return await self._test_alpaca_data()
            else:
                self.log_result("market_data", False, f"Data source {self.config.data_source} not implemented")
                return False
        except Exception as e:
            self.log_result("market_data", False, f"Data test failed: {e}")
            return False
    
    async def _test_alpaca_data(self) -> bool:
        """Test Alpaca market data"""
        headers = {
            "APCA-API-KEY-ID": self.config.paper_api_key,
            "APCA-API-SECRET-KEY": self.config.paper_api_secret
        }
        
        try:
            # Test latest trades for first test symbol (using data API)
            symbol = self.config.test_symbols[0]
            async with self.session.get(
                f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest",
                headers=headers
            ) as response:
                if response.status == 200:
                    trade_data = await response.json()
                    self.log_result(
                        "alpaca_quotes",
                        True,
                        f"Received trade data for {symbol}",
                        {"price": trade_data.get("p"), "size": trade_data.get("s"), "timestamp": trade_data.get("t")}
                    )
                    return True
                else:
                    error_text = await response.text()
                    self.log_result("alpaca_quotes", False, f"HTTP {response.status}: {error_text}")
                    return False
        except Exception as e:
            self.log_result("alpaca_quotes", False, f"Trade data request failed: {e}")
            return False
    
    async def test_paper_order(self) -> bool:
        """Test placing a paper order"""
        try:
            if self.config.broker_type == "alpaca":
                return await self._test_alpaca_order()
            else:
                self.log_result("paper_order", False, "Order testing not implemented for this broker")
                return False
        except Exception as e:
            self.log_result("paper_order", False, f"Order test failed: {e}")
            return False
    
    async def _test_alpaca_order(self) -> bool:
        """Test placing an Alpaca paper order"""
        headers = {
            "APCA-API-KEY-ID": self.config.paper_api_key,
            "APCA-API-SECRET-KEY": self.config.paper_api_secret,
            "Content-Type": "application/json"
        }
        
        # Place a small test order (likely to fill immediately)
        order_data = {
            "symbol": self.config.test_symbols[0],
            "qty": 1,
            "side": "buy",
            "type": "market",
            "time_in_force": "day"
        }
        
        try:
            async with self.session.post(
                f"{self.config.paper_base_url}/v2/orders",
                headers=headers,
                json=order_data
            ) as response:
                if response.status in [200, 201]:
                    order_result = await response.json()
                    order_id = order_result.get("id")
                    
                    self.log_result(
                        "paper_order",
                        True,
                        f"Paper order placed: {order_id}",
                        {"symbol": order_result.get("symbol"), "qty": order_result.get("qty"), "status": order_result.get("status")}
                    )
                    
                    # Cancel the order immediately to avoid holding positions
                    await self._cancel_alpaca_order(order_id, headers)
                    return True
                else:
                    error_text = await response.text()
                    self.log_result("paper_order", False, f"HTTP {response.status}: {error_text}")
                    return False
        except Exception as e:
            self.log_result("paper_order", False, f"Order placement failed: {e}")
            return False
    
    async def _cancel_alpaca_order(self, order_id: str, headers: Dict) -> None:
        """Cancel an Alpaca order"""
        try:
            async with self.session.delete(
                f"{self.config.paper_base_url}/v2/orders/{order_id}",
                headers=headers
            ) as response:
                if response.status == 200 or response.status == 204:
                    print(f"   ✅ Test order {order_id} cancelled")
                else:
                    print(f"   ⚠️  Could not cancel test order {order_id}")
        except Exception as e:
            print(f"   ⚠️  Error cancelling order: {e}")
    
    async def test_merid_integration(self) -> bool:
        """Test MERID system integration"""
        try:
            # Test MERID API is running (use port 8011)
            async with self.session.get("http://127.0.0.1:8011/api/v1/system/health") as response:
                if response.status == 200:
                    health_data = await response.json()
                    self.log_result(
                        "merid_health",
                        True,
                        "MERID API is healthy",
                        {"status": health_data.get("status"), "version": health_data.get("version")}
                    )
                else:
                    self.log_result("merid_health", False, f"MERID API returned {response.status}")
                    return False
            
            # Test prediction markets endpoint
            async with self.session.get("http://127.0.0.1:8011/api/v1/institutional/predictions/markets") as response:
                if response.status == 200:
                    markets_data = await response.json()
                    market_count = len(markets_data.get("markets", []))
                    self.log_result(
                        "merid_markets",
                        True,
                        f"MERID markets endpoint working: {market_count} markets",
                        {"count": market_count}
                    )
                    return True
                else:
                    self.log_result("merid_markets", False, f"Markets endpoint returned {response.status}")
                    return False
        except Exception as e:
            self.log_result("merid_integration", False, f"MERID integration failed: {e}")
            return False
    
    async def generate_config_file(self) -> str:
        """Generate configuration file for paper trading"""
        config_data = {
            "paper_trading": {
                "enabled": True,
                "broker": self.config.broker_type,
                "api_base": self.config.paper_base_url,
                "real_time_data": self.config.real_time_data,
                "test_symbols": self.config.test_symbols
            },
            "risk_limits": {
                "max_position_size": self.config.max_position_size,
                "max_daily_loss": self.config.max_daily_loss,
                "max_positions": self.config.max_positions
            },
            "monitoring": {
                "data_freshness_threshold": 60,  # seconds
                "order_timeout": 30,  # seconds
                "health_check_interval": 10  # seconds
            }
        }
        
        config_file = "config/paper_trading.json"
        os.makedirs("config", exist_ok=True)
        
        with open(config_file, "w") as f:
            json.dump(config_data, f, indent=2)
        
        self.log_result(
            "config_file",
            True,
            f"Configuration file generated: {config_file}",
            {"file_size": os.path.getsize(config_file)}
        )
        
        return config_file
    
    async def run_full_setup(self) -> Dict[str, Any]:
        """Run complete paper trading setup validation"""
        print("🚀 MERID Paper Trading Setup")
        print("=" * 50)
        print(f"Broker: {self.config.broker_type}")
        print(f"Data Source: {self.config.data_source}")
        print(f"Test Symbols: {', '.join(self.config.test_symbols)}")
        print("=" * 50)
        
        # Run all tests
        tests = [
            ("Broker Connection", self.test_broker_connection),
            ("Market Data", self.test_market_data),
            ("Paper Order", self.test_paper_order),
            ("MERID Integration", self.test_merid_integration)
        ]
        
        for test_name, test_func in tests:
            print(f"" + "\\" + f"n🧪 Testing {test_name}...")
            await test_func()
        
        # Generate configuration
        print(f"\n📝 Generating configuration...")
        config_file = await self.generate_config_file()
        
        # Summary
        print("\n" + "=" * 50)
        print("📊 SETUP SUMMARY")
        print("=" * 50)
        
        total_tests = len(self.results)
        passed_tests = len([r for r in self.results if r["success"]])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"✅ Passed: {passed_tests}")
        print(f"❌ Failed: {failed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests*100):.1f}%")
        
        if failed_tests > 0:
            print("\n❌ FAILED TESTS:")
            for result in self.results:
                if not result["success"]:
                    print(f"  - {result['test']}: {result['message']}")
        
        print(f"" + "\\" + f"n📄 Configuration: {config_file}")
        print(f"📝 Full results saved to: logs/paper_setup_{int(time.time())}.json")
        
        # Save results
        os.makedirs("logs", exist_ok=True)
        results_file = f"logs/paper_setup_{int(time.time())}.json"
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2)
        
        return {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "success_rate": passed_tests/total_tests,
            "config_file": config_file,
            "results_file": results_file,
            "ready_for_paper_trading": failed_tests == 0
        }

async def main():
    """Main setup function"""
    # Load configuration from environment or defaults
    config = PaperTradingConfig(
        broker_type=os.getenv("PAPER_BROKER", "alpaca"),
        paper_api_key=os.getenv("PAPER_API_KEY"),
        paper_api_secret=os.getenv("PAPER_API_SECRET"),
        data_source=os.getenv("PAPER_DATA_SOURCE", "alpaca")
    )
    
    # Check if credentials are provided
    if not config.paper_api_key or not config.paper_api_secret:
        print("❌ Missing paper trading credentials")
        print("Please set environment variables:")
        print("  PAPER_API_KEY=your_paper_api_key")
        print("  PAPER_API_SECRET=your_paper_api_secret")
        print("  PAPER_BROKER=alpaca (default)")
        return False
    
    # Run setup
    async with PaperTradingSetup(config) as setup:
        results = await setup.run_full_setup()
        
        if results["ready_for_paper_trading"]:
            print("\n🎉 Paper trading environment is ready!")
            print("Next steps:")
            print("1. Review the generated configuration file")
            print("2. Start MERID with paper trading enabled")
            print("3. Follow the runbook for Phase 2: Data Pipeline Verification")
        else:
            print("\n⚠️  Paper trading setup incomplete")
            print("Please fix the failed tests before proceeding")
        
        return results["ready_for_paper_trading"]

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
