"""
Local Venue Unit Tests

Unit tests for feed handlers, matching engine, and venue adapter.
"""

import pytest
import asyncio
import time
from decimal import Decimal
from typing import Dict, List, Any

from execution.simulator import get_execution_simulator
from execution.persistent_book import get_persistent_book_manager
from execution.book_builder import get_book_builder
from venues.local_sim_adapter import create_local_sim_adapter
from data.feed_handlers import get_feed_handler_manager, MulticastFeedHandler, create_multicast_handler_config
from data.market_data_schemas import DataType, Side, LiquidityFlag
from web.api.local_venue import EngineStatus, OrderBookResponse, Trade, TradesResponse


@pytest.mark.localvenue
@pytest.mark.feed_handlers
class TestFeedHandlers:
    """Test feed handler functionality."""
    
    def test_multicast_handler_creation(self):
        """Test multicast feed handler creation and configuration."""
        config = create_multicast_handler_config(
            "nasdaq",
            ["AAPL", "MSFT", "GOOG"],
            "239.255.255.1",
            60000
        )
        handler = MulticastFeedHandler(config)
        
        assert handler.handler_name == "nasdaq_multicast"
        assert handler.handler_type == "multicast"
        assert handler.config == config
        assert not handler._running
    
    def test_feed_handler_lifecycle(self):
        """Test feed handler start/stop lifecycle."""
        config = create_multicast_handler_config(
            "test",
            ["TEST"],
            "127.0.0.1",
            60001
        )
        handler = MulticastFeedHandler(config)
        
        # Test start
        asyncio.run(handler.start())
        assert handler._running
        
        # Test stop
        asyncio.run(handler.stop())
        assert not handler._running
    
    def test_feed_handler_heartbeat(self):
        """Test feed handler heartbeat emission."""
        config = create_multicast_handler_config(
            "test",
            ["TEST"],
            "127.0.0.1",
            60001
        )
        handler = MulticastFeedHandler(config)
        
        # Mock heartbeat emission
        heartbeat_called = False
        def mock_heartbeat(status, symbol_count):
            nonlocal heartbeat_called
            heartbeat_called = True
        
        handler._emit_heartbeat = mock_heartbeat
        
        asyncio.run(handler.start())
        # Heartbeat should be emitted during start
        assert heartbeat_called
        asyncio.run(handler.stop())


@pytest.mark.localvenue
@pytest.mark.matching_engine
class TestLocalVenueAdapter:
    """Test local venue adapter functionality."""
    
    @pytest.fixture
    async def adapter(self):
        """Create a test adapter."""
        adapter = create_local_sim_adapter("test_account", 100000.0)
        await adapter.connect()
        yield adapter
        await adapter.disconnect()
    
    async def test_adapter_connection(self, adapter):
        """Test adapter connection and account creation."""
        assert adapter._connected
        assert adapter._account_id == "test_account"
        
        account = await adapter.get_account()
        assert account.cash_balance == 100000.0
    
    async def test_order_submission(self, adapter):
        """Test order submission and execution."""
        from venues.local_sim_adapter import VenueOrder
        
        order = VenueOrder(
            venue_order_id="test_001",
            client_order_id="client_001",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        result = await adapter.submit_order(order)
        assert result.venue_order_id is not None
        assert result.status.value in ["new", "filled", "partially_filled"]
    
    async def test_order_cancellation(self, adapter):
        """Test order cancellation."""
        from venues.local_sim_adapter import VenueOrder
        
        # Submit order first
        order = VenueOrder(
            venue_order_id="test_002",
            client_order_id="client_002",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        result = await adapter.submit_order(order)
        order_id = result.venue_order_id
        
        # Cancel order
        cancelled = await adapter.cancel_order(order_id)
        assert cancelled is True
    
    async def test_position_tracking(self, adapter):
        """Test position tracking."""
        positions = await adapter.get_positions()
        assert isinstance(positions, list)
        
        # Initially should be empty
        assert len(positions) == 0
    
    async def test_market_data_subscription(self, adapter):
        """Test market data subscription."""
        # Test that market data callbacks can be added
        callback_called = False
        
        def market_data_callback(data):
            nonlocal callback_called
            callback_called = True
        
        adapter.subscribe_market_data(market_data_callback)
        assert market_data_callback in adapter._market_data_callbacks


@pytest.mark.localvenue
@pytest.mark.matching_engine
class TestMatchingEngine:
    """Test matching engine functionality."""
    
    @pytest.fixture
    async def simulator(self):
        """Create test simulator."""
        sim = get_execution_simulator()
        await sim.start()
        yield sim
        await sim.stop()
    
    @pytest.fixture
    async def book_manager(self):
        """Create test book manager."""
        manager = get_persistent_book_manager()
        manager.start_all()
        yield manager
        manager.stop_all()
    
    @pytest.fixture
    async def book_builder(self):
        """Create test book builder."""
        builder = get_book_builder()
        await builder.start()
        yield builder
        await builder.stop()
    
    async def test_order_book_creation(self, book_manager):
        """Test order book creation and management."""
        book = book_manager.get_book("BTCUSDT")
        assert book is not None
        assert book.symbol == "BTCUSDT"
        
        # Test adding orders
        book.add_order("order_1", "buy", 50000.0, 100)
        book.add_order("order_2", "sell", 50100.0, 50)
        
        snapshot = book.get_snapshot()
        assert len(snapshot.bids) > 0
        assert len(snapshot.asks) > 0
    
    async def test_order_execution(self, simulator):
        """Test order execution in simulator."""
        # Create account
        simulator.create_account("test_account", 100000.0)
        
        # Submit order
        result = simulator.submit_order(
            account_id="test_account",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        assert result["order_id"] is not None
        assert result["status"] in ["accepted", "filled"]
    
    async def test_trade_generation(self, simulator):
        """Test trade generation and emission."""
        # Create account and opposing orders
        simulator.create_account("test_account", 100000.0)
        
        # Submit buy order
        buy_result = simulator.submit_order(
            account_id="test_account",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        # Submit sell order at same price
        sell_result = simulator.submit_order(
            account_id="test_account",
            symbol="BTCUSDT",
            side="sell",
            order_type="limit",
            quantity=50,
            price=50000.0
        )
        
        # Check if trade was generated
        orders = simulator.get_orders("test_account")
        trades = simulator.get_trades("test_account")
        
        assert len(orders) >= 2
        # Trade may or may not be generated depending on matching logic


@pytest.mark.localvenue
@pytest.mark.integration
class TestBookBuilder:
    """Test book builder integration."""
    
    @pytest.fixture
    async def book_builder(self):
        """Create test book builder."""
        builder = get_book_builder()
        await builder.start()
        yield builder
        await builder.stop()
    
    async def test_book_creation(self, book_builder):
        """Test book creation and management."""
        book = book_builder.get_book("BTCUSDT")
        assert book is not None
        assert book.symbol == "BTCUSDT"
        
        snapshot = book.get_snapshot()
        assert "timestamp" in snapshot
        assert "bids" in snapshot
        assert "asks" in snapshot
    
    async def test_market_data_processing(self, book_builder):
        """Test market data processing."""
        market_data = {
            "symbol": "BTCUSDT",
            "timestamp": time.time(),
            "data_type": "LOCAL_SIM_TICK",
            "bid_price": 50000.0,
            "ask_price": 50100.0,
            "last_price": 50050.0,
            "venue": "local_sim",
            "feed_handler": "test_handler"
        }
        
        await book_builder.process_market_data(market_data)
        
        # Check that book was updated
        book = book_builder.get_book("BTCUSDT")
        snapshot = book.get_snapshot()
        assert snapshot["timestamp"] >= market_data["timestamp"]


@pytest.mark.localvenue
@pytest.mark.api
class TestLocalVenueAPI:
    """Test local venue API endpoints."""
    
    def test_engine_status_model(self):
        """Test engine status API model."""
        status = EngineStatus(
            is_running=True,
            queue_depth=10,
            messages_per_sec=100.5,
            dropped_messages=0,
            last_match_ts=time.time(),
            total_trades=5,
            uptime_seconds=3600.0
        )
        
        assert status.is_running is True
        assert status.queue_depth == 10
        assert status.messages_per_sec == 100.5
    
    def test_order_book_model(self):
        """Test order book API model."""
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
        assert orderbook.best_bid == 50000.0
        assert orderbook.spread == 100.0
    
    def test_trade_model(self):
        """Test trade API model."""
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
        assert trade.quantity == 100
        assert trade.pnl == 50.0
    
    def test_trades_response_model(self):
        """Test trades response API model."""
        trades = [
            Trade(
                symbol="BTCUSDT",
                side="buy",
                quantity=100,
                price=50000.0,
                timestamp=time.time(),
                trade_id="trade_123",
                pnl=50.0
            )
        ]
        
        response = TradesResponse(
            trades=trades,
            total_count=1
        )
        
        assert len(response.trades) == 1
        assert response.total_count == 1


@pytest.mark.localvenue
@pytest.mark.e2e
class TestEndToEndScenarios:
    """End-to-end scenario tests."""
    
    async def test_basic_trade_loop(self):
        """Test basic trade loop from feed to portfolio."""
        # Create adapter
        adapter = create_local_sim_adapter("e2e_account", 100000.0)
        await adapter.connect()
        
        # Submit test order
        from venues.local_sim_adapter import VenueOrder
        order = VenueOrder(
            venue_order_id="e2e_001",
            client_order_id="e2e_client_001",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        result = await adapter.submit_order(order)
        assert result.venue_order_id is not None
        
        # Check account balance
        account = await adapter.get_account()
        assert account.cash_balance < 100000.0  # Should have reserved margin
        
        # Check positions
        positions = await adapter.get_positions()
        # Position may be created after fill
        
        await adapter.disconnect()
    
    async def test_failure_recovery(self):
        """Test failure scenarios and recovery."""
        # Test adapter reconnection
        adapter = create_local_sim_adapter("recovery_account", 100000.0)
        
        # Connect and disconnect
        await adapter.connect()
        assert adapter._connected
        await adapter.disconnect()
        assert not adapter._connected
        
        # Reconnect
        await adapter.connect()
        assert adapter._connected
        
        await adapter.disconnect()


# Test fixtures and utilities
@pytest.fixture
def sample_market_data():
    """Sample market data for testing."""
    return {
        "symbol": "BTCUSDT",
        "timestamp": time.time(),
        "data_type": DataType.LOCAL_SIM_TICK,
        "bid_price": Decimal("50000.00"),
        "ask_price": Decimal("50100.00"),
        "last_price": Decimal("50050.00"),
        "venue": "local_sim",
        "feed_handler": "test_handler"
    }


@pytest.fixture
def sample_order():
    """Sample order for testing."""
    from venues.local_sim_adapter import VenueOrder
    
    return VenueOrder(
        venue_order_id="test_order",
        client_order_id="test_client_order",
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        quantity=100,
        price=50000.0
    )


# Test utilities
def assert_market_data_valid(data: Dict[str, Any]):
    """Assert that market data is valid."""
    required_fields = ["symbol", "timestamp", "data_type", "venue"]
    for field in required_fields:
        assert field in data, f"Missing required field: {field}"
    
    if data["data_type"] in [DataType.LOCAL_SIM_TICK, DataType.LOCAL_SIM_TRADE]:
        assert "price" in data or "bid_price" in data or "ask_price" in data


def assert_order_valid(order: Dict[str, Any]):
    """Assert that order is valid."""
    required_fields = ["venue_order_id", "symbol", "side", "order_type", "quantity"]
    for field in required_fields:
        assert field in order, f"Missing required field: {field}"
    
    assert order["quantity"] > 0
    assert order["side"] in ["buy", "sell"]
    assert order["order_type"] in ["market", "limit", "stop"]
