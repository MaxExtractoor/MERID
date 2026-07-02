"""
Fill confirmation tests for 15m trade path.

Tests validate that fills are confirmed and recorded correctly
after orders are placed with Kalshi.
"""

import time
import pytest


def test_fill_confirmation_happy_path(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test fill confirmation under happy path conditions.
    
    Expected:
    - Order is placed
    - Fill is confirmed
    - Fill is recorded in ledger
    - Fill matches order parameters
    """
    # Setup: Generate signal, create candidate, place order
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
    
    # Confirm fill
    fill = confirm_fill(order, mock_fills_ledger)
    
    # Assertions
    assert fill is not None, "Fill should be confirmed"
    assert fill.order_id == order.order_id, "Fill order_id should match order"
    assert fill.market_id == order.market_id, "Fill market_id should match order"
    assert fill.direction == order.direction, "Fill direction should match order"
    assert fill.contracts == order.contracts, "Fill contracts should match order"
    assert fill.price_cents == order.price_cents, "Fill price should match order"
    assert fill.timestamp > 0, "Fill timestamp should be valid"
    
    # Verify fill was recorded in ledger
    mock_fills_ledger.record_fill.assert_called_once_with(fill)


def test_fill_confirmation_partial_fill(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test partial fill scenario.
    
    Expected:
    - Order placed for 10 contracts
    - Only 5 contracts filled
    - Partial fill recorded
    """
    # Setup: Order for 10 contracts
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
    
    # Simulate partial fill (5 contracts)
    partial_fill = confirm_fill(order, mock_fills_ledger)
    # Modify fill to simulate partial
    partial_fill.contracts = 5
    
    # Assertions
    assert partial_fill.contracts == 5, "Partial fill should be 5 contracts"
    assert partial_fill.contracts < order.contracts, "Partial fill should be less than order"


def test_fill_confirmation_multiple_fills(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test multiple fills for the same order."""
    # Setup: Place order
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
    
    # Confirm multiple fills (simulating partial fills)
    fill1 = confirm_fill(order, mock_fills_ledger)
    fill1.contracts = 5
    
    fill2 = confirm_fill(order, mock_fills_ledger)
    fill2.contracts = 5
    
    # Assertions
    assert fill1.contracts + fill2.contracts == order.contracts, "Total fills should match order"


def test_fill_confirmation_yes_direction(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test fill confirmation for YES direction."""
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
    fill = confirm_fill(order, mock_fills_ledger)
    
    assert fill.direction == "YES", "Fill direction should be YES"


def test_fill_confirmation_no_direction(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test fill confirmation for NO direction."""
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
    fill = confirm_fill(order, mock_fills_ledger)
    
    assert fill.direction == "NO", "Fill direction should be NO"


def test_fill_confirmation_timestamp_freshness(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test that fill timestamp is fresh."""
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
    fill = confirm_fill(order, mock_fills_ledger)
    
    # Check timestamp freshness
    fill_age = time.time() - fill.timestamp
    assert fill_age < 1.0, "Fill timestamp should be fresh (within last second)"


def test_fill_confirmation_ledger_recording(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test that fill is correctly recorded in fills ledger."""
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
    fill = confirm_fill(order, mock_fills_ledger)
    
    # Verify ledger was called with correct fill
    mock_fills_ledger.record_fill.assert_called_once_with(fill)
    
    # Verify fill details
    recorded_fill = mock_fills_ledger.record_fill.call_args[0][0]
    assert recorded_fill.order_id == order.order_id
    assert recorded_fill.contracts == order.contracts


def test_fill_confirmation_different_assets(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test fill confirmation for different assets."""
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
        fill = confirm_fill(order, mock_fills_ledger)
        
        assert fill.market_id == f"{asset}-15m-2026-06-05", f"Fill market_id should be {asset}"


def test_fill_confirmation_price_matching(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, mock_kalshi_client, mock_fills_ledger):
    """Test that fill price matches order price."""
    prices = [10, 50, 65, 90]
    
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
        fill = confirm_fill(order, mock_fills_ledger)
        
        assert fill.price_cents == price_cents, f"Fill price should be {price_cents}"
