#!/usr/bin/env python3
"""
Risk Configuration Mismatch Auditor

This script identifies mismatches between risk configuration layers in the MERID production stack.
It compares values across:
- Profile YAML (single source of truth)
- Risk envelope
- Profile adapter
- Unified risk manager
- Unified sizing

Usage:
    python scripts/audit_risk_configuration_mismatches.py
"""

import sys
import os
from pathlib import Path
from decimal import Decimal

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def get_profile_yaml_config():
    """Load configuration from profile YAML (single source of truth)."""
    try:
        import yaml
        profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Extract key risk parameters
        risk_config = {
            'agent_max_notional_pct': config.get('risk', {}).get('agent_max_notional_pct', 0.03),
            'venue_max_total_notional_pct': config.get('risk', {}).get('venue_max_total_notional_pct', 0.15),
            'guardrails_per_window_risk_pct': config.get('risk', {}).get('guardrails_per_window_risk_pct', 0.03),
            'guardrails_total_venue_risk_pct': config.get('risk', {}).get('guardrails_total_venue_risk_pct', 0.05),
            'kelly_hard_cap': config.get('risk', {}).get('kelly_hard_cap', 0.02),
            'kelly_global_notional_cap_pct': config.get('risk', {}).get('kelly_global_notional_cap_pct', 0.02),
            'max_yes_position': config.get('risk', {}).get('max_yes_position', 5),
            'max_no_position': config.get('risk', {}).get('max_no_position', 5),
        }
        
        return risk_config
    except Exception as e:
        print(f"[ERROR] Failed to load profile YAML: {e}")
        return None

def get_risk_envelope_config():
    """Get risk envelope configuration."""
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
        
        envelope = get_kalshi_crypto_15m_risk_envelope()
        
        # Get current bankroll for USD calculations
        bankroll = envelope._live_bankroll if hasattr(envelope, '_live_bankroll') else 30.81
        
        config = {
            'per_agent_limit_usd': envelope.per_agent_limit,
            'total_venue_limit_usd': envelope.total_venue_limit,
            'bankroll_usd': bankroll,
            'agent_max_notional_pct': envelope.per_agent_limit / bankroll if bankroll > 0 else 0.03,
            'venue_max_total_notional_pct': envelope.total_venue_limit / bankroll if bankroll > 0 else 0.15,
        }
        
        return config
    except Exception as e:
        print(f"[ERROR] Failed to get risk envelope config: {e}")
        return None

def get_profile_adapter_config():
    """Get profile adapter configuration."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_crypto_15m_profile
        
        profile = get_crypto_15m_profile()
        
        config = {
            'agent_max_notional_pct': profile.agent_max_notional_pct,
            'venue_max_total_notional_pct': profile.venue_max_total_notional_pct,
            'guardrails_per_window_risk_pct': profile.guardrails_per_window_risk_pct,
            'guardrails_total_venue_risk_pct': profile.guardrails_total_venue_risk_pct,
            'kelly_hard_cap': profile.kelly_hard_cap,
            'kelly_global_notional_cap_pct': profile.kelly_global_notional_cap_pct,
        }
        
        return config
    except Exception as e:
        print(f"[ERROR] Failed to get profile adapter config: {e}")
        return None

def get_risk_limits_yaml_config():
    """Get configuration from risk_limits.yaml (single source of truth for URM)."""
    try:
        import yaml
        risk_limits_path = project_root / "config" / "risk_limits.yaml"
        
        with open(risk_limits_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Extract key risk parameters
        risk_config = {
            'max_cycle_risk_pct': config.get('bankroll', {}).get('max_cycle_risk_pct', 0.05),
            'max_total_risk_pct': config.get('bankroll', {}).get('max_total_risk_pct', 0.25),
            'per_trade_max_notional_pct': config.get('per_trade', {}).get('max_notional_pct', 0.02),
            'correlated_stack_max_notional_pct': config.get('correlated_stack', {}).get('max_notional_pct', 0.15),
        }
        
        return risk_config
    except Exception as e:
        print(f"[ERROR] Failed to load risk_limits.yaml: {e}")
        return None

def get_unified_risk_manager_config():
    """Get unified risk manager configuration."""
    try:
        from merid.risk.unified_risk_manager import get_unified_risk_manager
        
        urm = get_unified_risk_manager()
        
        # Get current configuration
        config = {
            'cycle_cap_pct': urm._cycle_cap_pct if hasattr(urm, '_cycle_cap_pct') else 0.05,
            'total_cap_pct': urm._total_cap_pct if hasattr(urm, '_total_cap_pct') else 0.25,
            'correlated_cap_pct': urm._correlated_cap_pct if hasattr(urm, '_correlated_cap_pct') else 0.15,
            'per_trade_notional_usd': urm._per_trade_notional if hasattr(urm, '_per_trade_notional') else None,
        }
        
        return config
    except Exception as e:
        print(f"[ERROR] Failed to get unified risk manager config: {e}")
        return None

def get_unified_sizing_config():
    """Get unified sizing configuration."""
    try:
        from merid.prediction.unified_sizing import compute_order_size
        
        # Test with sample values to see what limits are applied
        bankroll = 30.81
        price_cents = 30  # Lower price to allow more contracts within limit
        asset = "BTC"
        
        count, notional, metadata = compute_order_size(
            bankroll_usd=Decimal(str(bankroll)),
            price_cents=price_cents,
            asset=asset,
        )
        
        config = {
            'max_notional_from_compute': float(notional),
            'count_from_compute': count,
            'test_bankroll': bankroll,
            'test_price_cents': price_cents,
        }
        
        return config
    except Exception as e:
        print(f"[ERROR] Failed to get unified sizing config: {e}")
        return None

def compare_configs(profile_yaml, risk_envelope, profile_adapter, risk_limits_yaml, urm, unified_sizing):
    """Compare configurations across layers and identify mismatches."""
    mismatches = []
    
    print("\n" + "="*80)
    print("RISK CONFIGURATION AUDIT REPORT")
    print("="*80)
    
    # 1. Profile YAML vs Risk Envelope
    print("\n[1] PROFILE YAML vs RISK ENVELOPE")
    print("-" * 80)
    if profile_yaml and risk_envelope:
        yaml_pct = profile_yaml['agent_max_notional_pct']
        envelope_pct = risk_envelope['agent_max_notional_pct']
        
        print(f"  agent_max_notional_pct:")
        print(f"    Profile YAML: {yaml_pct:.4f} ({yaml_pct*100:.2f}%)")
        print(f"    Risk Envelope: {envelope_pct:.4f} ({envelope_pct*100:.2f}%)")
        
        if abs(yaml_pct - envelope_pct) > 0.0001:
            mismatches.append(f"agent_max_notional_pct mismatch: YAML={yaml_pct:.4f}, Envelope={envelope_pct:.4f}")
            print(f"    ⚠️  MISMATCH DETECTED")
        else:
            print(f"    ✓ MATCH")
        
        yaml_venue_pct = profile_yaml['venue_max_total_notional_pct']
        envelope_venue_pct = risk_envelope['venue_max_total_notional_pct']
        
        print(f"  venue_max_total_notional_pct:")
        print(f"    Profile YAML: {yaml_venue_pct:.4f} ({yaml_venue_pct*100:.2f}%)")
        print(f"    Risk Envelope: {envelope_venue_pct:.4f} ({envelope_venue_pct*100:.2f}%)")
        
        if abs(yaml_venue_pct - envelope_venue_pct) > 0.0001:
            mismatches.append(f"venue_max_total_notional_pct mismatch: YAML={yaml_venue_pct:.4f}, Envelope={envelope_venue_pct:.4f}")
            print(f"    ⚠️  MISMATCH DETECTED")
        else:
            print(f"    ✓ MATCH")
    
    # 2. Profile YAML vs Profile Adapter
    print("\n[2] PROFILE YAML vs PROFILE ADAPTER")
    print("-" * 80)
    if profile_yaml and profile_adapter:
        for key in ['agent_max_notional_pct', 'venue_max_total_notional_pct', 
                   'guardrails_per_window_risk_pct', 'guardrails_total_venue_risk_pct',
                   'kelly_hard_cap', 'kelly_global_notional_cap_pct']:
            yaml_val = profile_yaml.get(key)
            adapter_val = profile_adapter.get(key)
            
            print(f"  {key}:")
            print(f"    Profile YAML: {yaml_val:.4f}")
            print(f"    Profile Adapter: {adapter_val:.4f}")
            
            if yaml_val is not None and adapter_val is not None and abs(yaml_val - adapter_val) > 0.0001:
                mismatches.append(f"{key} mismatch: YAML={yaml_val:.4f}, Adapter={adapter_val:.4f}")
                print(f"    ⚠️  MISMATCH DETECTED")
            else:
                print(f"    ✓ MATCH")
    
    # 3. Profile YAML vs risk_limits.yaml (Single Source of Truth for URM)
    print("\n[3] PROFILE YAML vs RISK_LIMITS.YAML (URM Source of Truth)")
    print("-" * 80)
    if profile_yaml and risk_limits_yaml:
        # Compare per-trade limits
        yaml_per_trade = profile_yaml['agent_max_notional_pct']
        risk_limits_per_trade = risk_limits_yaml['per_trade_max_notional_pct']
        
        print(f"  Per-trade notional limit:")
        print(f"    Profile YAML (agent_max_notional_pct): {yaml_per_trade:.4f} ({yaml_per_trade*100:.2f}%)")
        print(f"    risk_limits.yaml (per_trade.max_notional_pct): {risk_limits_per_trade:.4f} ({risk_limits_per_trade*100:.2f}%)")
        
        if abs(yaml_per_trade - risk_limits_per_trade) > 0.0001:
            mismatches.append(f"Per-trade limit mismatch: YAML={yaml_per_trade:.4f}, risk_limits.yaml={risk_limits_per_trade:.4f}")
            print(f"    ⚠️  MISMATCH DETECTED")
        else:
            print(f"    ✓ MATCH")
        
        # Compare cycle/window limits
        yaml_window = profile_yaml['guardrails_total_venue_risk_pct']
        risk_limits_cycle = risk_limits_yaml['max_cycle_risk_pct']
        
        print(f"  Cycle/window risk limit:")
        print(f"    Profile YAML (guardrails_total_venue_risk_pct): {yaml_window:.4f} ({yaml_window*100:.2f}%)")
        print(f"    risk_limits.yaml (bankroll.max_cycle_risk_pct): {risk_limits_cycle:.4f} ({risk_limits_cycle*100:.2f}%)")
        
        if abs(yaml_window - risk_limits_cycle) > 0.0001:
            mismatches.append(f"Cycle/window limit mismatch: YAML={yaml_window:.4f}, risk_limits.yaml={risk_limits_cycle:.4f}")
            print(f"    ⚠️  MISMATCH DETECTED")
        else:
            print(f"    ✓ MATCH")
        
        # Compare total venue limits
        yaml_total = profile_yaml['venue_max_total_notional_pct']
        risk_limits_total = risk_limits_yaml['max_total_risk_pct']
        
        print(f"  Total venue risk limit:")
        print(f"    Profile YAML (venue_max_total_notional_pct): {yaml_total:.4f} ({yaml_total*100:.2f}%)")
        print(f"    risk_limits.yaml (bankroll.max_total_risk_pct): {risk_limits_total:.4f} ({risk_limits_total*100:.2f}%)")
        
        if abs(yaml_total - risk_limits_total) > 0.0001:
            mismatches.append(f"Total venue limit mismatch: YAML={yaml_total:.4f}, risk_limits.yaml={risk_limits_total:.4f}")
            print(f"    ⚠️  MISMATCH DETECTED")
        else:
            print(f"    ✓ MATCH")
    
    # 4. Risk Envelope vs Unified Risk Manager
    print("\n[4] RISK ENVELOPE vs UNIFIED RISK MANAGER")
    print("-" * 80)
    if risk_envelope and urm:
        envelope_per_agent = risk_envelope['per_agent_limit_usd']
        envelope_total = risk_envelope['total_venue_limit_usd']
        
        urm_cycle_pct = urm['cycle_cap_pct']
        urm_total_pct = urm['total_cap_pct']
        
        bankroll = risk_envelope['bankroll_usd']
        
        print(f"  Per-agent limit:")
        print(f"    Risk Envelope: ${envelope_per_agent:.2f} ({envelope_per_agent/bankroll*100:.2f}% of ${bankroll:.2f})")
        print(f"    URM cycle cap: {urm_cycle_pct:.4f} ({urm_cycle_pct*100:.2f}%) = ${urm_cycle_pct*bankroll:.2f}")
        
        expected_cycle_usd = urm_cycle_pct * bankroll
        if abs(envelope_per_agent - expected_cycle_usd) > 0.01:
            mismatches.append(f"Per-agent limit mismatch: Envelope=${envelope_per_agent:.2f}, URM=${expected_cycle_usd:.2f}")
            print(f"    ⚠️  MISMATCH DETECTED")
        else:
            print(f"    ✓ MATCH")
        
        print(f"  Total venue limit:")
        print(f"    Risk Envelope: ${envelope_total:.2f} ({envelope_total/bankroll*100:.2f}% of ${bankroll:.2f})")
        print(f"    URM total cap: {urm_total_pct:.4f} ({urm_total_pct*100:.2f}%) = ${urm_total_pct*bankroll:.2f}")
        
        expected_total_usd = urm_total_pct * bankroll
        if abs(envelope_total - expected_total_usd) > 0.01:
            mismatches.append(f"Total venue limit mismatch: Envelope=${envelope_total:.2f}, URM=${expected_total_usd:.2f}")
            print(f"    ⚠️  MISMATCH DETECTED")
        else:
            print(f"    ✓ MATCH")
        
        # Check per-trade notional limit
        if urm['per_trade_notional_usd'] is not None:
            urm_per_trade = urm['per_trade_notional_usd']
            expected_per_trade = profile_yaml['agent_max_notional_pct'] * bankroll if profile_yaml else None
            
            print(f"  Per-trade notional limit:")
            print(f"    URM: ${urm_per_trade:.2f}")
            if expected_per_trade:
                print(f"    Expected (from YAML): ${expected_per_trade:.2f}")
                if abs(urm_per_trade - expected_per_trade) > 0.01:
                    mismatches.append(f"Per-trade notional mismatch: URM=${urm_per_trade:.2f}, Expected=${expected_per_trade:.2f}")
                    print(f"    ⚠️  MISMATCH DETECTED")
                else:
                    print(f"    ✓ MATCH")
    
    # 5. Unified Sizing vs Expected
    print("\n[5] UNIFIED SIZING vs EXPECTED")
    print("-" * 80)
    if unified_sizing and profile_yaml:
        computed_notional = unified_sizing['max_notional_from_compute']
        expected_notional = profile_yaml['agent_max_notional_pct'] * unified_sizing['test_bankroll']
        test_price_cents = unified_sizing['test_price_cents']
        contract_cost = test_price_cents / 100.0
        
        print(f"  Max notional for test order:")
        print(f"    Unified sizing: ${computed_notional:.2f} ({unified_sizing['count_from_compute']} contracts @ {test_price_cents}c)")
        print(f"    Expected (from YAML): ${expected_notional:.2f}")
        print(f"    Contract cost: ${contract_cost:.2f}")
        
        # Allow difference up to cost of 1 contract (due to floor operation)
        tolerance = contract_cost
        if abs(computed_notional - expected_notional) > tolerance:
            mismatches.append(f"Unified sizing mismatch: Computed=${computed_notional:.2f}, Expected=${expected_notional:.2f}")
            print(f"    ⚠️  MISMATCH DETECTED (diff=${abs(computed_notional - expected_notional):.2f} > tolerance=${tolerance:.2f})")
        else:
            print(f"    ✓ MATCH (diff=${abs(computed_notional - expected_notional):.2f} within contract cost tolerance)")
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    if mismatches:
        print(f"\n⚠️  {len(mismatches)} MISMATCH(ES) DETECTED:\n")
        for i, mismatch in enumerate(mismatches, 1):
            print(f"  {i}. {mismatch}")
        print("\n⚠️  ACTION REQUIRED: Fix mismatches to ensure consistent risk enforcement")
    else:
        print("\n✓ No mismatches detected - all risk configurations are consistent")
    
    print("\n" + "="*80)
    
    return mismatches

def main():
    """Main audit function."""
    print("Loading risk configurations...")
    
    # Load all configurations
    profile_yaml = get_profile_yaml_config()
    risk_envelope = get_risk_envelope_config()
    profile_adapter = get_profile_adapter_config()
    risk_limits_yaml = get_risk_limits_yaml_config()
    urm = get_unified_risk_manager_config()
    unified_sizing = get_unified_sizing_config()
    
    # Compare and report
    mismatches = compare_configs(profile_yaml, risk_envelope, profile_adapter, risk_limits_yaml, urm, unified_sizing)
    
    # Exit with error code if mismatches found
    if mismatches:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
