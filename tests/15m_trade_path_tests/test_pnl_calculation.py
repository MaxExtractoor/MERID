"""
PnL calculation tests for 15m trade path.

Tests validate that PnL is calculated correctly after fills
and that risk budget is updated appropriately.
"""

import pytest


def test_pnl_calculation_yes_settlement(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test PnL calculation for YES direction at settlement.
    
    Expected:
    - Fill confirmed
    - PnL calculated at settlement
    - Risk budget updated
    - Position tracked
    """
    # Setup: Complete trade path
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
    
    # Calculate PnL at settlement (YES settles at 100)
    settlement_price_cents = 100
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # Assertions
    assert position is not None, "Position should be created"
    assert position.market_id == fill.market_id, "Position market_id should match fill"
    assert position.direction == fill.direction, "Position direction should match fill"
    assert position.contracts == fill.contracts, "Position contracts should match fill"
    assert position.entry_price_cents == fill.price_cents, "Position entry price should match fill"
    assert position.current_price_cents == settlement_price_cents, "Position current price should be settlement"
    
    # PnL calculation: (100 - 65) * 10 = 350 cents
    expected_pnl = (settlement_price_cents - fill.price_cents) * fill.contracts
    assert position.pnl_cents == expected_pnl, f"PnL should be {expected_pnl} cents"
    
    # Verify risk environment was updated
    mock_risk_env.update_position.assert_called_once()


def test_pnl_calculation_no_settlement(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test PnL calculation for NO direction at settlement.
    
    Expected:
    - Fill confirmed
    - PnL calculated at settlement
    - PnL formula reversed for NO direction
    """
    # Setup: NO direction trade
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
    
    # Calculate PnL at settlement (NO settles at 0)
    settlement_price_cents = 0
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # Assertions
    assert position.direction == "NO", "Position direction should be NO"
    
    # PnL calculation: (35 - 0) * 10 = 350 cents
    expected_pnl = (fill.price_cents - settlement_price_cents) * fill.contracts
    assert position.pnl_cents == expected_pnl, f"PnL should be {expected_pnl} cents"


def test_pnl_calculation_profitable_trade(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test PnL calculation for profitable trade."""
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=50,
        edge_pct=2.0,
    )
    
    candidate = create_candidate(signal, gate_decision_pass)
    order = place_order(candidate, mock_kalshi_client)
    fill = confirm_fill(order, mock_fills_ledger)
    
    # Settlement at 100 (profitable)
    settlement_price_cents = 100
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # PnL: (100 - 50) * 10 = 500 cents (profit)
    assert position.pnl_cents > 0, "PnL should be positive for profitable trade"


def test_pnl_calculation_loss_trade(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test PnL calculation for losing trade."""
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=80,
        edge_pct=2.0,
    )
    
    candidate = create_candidate(signal, gate_decision_pass)
    order = place_order(candidate, mock_kalshi_client)
    fill = confirm_fill(order, mock_fills_ledger)
    
    # Settlement at 50 (loss)
    settlement_price_cents = 50
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # PnL: (50 - 80) * 10 = -300 cents (loss)
    assert position.pnl_cents < 0, "PnL should be negative for losing trade"


def test_pnl_calculation_breakeven_trade(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test PnL calculation for breakeven trade."""
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
    
    # Settlement at 65 (breakeven)
    settlement_price_cents = 65
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # PnL: (65 - 65) * 10 = 0 cents (breakeven)
    assert position.pnl_cents == 0, "PnL should be zero for breakeven trade"


def test_pnl_calculation_multiple_contracts(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test PnL calculation with different contract sizes."""
    contract_sizes = [1, 5, 10, 20, 50]
    
    for contracts in contract_sizes:
        signal = generate_signal(
            asset="BTC",
            market_id="BTC-15m-2026-06-05",
            direction="YES",
            contracts=contracts,
            price_cents=50,
            edge_pct=2.0,
        )
        
        candidate = create_candidate(signal, gate_decision_pass)
        order = place_order(candidate, mock_kalshi_client)
        fill = confirm_fill(order, mock_fills_ledger)
        
        # Settlement at 100
        settlement_price_cents = 100
        position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
        
        # PnL: (100 - 50) * contracts
        expected_pnl = (settlement_price_cents - fill.price_cents) * contracts
        assert position.pnl_cents == expected_pnl, f"PnL should be {expected_pnl} for {contracts} contracts"


def test_pnl_calculation_risk_budget_update(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test that risk budget is updated after PnL calculation."""
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
    
    # Calculate PnL
    settlement_price_cents = 100
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # Verify risk environment was called with correct parameters
    mock_risk_env.update_position.assert_called_once()
    call_args = mock_risk_env.update_position.call_args
    assert call_args[1]["market_id"] == fill.market_id
    assert call_args[1]["contracts"] == fill.contracts
    assert call_args[1]["pnl_cents"] == position.pnl_cents


def test_pnl_calculation_different_assets(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test PnL calculation for different assets."""
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
        
        # Calculate PnL
        settlement_price_cents = 100
        position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
        
        assert position.market_id == f"{asset}-15m-2026-06-05", f"Position market_id should be {asset}"


def test_pnl_calculation_position_tracking(generate_signal, gate_decision_pass, create_candidate, place_order, confirm_fill, calculate_pnl, mock_kalshi_client, mock_fills_ledger, mock_risk_env):
    """Test that position is tracked correctly after PnL calculation."""
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
    
    # Calculate PnL
    settlement_price_cents = 100
    position = calculate_pnl(fill, settlement_price_cents, mock_risk_env)
    
    # Verify position tracking
    assert position.market_id == fill.market_id
    assert position.direction == fill.direction
    assert position.contracts == fill.contracts
    assert position.entry_price_cents == fill.price_cents
    assert position.current_price_cents == settlement_price_cents
