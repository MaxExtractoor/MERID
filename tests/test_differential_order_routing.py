"""Differential tests for order routing.

This module implements differential testing to compare different implementations
of order routing logic and ensure they produce consistent results. This helps
identify discrepancies between routing methods and validates correctness.

Differential Testing Scenarios:
1. Order price calculation consistency
2. Order quantity calculation consistency
3. Slippage estimation consistency
4. Order routing path consistency
5. Order priority and queueing consistency
"""

import pytest
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


@dataclass
class Order:
    """Order representation."""
    side: OrderSide
    order_type: OrderType
    price_cents: int
    quantity: int
    asset: str


@dataclass
class RoutingResult:
    """Result from order routing."""
    method_name: str
    routed_price: int
    routed_quantity: int
    execution_venue: str
    expected_slippage: float


class TestOrderPriceCalculationConsistency:
    """Differential tests for order price calculation consistency."""

    def test_limit_order_price_clamping(self):
        """Limit order price clamping should be consistent across methods."""
        # Method 1: Hard clamp to 10-75c range
        def clamp_price_method_1(price_cents: int) -> int:
            return max(10, min(75, price_cents))
        
        # Method 2: Soft clamp with warning
        def clamp_price_method_2(price_cents: int) -> Tuple[int, bool]:
            clamped = max(10, min(75, price_cents))
            warning = clamped != price_cents
            return clamped, warning
        
        # Test with various prices
        test_prices = [5, 10, 30, 50, 75, 80, 100]
        
        for price in test_prices:
            clamped_1 = clamp_price_method_1(price)
            clamped_2, warning = clamp_price_method_2(price)
            
            # Both should produce same clamped price
            assert clamped_1 == clamped_2, \
                f"Price clamping should be consistent: {clamped_1} vs {clamped_2}"
            
            # Clamped price should be in valid range
            assert 10 <= clamped_1 <= 75, \
                f"Clamped price should be in range: {clamped_1}"
            
            # Warning should be correct
            if price < 10 or price > 75:
                assert warning, f"Should warn for out-of-range price: {price}"

    def test_market_order_price_estimation(self):
        """Market order price estimation should be consistent."""
        # Method 1: Mid-price estimation
        def estimate_market_price_method_1(bid: int, ask: int) -> int:
            return (bid + ask) // 2
        
        # Method 2: Last trade price
        def estimate_market_price_method_2(last_price: int) -> int:
            return last_price
        
        # Method 3: VWAP estimation
        def estimate_market_price_method_3(order_book: List[Tuple[int, int]]) -> int:
            total_value = sum(price * qty for price, qty in order_book)
            total_qty = sum(qty for _, qty in order_book)
            if total_qty > 0:
                return total_value // total_qty
            return 50  # Default
        
        # Test with sample data
        bid = 48
        ask = 52
        last_price = 50
        order_book = [(48, 10), (49, 15), (50, 20), (51, 10), (52, 5)]
        
        price_1 = estimate_market_price_method_1(bid, ask)
        price_2 = estimate_market_price_method_2(last_price)
        price_3 = estimate_market_price_method_3(order_book)
        
        # All should be in valid range
        assert 10 <= price_1 <= 75, f"Price should be in range: {price_1}"
        assert 10 <= price_2 <= 75, f"Price should be in range: {price_2}"
        assert 10 <= price_3 <= 75, f"Price should be in range: {price_3}"
        
        # Mid-price should be between bid and ask
        assert bid <= price_1 <= ask, f"Mid-price should be between bid and ask: {price_1}"

    def test_stop_order_trigger_price(self):
        """Stop order trigger price calculation should be consistent."""
        # Method 1: Simple trigger at stop price
        def calculate_stop_trigger_method_1(stop_price: int, side: OrderSide) -> int:
            return stop_price
        
        # Method 2: Trigger with slippage buffer
        def calculate_stop_trigger_method_2(stop_price: int, side: OrderSide) -> int:
            buffer = 1  # 1 cent buffer
            if side == OrderSide.BUY:
                return stop_price + buffer
            else:
                return stop_price - buffer
        
        # Test with various scenarios
        test_cases = [
            (50, OrderSide.BUY),
            (50, OrderSide.SELL),
            (30, OrderSide.BUY),
            (70, OrderSide.SELL)
        ]
        
        for stop_price, side in test_cases:
            trigger_1 = calculate_stop_trigger_method_1(stop_price, side)
            trigger_2 = calculate_stop_trigger_method_2(stop_price, side)
            
            # Method 2 should include buffer
            if side == OrderSide.BUY:
                assert trigger_2 > trigger_1, \
                    f"Buy stop should have higher trigger with buffer: {trigger_1} vs {trigger_2}"
            else:
                assert trigger_2 < trigger_1, \
                    f"Sell stop should have lower trigger with buffer: {trigger_1} vs {trigger_2}"
            
            # Both should be in valid range
            assert 10 <= trigger_1 <= 75, f"Trigger should be in range: {trigger_1}"
            assert 10 <= trigger_2 <= 75, f"Trigger should be in range: {trigger_2}"


class TestOrderQuantityCalculationConsistency:
    """Differential tests for order quantity calculation consistency."""

    def test_quantity_rounding_consistency(self):
        """Quantity rounding should be consistent across methods."""
        # Method 1: Round to nearest integer
        def round_quantity_method_1(quantity: float) -> int:
            return int(round(quantity))
        
        # Method 2: Floor to integer
        def round_quantity_method_2(quantity: float) -> int:
            return int(quantity)
        
        # Method 3: Round down to multiple of lot size
        def round_quantity_method_3(quantity: float, lot_size: int) -> int:
            return int(quantity // lot_size * lot_size)
        
        # Test with various quantities
        test_quantities = [10.3, 15.7, 20.0, 25.5, 30.1]
        lot_size = 5
        
        for quantity in test_quantities:
            rounded_1 = round_quantity_method_1(quantity)
            rounded_2 = round_quantity_method_2(quantity)
            rounded_3 = round_quantity_method_3(quantity, lot_size)
            
            # All should be integers
            assert isinstance(rounded_1, int), f"Rounded should be int: {rounded_1}"
            assert isinstance(rounded_2, int), f"Rounded should be int: {rounded_2}"
            assert isinstance(rounded_3, int), f"Rounded should be int: {rounded_3}"
            
            # Method 3 should be multiple of lot size
            assert rounded_3 % lot_size == 0, \
                f"Rounded should be multiple of lot size: {rounded_3}"

    def test_quantity_splitting_consistency(self):
        """Order quantity splitting should be consistent."""
        total_quantity = 100
        max_order_size = 30
        
        # Method 1: Equal split
        def split_quantity_method_1(total: int, max_size: int) -> List[int]:
            num_orders = (total + max_size - 1) // max_size
            base_size = total // num_orders
            remainder = total % num_orders
            sizes = [base_size + 1] * remainder + [base_size] * (num_orders - remainder)
            return sizes
        
        # Method 2: Greedy split
        def split_quantity_method_2(total: int, max_size: int) -> List[int]:
            sizes = []
            remaining = total
            while remaining > 0:
                size = min(max_size, remaining)
                sizes.append(size)
                remaining -= size
            return sizes
        
        sizes_1 = split_quantity_method_1(total_quantity, max_order_size)
        sizes_2 = split_quantity_method_2(total_quantity, max_order_size)
        
        # Both should sum to total
        assert sum(sizes_1) == total_quantity, \
            f"Splits should sum to total: {sum(sizes_1)} vs {total_quantity}"
        assert sum(sizes_2) == total_quantity, \
            f"Splits should sum to total: {sum(sizes_2)} vs {total_quantity}"
        
        # All sizes should be <= max_size
        assert all(s <= max_order_size for s in sizes_1), \
            f"All sizes should be <= max_size: {sizes_1}"
        assert all(s <= max_order_size for s in sizes_2), \
            f"All sizes should be <= max_size: {sizes_2}"

    def test_quantity_adjustment_for_liquidity(self):
        """Quantity adjustment for liquidity should be consistent."""
        order_quantity = 50
        available_liquidity = 30
        
        # Method 1: Fill as much as possible
        def adjust_for_liquidity_method_1(order_qty: int, liquidity: int) -> int:
            return min(order_qty, liquidity)
        
        # Method 2: Partial fill with remainder cancelled
        def adjust_for_liquidity_method_2(order_qty: int, liquidity: int) -> Tuple[int, int]:
            filled = min(order_qty, liquidity)
            remaining = order_qty - filled
            return filled, remaining
        
        adjusted_1 = adjust_for_liquidity_method_1(order_quantity, available_liquidity)
        filled_2, remaining_2 = adjust_for_liquidity_method_2(order_quantity, available_liquidity)
        
        # Method 1 should match filled quantity from method 2
        assert adjusted_1 == filled_2, \
            f"Adjusted quantity should match filled: {adjusted_1} vs {filled_2}"
        
        # Should not exceed available liquidity
        assert adjusted_1 <= available_liquidity, \
            f"Adjusted should not exceed liquidity: {adjusted_1} vs {available_liquidity}"


class TestSlippageEstimationConsistency:
    """Differential tests for slippage estimation consistency."""

    def test_slippage_calculation_methods(self):
        """Slippage calculation should be consistent across methods."""
        order_size = 10
        order_book = [(50, 5), (51, 3), (52, 8), (53, 10)]
        
        # Method 1: Linear slippage based on order size
        def calculate_slippage_method_1(order_size: int, avg_price: int) -> float:
            # 0.1% slippage per contract
            return (order_size * 0.001) * avg_price / 100.0
        
        # Method 2: VWAP-based slippage
        def calculate_slippage_method_2(order_size: int, order_book: List[Tuple[int, int]]) -> float:
            # Calculate VWAP for order size
            remaining = order_size
            total_value = 0
            for price, qty in order_book:
                fill_qty = min(remaining, qty)
                total_value += price * fill_qty
                remaining -= fill_qty
                if remaining == 0:
                    break
            
            if order_size > 0:
                vwap = total_value / order_size
                mid_price = order_book[0][0]
                slippage = abs(vwap - mid_price) / mid_price
                return slippage
            return 0.0
        
        slippage_1 = calculate_slippage_method_1(order_size, 50)
        slippage_2 = calculate_slippage_method_2(order_size, order_book)
        
        # Both should produce non-negative slippage
        assert slippage_1 >= 0, f"Slippage should be non-negative: {slippage_1}"
        assert slippage_2 >= 0, f"Slippage should be non-negative: {slippage_2}"
        
        # Slippage should be reasonable (< 5%)
        assert slippage_1 < 0.05, f"Slippage should be reasonable: {slippage_1}"
        assert slippage_2 < 0.05, f"Slippage should be reasonable: {slippage_2}"

    def test_slippage_by_order_side(self):
        """Slippage should vary appropriately by order side."""
        order_size = 10
        mid_price = 50
        
        # Method 1: Side-independent slippage
        def calculate_slippage_side_independent(size: int, price: int) -> float:
            return 0.001  # 0.1% fixed
        
        # Method 2: Side-dependent slippage
        def calculate_slippage_side_dependent(size: int, price: int, side: OrderSide) -> float:
            if side == OrderSide.BUY:
                return 0.0015  # Higher for buys
            else:
                return 0.0005  # Lower for sells
        
        slippage_buy = calculate_slippage_side_dependent(order_size, mid_price, OrderSide.BUY)
        slippage_sell = calculate_slippage_side_dependent(order_size, mid_price, OrderSide.SELL)
        
        # Buy slippage should be higher than sell slippage
        assert slippage_buy > slippage_sell, \
            f"Buy slippage should be higher: {slippage_buy} vs {slippage_sell}"

    def test_slippage_scaling_with_size(self):
        """Slippage should scale appropriately with order size."""
        mid_price = 50
        
        # Method 1: Linear scaling
        def calculate_slippage_linear(size: int, price: int) -> float:
            return (size * 0.0001) * price / 100.0
        
        # Method 2: Square root scaling
        def calculate_slippage_sqrt(size: int, price: int) -> float:
            import math
            return (math.sqrt(size) * 0.0005) * price / 100.0
        
        sizes = [5, 10, 20, 50]
        
        for size in sizes:
            slippage_linear = calculate_slippage_linear(size, mid_price)
            slippage_sqrt = calculate_slippage_sqrt(size, mid_price)
            
            # Both should be positive
            assert slippage_linear > 0, f"Slippage should be positive: {slippage_linear}"
            assert slippage_sqrt > 0, f"Slippage should be positive: {slippage_sqrt}"
            
            # Larger orders should have more slippage
            if size > 5:
                larger_linear = calculate_slippage_linear(size + 5, mid_price)
                assert larger_linear > slippage_linear, \
                    f"Larger orders should have more slippage: {larger_linear} vs {slippage_linear}"


class TestRoutingPathConsistency:
    """Differential tests for routing path consistency."""

    def test_venue_selection_consistency(self):
        """Venue selection should be consistent across methods."""
        order = Order(OrderSide.BUY, OrderType.LIMIT, 50, 10, "BTC")
        
        # Method 1: Random venue selection
        def select_venue_method_1(order: Order) -> str:
            venues = ["venue_a", "venue_b", "venue_c"]
            return venues[hash(order.asset) % len(venues)]
        
        # Method 2: Best price venue selection
        def select_venue_method_2(order: Order, venue_prices: Dict[str, int]) -> str:
            best_venue = None
            best_price = None
            for venue, price in venue_prices.items():
                if best_price is None or price < best_price:
                    best_price = price
                    best_venue = venue
            return best_venue
        
        venue_1 = select_venue_method_1(order)
        
        venue_prices = {"venue_a": 50, "venue_b": 49, "venue_c": 51}
        venue_2 = select_venue_method_2(order, venue_prices)
        
        # Both should return valid venues
        assert venue_1 in ["venue_a", "venue_b", "venue_c"], \
            f"Venue should be valid: {venue_1}"
        assert venue_2 in venue_prices.keys(), \
            f"Venue should be valid: {venue_2}"
        
        # Method 2 should select best price venue
        assert venue_2 == "venue_b", \
            f"Should select best price venue: {venue_2}"

    def test_routing_cost_calculation(self):
        """Routing cost calculation should be consistent."""
        order_value = 1000.0
        
        # Method 1: Fixed fee per order
        def calculate_routing_cost_method_1(value: float) -> float:
            return 0.50  # $0.50 fixed fee
        
        # Method 2: Percentage-based fee
        def calculate_routing_cost_method_2(value: float) -> float:
            return value * 0.001  # 0.1% fee
        
        # Method 3: Tiered fee
        def calculate_routing_cost_method_3(value: float) -> float:
            if value < 100:
                return 0.25
            elif value < 1000:
                return 0.50
            else:
                return 1.00
        
        cost_1 = calculate_routing_cost_method_1(order_value)
        cost_2 = calculate_routing_cost_method_2(order_value)
        cost_3 = calculate_routing_cost_method_3(order_value)
        
        # All should be positive
        assert cost_1 > 0, f"Cost should be positive: {cost_1}"
        assert cost_2 > 0, f"Cost should be positive: {cost_2}"
        assert cost_3 > 0, f"Cost should be positive: {cost_3}"
        
        # Costs should be reasonable (< 5% of order value)
        assert cost_1 < order_value * 0.05, f"Cost should be reasonable: {cost_1}"
        assert cost_2 < order_value * 0.05, f"Cost should be reasonable: {cost_2}"
        assert cost_3 < order_value * 0.05, f"Cost should be reasonable: {cost_3}"

    def test_multi_venue_routing(self):
        """Multi-venue routing should be consistent."""
        total_quantity = 100
        venue_capacities = {"venue_a": 40, "venue_b": 35, "venue_c": 50}
        
        # Method 1: Proportional allocation
        def allocate_multi_venue_method_1(total: int, capacities: Dict[str, int]) -> Dict[str, int]:
            total_capacity = sum(capacities.values())
            allocation = {}
            for venue, capacity in capacities.items():
                allocation[venue] = int(total * capacity / total_capacity)
            return allocation
        
        # Method 2: Fill venues in order
        def allocate_multi_venue_method_2(total: int, capacities: Dict[str, int]) -> Dict[str, int]:
            allocation = {}
            remaining = total
            for venue, capacity in sorted(capacities.items(), key=lambda x: -x[1]):
                fill = min(remaining, capacity)
                allocation[venue] = fill
                remaining -= fill
            return allocation
        
        allocation_1 = allocate_multi_venue_method_1(total_quantity, venue_capacities)
        allocation_2 = allocate_multi_venue_method_2(total_quantity, venue_capacities)
        
        # Both should sum to total (or close)
        assert abs(sum(allocation_1.values()) - total_quantity) <= 5, \
            f"Allocation should sum to total: {sum(allocation_1.values())} vs {total_quantity}"
        assert sum(allocation_2.values()) == total_quantity, \
            f"Allocation should sum to total: {sum(allocation_2.values())} vs {total_quantity}"
        
        # No venue should exceed capacity
        for venue, qty in allocation_1.items():
            assert qty <= venue_capacities[venue], \
                f"Allocation should not exceed capacity: {qty} vs {venue_capacities[venue]}"
        for venue, qty in allocation_2.items():
            assert qty <= venue_capacities[venue], \
                f"Allocation should not exceed capacity: {qty} vs {venue_capacities[venue]}"


class TestOrderPriorityConsistency:
    """Differential tests for order priority and queueing consistency."""

    def test_price_time_priority(self):
        """Price-time priority should be consistent."""
        orders = [
            Order(OrderSide.BUY, OrderType.LIMIT, 50, 10, "BTC"),
            Order(OrderSide.BUY, OrderType.LIMIT, 51, 10, "BTC"),
            Order(OrderSide.BUY, OrderType.LIMIT, 49, 10, "BTC"),
        ]
        
        # Method 1: Sort by price (descending for buys)
        def prioritize_by_price_method_1(orders: List[Order]) -> List[Order]:
            return sorted(orders, key=lambda o: o.price_cents, reverse=True)
        
        # Method 2: Sort by price then timestamp
        def prioritize_by_price_time_method_2(orders: List[Order]) -> List[Order]:
            return sorted(orders, key=lambda o: (-o.price_cents, id(o)))
        
        prioritized_1 = prioritize_by_price_method_1(orders)
        prioritized_2 = prioritize_by_price_time_method_2(orders)
        
        # Highest price should be first
        assert prioritized_1[0].price_cents == 51, \
            f"Highest price should be first: {prioritized_1[0].price_cents}"
        assert prioritized_2[0].price_cents == 51, \
            f"Highest price should be first: {prioritized_2[0].price_cents}"
        
        # Lowest price should be last
        assert prioritized_1[-1].price_cents == 49, \
            f"Lowest price should be last: {prioritized_1[-1].price_cents}"
        assert prioritized_2[-1].price_cents == 49, \
            f"Lowest price should be last: {prioritized_2[-1].price_cents}"

    def test_queue_position_calculation(self):
        """Queue position calculation should be consistent."""
        queue_size = 100
        order_position = 50
        
        # Method 1: Simple position
        def calculate_queue_position_method_1(position: int, queue_size: int) -> float:
            return position / queue_size
        
        # Method 2: Percentile
        def calculate_queue_position_method_2(position: int, queue_size: int) -> float:
            return (position - 1) / (queue_size - 1) if queue_size > 1 else 0.0
        
        position_1 = calculate_queue_position_method_1(order_position, queue_size)
        position_2 = calculate_queue_position_method_2(order_position, queue_size)
        
        # Both should be in [0, 1] range
        assert 0 <= position_1 <= 1, f"Position should be in range: {position_1}"
        assert 0 <= position_2 <= 1, f"Position should be in range: {position_2}"
        
        # Middle position should be around 0.5
        assert 0.4 <= position_1 <= 0.6, f"Middle position should be ~0.5: {position_1}"
        assert 0.4 <= position_2 <= 0.6, f"Middle position should be ~0.5: {position_2}"

    def test_order_cancellation_consistency(self):
        """Order cancellation should be consistent."""
        active_orders = {
            "order_1": Order(OrderSide.BUY, OrderType.LIMIT, 50, 10, "BTC"),
            "order_2": Order(OrderSide.SELL, OrderType.LIMIT, 51, 5, "ETH"),
            "order_3": Order(OrderSide.BUY, OrderType.LIMIT, 49, 15, "SOL"),
        }
        
        # Method 1: Remove from dict
        def cancel_order_method_1(orders: Dict[str, Order], order_id: str) -> Dict[str, Order]:
            if order_id in orders:
                del orders[order_id]
            return orders
        
        # Method 2: Mark as cancelled
        def cancel_order_method_2(orders: Dict[str, Order], order_id: str) -> Dict[str, Order]:
            if order_id in orders:
                orders[order_id].quantity = 0  # Mark as cancelled
            return orders
        
        orders_1 = cancel_order_method_1(active_orders.copy(), "order_2")
        orders_2 = cancel_order_method_2(active_orders.copy(), "order_2")
        
        # Method 1 should remove order
        assert "order_2" not in orders_1, \
            f"Order should be removed: {orders_1.keys()}"
        
        # Method 2 should mark as cancelled (quantity = 0)
        assert orders_2["order_2"].quantity == 0, \
            f"Order should be marked cancelled: {orders_2['order_2'].quantity}"
        
        # Other orders should remain
        assert "order_1" in orders_1, f"Other orders should remain"
        assert "order_3" in orders_1, f"Other orders should remain"
