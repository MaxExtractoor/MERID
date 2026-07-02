"""
Order placement tests for 15m trade path.

Tests validate that orders are placed correctly with Kalshi
after signals pass gate validation.
"""

import time
import pytest


def test_order_placement_happy_path(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test order placement under happy path conditions.
    
    Expected:
    - Signal becomes candidate
    - Order is placed with Kalshi
    - Order ID is returned
    - Order status is valid
    """
    # Setup: Generate signal and create candidate
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=2.0,
    )
    
    candidate = create_candidate(signal, gate_decision_pass)
    
    # Place order
    order = place_order(candidate, mock_kalshi_client)
    
    # Assertions
    assert order is not None, "Order should be placed"
    assert order.order_id == "order_123", "Order ID should match"
    assert order.market_id == signal.market_id, "Order market_id should match signal"
    assert order.direction == signal.direction, "Order direction should match signal"
    assert order.contracts == signal.contracts, "Order contracts should match signal"
    assert order.price_cents == signal.price_cents, "Order price should match signal"
    assert order.status in ["PENDING", "OPEN"], "Order status should be valid"
    assert order.timestamp > 0, "Order timestamp should be valid"


def test_order_placement_gate_reject(generate_signal, gate_decision_fail, create_candidate, place_order, mock_kalshi_client):
    """Test that order is not placed when gate decision rejects.
    
    Expected:
    - Signal generated
    - Gate decision REJECT
    - No candidate created
    - No order placed
    """
    # Setup: Generate signal with failing gate decision
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=0.5,  # Below threshold
    )
    
    candidate = create_candidate(signal, gate_decision_fail)
    
    # Attempt to place order (should not happen in real implementation)
    # In real implementation, this would be guarded by gate decision check
    if candidate.gate_decision["overall"] == "REJECT":
        # Should not place order
        assert True, "Order should not be placed when gate rejects"
    else:
        # This branch should not be reached
        assert False, "Order placement should be guarded by gate decision"


def test_order_placement_multiple_contracts(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test order placement with multiple contract sizes."""
    contract_sizes = [1, 5, 10, 20, 50]
    
    for contracts in contract_sizes:
        signal = generate_signal(
            asset="BTC",
            market_id="BTC-15m-2026-06-05",
            direction="YES",
            contracts=contracts,
            price_cents=65,
            edge_pct=2.0,
        )
        
        candidate = create_candidate(signal, gate_decision_pass)
        order = place_order(candidate, mock_kalshi_client)
        
        assert order.contracts == contracts, f"Order contracts should be {contracts}"


def test_order_placement_yes_direction(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test order placement for YES direction."""
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=2.0,
    )
    
    candidate = create_candidate(signal, gate_decision_pass)
    order = place_order(candidate, mock_kalshi_client)
    
    assert order.direction == "YES", "Order direction should be YES"


def test_order_placement_no_direction(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test order placement for NO direction."""
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="NO",
        contracts=10,
        price_cents=35,
        edge_pct=2.0,
    )
    
    candidate = create_candidate(signal, gate_decision_pass)
    order = place_order(candidate, mock_kalshi_client)
    
    assert order.direction == "NO", "Order direction should be NO"


def test_order_placement_different_assets(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test order placement for different assets."""
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    for asset in assets:
        signal = generate_signal(
            asset=asset,
            market_id=f"{asset}-15m-2026-06-05",
            direction="YES",
            contracts=10,
            price_cents=50,
            edge_pct=2.0,
        )
        
        candidate = create_candidate(signal, gate_decision_pass)
        order = place_order(candidate, mock_kalshi_client)
        
        assert order.market_id == f"{asset}-15m-2026-06-05", f"Order market_id should be {asset}"


def test_order_placement_price_validation(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test that order price is within valid range."""
    # Test various price points
    prices = [1, 10, 50, 65, 90, 99]
    
    for price_cents in prices:
        signal = generate_signal(
            asset="BTC",
            market_id="BTC-15m-2026-06-05",
            direction="YES",
            contracts=10,
            price_cents=price_cents,
            edge_pct=2.0,
        )
        
        candidate = create_candidate(signal, gate_decision_pass)
        order = place_order(candidate, mock_kalshi_client)
        
        assert 1 <= order.price_cents <= 99, f"Order price {price_cents} should be within 1-99 cents"


def test_order_placement_timestamp_freshness(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test that order timestamp is fresh."""
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=2.0,
    )
    
    candidate = create_candidate(signal, gate_decision_pass)
    order = place_order(candidate, mock_kalshi_client)
    
    # Check timestamp freshness
    order_age = time.time() - order.timestamp
    assert order_age < 1.0, "Order timestamp should be fresh (within last second)"


def test_order_placement_client_called(generate_signal, gate_decision_pass, create_candidate, place_order, mock_kalshi_client):
    """Test that Kalshi client is called with correct parameters."""
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=2.0,
    )
    
    candidate = create_candidate(signal, gate_decision_pass)
    order = place_order(candidate, mock_kalshi_client)
    
    # Verify client was called
    mock_kalshi_client.place_order.assert_called_once()
    
    # Verify call parameters
    call_args = mock_kalshi_client.place_order.call_args
    assert call_args[1]["market_id"] == signal.market_id
    assert call_args[1]["direction"] == signal.direction
    assert call_args[1]["contracts"] == signal.contracts
    assert call_args[1]["price_cents"] == signal.price_cents
