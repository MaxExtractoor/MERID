"""Test agent_grid_config.py default values alignment with profile YAML.

This test verifies the CRITICAL FIX (2026-07-07) that changed the default
per_trade_risk_pct from 0.02 (2%) to 0.03 (3%) to align with profile YAML.
"""

import pytest
from pathlib import Path


def test_agent_grid_config_per_trade_risk_default():
    """Test that agent_grid_config.py has correct per_trade_risk_pct default.
    
    CRITICAL FIX (2026-07-07): Default changed from 0.02 (2%) to 0.03 (3%) to align with profile YAML.
    """
    config_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_config.py"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the CRITICAL FIX comment exists
    assert "CRITICAL FIX: Default 3% to match profile YAML (was 0.02)" in content or \
           "CRITICAL FIX: Default 3% to match profile YAML" in content, \
        "CRITICAL FIX comment for per_trade_risk_pct default missing"
    
    # Verify the default value is 0.03 (3%)
    assert "getattr(profile, 'per_trade_risk_pct', 0.03)" in content, \
        "per_trade_risk_pct default should be 0.03 (3%), not 0.02 (2%)"
    
    # Verify there's no reference to 0.02 as the default for per_trade_risk_pct
    # (except in comments explaining the fix)
    lines = content.split('\n')
    for i, line in enumerate(lines):
        # Skip lines that are comments
        if line.strip().startswith('#'):
            continue
        # Check for getattr with 0.02 default for per_trade_risk_pct
        # Allow comments that explain the fix (e.g., "was 0.02")
        if "getattr(profile, 'per_trade_risk_pct'" in line and "0.02" in line and "was 0.02" not in line:
            pytest.fail(f"Line {i+1} still has 0.02 default for per_trade_risk_pct: {line}")


def test_agent_grid_config_no_stale_2_percent_comments():
    """Test that agent_grid_config.py has no stale comments referencing 2% per_trade_risk_pct.
    
    CRITICAL FIX (2026-07-07): Comments should reference 3%, not 2%.
    """
    config_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_config.py"
    
    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for stale comments that might reference 2% per_trade_risk_pct
    # (comments explaining the fix are OK)
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'per_trade_risk_pct' in line.lower() and '2%' in line and 'was 0.02' not in line:
            # Allow comments that explain the fix (e.g., "was 0.02")
            if 'CRITICAL FIX' not in line and 'was' not in line.lower():
                pytest.fail(f"Line {i+1} has stale 2% reference for per_trade_risk_pct: {line}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
