"""
Mock Trading API Infrastructure for Testing.

Provides deterministic, regulation-friendly mocks for external trading APIs.
Implements contract-first mocks with realistic failure scenarios.
"""

import json
import time
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum
import random
from unittest.mock import MagicMock

from utils.logger import get_logger

logger = get_logger("mock_trading_api")


class MockApiProfile(Enum):
    """Mock API profiles for different test scenarios."""
    HAPPY_PATH = "happy_path"
    RATE_LIMIT = "rate_limit"
    PARTIAL_OUTAGE = "partial_outage"
    COMPLETE_OUTAGE = "complete_outage"
    ERROR_RESPONSES = "error_responses"
    STALE_DATA = "stale_data"
    MALFORMED_DATA = "malformed_data"


@dataclass
class MockOrderResponse:
    """Mock order response structure."""
    order_id: str
    status: str
    symbol: str
    side: str
    quantity: float
    price: Optional[float]
    filled_quantity: float
    remaining_quantity: float
    timestamp: float
    venue: str
    error: Optional[str] = None


@dataclass
class MockMarketData:
    """Mock market data structure."""
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    timestamp: float
    venue: str
    stale: bool = False


@dataclass
class MockPosition:
    """Mock position data structure."""
    symbol: str
    quantity: float
    avg_price: float
    market_value: float
    venue: str
    timestamp: float


class MockTradingApi:
    """Mock trading API with realistic behavior and failure scenarios."""
    
    def __init__(self, profile: MockApiProfile = MockApiProfile.HAPPY_PATH):
        self.profile = profile
        self.request_count = 0
        self.error_rate = 0.0
        self.latency_ms = 50.0
        self.rate_limit_remaining = 1000
        self.rate_limit_window = 60.0
        self.rate_limit_reset_time = time.time()
        
        # Mock data stores
        self.orders: Dict[str, MockOrderResponse] = {}
        self.positions: Dict[str, MockPosition] = {}
        self.market_data: Dict[str, MockMarketData] = {}
        
        # Load mock data based on profile
        self._load_mock_data()
    
    def _load_mock_data(self):
        """Load mock data based on the selected profile."""
        
        if self.profile == MockApiProfile.HAPPY_PATH:
            self._load_happy_path_data()
        elif self.profile == MockApiProfile.RATE_LIMIT:
            self._load_rate_limit_data()
        elif self.profile == MockApiProfile.PARTIAL_OUTAGE:
            self._load_partial_outage_data()
        elif self.profile == MockApiProfile.COMPLETE_OUTAGE:
            self._load_complete_outage_data()
        elif self.profile == MockApiProfile.ERROR_RESPONSES:
            self._load_error_responses_data()
        elif self.profile == MockApiProfile.STALE_DATA:
            self._load_stale_data()
        elif self.profile == MockApiProfile.MALFORMED_DATA:
            self._load_malformed_data()
    
    def _load_happy_path_data(self):
        """Load happy path mock data."""
        
        # Mock market data
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD"]
        for symbol in symbols:
            base_price = {"BTC/USD": 45000, "ETH/USD": 3000, "SOL/USD": 120, "MATIC/USD": 0.85}[symbol]
            spread = base_price * 0.001  # 0.1% spread
            
            self.market_data[symbol] = MockMarketData(
                symbol=symbol,
                bid=base_price - spread/2,
                ask=base_price + spread/2,
                bid_size=1000.0,
                ask_size=1000.0,
                timestamp=time.time(),
                venue="mock_exchange"
            )
        
        # Mock positions
        self.positions["BTC/USD"] = MockPosition(
            symbol="BTC/USD",
            quantity=1.5,
            avg_price=44000.0,
            market_value=66000.0,
            venue="mock_exchange",
            timestamp=time.time()
        )
        
        self.positions["ETH/USD"] = MockPosition(
            symbol="ETH/USD",
            quantity=10.0,
            avg_price=2900.0,
            market_value=29000.0,
            venue="mock_exchange",
            timestamp=time.time()
        )
    
    def _load_rate_limit_data(self):
        """Load rate limit mock data."""
        
        # Set low rate limit
        self.rate_limit_remaining = 10
        self.rate_limit_window = 60.0
        self.rate_limit_reset_time = time.time() + 60.0
        
        # Load basic market data
        self._load_happy_path_data()
    
    def _load_partial_outage_data(self):
        """Load partial outage mock data."""
        
        # Load basic market data but with some symbols missing
        self._load_happy_path_data()
        
        # Remove some symbols to simulate partial outage
        symbols_to_remove = ["SOL/USD", "MATIC/USD"]
        for symbol in symbols_to_remove:
            if symbol in self.market_data:
                del self.market_data[symbol]
            if symbol in self.positions:
                del self.positions[symbol]
    
    def _load_complete_outage_data(self):
        """Load complete outage mock data."""
        
        # No market data available
        self.market_data.clear()
        self.positions.clear()
        self.orders.clear()
    
    def _load_error_responses_data(self):
        """Load error response mock data."""
        
        # Load basic data but set high error rate
        self.error_rate = 0.5  # 50% error rate
        self._load_happy_path_data()
    
    def _load_stale_data(self):
        """Load stale data mock data."""
        
        # Load basic data but with old timestamps
        self._load_happy_path_data()
        
        # Make data stale (more than 5 minutes old)
        stale_time = time.time() - 300.0
        for market_data in self.market_data.values():
            market_data.timestamp = stale_time
            market_data.stale = True
        
        for position in self.positions.values():
            position.timestamp = stale_time
    
    def _load_malformed_data(self):
        """Load malformed data mock data."""
        
        # Load some data but with malformed entries
        self._load_happy_path_data()
        
        # Add malformed market data
        self.market_data["MALFORMED/USD"] = MockMarketData(
            symbol="MALFORMED/USD",
            bid="invalid_price",
            ask="invalid_price",
            bid_size=-100.0,  # Invalid size
            ask_size="invalid_size",  # Invalid type
            timestamp=time.time(),
            venue="mock_exchange"
        )
    
    def _check_rate_limit(self) -> bool:
        """Check if request is rate limited."""
        
        current_time = time.time()
        
        # Reset rate limit if window expired
        if current_time > self.rate_limit_reset_time:
            self.rate_limit_remaining = 1000
            self.rate_limit_reset_time = current_time + self.rate_limit_window
        
        # Check if rate limit exceeded
        if self.rate_limit_remaining <= 0:
            return False
        
        self.rate_limit_remaining -= 1
        return True
    
    def _simulate_latency(self) -> float:
        """Simulate API latency based on profile."""
        
        if self.profile == MockApiProfile.STALE_DATA:
            return self.latency_ms * 3  # 3x slower for stale data
        elif self.profile == MockApiProfile.ERROR_RESPONSES:
            return self.latency_ms * 2  # 2x slower for error responses
        else:
            return self.latency_ms
    
    def _simulate_error(self) -> Optional[str]:
        """Simulate error based on profile error rate."""
        
        if self.profile == MockApiProfile.ERROR_RESPONSES:
            if random.random() < self.error_rate:
                errors = [
                    "Internal server error",
                    "Database connection failed",
                    "Rate limit exceeded",
                    "Invalid request format",
                    "Service temporarily unavailable"
                ]
                return random.choice(errors)
        elif self.profile == MockApiProfile.MALFORMED_DATA:
            if random.random() < 0.3:  # 30% error rate for malformed data
                return "Data validation error"
        
        return None
    
    def _simulate_timeout(self) -> bool:
        """Simulate timeout based on profile."""
        
        # Higher timeout rate for certain profiles
        timeout_rates = {
            MockApiProfile.STALE_DATA: 0.1,
            MockApiProfile.ERROR_RESPONSES: 0.05,
            MockApiProfile.COMPLETE_OUTAGE: 0.5
        }
        
        timeout_rate = timeout_rates.get(self.profile, 0.0)
        return random.random() < timeout_rate
    
    def _validate_request(self, endpoint: str, data: Dict[str, Any]) -> bool:
        """Validate request data and return True if valid."""
        
        if self.profile == MockApiProfile.MALFORMED_DATA:
            # Simulate validation errors for certain requests
            if endpoint == "/orders" and "quantity" in data:
                try:
                    quantity = float(data["quantity"])
                    if quantity <= 0 or quantity > 1000000:
                        return False
                except (ValueError, TypeError):
                    return False
        
        return True
    
    def _generate_order_id(self) -> str:
        """Generate a mock order ID."""
        return f"order_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
    
    def _calculate_fills(self, quantity: float, market_data: MockMarketData) -> tuple:
        """Calculate realistic fills for an order."""
        
        if market_data.bid_size <= 0 or market_data.ask_size <= 0:
            return 0.0, quantity
        
        # Simulate partial fills
        fill_probability = 0.8  # 80% fill rate
        if random.random() > fill_probability:
            return 0.0, quantity
        
        # Calculate fill based on market depth
        max_fill = min(market_data.bid_size, market_data.ask_size)
        
        if quantity <= max_fill:
            fill_quantity = quantity
        else:
            fill_quantity = max_fill * 0.9  # 90% of max fill
        
        return fill_quantity, quantity - fill_quantity
    
    def submit_order(self, symbol: str, side: str, quantity: float, 
                     price: Optional[float] = None, order_type: str = "market") -> MockOrderResponse:
        """Submit a mock order."""
        
        self.request_count += 1
        
        # Check rate limiting
        if not self._check_rate_limit():
            return MockOrderResponse(
                order_id="",
                status="rejected",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                filled_quantity=0.0,
                remaining_quantity=quantity,
                timestamp=time.time(),
                venue="mock_exchange",
                error="Rate limit exceeded"
            )
        
        # Simulate latency
        time.sleep(self._simulate_latency() / 1000.0)
        
        # Check for timeout
        if self._simulate_timeout():
            return MockOrderResponse(
                order_id="",
                status="timeout",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                filled_quantity=0.0,
                remaining_quantity=quantity,
                timestamp=time.time(),
                venue="mock_exchange",
                error="Request timeout"
            )
        
        # Check for errors
        error = self._simulate_error()
        if error:
            return MockOrderResponse(
                order_id="",
                status="error",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                filled_quantity=0.0,
                remaining_quantity=quantity,
                timestamp=time.time(),
                venue="mock_exchange",
                error=error
            )
        
        # Validate request
        request_data = {"symbol": symbol, "side": side, "quantity": quantity, "price": price}
        if not self._validate_request("/orders", request_data):
            return MockOrderResponse(
                order_id="",
                status="rejected",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                filled_quantity=0.0,
                remaining_quantity=quantity,
                timestamp=time.time(),
                venue="mock_exchange",
                error="Invalid request data"
            )
        
        # Get market data
        market_data = self.market_data.get(symbol)
        if not market_data:
            return MockOrderResponse(
                order_id="",
                status="rejected",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                filled_quantity=0.0,
                remaining_quantity=quantity,
                timestamp=time.time(),
                venue="mock_exchange",
                error="No market data available"
            )
        
        # Handle market orders
        if order_type == "market" and price is None:
            price = market_data.bid if side == "sell" else market_data.ask
        
        # Calculate fills
        filled_quantity, remaining_quantity = self._calculate_fills(quantity, market_data)
        
        # Create order response
        order_id = self._generate_order_id()
        status = "filled" if filled_quantity > 0 else "rejected"
        
        response = MockOrderResponse(
            order_id=order_id,
            status=status,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            filled_quantity=filled_quantity,
            remaining_quantity=remaining_quantity,
            timestamp=time.time(),
            venue="mock_exchange"
        )
        
        # Store order
        self.orders[order_id] = response
        
        return response
    
    def cancel_order(self, order_id: str) -> MockOrderResponse:
        """Cancel a mock order."""
        
        self.request_count += 1
        
        # Check rate limiting
        if not self._check_rate_limit():
            return MockOrderResponse(
                order_id=order_id,
                status="rejected",
                symbol="",
                side="",
                quantity=0.0,
                price=None,
                filled_quantity=0.0,
                remaining_quantity=0.0,
                timestamp=time.time(),
                venue="mock_exchange",
                error="Rate limit exceeded"
            )
        
        # Simulate latency
        time.sleep(self._simulate_latency() / 1000.0)
        
        # Check for errors
        error = self._simulate_error()
        if error:
            return MockOrderResponse(
                order_id=order_id,
                status="error",
                symbol="",
                side="",
                quantity=0.0,
                price=None,
                filled_quantity=0.0,
                remaining_quantity=0.0,
                timestamp=time.time(),
                venue="mock_exchange",
                error=error
            )
        
        # Get existing order
        order = self.orders.get(order_id)
        if not order:
            return MockOrderResponse(
                order_id=order_id,
                status="not_found",
                symbol="",
                side="",
                quantity=0.0,
                price=None,
                filled_quantity=0.0,
                remaining_quantity=0.0,
                timestamp=time.time(),
                venue="mock_exchange",
                error="Order not found"
            )
        
        # Cancel the order
        order.status = "cancelled"
        order.timestamp = time.time()
        
        return order
    
    def get_market_data(self, symbol: str) -> Optional[MockMarketData]:
        """Get mock market data for a symbol."""
        
        self.request_count += 1
        
        # Check rate limiting
        if not self._check_rate_limit():
            return None
        
        # Simulate latency
        time.sleep(self._simulate_latency() / 1000.0)
        
        # Check for errors
        error = self._simulate_error()
        if error:
            logger.error(f"Error getting market data: {error}")
            return None
        
        return self.market_data.get(symbol)
    
    def get_positions(self) -> List[MockPosition]:
        """Get mock positions."""
        
        self.request_count += 1
        
        # Check rate limiting
        if not self._check_rate_limit():
            return []
        
        # Simulate latency
        time.sleep(self._simulate_latency() / 1000.0)
        
        # Return positions
        return list(self.positions.values())
    
    def get_order_status(self, order_id: str) -> Optional[MockOrderResponse]:
        """Get mock order status."""
        
        self.request_count += 1
        
        # Check rate limiting
        if not self._check_rate_limit():
            return None
        
        # Simulate latency
        time.sleep(self._simulate_latency() / 1000.0)
        
        return self.orders.get(order_id)


class MockTradingApiManager:
    """Manages multiple mock trading API instances with different profiles."""
    
    def __init__(self):
        self.apis: Dict[str, MockTradingApi] = {}
        self.default_profile = MockApiProfile.HAPPY_PATH
    
    def get_api(self, profile: Optional[MockApiProfile] = None) -> MockTradingApi:
        """Get a mock trading API instance with specified profile."""
        
        profile = profile or self.default_profile
        key = profile.value
        
        if key not in self.apis:
            self.apis[key] = MockTradingApi(profile)
        
        return self.apis[key]
    
    def set_default_profile(self, profile: MockApiProfile):
        """Set the default profile for new APIs."""
        self.default_profile = profile
    
    def clear_cache(self):
        """Clear all cached API instances."""
        self.apis.clear()


# Global mock API manager
_mock_api_manager = MockTradingApiManager()


def get_mock_trading_api(profile: Optional[MockApiProfile] = None) -> MockTradingApi:
    """Get the global mock trading API manager."""
    return _mock_api_manager.get_api(profile)


def set_default_mock_profile(profile: MockApiProfile):
    """Set the default mock trading API profile."""
    _mock_api_manager.set_default_profile(profile)


# Factory functions for common test scenarios
def create_happy_path_api() -> MockTradingApi:
    """Create a mock trading API with happy path behavior."""
    return get_mock_trading_api(MockApiProfile.HAPPY_PATH)


def create_rate_limited_api() -> MockTradingApi:
    """Create a mock trading API with rate limiting."""
    return get_mock_trading_api(MockApiProfile.RATE_LIMIT)


def create_partial_outage_api() -> MockTradingApi:
    """Create a mock trading API with partial outage."""
    return get_mock_trading_api(MockApiProfile.PARTIAL_OUTAGE)


def create_complete_outage_api() -> MockTradingApi:
    """Create a mock trading API with complete outage."""
    return get_mock_trading_api(MockApiProfile.COMPLETE_OUTAGE)


def create_error_prone_api() -> MockTradingApi:
    """Create a mock trading API with high error rate."""
    return get_mock_trading_api(MockApiProfile.ERROR_RESPONSES)


def create_stale_data_api() -> MockTradingApi:
    """Create a mock trading API with stale data."""
    return get_mock_trading_api(MockApiProfile.STALE_DATA)


if __name__ == "__main__":
    # Example usage
    api = create_happy_path_api()
    
    # Submit a test order
    order = api.submit_order("BTC/USD", "buy", 1.0)
    print(f"Order submitted: {order.order_id} - {order.status}")
    
    # Get market data
    market_data = api.get_market_data("BTC/USD")
    if market_data:
        print(f"Market data: {market_data.bid}/{market_data.ask}")
    
    # Get positions
    positions = api.get_positions()
    print(f"Positions: {len(positions)}")
    
    print("Mock trading API test completed successfully")
