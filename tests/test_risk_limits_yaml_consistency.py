"""
Tests for risk_limits.yaml consistency with profile YAML.

These tests verify that risk_limits.yaml values match the profile YAML
to prevent order rejections due to configuration mismatches.
"""

import pytest
import yaml
from pathlib import Path


def test_risk_limits_yaml_per_trade_limit_is_correct():
    """Test that risk_limits.yaml per_trade.max_notional_pct is set to 3%."""
    project_root = Path(__file__).parent.parent
    
    # Load risk_limits.yaml
    risk_limits_path = project_root / "config" / "risk_limits.yaml"
    with open(risk_limits_path, 'r', encoding='utf-8') as f:
        risk_limits = yaml.safe_load(f)
    
    # Get per-trade limit
    risk_limits_per_trade = risk_limits.get('per_trade', {}).get('max_notional_pct')
    
    # Verify the expected value is 3%
    assert risk_limits_per_trade == 0.03, \
        f"Expected per_trade.max_notional_pct to be 0.03 (3%), got {risk_limits_per_trade}"


def test_risk_limits_yaml_cycle_limit_is_correct():
    """Test that risk_limits.yaml bankroll.max_cycle_risk_pct is set to 5%."""
    project_root = Path(__file__).parent.parent
    
    # Load risk_limits.yaml
    risk_limits_path = project_root / "config" / "risk_limits.yaml"
    with open(risk_limits_path, 'r', encoding='utf-8') as f:
        risk_limits = yaml.safe_load(f)
    
    # Get cycle/window limit
    risk_limits_cycle = risk_limits.get('bankroll', {}).get('max_cycle_risk_pct')
    
    # Verify the expected value is 5%
    assert risk_limits_cycle == 0.05, \
        f"Expected bankroll.max_cycle_risk_pct to be 0.05 (5%), got {risk_limits_cycle}"


def test_risk_limits_yaml_total_limit_is_correct():
    """Test that risk_limits.yaml bankroll.max_total_risk_pct is set to 15%."""
    project_root = Path(__file__).parent.parent
    
    # Load risk_limits.yaml
    risk_limits_path = project_root / "config" / "risk_limits.yaml"
    with open(risk_limits_path, 'r', encoding='utf-8') as f:
        risk_limits = yaml.safe_load(f)
    
    # Get total venue limit
    risk_limits_total = risk_limits.get('bankroll', {}).get('max_total_risk_pct')
    
    # Verify the expected value is 15%
    assert risk_limits_total == 0.15, \
        f"Expected bankroll.max_total_risk_pct to be 0.15 (15%), got {risk_limits_total}"


def test_risk_limits_yaml_correlated_stack_limit():
    """Test that risk_limits.yaml correlated_stack.max_notional_pct is set correctly."""
    project_root = Path(__file__).parent.parent
    
    # Load risk_limits.yaml
    risk_limits_path = project_root / "config" / "risk_limits.yaml"
    with open(risk_limits_path, 'r', encoding='utf-8') as f:
        risk_limits = yaml.safe_load(f)
    
    # Get correlated stack limit
    correlated_stack_limit = risk_limits.get('correlated_stack', {}).get('max_notional_pct')
    
    # Should be 15% (same as total venue limit for highly correlated assets)
    assert correlated_stack_limit == 0.15, \
        f"Expected correlated_stack.max_notional_pct to be 0.15 (15%), got {correlated_stack_limit}"


def test_risk_limits_yaml_per_asset_disabled():
    """Test that risk_limits.yaml per_asset is disabled for highly correlated crypto assets."""
    project_root = Path(__file__).parent.parent
    
    # Load risk_limits.yaml
    risk_limits_path = project_root / "config" / "risk_limits.yaml"
    with open(risk_limits_path, 'r', encoding='utf-8') as f:
        risk_limits = yaml.safe_load(f)
    
    # Get per_asset config
    per_asset_config = risk_limits.get('per_asset', {})
    
    # Should be disabled
    assert per_asset_config.get('enabled') == False, \
        "per_asset should be disabled for highly correlated crypto assets"
