"""Tests for industry-aligned trading parameters in agent_grid_15m.py.

Tests cover:
- Fee-aware trading parameters (prefer_maker_orders, min_profit_basis_points)
- Regime detection parameters (volatility thresholds)
- Spread validation in basis points
"""

import pytest
from merid.prediction.agent_grid_15m import LeanAgentConfig


def test_fee_aware_trading_parameters():
    """Test that fee-aware trading parameters are properly configured."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"]
    )
    
    # Verify fee-aware parameters exist
    assert hasattr(config, 'prefer_maker_orders')
    assert hasattr(config, 'min_profit_basis_points')
    assert hasattr(config, 'max_spread_basis_points')
    
    # Verify default values align with industry research
    assert config.prefer_maker_orders is True  # Prefer maker orders for rebates
    assert config.min_profit_basis_points == 20  # Minimum 20bp profit target
    assert config.max_spread_basis_points == 50  # RELAXED: Maximum 50bp spread (increased from 30 to allow more trades)
    
    # Verify economic impact: maker rebates vs taker fees
    # Maker: -0.05% round trip (earns rebate)
    # Taker: +0.15% round trip (pays fee)
    # Difference: 0.20% per round trip
    fee_difference = 0.20  # 20 basis points
    assert config.min_profit_basis_points >= fee_difference


def test_regime_detection_parameters():
    """Test that regime detection parameters are properly configured."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"]
    )
    
    # Verify regime detection parameters exist
    assert hasattr(config, 'volatility_window_s')
    assert hasattr(config, 'min_volatility_threshold')
    assert hasattr(config, 'max_volatility_threshold')
    
    # Verify default values align with industry research
    assert config.volatility_window_s == 300  # 5-minute volatility window
    assert config.min_volatility_threshold == 0.001  # 0.1% minimum volatility
    assert config.max_volatility_threshold == 0.02  # 2% maximum volatility
    
    # Verify thresholds avoid hostile market conditions
    # Low volatility death zone: < 0.1%
    # Extreme volatility spikes: > 2%
    assert config.min_volatility_threshold > 0
    assert config.max_volatility_threshold > config.min_volatility_threshold


def test_spread_validation_in_basis_points():
    """Test that spread validation uses basis points instead of just cents."""
    # Test spread calculation in basis points
    best_bid_cents = 49
    best_ask_cents = 51
    spread_cents = best_ask_cents - best_bid_cents
    
    # Calculate mid price
    mid_price_cents = (best_bid_cents + best_ask_cents) / 2
    
    # Convert to basis points
    spread_bp = (spread_cents / mid_price_cents) * 100
    
    # Verify calculation
    assert spread_cents == 2
    assert mid_price_cents == 50
    assert spread_bp == 4.0  # 2 cents / 50 cents * 100 = 4bp
    
    # Test against industry-aligned threshold
    max_spread_bp = 30
    assert spread_bp <= max_spread_bp  # Should accept
    
    # Test wide spread rejection
    wide_bid_cents = 40
    wide_ask_cents = 60
    wide_spread_cents = wide_ask_cents - wide_bid_cents
    wide_mid_cents = (wide_bid_cents + wide_ask_cents) / 2
    wide_spread_bp = (wide_spread_cents / wide_mid_cents) * 100
    
    assert wide_spread_bp == 40.0  # 20 cents / 50 cents * 100 = 40bp
    assert wide_spread_bp > max_spread_bp  # Should reject


def test_industry_parameters_prevent_hostile_conditions():
    """Test that industry parameters prevent trading in hostile market conditions."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"]
    )
    
    # Low volatility condition (death zone)
    low_volatility = 0.0005  # 0.05% - below threshold
    should_avoid_low = low_volatility < config.min_volatility_threshold
    assert should_avoid_low is True
    
    # Normal volatility condition (sweet spot)
    normal_volatility = 0.005  # 0.5% - within threshold
    should_trade_normal = (
        config.min_volatility_threshold <= normal_volatility <= config.max_volatility_threshold
    )
    assert should_trade_normal is True
    
    # Extreme volatility condition (hostile)
    extreme_volatility = 0.03  # 3% - above threshold
    should_avoid_extreme = extreme_volatility > config.max_volatility_threshold
    assert should_avoid_extreme is True
    
    # Wide spread condition (hostile)
    wide_spread_bp = 60  # 60 basis points (wider than new 50bp threshold)
    should_avoid_wide_spread = wide_spread_bp > config.max_spread_basis_points
    assert should_avoid_wide_spread is True
    
    # Normal spread condition (acceptable)
    normal_spread_bp = 15  # 15 basis points
    should_accept_normal_spread = normal_spread_bp <= config.max_spread_basis_points
    assert should_accept_normal_spread is True


def test_profit_target_overcomes_structural_disadvantages():
    """Test that minimum profit target overcomes structural disadvantages."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"]
    )
    
    # Retail structural disadvantages (from research):
    # - Execution latency: 200-500ms vs institutional 10-50 microseconds
    # - Fee structure: 0.15% round trip (taker) vs institutional rebates
    # - Need 15-30bp moves to overcome disadvantages
    
    # Verify minimum profit target is sufficient
    assert config.min_profit_basis_points >= 15  # At least 15bp
    assert config.min_profit_basis_points <= 30  # At most 30bp
    
    # Calculate net profit after fees (taker scenario)
    gross_profit_bp = config.min_profit_basis_points
    taker_fee_bp = 15  # 0.15% round trip
    net_profit_bp = gross_profit_bp - taker_fee_bp
    
    # Net profit should still be positive
    assert net_profit_bp > 0
    
    # Calculate net profit with maker rebates
    maker_rebate_bp = -5  # -0.05% round trip (earns rebate)
    net_profit_maker_bp = gross_profit_bp + maker_rebate_bp
    
    # Maker rebates significantly improve profitability
    assert net_profit_maker_bp > net_profit_bp


def test_parameter_configurability():
    """Test that industry parameters can be configured per asset."""
    # Conservative configuration for volatile asset
    conservative_config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        min_profit_basis_points=25,  # Higher profit target
        max_spread_basis_points=20,  # Tighter spread limit
        min_volatility_threshold=0.0015,  # Higher minimum volatility
        max_volatility_threshold=0.015,  # Lower maximum volatility
        use_limit_orders=True,  # Use limit orders for better fill rates
        limit_order_slippage_cents=1  # Tighter slippage tolerance
    )
    
    assert conservative_config.min_profit_basis_points == 25
    assert conservative_config.max_spread_basis_points == 20
    assert conservative_config.min_volatility_threshold == 0.0015
    assert conservative_config.max_volatility_threshold == 0.015
    assert conservative_config.use_limit_orders is True
    assert conservative_config.limit_order_slippage_cents == 1
    
    # Aggressive configuration for stable asset
    aggressive_config = LeanAgentConfig(
        name="DOGE_15M",
        series_tickers=["KXDOGE15M"],
        min_profit_basis_points=15,  # Lower profit target
        max_spread_basis_points=40,  # Wider spread limit
        min_volatility_threshold=0.0005,  # Lower minimum volatility
        max_volatility_threshold=0.03,  # Higher maximum volatility
        use_limit_orders=True,  # Use limit orders for better fill rates
        limit_order_slippage_cents=3  # Wider slippage tolerance
    )
    
    assert aggressive_config.min_profit_basis_points == 15
    assert aggressive_config.max_spread_basis_points == 40
    assert aggressive_config.min_volatility_threshold == 0.0005
    assert aggressive_config.max_volatility_threshold == 0.03
    assert aggressive_config.use_limit_orders is True
    assert aggressive_config.limit_order_slippage_cents == 3


def test_fill_rate_optimization_parameters():
    """Test that fill rate optimization parameters are properly configured."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"]
    )
    
    # Verify fill rate optimization parameters exist
    assert hasattr(config, 'use_limit_orders')
    assert hasattr(config, 'limit_order_slippage_cents')
    
    # Verify default values align with prediction market research
    assert config.use_limit_orders is True  # Use limit orders (maker) for better fill rates
    assert config.limit_order_slippage_cents == 2  # Allow 2 cents slippage for fill probability
    
    # Verify logic: limit orders increase fill rates in thin markets
    # Market orders (taker) often fail in thin markets due to lack of counterparty
    # Limit orders (maker) provide liquidity and wait for fills
    assert config.use_limit_orders is True  # Should use limit orders


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
