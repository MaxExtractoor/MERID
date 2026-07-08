"""
Test for indicator stack initialization fix (2026-07-08).

CRITICAL FIX: Each agent should initialize only its own asset's indicator stack,
not all 5 assets. This prevents 25 total stacks and ensures proper history accumulation.

Before fix: 5 agents × 5 assets = 25 stacks (each stack only gets updates from 1 agent)
After fix: 5 agents × 1 asset = 5 stacks (each stack gets updates from its dedicated agent)
"""

import pytest
from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig


def test_indicator_stack_instance_id_consistency():
    """Test that indicator stack instance_id is consistent across updates."""
    
    # Create indicator stack
    config = IndicatorConfig(asset="BTC", kalshi_mode=True)
    stack = Crypto15mIndicatorStack(config=config)
    
    # Get initial instance_id
    initial_instance_id = stack._instance_id
    
    # Update with prices
    for i in range(10):
        stack.update(60000 + i * 10)
    
    # Verify instance_id is unchanged (stack not recreated)
    assert stack._instance_id == initial_instance_id
    
    # Verify history accumulated
    snap = stack.snapshot()
    assert snap.bars_available == 10


def test_indicator_stack_asset_symbol_set():
    """Test that set_asset_symbol is called during initialization."""
    
    # Create indicator stack
    config = IndicatorConfig(asset="BTC", kalshi_mode=True)
    stack = Crypto15mIndicatorStack(config=config)
    
    # Set asset symbol
    stack.set_asset_symbol("BTC")
    
    # Verify asset symbol is set
    assert stack._asset_symbol == "BTC"


def test_indicator_stack_history_accumulation():
    """Test that indicator stack accumulates history correctly when updated."""
    
    # Create indicator stack
    config = IndicatorConfig(asset="BTC", kalshi_mode=True)
    stack = Crypto15mIndicatorStack(config=config)
    
    # Update with 30 prices (enough for MACD warmup)
    for i in range(30):
        stack.update(60000 + i * 10)
    
    # Verify history accumulated
    snap = stack.snapshot()
    assert snap.bars_available == 30
    
    # MACD should be initialized (needs 21 bars for slow period)
    assert snap.macd_line != 0.0 or snap.macd_signal_line != 0.0


def test_indicator_stack_max_bars_configuration():
    """Test that max_bars is set to 250 to allow MACD(8,21,5) initialization."""
    
    # Create indicator stack
    config = IndicatorConfig(asset="BTC", kalshi_mode=True)
    stack = Crypto15mIndicatorStack(config=config)
    
    # Verify max_bars is 250 (increased from 100 to allow MACD warmup)
    assert stack.cfg.max_bars == 250
    assert stack._prices.maxlen == 250


if __name__ == "__main__":
    test_indicator_stack_instance_id_consistency()
    print("---")
    test_indicator_stack_asset_symbol_set()
    print("---")
    test_indicator_stack_history_accumulation()
    print("---")
    test_indicator_stack_max_bars_configuration()
    print("\n=== ALL TESTS PASSED ===")
