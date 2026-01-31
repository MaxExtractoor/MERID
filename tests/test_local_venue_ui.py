"""
UI Integration Tests for Local Venue

Automated tests for Local Venue UI components and API endpoints.
"""

import pytest
import asyncio
import time
import json
from decimal import Decimal
from typing import Dict, List, Any

from web.main import create_app
from web.api.local_venue import EngineStatus, OrderBookResponse, Trade, TradesResponse
from execution.simulator import get_execution_simulator
from venues.local_sim_adapter import create_local_sim_adapter


@pytest.mark.localvenue
@pytest.mark.ui_api
class TestLocalVenueAPI:
    """Test local venue API endpoints."""
    
    @pytest.fixture
    def app(self):
        """Create FastAPI app for testing."""
        return create_app()
    
    @pytest.fixture
    async def client(self, app):
        """Create test client."""
        from httpx import AsyncClient
        async with AsyncClient(app=app, base_url="http://test") as client:
            yield client
    
    async def test_engine_status_endpoint(self, client):
        """Test engine status API response structure."""
        response = await client.get("/api/v1/localvenue/engine-status")
        assert response.status_code == 200
        
        data = response.json()
        assert "is_running" in data
        assert "queue_depth" in data
        assert "messages_per_sec" in data
        assert "dropped_messages" in data
        assert "total_trades" in data
        assert "uptime_seconds" in data
        
        # Validate data types
        assert isinstance(data["is_running"], bool)
        assert isinstance(data["queue_depth"], int)
        assert isinstance(data["messages_per_sec"], (int, float))
        assert isinstance(data["dropped_messages"], int)
        assert isinstance(data["total_trades"], int)
        assert isinstance(data["uptime_seconds"], (int, float))
    
    async def test_orderbook_endpoint(self, client):
        """Test order book API response structure."""
        response = await client.get("/api/v1/localvenue/orderbook?symbol=BTCUSDT")
        assert response.status_code == 200
        
        data = response.json()
        assert "symbol" in data
        assert "timestamp" in data
        assert "bids" in data
        assert "asks" in data
        assert "sequence_number" in data
        
        # Validate data structure
        assert data["symbol"] == "BTCUSDT"
        assert isinstance(data["timestamp"], (int, float))
        assert isinstance(data["bids"], list)
        assert isinstance(data["asks"], list)
        assert isinstance(data["sequence_number"], int)
        
        # Validate bid/ask structure
        if data["bids"]:
            bid = data["bids"][0]
            assert "price" in bid
            assert "quantity" in bid
            assert isinstance(bid["price"], (int, float))
            assert isinstance(bid["quantity"], int)
    
    async def test_trades_endpoint(self, client):
        """Test trades API response structure."""
        response = await client.get("/api/v1/localvenue/trades?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert "trades" in data
        assert "total_count" in data
        
        # Validate data structure
        assert isinstance(data["trades"], list)
        assert isinstance(data["total_count"], int)
        
        # Validate trade structure
        if data["trades"]:
            trade = data["trades"][0]
            assert "symbol" in trade
            assert "side" in trade
            assert "quantity" in trade
            assert "price" in trade
            assert "timestamp" in trade
            assert "trade_id" in trade
            assert "pnl" in trade
            
            assert isinstance(trade["quantity"], int)
            assert isinstance(trade["price"], (int, float))
            assert isinstance(trade["pnl"], (int, float))
            assert trade["side"] in ["buy", "sell"]
    
    async def test_health_endpoint(self, client):
        """Test health check API response."""
        response = await client.get("/api/v1/localvenue/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        
        # Validate status values
        assert data["status"] in ["healthy", "unhealthy"]
        assert isinstance(data["timestamp"], (int, float))
    
    async def test_feed_handlers_endpoint(self, client):
        """Test feed handlers API response."""
        response = await client.get("/api/v1/localvenue/feed-handlers")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        
        # Validate handler structure
        if data:
            handler = data[0]
            assert "handler_name" in handler
            assert "handler_type" in handler
            assert "status" in handler
            assert "symbol_count" in handler
            assert "last_heartbeat" in handler
            
            assert isinstance(handler["symbol_count"], int)
            assert isinstance(handler["last_heartbeat"], (int, float))
    
    async def test_control_endpoint(self, client):
        """Test engine control endpoint."""
        # Test start action
        response = await client.post(
            "/api/v1/localvenue/control",
            json={"action": "start", "reason": "test"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "success" in data
        assert "message" in data
        assert "timestamp" in data
        
        assert isinstance(data["success"], bool)
        assert isinstance(data["timestamp"], (int, float))


@pytest.mark.localvenue
@pytest.mark.ui_integration
class TestLocalVenueUI:
    """Test local venue UI integration."""
    
    @pytest.fixture
    async def adapter(self):
        """Create test adapter for UI testing."""
        adapter = create_local_sim_adapter("ui_test_account", 100000.0)
        await adapter.connect()
        yield adapter
        await adapter.disconnect()
    
    async def test_ui_data_flow(self, adapter):
        """Test data flow from adapter to UI."""
        # Submit test order
        from venues.local_sim_adapter import VenueOrder
        order = VenueOrder(
            venue_order_id="ui_test_001",
            client_order_id="ui_client_001",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        result = await adapter.submit_order(order)
        assert result.venue_order_id is not None
        
        # Check that order book reflects the order
        book_manager = get_persistent_book_manager()
        book = book_manager.get_book("BTCUSDT")
        snapshot = book.get_snapshot()
        
        # Should have at least one bid level
        assert len(snapshot.bids) > 0
    
    async def test_ui_real_time_updates(self, adapter):
        """Test real-time update mechanisms."""
        # Test market data subscription
        updates_received = []
        
        def market_data_callback(data):
            updates_received.append(data)
        
        adapter.subscribe_market_data(market_data_callback)
        
        # Submit order to trigger updates
        from venues.local_sim_adapter import VenueOrder
        order = VenueOrder(
            venue_order_id="ui_test_002",
            client_order_id="ui_client_002",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        await adapter.submit_order(order)
        
        # Give time for updates
        await asyncio.sleep(0.1)
        
        # Should have received some updates
        assert len(updates_received) > 0


@pytest.mark.localvenue
@pytest.mark.ui_smoke
class TestLocalVenueUISmoke:
    """Smoke tests for local venue UI."""
    
    def test_ui_components_load(self):
        """Test that UI components can be loaded."""
        # Test JavaScript module loading
        try:
            from web.static.js.unified_master import loadLocalVenue
            assert callable(loadLocalVenue)
        except ImportError:
            pytest.skip("JavaScript module not available in Python test")
    
    def test_ui_models_validation(self):
        """Test UI model validation."""
        # Test EngineStatus model
        engine_status = EngineStatus(
            is_running=True,
            queue_depth=10,
            messages_per_sec=100.5,
            dropped_messages=0,
            last_match_ts=time.time(),
            total_trades=5,
            uptime_seconds=3600.0
        )
        
        assert engine_status.is_running is True
        assert engine_status.queue_depth == 10
        
        # Test OrderBookResponse model
        from web.api.local_venue import OrderBookLevel
        
        bids = [OrderBookLevel(price=50000.0, quantity=100)]
        asks = [OrderBookLevel(price=50100.0, quantity=50)]
        
        orderbook = OrderBookResponse(
            symbol="BTCUSDT",
            timestamp=time.time(),
            bids=bids,
            asks=asks,
            best_bid=50000.0,
            best_ask=50100.0,
            spread=100.0,
            sequence_number=12345
        )
        
        assert orderbook.symbol == "BTCUSDT"
        assert orderbook.spread == 100.0
        
        # Test Trade model
        trade = Trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=100,
            price=50000.0,
            timestamp=time.time(),
            trade_id="trade_123",
            pnl=50.0
        )
        
        assert trade.symbol == "BTCUSDT"
        assert trade.side == "buy"
        assert trade.pnl == 50.0


@pytest.mark.localvenue
@pytest.mark.e2e_ui
class TestLocalVenueUIE2E:
    """End-to-end tests for local venue UI."""
    
    async def test_complete_ui_workflow(self):
        """Test complete UI workflow from order submission to display."""
        # Create adapter
        adapter = create_local_sim_adapter("e2e_ui_account", 100000.0)
        await adapter.connect()
        
        try:
            # Submit multiple orders
            from venues.local_sim_adapter import VenueOrder
            
            orders = [
                VenueOrder(
                    venue_order_id="e2e_ui_001",
                    client_order_id="e2e_ui_client_001",
                    symbol="BTCUSDT",
                    side="buy",
                    order_type="limit",
                    quantity=100,
                    price=50000.0
                ),
                VenueOrder(
                    venue_order_id="e2e_ui_002",
                    client_order_id="e2e_ui_client_002",
                    symbol="BTCUSDT",
                    side="sell",
                    order_type="limit",
                    quantity=50,
                    price=50100.0
                )
            ]
            
            results = []
            for order in orders:
                result = await adapter.submit_order(order)
                results.append(result)
                assert result.venue_order_id is not None
            
            # Check order book state
            book_manager = get_persistent_book_manager()
            book = book_manager.get_book("BTCUSDT")
            snapshot = book.get_snapshot()
            
            # Should have both bids and asks
            assert len(snapshot.bids) > 0
            assert len(snapshot.asks) > 0
            
            # Check spread calculation
            if snapshot.bids and snapshot.asks:
                best_bid = snapshot.bids[0].price
                best_ask = snapshot.asks[0].price
                spread = best_ask - best_bid
                assert spread > 0
            
            # Check trades
            trades = await adapter.get_trades()
            assert isinstance(trades, list)
            
        finally:
            await adapter.disconnect()
    
    async def test_ui_failure_scenarios(self):
        """Test UI failure scenarios and recovery."""
        # Test adapter reconnection
        adapter = create_local_sim_adapter("failure_test_account", 100000.0)
        
        # Connect and disconnect
        await adapter.connect()
        assert adapter._connected
        
        await adapter.disconnect()
        assert not adapter._connected
        
        # Reconnect
        await adapter.connect()
        assert adapter._connected
        
        await adapter.disconnect()


# UI Test Utilities
def create_mock_ui_data():
    """Create mock UI data for testing."""
    return {
        "engine_status": {
            "is_running": True,
            "queue_depth": 10,
            "messages_per_sec": 100.5,
            "dropped_messages": 0,
            "total_trades": 5,
            "uptime_seconds": 3600.0
        },
        "order_book": {
            "symbol": "BTCUSDT",
            "timestamp": time.time(),
            "bids": [
                {"price": 50000.0, "quantity": 100},
                {"price": 49900.0, "quantity": 200}
            ],
            "asks": [
                {"price": 50100.0, "quantity": 50},
                {"price": 50200.0, "quantity": 150}
            ],
            "best_bid": 50000.0,
            "best_ask": 50100.0,
            "spread": 100.0,
            "sequence_number": 12345
        },
        "trades": [
            {
                "symbol": "BTCUSDT",
                "side": "buy",
                "quantity": 100,
                "price": 50050.0,
                "timestamp": time.time(),
                "trade_id": "trade_123",
                "pnl": 50.0
            }
        ]
    }


def validate_ui_response_structure(data: Dict[str, Any], expected_type: str):
    """Validate UI response structure."""
    if expected_type == "engine_status":
        required_fields = ["is_running", "queue_depth", "messages_per_sec", "dropped_messages", "total_trades", "uptime_seconds"]
    elif expected_type == "order_book":
        required_fields = ["symbol", "timestamp", "bids", "asks", "sequence_number"]
    elif expected_type == "trades":
        required_fields = ["trades", "total_count"]
    elif expected_type == "health":
        required_fields = ["status", "timestamp"]
    else:
        raise ValueError(f"Unknown expected_type: {expected_type}")
    
    for field in required_fields:
        assert field in data, f"Missing required field: {field}"


def validate_ui_data_consistency(engine_status: Dict[str, Any], order_book: Dict[str, Any], trades: List[Dict[str, Any]]):
    """Validate UI data consistency across endpoints."""
    # Check timestamps are reasonable
    current_time = time.time()
    
    if engine_status.get("uptime_seconds", 0) > 0:
        # Engine should have been running
        assert engine_status["is_running"] is True
    
    if order_book.get("bids") and order_book.get("asks"):
        # Order book should have valid spread
        best_bid = order_book["bids"][0]["price"]
        best_ask = order_book["asks"][0]["price"]
        assert best_ask > best_bid
    
    if trades:
        # Trades should have valid data
        for trade in trades:
            assert trade["price"] > 0
            assert trade["quantity"] > 0
            assert trade["side"] in ["buy", "sell"]
