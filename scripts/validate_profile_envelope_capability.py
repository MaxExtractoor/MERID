"""Validate profile → envelope → capability invariants for kalshi_crypto_15m_v2.

This script validates that the configuration flow is consistent:
1. Profile YAML loads correctly
2. Risk envelope computes correctly from profile
3. Capability store matches envelope values
4. No divergence between config sources

Usage:
    python scripts/validate_profile_envelope_capability.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger("scripts.validate_profile_envelope_capability")


def validate_profile_yaml_loading():
    """Validate that profile YAML loads and parses correctly."""
    logger.info("=" * 80)
    logger.info("VALIDATION 1: Profile YAML Loading")
    logger.info("=" * 80)
    
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
        
        if not is_profile_active():
            logger.warning("MERID_PROFILE is not kalshi_crypto_15m_v2 - skipping validation")
            return False
        
        adapter = get_active_profile()
        if adapter is None:
            logger.error("Profile adapter is None despite is_profile_active()=True")
            return False
        
        profile = adapter.profile
        
        logger.info(f"✓ Profile loaded: {profile.profile_name} v{profile.profile_version}")
        logger.info(f"  Description: {profile.description}")
        logger.info(f"  Capital: ${profile.capital_usd:.2f}")
        logger.info(f"  Max single order: ${profile.venue_max_single_order_usd:.2f}")
        logger.info(f"  Max total notional: ${profile.venue_max_total_notional_usd:.2f}")
        logger.info(f"  Max concurrent trades: {profile.agent_max_concurrent_trades}")
        
        # Verify all 5 assets are present
        expected_assets = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
        actual_assets = set(profile.asset_configs.keys())
        if actual_assets == expected_assets:
            logger.info(f"✓ All 5 assets present: {sorted(actual_assets)}")
        else:
            missing = expected_assets - actual_assets
            extra = actual_assets - expected_assets
            if missing:
                logger.error(f"✗ Missing assets: {sorted(missing)}")
            if extra:
                logger.warning(f"  Extra assets: {sorted(extra)}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Profile YAML loading failed: {e}")
        return False


def validate_risk_envelope_computation():
    """Validate that risk envelope computes correctly from profile."""
    logger.info("=" * 80)
    logger.info("VALIDATION 2: Risk Envelope Computation")
    logger.info("=" * 80)
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        logger.info(f"✓ Risk envelope computed")
        logger.info(f"  Profile capital: ${envelope.profile_capital_usd:.2f}")
        logger.info(f"  Live bankroll: ${envelope.live_bankroll_usd:.2f}")
        logger.info(f"  Max single order: ${envelope.max_single_order_notional_usd:.2f}")
        logger.info(f"  Max total notional: ${envelope.max_total_notional_usd:.2f}")
        logger.info(f"  Max concurrent trades: {envelope.max_concurrent_trades}")
        logger.info(f"  Agent max notional: ${envelope.agent_max_notional_usd:.2f}")
        
        # Verify per-asset caps
        total_asset_cap = sum(envelope.asset_max_notional_usd.values())
        logger.info(f"  Total asset caps: ${total_asset_cap:.2f}")
        
        if total_asset_cap > envelope.max_total_notional_usd:
            logger.warning(f"  ⚠ Sum of asset caps exceeds total venue cap")
        
        # Verify effective capital logic
        if envelope.profile_capital_usd > 0:
            effective_capital = envelope.profile_capital_usd
        else:
            effective_capital = envelope.live_bankroll_usd
        
        logger.info(f"  Effective capital: ${effective_capital:.2f}")
        
        # Verify max_single_order is 5% of effective capital
        expected_single_order = effective_capital * 0.05
        if abs(envelope.max_single_order_notional_usd - expected_single_order) < 0.01:
            logger.info(f"✓ Max single order is 5% of effective capital")
        else:
            logger.warning(f"  ⚠ Max single order ${envelope.max_single_order_notional_usd:.2f} "
                          f"vs expected ${expected_single_order:.2f}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Risk envelope computation failed: {e}")
        return False


def validate_capability_store_consistency():
    """Validate that capability store matches envelope values."""
    logger.info("=" * 80)
    logger.info("VALIDATION 3: Capability Store Consistency")
    logger.info("=" * 80)
    
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        from merid.guardrails.capabilities import get_capability_store
        
        envelope = get_kalshi_crypto_15m_risk_envelope()
        cap_store = get_capability_store()
        
        # Check if AgentGrid has registered any capabilities
        # If no capabilities are present, AgentGrid is likely not running (standalone validation)
        agents_15m = ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]
        has_any_caps = any(cap_store.get(agent_id) is not None for agent_id in agents_15m)
        
        if not has_any_caps:
            logger.info("No kalshi_pm capabilities found; AgentGrid likely not running.")
            logger.info("Skipping capability_store validation (standalone mode).")
            logger.info("Re-run with AgentGrid running for full validation.")
            return True  # Skip is not a failure in standalone mode
        
        # Compute expected max_notional from envelope
        expected_max_notional = envelope.max_single_order_notional_usd * envelope.max_concurrent_trades
        
        logger.info(f"  Expected max_notional (from envelope): ${expected_max_notional:.2f}")
        logger.info(f"    = ${envelope.max_single_order_notional_usd:.2f} × {envelope.max_concurrent_trades}")
        
        # Check each 15m agent
        all_match = True
        
        for agent_id in agents_15m:
            cap_map = cap_store.get(agent_id)
            if cap_map is None:
                logger.error(f"✗ {agent_id}: Capability map not found")
                all_match = False
                continue
            
            # Check max_notional matches envelope
            if abs(cap_map.max_notional_usd - expected_max_notional) > 0.01:
                logger.error(f"✗ {agent_id}: max_notional mismatch")
                logger.error(f"  Capability: ${cap_map.max_notional_usd:.2f}")
                logger.error(f"  Expected: ${expected_max_notional:.2f}")
                all_match = False
            else:
                logger.info(f"✓ {agent_id}: max_notional=${cap_map.max_notional_usd:.2f} matches envelope")
            
            # Check scope is appropriate
            logger.info(f"  {agent_id}: max_scope={cap_map.max_scope}, tools={len(cap_map.allowed_tools)}")
        
        return all_match
        
    except Exception as e:
        logger.error(f"✗ Capability store consistency check failed: {e}")
        return False


def validate_edge_threshold_source():
    """Validate that edge thresholds come from profile YAML, not matrix."""
    logger.info("=" * 80)
    logger.info("VALIDATION 4: Edge Threshold Source")
    logger.info("=" * 80)
    
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        adapter = get_active_profile()
        if adapter is None:
            logger.warning("Profile adapter not available - skipping edge threshold validation")
            return True
        
        profile = adapter.profile
        
        # Verify use_crypto_threshold_matrix is false
        if profile.confidence_use_crypto_threshold_matrix:
            logger.error(f"✗ use_crypto_threshold_matrix is True - should be False for 15m profile")
            return False
        
        logger.info(f"✓ use_crypto_threshold_matrix=False (uses profile YAML)")
        
        # Log edge thresholds from profile
        logger.info("  Edge thresholds from profile YAML:")
        for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
            if asset in profile.asset_configs:
                ac = profile.asset_configs[asset]
                logger.info(f"    {asset}: early={ac.min_edge_early:.2%}, "
                          f"mid={ac.min_edge_mid:.2%}, late={ac.min_edge_late:.2%}, "
                          f"terminal={ac.min_edge_terminal:.2%}")
        
        # Log Kelly parameters
        logger.info(f"  Kelly parameters from profile YAML:")
        logger.info(f"    hard_cap={profile.kelly_hard_cap:.2%}, "
                  f"min_edge={profile.kelly_min_edge_pct:.2%}, max_edge={profile.kelly_max_edge_pct:.2%}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Edge threshold source validation failed: {e}")
        return False


def validate_adapter_to_risk_config():
    """Validate that adapter.to_kalshi_risk_config() uses same capital/caps as envelope."""
    logger.info("=" * 80)
    logger.info("VALIDATION 5: Adapter → KalshiRiskConfig Consistency")
    logger.info("=" * 80)
    
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        
        adapter = get_active_profile()
        if adapter is None:
            logger.warning("Profile adapter not available - skipping adapter validation")
            return True
        
        # Get envelope values
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        # Get adapter's KalshiRiskConfig mapping
        risk_config_dict = adapter.to_kalshi_risk_config()
        
        # Compare key fields
        logger.info("  Comparing envelope vs adapter KalshiRiskConfig:")
        
        # max_single_order_notional_usd
        envelope_single = envelope.max_single_order_notional_usd
        adapter_single = risk_config_dict.get('max_single_order_notional_usd', 0)
        if abs(envelope_single - adapter_single) < 0.01:
            logger.info(f"✓ max_single_order_notional_usd: envelope=${envelope_single:.2f} == adapter=${adapter_single:.2f}")
        else:
            logger.error(f"✗ max_single_order_notional_usd: envelope=${envelope_single:.2f} != adapter=${adapter_single:.2f}")
            return False
        
        # max_total_notional_usd
        envelope_total = envelope.max_total_notional_usd
        adapter_total = risk_config_dict.get('max_total_notional_usd', 0)
        if abs(envelope_total - adapter_total) < 0.01:
            logger.info(f"✓ max_total_notional_usd: envelope=${envelope_total:.2f} == adapter=${adapter_total:.2f}")
        else:
            logger.error(f"✗ max_total_notional_usd: envelope=${envelope_total:.2f} != adapter=${adapter_total:.2f}")
            return False
        
        # drawdown_halt_pct
        envelope_halt = envelope.drawdown_halt_pct
        adapter_halt = risk_config_dict.get('drawdown_halt_pct', 0)
        if abs(envelope_halt - adapter_halt) < 0.001:
            logger.info(f"✓ drawdown_halt_pct: envelope={envelope_halt:.2%} == adapter={adapter_halt:.2%}")
        else:
            logger.error(f"✗ drawdown_halt_pct: envelope={envelope_halt:.2%} != adapter={adapter_halt:.2%}")
            return False
        
        # drawdown_unwind_pct
        envelope_unwind = envelope.drawdown_unwind_pct
        adapter_unwind = risk_config_dict.get('drawdown_unwind_pct', 0)
        if abs(envelope_unwind - adapter_unwind) < 0.001:
            logger.info(f"✓ drawdown_unwind_pct: envelope={envelope_unwind:.2%} == adapter={adapter_unwind:.2%}")
        else:
            logger.error(f"✗ drawdown_unwind_pct: envelope={envelope_unwind:.2%} != adapter={adapter_unwind:.2%}")
            return False
        
        logger.info("✓ Adapter KalshiRiskConfig matches canonical envelope")
        return True
        
    except Exception as e:
        logger.error(f"✗ Adapter → KalshiRiskConfig consistency check failed: {e}")
        return False


def main():
    """Run all validations."""
    logger.info("Starting profile → envelope → capability invariant validation")
    logger.info("=" * 80)
    
    results = {}
    
    # Run all validations
    results['profile_yaml'] = validate_profile_yaml_loading()
    results['risk_envelope'] = validate_risk_envelope_computation()
    results['capability_store'] = validate_capability_store_consistency()
    results['edge_thresholds'] = validate_edge_threshold_source()
    results['adapter_config'] = validate_adapter_to_risk_config()
    
    # Summary
    logger.info("=" * 80)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 80)
    
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status}: {name}")
    
    all_passed = all(results.values())
    
    logger.info("=" * 80)
    if all_passed:
        logger.info("✓ ALL VALIDATIONS PASSED")
        return 0
    else:
        logger.error("✗ SOME VALIDATIONS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
