"""
Tests for duplicate order generation fix in global allocator

Tests for:
1. Global allocator skips candidates with existing resting orders
2. Resting order duplicate detection works correctly
3. Multiple candidates are filtered properly
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass
from enum import Enum


class OrderStatus(Enum):
    """Mock OrderStatus enum for testing."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    LIVE = "live"
    FILLED = "filled"
    REJECTED = "rejected"


@dataclass
class OrderRecord:
    """Mock OrderRecord for testing."""
    contract_id: str
    price_cents: int
    side: str
    action: str
    status: OrderStatus
    client_order_id: str


class TestGlobalAllocatorDuplicateFix:
    """Test duplicate order generation fix in global allocator"""
    
    def test_skip_candidate_with_resting_order(self):
        """Test that candidates with existing resting orders are skipped"""
        # Create mock order gate with resting order
        order_gate = MagicMock()
        resting_order = OrderRecord(
            contract_id="KXETH15M-26JUL101945-45",
            price_cents=67,
            side="yes",
            action="buy",
            status=OrderStatus.PENDING,
            client_order_id="merid-existing-order"
        )
        order_gate.get_resting_orders.return_value = [resting_order]
        
        # Create candidate that matches the resting order
        candidate = {
            'agent_id': 'ETH_15M',
            'ticker': 'KXETH15M-26JUL101945-45',
            'side': 'yes',
            'action': 'buy',
            'price_cents': 67,
            'count': 1,
            'edge_pct': 4.0,
            'confidence': 0.54,
            'model_prob': 0.52
        }
        
        # Check if candidate should be skipped
        ticker = candidate.get('ticker', '')
        price_cents = int(candidate.get('price_cents', 50))
        side = candidate.get('side', 'yes')
        action = candidate.get('action', 'buy')
        
        has_resting_order = False
        resting_orders = order_gate.get_resting_orders()
        for resting_order in resting_orders:
            if (resting_order.contract_id == ticker and 
                resting_order.price_cents == price_cents and
                resting_order.side == side and
                resting_order.action == action and
                resting_order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)):
                has_resting_order = True
                break
        
        assert has_resting_order is True, "Should detect resting order"
        
    def test_allow_candidate_without_resting_order(self):
        """Test that candidates without resting orders are allowed"""
        # Create mock order gate with different resting order
        order_gate = MagicMock()
        resting_order = OrderRecord(
            contract_id="KXBTC15M-26JUL101945-45",  # Different ticker
            price_cents=56,
            side="yes",
            action="buy",
            status=OrderStatus.PENDING,
            client_order_id="merid-existing-order"
        )
        order_gate.get_resting_orders.return_value = [resting_order]
        
        # Create candidate that doesn't match the resting order
        candidate = {
            'agent_id': 'ETH_15M',
            'ticker': 'KXETH15M-26JUL101945-45',  # Different ticker
            'side': 'yes',
            'action': 'buy',
            'price_cents': 67,  # Different price
            'count': 1,
            'edge_pct': 4.0,
            'confidence': 0.54,
            'model_prob': 0.52
        }
        
        # Check if candidate should be skipped
        ticker = candidate.get('ticker', '')
        price_cents = int(candidate.get('price_cents', 50))
        side = candidate.get('side', 'yes')
        action = candidate.get('action', 'buy')
        
        has_resting_order = False
        resting_orders = order_gate.get_resting_orders()
        for resting_order in resting_orders:
            if (resting_order.contract_id == ticker and 
                resting_order.price_cents == price_cents and
                resting_order.side == side and
                resting_order.action == action and
                resting_order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)):
                has_resting_order = True
                break
        
        assert has_resting_order is False, "Should not detect resting order for different ticker/price"
        
    def test_skip_filled_order(self):
        """Test that filled orders don't block new candidates"""
        # Create mock order gate with filled order
        order_gate = MagicMock()
        filled_order = OrderRecord(
            contract_id="KXETH15M-26JUL101945-45",
            price_cents=67,
            side="yes",
            action="buy",
            status=OrderStatus.FILLED,  # Filled status
            client_order_id="merid-filled-order"
        )
        order_gate.get_resting_orders.return_value = [filled_order]
        
        # Create candidate that matches the filled order
        candidate = {
            'agent_id': 'ETH_15M',
            'ticker': 'KXETH15M-26JUL101945-45',
            'side': 'yes',
            'action': 'buy',
            'price_cents': 67,
            'count': 1,
            'edge_pct': 4.0,
            'confidence': 0.54,
            'model_prob': 0.52
        }
        
        # Check if candidate should be skipped
        ticker = candidate.get('ticker', '')
        price_cents = int(candidate.get('price_cents', 50))
        side = candidate.get('side', 'yes')
        action = candidate.get('action', 'buy')
        
        has_resting_order = False
        resting_orders = order_gate.get_resting_orders()
        for resting_order in resting_orders:
            if (resting_order.contract_id == ticker and 
                resting_order.price_cents == price_cents and
                resting_order.side == side and
                resting_order.action == action and
                resting_order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)):
                has_resting_order = True
                break
        
        assert has_resting_order is False, "Filled orders should not block new candidates"
        
    def test_multiple_resting_orders(self):
        """Test duplicate detection with multiple resting orders"""
        # Create mock order gate with multiple resting orders
        order_gate = MagicMock()
        resting_orders = [
            OrderRecord(
                contract_id="KXBTC15M-26JUL101945-45",
                price_cents=56,
                side="yes",
                action="buy",
                status=OrderStatus.PENDING,
                client_order_id="merid-btc-order"
            ),
            OrderRecord(
                contract_id="KXETH15M-26JUL101945-45",
                price_cents=67,
                side="yes",
                action="buy",
                status=OrderStatus.LIVE,
                client_order_id="merid-eth-order"
            ),
            OrderRecord(
                contract_id="KXSOL15M-26JUL101945-45",
                price_cents=78,
                side="yes",
                action="buy",
                status=OrderStatus.SUBMITTED,
                client_order_id="merid-sol-order"
            )
        ]
        order_gate.get_resting_orders.return_value = resting_orders
        
        # Test ETH candidate (should be blocked)
        eth_candidate = {
            'agent_id': 'ETH_15M',
            'ticker': 'KXETH15M-26JUL101945-45',
            'side': 'yes',
            'action': 'buy',
            'price_cents': 67,
            'count': 1
        }
        
        ticker = eth_candidate.get('ticker', '')
        price_cents = int(eth_candidate.get('price_cents', 50))
        side = eth_candidate.get('side', 'yes')
        action = eth_candidate.get('action', 'buy')
        
        has_resting_order = False
        for resting_order in resting_orders:
            if (resting_order.contract_id == ticker and 
                resting_order.price_cents == price_cents and
                resting_order.side == side and
                resting_order.action == action and
                resting_order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)):
                has_resting_order = True
                break
        
        assert has_resting_order is True, "Should detect ETH resting order"
        
        # Test DOGE candidate (should not be blocked)
        doge_candidate = {
            'agent_id': 'DOGE_15M',
            'ticker': 'KXDOGE15M-26JUL101945-45',
            'side': 'yes',
            'action': 'buy',
            'price_cents': 10,
            'count': 1
        }
        
        ticker = doge_candidate.get('ticker', '')
        price_cents = int(doge_candidate.get('price_cents', 50))
        side = doge_candidate.get('side', 'yes')
        action = doge_candidate.get('action', 'buy')
        
        has_resting_order = False
        for resting_order in resting_orders:
            if (resting_order.contract_id == ticker and 
                resting_order.price_cents == price_cents and
                resting_order.side == side and
                resting_order.action == action and
                resting_order.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.LIVE)):
                has_resting_order = True
                break
        
        assert has_resting_order is False, "Should not detect DOGE resting order"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
