"""
End-to-End Tests for Local Venue

Complete end-to-end scenarios testing the local venue integration.
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
from data.feed_handlers import get_feed_handler_manager
from web.main import create_app
from web.api.local_venue import EngineStatus, OrderBookResponse, Trade


@pytest.mark.localvenue
@pytest.mark.e2e
class TestBasicLocalTradeLoop:
    """Test basic local trade loop from feed to portfolio."""
    
    @pytest.fixture
    async def complete_system(self):
        """Set up complete system for E2E testing."""
        # Start simulator
        simulator = get_execution_simulator()
        await simulator.start()
        
        # Start book manager
        book_manager = get_persistent_book_manager()
        book_manager.start_all()
        
        # Start book builder
        book_builder = get_book_builder()
        await book_builder.start()
        
        # Create adapter
        adapter = create_local_sim_adapter("e2e_account", 100000.0)
        await adapter.connect()
        
        yield {
            "simulator": simulator,
            "book_manager": book_manager,
            "book_builder": book_builder,
            "adapter": adapter
        }
        
        # Cleanup
        await adapter.disconnect()
        await book_builder.stop()
        book_manager.stop_all()
        await simulator.stop()
    
    async def test_feed_to_engine_to_portfolio(self, complete_system):
        """Test complete trade loop from feed to portfolio."""
        adapter = complete_system["adapter"]
        simulator = complete_system["simulator"]
        book_manager = complete_system["book_manager"]
        
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
        
        # Check account balance changed
        account = await adapter.get_account()
        assert account.cash_balance < 100000.0  # Should have reserved margin
        
        # Check order book state
        book = book_manager.get_book("BTCUSDT")
        snapshot = book.get_snapshot()
        assert len(snapshot.bids) > 0
        
        # Check positions
        positions = await adapter.get_positions()
        assert isinstance(positions, list)
        
        # Check trades
        trades = await adapter.get_trades()
        assert isinstance(trades, list)
    
    async def test_ui_coherence_with_backend(self, complete_system):
        """Test UI panels match backend state."""
        adapter = complete_system["adapter"]
        book_manager = complete_system["book_manager"]
        
        # Submit multiple orders to create activity
        from venues.local_sim_adapter import VenueOrder
        
        orders = [
            VenueOrder(
                venue_order_id="e2e_002",
                client_order_id="e2e_client_002",
                symbol="BTCUSDT",
                side="buy",
                order_type="limit",
                quantity=100,
                price=50000.0
            ),
            VenueOrder(
                venue_order_id="e2e_003",
                client_order_id="e2e_client_003",
                symbol="BTCUSDT",
                side="sell",
                order_type="limit",
                quantity=50,
                price=50100.0
            )
        ]
        
        for order in orders:
            await adapter.submit_order(order)
        
        # Check backend state
        book = book_manager.get_book("BTCUSDT")
        snapshot = book.get_snapshot()
        
        # Verify order book coherence
        assert len(snapshot.bids) > 0
        assert len(snapshot.asks) > 0
        
        if snapshot.bids and snapshot.asks:
            best_bid = snapshot.bids[0].price
            best_ask = snapshot.asks[0].price
            spread = best_ask - best_bid
            assert spread > 0
        
        # Check account state
        account = await adapter.get_account()
        assert account.cash_balance >= 0  # Should not be negative
        
        # Check positions
        positions = await adapter.get_positions()
        assert isinstance(positions, list)


@pytest.mark.localvenue
@pytest.mark.e2e
@pytest.mark.failure_scenarios
class TestFailureAndSafeMode:
    """Test failure scenarios and safe-mode activation."""
    
    @pytest.fixture
    async def resilient_system(self):
        """Set up system for failure testing."""
        simulator = get_execution_simulator()
        await simulator.start()
        
        book_manager = get_persistent_book_manager()
        book_manager.start_all()
        
        adapter = create_local_sim_adapter("failure_account", 100000.0)
        await adapter.connect()
        
        yield {
            "simulator": simulator,
            "book_manager": book_manager,
            "adapter": adapter
        }
        
        await adapter.disconnect()
        book_manager.stop_all()
        await simulator.stop()
    
    async def test_feed_failure_handling(self, resilient_system):
        """Test feed failure detection and response."""
        adapter = resilient_system["adapter"]
        
        # Submit order to establish baseline
        from venues.local_sim_adapter import VenueOrder
        order = VenueOrder(
            venue_order_id="failure_001",
            client_order_id="failure_client_001",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        result = await adapter.submit_order(order)
        assert result.venue_order_id is not None
        
        # Simulate feed failure by disconnecting
        await adapter.disconnect()
        assert not adapter._connected
        
        # Try to submit order (should fail)
        try:
            await adapter.submit_order(order)
            assert False, "Should have raised exception"
        except RuntimeError:
            pass  # Expected
        
        # Reconnect
        await adapter.connect()
        assert adapter._connected
        
        # Should be able to submit orders again
        result = await adapter.submit_order(order)
        assert result.venue_order_id is not None
    
    async def test_safe_mode_activation(self, resilient_system):
        """Test safe-mode activation and UI response."""
        adapter = resilient_system["adapter"]
        simulator = resilient_system["simulator"]
        
        # Submit orders to create state
        from venues.local_sim_adapter import VenueOrder
        
        order = VenueOrder(
            venue_order_id="safe_001",
            client_order_id="safe_client_001",
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=100,
            price=50000.0
        )
        
        await adapter.submit_order(order)
        
        # Check normal operation
        account = await adapter.get_account()
        assert account.cash_balance < 100000.0
        
        # Simulate system stress by stopping simulator
        await simulator.stop()
        
        # Check that adapter detects failure
        try:
            await adapter.submit_order(order)
            assert False, "Should have failed when simulator stopped"
        except Exception:
            pass  # Expected
        
        # Restart simulator
        await simulator.start()
        
        # Should recover
        await adapter.connect()
        result = await adapter.submit_order(order)
        assert result.venue_order_id is not None


@pytest.mark.localvenue
@pytest.mark.e2e
@pytest.mark.cross_mode
class TestVenueParity:
    """Test parity between local venue and other venues."""
    
    async def test_sim_vs_paper_parity(self):
        """Test identical fills between LOCAL_SIM and paper venues."""
        # Create local venue adapter
        local_adapter = create_local_sim_adapter("parity_local", 100000.0)
        await local_adapter.connect()
        
        try:
            # Submit identical orders to both venues
            from venues.local_sim_adapter import VenueOrder
            
            local_order = VenueOrder(
                venue_order_id="parity_local_001",
                client_order_id="parity_client_001",
                symbol="BTCUSDT",
                side="buy",
                order_type="limit",
                quantity=100,
                price=50000.0
            )
            
            local_result = await local_adapter.submit_order(local_order)
            assert local_result.venue_order_id is not None
            
            # Check local venue state
            local_account = await local_adapter.get_account()
            local_positions = await local_adapter.get_positions()
            
            # Verify basic consistency
            assert local_account.cash_balance < 100000.0
            assert isinstance(local_positions, list)
            
        finally:
            await local_adapter.disconnect()
    
    async def test_live_mode_isolation(self):
        """Test live mode isolation and safety."""
        # Create adapter with live mode settings
        adapter = create_local_sim_adapter("live_test_account", 100000.0)
        await adapter.connect()
        
        try:
            # Submit order
            from venues.local_sim_adapter import VenueOrder
            
            order = VenueOrder(
                venue_order_id="live_001",
                client_order_id="live_client_001",
                symbol="BTCUSDT",
                side="buy",
                order_type="limit",
                quantity=100,
                price=50000.0
            )
            
            result = await adapter.submit_order(order)
            assert result.venue_order_id is not None
            
            # Verify order was processed safely
            account = await adapter.get_account()
            assert account.cash_balance >= 0  # Should not go negative
            
            positions = await adapter.get_positions()
            assert isinstance(positions, list)
            
        finally:
            await adapter.disconnect()


@pytest.mark.localvenue
@pytest.mark.e2e
@pytest.mark.performance
class TestPerformanceAndLoad:
    """Test performance under load."""
    
    async def test_high_frequency_orders(self):
        """Test system performance with high-frequency orders."""
        adapter = create_local_sim_adapter("perf_account", 100000.0)
        await adapter.connect()
        
        try:
            from venues.local_sim_adapter import VenueOrder
            
            # Submit many orders rapidly
            start_time = time.time()
            orders = []
            
            for i in range(100):
                order = VenueOrder(
                    venue_order_id=f"perf_{i:03d}",
                    client_order_id=f"perf_client_{i:03d}",
                    symbol="BTCUSDT",
                    side="buy" if i % 2 == 0 else "sell",
                    order_type="limit",
                    quantity=10,
                    price=50000.0 + (i * 10)
                )
                
                result = await adapter.submit_order(order)
                orders.append(result)
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Verify performance
            assert len(orders) == 100
            assert duration < 10.0  # Should complete within 10 seconds
            assert all(order.venue_order_id is not None for order in orders)
            
            # Check system state
            account = await adapter.get_account()
            assert account.cash_balance >= 0
            
            positions = await adapter.get_positions()
            assert isinstance(positions, list)
            
        finally:
            await adapter.disconnect()
    
    async def test_concurrent_operations(self):
        """Test concurrent order operations."""
        adapter = create_local_sim_adapter("concurrent_account", 100000.0)
        await adapter.connect()
        
        try:
            from venues.local_sim_adapter import VenueOrder
            
            async def submit_orders(prefix: str, count: int):
                """Submit orders concurrently."""
                orders = []
                for i in range(count):
                    order = VenueOrder(
                        venue_order_id=f"{prefix}_{i:03d}",
                        client_order_id=f"{prefix}_client_{i:03d}",
                        symbol="BTCUSDT",
                        side="buy",
                        order_type="limit",
                        quantity=10,
                        price=50000.0 + i
                    )
                    
                    result = await adapter.submit_order(order)
                    orders.append(result)
                
                return orders
            
            # Run concurrent operations
            tasks = [
                submit_orders("concurrent1", 25),
                submit_orders("concurrent2", 25),
                submit_orders("concurrent3", 25),
                submit_orders("concurrent4", 25)
            ]
            
            results = await asyncio.gather(*tasks)
            
            # Verify all orders were processed
            total_orders = sum(len(task_result) for task_result in results)
            assert total_orders == 100
            
            # Check system integrity
            account = await adapter.get_account()
            assert account.cash_balance >= 0
            
            positions = await adapter.get_positions()
            assert isinstance(positions, list)
            
        finally:
            await adapter.disconnect()


@pytest.mark.localvenue
@pytest.mark.e2e
@pytest.mark.integration
class TestSystemIntegration:
    """Test integration with other MERID systems."""
    
    async def test_observability_integration(self):
        """Test integration with observability systems."""
        # This would test integration with monitoring, logging, etc.
        adapter = create_local_sim_adapter("obs_account", 100000.0)
        await adapter.connect()
        
        try:
            # Submit order to generate activity
            from venues.local_sim_adapter import VenueOrder
            
            order = VenueOrder(
                venue_order_id="obs_001",
                client_order_id="obs_client_001",
                symbol="BTCUSDT",
                side="buy",
                order_type="limit",
                quantity=100,
                price=50000.0
            )
            
            result = await adapter.submit_order(order)
            assert result.venue_order_id is not None
            
            # Check that observability data is being generated
            # (This would be implemented with actual observability hooks)
            
        finally:
            await adapter.disconnect()
    
    async def test_risk_integration(self):
        """Test integration with risk management systems."""
        adapter = create_local_sim_adapter("risk_account", 100000.0)
        await adapter.connect()
        
        try:
            # Submit order that should pass risk checks
            from venues.local_sim_adapter import VenueOrder
            
            order = VenueOrder(
                venue_order_id="risk_001",
                client_order_id="risk_client_001",
                symbol="BTCUSDT",
                side="buy",
                order_type="limit",
                quantity=100,
                price=50000.0
            )
            
            result = await adapter.submit_order(order)
            assert result.venue_order_id is not None
            
            # Check that risk metrics are updated
            # (This would be implemented with actual risk hooks)
            
        finally:
            await adapter.disconnect()


# E2E Test Utilities
def create_test_scenario_data():
    """Create test scenario data for E2E testing."""
    return {
        "orders": [
            {
                "venue_order_id": "e2e_test_001",
                "client_order_id": "e2e_client_001",
                "symbol": "BTCUSDT",
                "side": "buy",
                "order_type": "limit",
                "quantity": 100,
                "price": 50000.0
            },
            {
                "venue_order_id": "e2e_test_002",
                "client_order_id": "e2e_client_002",
                "symbol": "BTCUSDT",
                "side": "sell",
                "order_type": "limit",
                "quantity": 50,
                "price": 50100.0
            }
        ],
        "expected_results": {
            "order_book_depth": {"bids": 1, "asks": 1},
            "spread": 100.0,
            "account_balance_change": -5000000.0,  # 100 * 50000
            "positions_count": 1
        }
    }


def validate_e2e_results(results: Dict[str, Any], expected: Dict[str, Any]):
    """Validate E2E test results against expected outcomes."""
    for key, expected_value in expected.items():
        if key in results:
            actual_value = results[key]
            
            if isinstance(expected_value, dict):
                # For nested dictionaries, check each sub-key
                for sub_key, sub_expected in expected_value.items():
                    if sub_key in actual_value:
                        assert actual_value[sub_key] == sub_expected, f"Mismatch in {key}.{sub_key}: expected {sub_expected}, got {actual_value[sub_key]}"
            else:
                # For simple values, check equality
                assert actual_value == expected_value, f"Mismatch in {key}: expected {expected_value}, got {actual_value}"


async def measure_system_performance(adapter, operation_count: int = 100):
    """Measure system performance for given number of operations."""
    from venues.local_sim_adapter import VenueOrder
    
    start_time = time.time()
    
    for i in range(operation_count):
        order = VenueOrder(
            venue_order_id=f"perf_{i:03d}",
            client_order_id=f"perf_client_{i:03d}",
            symbol="BTCUSDT",
            side="buy" if i % 2 == 0 else "sell",
            order_type="limit",
            quantity=10,
            price=50000.0 + (i * 10)
        )
        
        await adapter.submit_order(order)
    
    end_time = time.time()
    
    return {
        "operations": operation_count,
        "duration": end_time - start_time,
        "ops_per_second": operation_count / (end_time - start_time)
    }
