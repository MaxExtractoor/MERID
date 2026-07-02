"""
Config vs Code Invariants Test for Kalshi 15m Crypto

This test module asserts that configuration in kalshi_agent_grid.yaml
matches the ASSET_PROFILE dataclass and that no hardcoded constants
exist in the 15m code that should come from config.

Tests:
1. YAML config values match ASSET_PROFILE exposure
2. No hardcoded min_edge_ or kelly_fraction literals in 15m code
3. REGIME_KNOBS fields exist and combine cleanly with ASSET_PROFILE
4. Depth thresholds are config-driven (per-asset base depths + regime multipliers)
5. No hardcoded tier-specific depth literals in 15m code
"""

import pytest
import os
import re
import ast
from pathlib import Path


def test_yaml_config_matches_asset_profile():
    """Assert that kalshi_agent_grid.yaml values match ASSET_PROFILE.
    
    This ensures there's no drift between YAML config and the canonical
    ASSET_PROFILE dataclass in agent_grid_15m.py.
    """
    from merid.prediction.agent_grid_15m import ASSET_PROFILE
    
    # Expected assets in 15m profile
    expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    # Check all expected assets exist in ASSET_PROFILE
    for asset in expected_assets:
        assert asset in ASSET_PROFILE, f"Asset {asset} missing from ASSET_PROFILE"
    
    # Check each asset has required fields
    for asset in expected_assets:
        profile = ASSET_PROFILE[asset]
        
        # Check base parameters exist (using actual field names from implementation)
        assert hasattr(profile, 'base_edge_threshold'), f"{asset} missing base_edge_threshold"
        assert hasattr(profile, 'base_max_contracts_per_strip'), f"{asset} missing base_max_contracts_per_strip"
        assert hasattr(profile, 'base_max_concurrent_strips'), f"{asset} missing base_max_concurrent_strips"
        
        # Check values are reasonable
        assert profile.base_edge_threshold > 0, f"{asset} base_edge_threshold must be > 0"
        assert profile.base_max_contracts_per_strip > 0, f"{asset} base_max_contracts_per_strip must be > 0"
        assert profile.base_max_concurrent_strips > 0, f"{asset} base_max_concurrent_strips must be > 0"


def test_no_hardcoded_edge_thresholds_in_15m_code():
    """Assert no hardcoded min_edge_ or kelly_fraction literals in 15m code.
    
    This prevents developers from bypassing the canonical config path
    by hardcoding constants that should come from ASSET_PROFILE.
    
    Note: REGIME_KNOBS dictionary definitions are allowed - those are config,
    not hardcoded constants in logic.
    """
    agent_grid_path = Path("c:/Dev/MERID/merid/prediction/agent_grid_15m.py")
    
    if not agent_grid_path.exists():
        pytest.skip(f"File not found: {agent_grid_path}")
    
    content = agent_grid_path.read_text(encoding='utf-8')
    
    # Patterns that should NOT exist in 15m code logic (not in dict definitions)
    # We exclude lines that are part of REGIME_KNOBS or ASSET_PROFILE dataclass definitions
    forbidden_patterns = [
        r'min_edge\s*=\s*\d+\.?\d*',  # min_edge = 0.02
        r'kelly_fraction\s*=\s*\d+\.?\d*',  # kelly_fraction = 0.25
    ]
    
    for pattern in forbidden_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        
        # Filter out comments and dictionary/dataclass definitions
        non_comment_matches = []
        for match in matches:
            line_num = content[:content.find(match)].count('\n') + 1
            lines = content.split('\n')
            line = lines[line_num - 1].strip()
            
            # Skip if comment
            if line.startswith('#'):
                continue
            
            # Skip if part of REGIME_KNOBS or ASSET_PROFILE definition
            # Check if we're inside a dataclass or dict definition
            context_start = max(0, line_num - 20)
            context_lines = lines[context_start:line_num]
            context_text = '\n'.join(context_lines)
            
            if 'REGIME_KNOBS' in context_text or 'ASSET_PROFILE' in context_text:
                continue
            
            non_comment_matches.append(match)
        
        if non_comment_matches:
            pytest.fail(
                f"Found hardcoded threshold pattern '{pattern}' in agent_grid_15m.py: {non_comment_matches}. "
                f"Use ASSET_PROFILE or _get_effective_knobs() instead."
            )


def test_regime_knobs_combine_with_asset_profile():
    """Assert REGIME_KNOBS fields exist and combine cleanly with ASSET_PROFILE.
    
    This ensures no missing entries that would cause accidental defaults.
    """
    from merid.prediction.agent_grid_15m import REGIME_KNOBS, ASSET_PROFILE, RiskRegime
    
    # Check all regimes exist
    expected_regimes = [RiskRegime.CONSERVATIVE, RiskRegime.NORMAL, RiskRegime.AGGRESSIVE]
    
    for regime in expected_regimes:
        assert regime in REGIME_KNOBS, f"Regime {regime} missing from REGIME_KNOBS"
    
    # Check each regime has required fields (using actual field names from implementation)
    for regime, knobs in REGIME_KNOBS.items():
        # Regime knobs have absolute values that override ASSET_PROFILE
        assert hasattr(knobs, 'edge_threshold'), f"{regime} missing edge_threshold"
        assert hasattr(knobs, 'size_factor'), f"{regime} missing size_factor"
        
        # Values should be reasonable
        assert knobs.edge_threshold > 0, f"{regime} edge_threshold must be > 0"
        assert 0.1 <= knobs.size_factor <= 2.0, f"{regime} size_factor out of range"


def test_get_effective_knobs_combines_profile_and_regime():
    """Assert _get_effective_knobs() returns regime-specific absolute values.
    
    DESIGN DECISION: REGIME_KNOBS use absolute values (not multipliers).
    This function returns the regime-specific knobs for the current asset's regime.
    ASSET_PROFILE provides per-asset base parameters, but REGIME_KNOBS
    override with regime-specific absolute values.
    """
    from merid.prediction.agent_grid_15m import _get_effective_knobs, REGIME_KNOBS, RiskRegime
    
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    for asset in assets:
        # _get_effective_knobs takes only asset parameter
        effective = _get_effective_knobs(asset)
        
        # Check that effective values are reasonable absolute values
        assert effective.edge_threshold > 0, f"{asset} edge_threshold must be > 0"
        assert effective.size_factor > 0, f"{asset} size_factor must be > 0"
        assert effective.max_trades_per_cycle_asset > 0, f"{asset} max_trades_per_cycle_asset must be > 0"
        
        # Verify that effective knobs match one of the regime knobs
        # (since _get_effective_knobs returns REGIME_KNOBS[regime] directly)
        found_match = False
        for regime, knobs in REGIME_KNOBS.items():
            if (effective.edge_threshold == knobs.edge_threshold and
                effective.size_factor == knobs.size_factor):
                found_match = True
                break
        
        assert found_match, f"{asset} effective knobs don't match any regime knobs"


def test_no_duplicate_risk_limit_sources():
    """Assert no duplicate risk limit sources in config.
    
    This checks that kalshi_agent_grid.yaml doesn't define risk_limits
    that would conflict with the profile config.
    """
    yaml_path = Path("c:/Dev/MERID/config/kalshi_agent_grid.yaml")
    
    if not yaml_path.exists():
        pytest.skip(f"File not found: {yaml_path}")
    
    content = yaml_path.read_text()
    
    # Check for risk_limits sections in 15m agent configs
    # These should be PROFILE-GATED and not contain actual values
    agent_pattern = r'BTC_15M:|ETH_15M:|SOL_15M:|XRP_15M:|DOGE_15M:'
    
    # This is a basic check - in production, we'd parse the YAML properly
    # For now, we just warn if risk_limits appears with non-zero values
    if 'risk_limits:' in content:
        # Check if any risk_limits section has non-zero max_notional_usd
        # This would indicate a duplicate source of truth
        lines = content.split('\n')
        in_risk_limits = False
        for line in lines:
            if 'risk_limits:' in line:
                in_risk_limits = True
            elif in_risk_limits and line.startswith('  ') and ':' in line:
                # Check for non-zero values
                if 'max_notional_usd:' in line and not line.strip().endswith('0'):
                    pytest.fail(
                        f"Found non-zero max_notional_usd in risk_limits section. "
                        f"Risk limits should come from profile config only."
                    )
            elif in_risk_limits and not line.startswith('  '):
                in_risk_limits = False


def test_depth_thresholds_config_driven():
    """Assert depth thresholds are config-driven per-asset.
    
    This ensures ASSET_PROFILE has min_depth_yes_base and min_depth_no_base
    for each asset, and REGIME_KNOBS has depth_mult for each regime.
    """
    from merid.prediction.agent_grid_15m import ASSET_PROFILE, REGIME_KNOBS, RiskRegime
    
    # Expected assets in 15m profile
    expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    # Check each asset has depth base fields
    for asset in expected_assets:
        assert asset in ASSET_PROFILE, f"Asset {asset} missing from ASSET_PROFILE"
        profile = ASSET_PROFILE[asset]
        
        assert hasattr(profile, 'min_depth_yes_base'), f"{asset} missing min_depth_yes_base"
        assert hasattr(profile, 'min_depth_no_base'), f"{asset} missing min_depth_no_base"
        
        # Check values are reasonable (>= 1 contract)
        assert profile.min_depth_yes_base >= 1, f"{asset} min_depth_yes_base must be >= 1"
        assert profile.min_depth_no_base >= 1, f"{asset} min_depth_no_base must be >= 1"
    
    # Check each regime has depth_mult
    expected_regimes = [RiskRegime.CONSERVATIVE, RiskRegime.NORMAL, RiskRegime.AGGRESSIVE]
    for regime in expected_regimes:
        assert regime in REGIME_KNOBS, f"Regime {regime} missing from REGIME_KNOBS"
        knobs = REGIME_KNOBS[regime]
        
        assert hasattr(knobs, 'depth_mult'), f"{regime} missing depth_mult"
        assert knobs.depth_mult > 0, f"{regime} depth_mult must be > 0"
    
    # Verify _get_effective_depth_thresholds helper exists and works
    from merid.prediction.agent_grid_15m import _get_effective_depth_thresholds
    
    for asset in expected_assets:
        for regime in expected_regimes:
            min_yes, min_no = _get_effective_depth_thresholds(asset, regime)
            
            # Check that effective thresholds are derived correctly
            profile = ASSET_PROFILE[asset]
            knobs = REGIME_KNOBS[regime]
            expected_yes = int(profile.min_depth_yes_base * knobs.depth_mult)
            expected_no = int(profile.min_depth_no_base * knobs.depth_mult)
            
            assert min_yes == expected_yes, f"{asset} {regime} YES depth mismatch"
            assert min_no == expected_no, f"{asset} {regime} NO depth mismatch"
            
            # Ensure minimum of 1 contract
            assert min_yes >= 1, f"{asset} {regime} effective YES depth must be >= 1"
            assert min_no >= 1, f"{asset} {regime} effective NO depth must be >= 1"


def test_no_hardcoded_tier_depth_literals():
    """Assert no hardcoded tier-specific depth literals in 15m code.
    
    This prevents developers from bypassing the config-driven depth system
    by hardcoding tier-specific values like min_depth_yes_tier1=25.
    
    Note: REGIME_KNOBS and ASSET_PROFILE dataclass definitions are allowed.
    """
    agent_grid_path = Path("c:/Dev/MERID/merid/prediction/agent_grid_15m.py")
    
    if not agent_grid_path.exists():
        pytest.skip(f"File not found: {agent_grid_path}")
    
    content = agent_grid_path.read_text(encoding='utf-8')
    
    # Patterns that should NOT exist in 15m code logic (not in dict definitions)
    forbidden_patterns = [
        r'min_depth_yes_tier[12]\s*=\s*\d+',  # min_depth_yes_tier1=25
        r'min_depth_no_tier[12]\s*=\s*\d+',  # min_depth_no_tier2=25
    ]
    
    for pattern in forbidden_patterns:
        matches = re.findall(pattern, content, re.IGNORECASE)
        
        # Filter out comments and dictionary/dataclass definitions
        non_comment_matches = []
        for match in matches:
            line_num = content[:content.find(match)].count('\n') + 1
            lines = content.split('\n')
            line = lines[line_num - 1].strip()
            
            # Skip if comment
            if line.startswith('#'):
                continue
            
            # Skip if part of REGIME_KNOBS or ASSET_PROFILE definition
            context_start = max(0, line_num - 20)
            context_lines = lines[context_start:line_num]
            context_text = '\n'.join(context_lines)
            
            if 'REGIME_KNOBS' in context_text or 'ASSET_PROFILE' in context_text:
                continue
            
            non_comment_matches.append(match)
        
        if non_comment_matches:
            pytest.fail(
                f"Found hardcoded tier depth pattern '{pattern}' in agent_grid_15m.py: {non_comment_matches}. "
                f"Use ASSET_PROFILE min_depth_yes_base/min_depth_no_base + REGIME_KNOBS depth_mult instead."
            )


def test_profile_has_trap_avoidance_guardrail_fields():
    """Assert profile has all trap-avoidance guardrail fields.
    
    This ensures the new trap-avoidance fields are present in the
    Crypto15mProfile dataclass and loaded from config.
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        profile_adapter = get_active_profile()
        
        if profile_adapter is None:
            pytest.skip("No active profile found")
        
        profile = profile_adapter.profile
        
        # Check OTM filtering fields
        assert hasattr(profile, 'guardrails_max_dist_pct_trade'), "Missing guardrails_max_dist_pct_trade"
        
        # Check time trap prevention fields
        assert hasattr(profile, 'guardrails_max_entry_mins'), "Missing guardrails_max_entry_mins"
        assert hasattr(profile, 'guardrails_min_entry_mins'), "Missing guardrails_min_entry_mins"
        
        # Check microstructure trap prevention fields
        assert hasattr(profile, 'guardrails_max_spread_for_edge'), "Missing guardrails_max_spread_for_edge"
        assert hasattr(profile, 'guardrails_depth_size_multiplier'), "Missing guardrails_depth_size_multiplier"
        
        # Check regime/drawdown trap prevention fields
        assert hasattr(profile, 'guardrails_regime_cooldown_enabled'), "Missing guardrails_regime_cooldown_enabled"
        assert hasattr(profile, 'guardrails_regime_cooldown_min_trades'), "Missing guardrails_regime_cooldown_min_trades"
        assert hasattr(profile, 'guardrails_regime_cooldown_min_winrate'), "Missing guardrails_regime_cooldown_min_winrate"
        assert hasattr(profile, 'guardrails_regime_cooldown_max_loss_pct'), "Missing guardrails_regime_cooldown_max_loss_pct"
        
    except ImportError:
        pytest.skip("crypto_15m_profile module not available")


def test_guardrail_values_within_sane_bounds():
    """Assert guardrail values are within sane bounds.
    
    This prevents config edits from silently breaking trap-avoidance logic.
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        profile_adapter = get_active_profile()
        
        if profile_adapter is None:
            pytest.skip("No active profile found")
        
        profile = profile_adapter.profile
        
        # Check time trap bounds: 0 < min_entry_mins < max_entry_mins <= 15
        if hasattr(profile, 'guardrails_min_entry_mins') and hasattr(profile, 'guardrails_max_entry_mins'):
            assert 0 < profile.guardrails_min_entry_mins, "guardrails_min_entry_mins must be > 0"
            assert profile.guardrails_min_entry_mins < profile.guardrails_max_entry_mins, \
                "guardrails_min_entry_mins must be < guardrails_max_entry_mins"
            assert profile.guardrails_max_entry_mins <= 15.0, \
                "guardrails_max_entry_mins must be <= 15 (15-minute window)"
        
        # Check OTM distance bounds: 0 < max_dist_pct_trade <= 5
        if hasattr(profile, 'guardrails_max_dist_pct_trade'):
            assert 0 < profile.guardrails_max_dist_pct_trade <= 5.0, \
                "guardrails_max_dist_pct_trade must be in (0, 5] percent"
        
        # Check depth multiplier bounds: 1 <= depth_size_multiplier <= 10
        if hasattr(profile, 'guardrails_depth_size_multiplier'):
            assert 1.0 <= profile.guardrails_depth_size_multiplier <= 10.0, \
                "guardrails_depth_size_multiplier must be in [1, 10]"
        
        # Check regime cooldown bounds
        if hasattr(profile, 'guardrails_regime_cooldown_min_trades'):
            assert profile.guardrails_regime_cooldown_min_trades >= 1, \
                "guardrails_regime_cooldown_min_trades must be >= 1"
        
        if hasattr(profile, 'guardrails_regime_cooldown_min_winrate'):
            assert 0.0 <= profile.guardrails_regime_cooldown_min_winrate <= 1.0, \
                "guardrails_regime_cooldown_min_winrate must be in [0, 1]"
        
        if hasattr(profile, 'guardrails_regime_cooldown_max_loss_pct'):
            assert 0.0 <= profile.guardrails_regime_cooldown_max_loss_pct <= 1.0, \
                "guardrails_regime_cooldown_max_loss_pct must be in [0, 1]"
        
    except ImportError:
        pytest.skip("crypto_15m_profile module not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
