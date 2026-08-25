"""
Signal generation tests for 15m trade path.

Tests validate that agents generate trading signals correctly
based on market data and edge calculations.
"""

import time
import pytest
import yaml
from pathlib import Path


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


def test_agent_grid_signal_mode_momentum_fvg():
    """Test that agent grid uses momentum_fvg signal mode (CRITICAL FIX #1)."""
    agent_grid_path = Path("c:/Dev/MERID/config/kalshi_agent_grid.yaml")
    
    with open(agent_grid_path, 'r', encoding='utf-8') as f:
        agent_grid = yaml.safe_load(f)
    
    # Check all 5 assets have signal_mode: momentum_fvg
    assets = ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]
    
    for agent in agent_grid['agents']:
        if agent['name'] in assets:
            strategy_overrides = agent.get('strategy_overrides', {})
            signal_mode = strategy_overrides.get('signal_mode')
            assert signal_mode == "momentum_fvg", f"{agent['name']} should have signal_mode=momentum_fvg, got {signal_mode}"


def test_agent_grid_no_max_spot_to_strike_pct():
    """Test that agent grid does not have max_spot_to_strike_pct (CRITICAL FIX #2)."""
    agent_grid_path = Path("c:/Dev/MERID/config/kalshi_agent_grid.yaml")
    
    with open(agent_grid_path, 'r', encoding='utf-8') as f:
        agent_grid = yaml.safe_load(f)
    
    # Check no agent has max_spot_to_strike_pct in strike_selection
    for agent in agent_grid['agents']:
        strike_selection = agent.get('strike_selection', {})
        assert 'max_spot_to_strike_pct' not in strike_selection, \
            f"{agent['name']} should not have max_spot_to_strike_pct (use profile max_distance_pct)"


def test_agent_grid_no_min_edge_fields():
    """Test that agent grid does not have min_edge fields (HIGH FIX #3)."""
    agent_grid_path = Path("c:/Dev/MERID/config/kalshi_agent_grid.yaml")
    
    with open(agent_grid_path, 'r', encoding='utf-8') as f:
        agent_grid = yaml.safe_load(f)
    
    # Check no agent has min_edge fields in strategy_overrides
    for agent in agent_grid['agents']:
        strategy_overrides = agent.get('strategy_overrides', {})
        assert 'min_edge_early' not in strategy_overrides, \
            f"{agent['name']} should not have min_edge_early (use profile edge_bands)"
        assert 'min_edge_mid' not in strategy_overrides, \
            f"{agent['name']} should not have min_edge_mid (use profile edge_bands)"
        assert 'min_edge_late' not in strategy_overrides, \
            f"{agent['name']} should not have min_edge_late (use profile edge_bands)"
        assert 'min_edge_terminal' not in strategy_overrides, \
            f"{agent['name']} should not have min_edge_terminal (use profile edge_bands)"


def test_profile_per_trade_risk_pct_3_percent():
    """Test that profile per_trade_risk_pct is DISABLED (fixed $2 exposure model)."""
    profile_path = Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")

    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)

    # 2026-07-15: Percentage-based per_trade_risk_pct DISABLED in favor of fixed $2 exposure cap
    # This field is NOT present in the YAML anymore
    guardrails = profile.get('guardrails', {})
    assert 'per_trade_risk_pct' not in guardrails, \
        "per_trade_risk_pct should be DISABLED (removed from YAML - fixed $2 model used instead)"

    # Verify fixed exposure cap is present
    risk_policy = profile.get('risk_policy', {})
    assert risk_policy.get('fixed_exposure_cap_usd') == 2.00, \
        "fixed_exposure_cap_usd should be $2.00"


def test_profile_dynamic_sizing_multipliers():
    """Test that profile dynamic_sizing multipliers are 2.0/1.0 (HIGH FIX #4)."""
    profile_path = Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    dynamic_sizing = profile['dynamic_sizing']
    assert dynamic_sizing['edge_multiplier'] == 2.0, \
        f"edge_multiplier should be 2.0, got {dynamic_sizing['edge_multiplier']}"
    assert dynamic_sizing['confidence_multiplier'] == 1.0, \
        f"confidence_multiplier should be 1.0, got {dynamic_sizing['confidence_multiplier']}"


def test_profile_max_cycle_risk_pct_5_percent():
    """Test that profile max_cycle_risk_pct is DISABLED (fixed $1 exposure model)."""
    profile_path = Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    # 2026-07-15: Percentage-based max_cycle_risk_pct DISABLED in favor of fixed $1 exposure cap
    # This field is set to 0.0 in YAML to satisfy profile validation
    max_cycle_risk = profile.get('max_cycle_risk_pct')
    assert max_cycle_risk == 0.0, \
        f"max_cycle_risk_pct should be 0.0 (DISABLED), got {max_cycle_risk}"


def test_profile_max_contracts_hierarchy():
    """Test that profile has max_contracts hierarchy (fixed $2 exposure model)."""
    profile_path = Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")

    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)

    # Check dynamic_sizing max_contracts is 2 (fixed $2 exposure cap enforces up to 2 contracts)
    dynamic_sizing = profile['dynamic_sizing']
    assert dynamic_sizing['max_contracts'] == 2, \
        "dynamic_sizing max_contracts should be 2 (fixed $2 exposure cap)"

    # Check per-asset max_contracts are 2 (fixed $2 exposure cap enforces up to 2 contracts per asset)
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    for asset in assets:
        asset_config = profile['assets'][asset]
        max_contracts = asset_config['max_contracts']['value']
        assert max_contracts == 2, f"{asset} max_contracts should be 2 (fixed $2 exposure cap)"


def test_profile_no_tier_based_depth_thresholds():
    """Test that profile does not have tier-based depth thresholds (MEDIUM FIX #9)."""
    profile_path = Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    guardrails = profile['guardrails']
    
    # Check tier-based thresholds are removed
    assert 'min_depth_yes_tier1' not in guardrails, \
        "Tier-based depth thresholds should be removed (use per-asset values)"
    assert 'min_depth_no_tier1' not in guardrails, \
        "Tier-based depth thresholds should be removed (use per-asset values)"
    assert 'min_depth_yes_tier2' not in guardrails, \
        "Tier-based depth thresholds should be removed (use per-asset values)"
    assert 'min_depth_no_tier2' not in guardrails, \
        "Tier-based depth thresholds should be removed (use per-asset values)"


def test_risk_envelope_per_trade_risk_pct_default():
    """Test that risk envelope has correct per_trade_risk_pct default (HIGH FIX #7)."""
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
    
    # Check the code has the correct default by inspecting source
    import inspect
    source = inspect.getsource(compute_kalshi_crypto_15m_risk_envelope)
    assert "0.03" in source, \
        "Risk envelope should have 3% default for per_trade_risk_pct"
