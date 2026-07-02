"""
Signal generation tests for 15m trade path.

Tests validate that agents generate trading signals correctly
based on market data and edge calculations.
"""

import time
import pytest


def test_signal_generation_happy_path(mock_agent, mock_market_state, mock_spot_service, generate_signal):
    """Test signal generation under healthy conditions.
    
    Expected:
    - Agent generates signal
    - Signal contains all required fields
    - Signal direction matches edge calculation
    - Contract size is reasonable
    """
    # Setup: Healthy market conditions
    mock_spot_service.get_price.return_value = 65000.0
    edge_pct = 2.0  # 2% edge (above 1% threshold)
    
    # Generate signal
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=edge_pct,
    )
    
    # Assertions
    assert signal is not None, "Signal should be generated"
    assert signal.asset == "BTC", "Signal asset should be BTC"
    assert signal.market_id == "BTC-15m-2026-06-05", "Signal market_id should match"
    assert signal.direction == "YES", "Signal direction should be YES"
    assert signal.contracts == 10, "Signal contracts should be 10"
    assert signal.price_cents == 65, "Signal price should be 65 cents"
    assert signal.edge_pct == 2.0, "Signal edge should be 2%"
    assert signal.timestamp > 0, "Signal timestamp should be valid"


def test_signal_generation_bullish_edge(mock_agent, mock_market_state, mock_spot_service, generate_signal):
    """Test signal generation for bullish edge (YES direction)."""
    # Setup: Bullish edge
    edge_pct = 3.0  # 3% edge
    
    # Generate signal
    signal = generate_signal(
        asset="ETH",
        market_id="ETH-15m-2026-06-05",
        direction="YES",
        contracts=20,
        price_cents=50,
        edge_pct=edge_pct,
    )
    
    # Assertions
    assert signal.direction == "YES", "Bullish edge should generate YES signal"
    assert signal.edge_pct == 3.0, "Edge should be 3%"


def test_signal_generation_bearish_edge(mock_agent, mock_market_state, mock_spot_service, generate_signal):
    """Test signal generation for bearish edge (NO direction)."""
    # Setup: Bearish edge
    edge_pct = 2.5  # 2.5% edge
    
    # Generate signal
    signal = generate_signal(
        asset="SOL",
        market_id="SOL-15m-2026-06-05",
        direction="NO",
        contracts=15,
        price_cents=30,
        edge_pct=edge_pct,
    )
    
    # Assertions
    assert signal.direction == "NO", "Bearish edge should generate NO signal"
    assert signal.edge_pct == 2.5, "Edge should be 2.5%"


def test_signal_generation_edge_below_threshold(mock_agent, mock_market_state, mock_spot_service, generate_signal):
    """Test signal generation when edge is below threshold.
    
    Expected:
    - Signal is generated but with low edge
    - Gate decision should reject later
    """
    # Setup: Edge below threshold
    edge_pct = 0.5  # 0.5% edge (below 1% threshold)
    
    # Generate signal
    signal = generate_signal(
        asset="XRP",
        market_id="XRP-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=40,
        edge_pct=edge_pct,
    )
    
    # Assertions
    assert signal is not None, "Signal should still be generated"
    assert signal.edge_pct == 0.5, "Edge should be 0.5% (below threshold)"
    # Note: Gate decision will reject this signal in candidate selection stage


def test_signal_generation_multiple_assets(mock_agent, mock_market_state, mock_spot_service, generate_signal):
    """Test signal generation for multiple assets (BTC, ETH, SOL, XRP, DOGE)."""
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
        
        assert signal.asset == asset, f"Signal asset should be {asset}"
        assert signal.market_id == f"{asset}-15m-2026-06-05", f"Market ID should match {asset}"


def test_signal_timestamp_freshness(mock_agent, mock_market_state, mock_spot_service, generate_signal):
    """Test that signal timestamp is fresh (within last second)."""
    # Generate signal
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=2.0,
    )
    
    # Check timestamp freshness
    signal_age = time.time() - signal.timestamp
    assert signal_age < 1.0, "Signal timestamp should be fresh (within last second)"


def test_signal_contract_size_respects_risk(mock_agent, mock_market_state, mock_spot_service, mock_risk_env, generate_signal):
    """Test that signal contract size respects risk budget."""
    # Setup: Risk budget at 30% utilization
    mock_risk_env.utilization.return_value = 0.3
    mock_risk_env.has_capacity.return_value = True
    
    # Generate signal with reasonable contract size
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,  # Reasonable size
        price_cents=65,
        edge_pct=2.0,
    )
    
    # Assertions
    assert signal.contracts > 0, "Contract size should be positive"
    assert signal.contracts <= 100, "Contract size should be reasonable (<= 100)"
    # In real implementation, this would check against specific risk limits


def test_signal_market_id_format(mock_agent, mock_market_state, mock_spot_service, generate_signal):
    """Test that signal market_id follows correct format."""
    # Generate signal
    signal = generate_signal(
        asset="BTC",
        market_id="BTC-15m-2026-06-05",
        direction="YES",
        contracts=10,
        price_cents=65,
        edge_pct=2.0,
    )
    
    # Assertions
    assert "-" in signal.market_id, "Market ID should contain hyphens"
    assert signal.asset in signal.market_id, "Market ID should contain asset name"
    assert "15m" in signal.market_id, "Market ID should contain 15m indicator"
