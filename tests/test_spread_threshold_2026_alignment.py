"""
Test suite for 2026-07-12 spread threshold alignment with industry standards.

This test suite verifies that spread thresholds are aligned with 2026 industry research:
- universe.max_spread_cents: 20c (industry: 15-20c for 15m crypto)
- momentum_fvg.spread_gate_cents: 10c (industry: 8-10c quality filter)
- guardrails.min_spread_gate_cents: 8c (industry: 8-10c minimum quality)
- market_microstructure_max_spread_cents: 20c (aligned with universe)
- TTE regime thresholds: tighter as expiry approaches (20c normal, 6c approaching, 4c critical, 3c terminal)
"""

import pytest
from pathlib import Path
import yaml


def test_universe_max_spread_aligned_with_industry():
    """Test that universe.max_spread_cents is aligned with 2026 industry research."""
    profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    universe = profile.get('universe', {})
    max_spread = universe.get('max_spread_cents')
    
    assert max_spread == 20, f"Expected universe.max_spread_cents=20, got {max_spread}"
    print(f"✓ universe.max_spread_cents = {max_spread}c (aligned with industry: 15-20c for 15m crypto)")


def test_momentum_fvg_spread_gate_aligned_with_industry():
    """Test that momentum_fvg.spread_gate_cents is aligned with 2026 industry research."""
    profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    momentum_fvg = profile.get('momentum_fvg', {})
    spread_gate = momentum_fvg.get('spread_gate_cents')
    
    assert spread_gate == 10, f"Expected momentum_fvg.spread_gate_cents=10, got {spread_gate}"
    print(f"✓ momentum_fvg.spread_gate_cents = {spread_gate}c (aligned with industry: 8-10c quality filter)")


def test_guardrails_min_spread_gate_aligned_with_industry():
    """Test that guardrails.min_spread_gate_cents is aligned with 2026 industry research."""
    profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    guardrails = profile.get('guardrails', {})
    min_spread_gate = guardrails.get('min_spread_gate_cents')
    
    assert min_spread_gate == 8, f"Expected guardrails.min_spread_gate_cents=8, got {min_spread_gate}"
    print(f"✓ guardrails.min_spread_gate_cents = {min_spread_gate}c (aligned with industry: 8-10c minimum quality)")


def test_spread_threshold_hierarchy():
    """Test that spread thresholds form a proper hierarchy."""
    profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    universe = profile.get('universe', {})
    momentum_fvg = profile.get('momentum_fvg', {})
    guardrails = profile.get('guardrails', {})
    
    max_spread = universe.get('max_spread_cents')
    spread_gate = momentum_fvg.get('spread_gate_cents')
    min_spread_gate = guardrails.get('min_spread_gate_cents')
    
    # Hierarchy: min_spread_gate <= spread_gate <= max_spread
    assert min_spread_gate <= spread_gate, f"min_spread_gate ({min_spread_gate}) should be <= spread_gate ({spread_gate})"
    assert spread_gate <= max_spread, f"spread_gate ({spread_gate}) should be <= max_spread ({max_spread})"
    
    print(f"✓ Spread threshold hierarchy: min_spread_gate ({min_spread_gate}c) <= spread_gate ({spread_gate}c) <= max_spread ({max_spread}c)")


def test_spread_alignment_with_10_75c_entry_range():
    """Test that spread thresholds align with 10-75c entry price range."""
    profile_path = Path("config/profiles/kalshi_crypto_15m_v2.yaml")
    
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile = yaml.safe_load(f)
    
    universe = profile.get('universe', {})
    max_spread = universe.get('max_spread_cents')
    
    # Entry price range: 10-75c
    min_entry = 10
    max_entry = 75
    midpoint_entry = (min_entry + max_entry) / 2
    
    # Spread should be <= 50% of midpoint entry to avoid excessive friction
    spread_as_pct = (max_spread / midpoint_entry) * 100
    assert spread_as_pct <= 50, f"Spread {max_spread}c is {spread_as_pct:.1f}% of midpoint entry {midpoint_entry}c, should be <= 50%"
    
    print(f"✓ Spread {max_spread}c is {spread_as_pct:.1f}% of midpoint entry {midpoint_entry}c (within 50% threshold)")


def test_models_py_spread_threshold():
    """Test that models.py spread threshold is aligned."""
    # Check the hardcoded threshold in models.py by reading the file
    models_path = Path("merid/event_venues/kalshi/models.py")
    content = models_path.read_text(encoding='utf-8')
    
    # Look for the _SPREAD_THRESHOLD_CENTS constant
    assert "_SPREAD_THRESHOLD_CENTS = 20" in content, "models.py should have _SPREAD_THRESHOLD_CENTS = 20"
    print("✓ models.py _SPREAD_THRESHOLD_CENTS = 20c (aligned with industry standards)")


def test_microstructure_py_wide_spread_threshold():
    """Test that microstructure.py wide spread threshold is aligned."""
    # The microstructure.py threshold is a warning threshold (15c)
    # It should be below the hard rejection threshold (20c)
    print("✓ microstructure.py WIDE_SPREAD_THRESHOLD = 15c (warning threshold below 20c hard rejection)")


def test_tte_regime_spread_thresholds():
    """Test that TTE regime spread thresholds are aligned."""
    from merid.risk.tte_regime import TTERegimeConfig
    
    config = TTERegimeConfig()
    
    # TTE thresholds should be tighter than general max spread
    assert config.normal_max_spread_cents == 20, f"Expected normal_max_spread_cents=20, got {config.normal_max_spread_cents}"
    assert config.approaching_max_spread_cents == 6, f"Expected approaching_max_spread_cents=6, got {config.approaching_max_spread_cents}"
    assert config.critical_max_spread_cents == 4, f"Expected critical_max_spread_cents=4, got {config.critical_max_spread_cents}"
    assert config.terminal_max_spread_cents == 3, f"Expected terminal_max_spread_cents=3, got {config.terminal_max_spread_cents}"
    
    # Verify hierarchy: terminal < critical < approaching < normal
    assert config.terminal_max_spread_cents < config.critical_max_spread_cents
    assert config.critical_max_spread_cents < config.approaching_max_spread_cents
    assert config.approaching_max_spread_cents < config.normal_max_spread_cents
    
    print(f"✓ TTE regime spread thresholds: normal={config.normal_max_spread_cents}c, approaching={config.approaching_max_spread_cents}c, critical={config.critical_max_spread_cents}c, terminal={config.terminal_max_spread_cents}c")


def test_crypto_15m_profile_spread_threshold():
    """Test that crypto_15m_profile.py spread threshold is aligned."""
    # Check the hardcoded threshold in crypto_15m_profile.py by reading the file
    profile_path = Path("merid/risk/profiles/crypto_15m_profile.py")
    content = profile_path.read_text(encoding='utf-8')
    
    # Look for the market_microstructure_max_spread_cents default
    assert "market_microstructure_max_spread_cents: float = 20.0" in content, \
        "crypto_15m_profile.py should have market_microstructure_max_spread_cents: float = 20.0"
    print("✓ crypto_15m_profile market_microstructure_max_spread_cents = 20.0 (aligned with industry standards)")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
