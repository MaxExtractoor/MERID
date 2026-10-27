#!/usr/bin/env python3
"""
Config Sanity Check for Dynamic Entry Window System

Loads dynamic_entry_window.py in isolation and prints the effective policy
for each asset with current .env configuration.

This catches mis-typed env vars or missing overrides before the process starts.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction.dynamic_entry_window import get_policies, DEFAULT_POLICIES
import json


def main():
    print("=" * 70)
    print("Dynamic Entry Window - Config Sanity Check")
    print("=" * 70)
    
    # Load current policies
    policies = get_policies()
    
    print(f"\nLoaded policies from environment variables:")
    print(f"Number of assets configured: {len(policies)}")
    print()
    
    # Print each policy
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        if asset not in policies:
            print(f"✗ FAIL: {asset} not found in loaded policies")
            continue
        
        policy = policies[asset]
        
        print(f"{asset}:")
        print(f"  Policy Name: {policy.policy_name}")
        print(f"  Base Window: {policy.base_window_start_minutes} - {policy.base_window_end_minutes} minutes")
        print(f"  Terminal Enabled: {policy.terminal_config.enabled}")
        if policy.terminal_config.enabled:
            print(f"  Terminal Band: 0 - {policy.terminal_config.max_terminal_minutes} minutes")
            print(f"  Terminal Edge Threshold: {policy.terminal_config.edge_threshold_pct}%")
        print()
    
    # Check for missing assets
    expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    loaded_assets = set(policies.keys())
    missing = expected_assets - loaded_assets
    
    if missing:
        print(f"✗ FAIL: Missing assets: {missing}")
        return 1
    
    # Check for sanity (window_start > window_end)
    sanity_issues = []
    for asset, policy in policies.items():
        if policy.base_window_start_minutes <= policy.base_window_end_minutes:
            sanity_issues.append(f"{asset}: window_start ({policy.base_window_start_minutes}) <= window_end ({policy.base_window_end_minutes})")
    
    if sanity_issues:
        print("✗ FAIL: Sanity issues detected:")
        for issue in sanity_issues:
            print(f"  - {issue}")
        return 1
    
    # Print JSON summary for machine parsing
    print("=" * 70)
    print("JSON Summary:")
    print("=" * 70)
    summary = {}
    for asset, policy in policies.items():
        summary[asset] = {
            "policy_name": policy.policy_name,
            "base_window_start_minutes": policy.base_window_start_minutes,
            "base_window_end_minutes": policy.base_window_end_minutes,
            "terminal_enabled": policy.terminal_config.enabled,
            "terminal_max_minutes": policy.terminal_config.max_terminal_minutes,
            "terminal_edge_threshold_pct": policy.terminal_config.edge_threshold_pct,
        }
    print(json.dumps(summary, indent=2))
    
    print()
    print("=" * 70)
    print("✓ PASS: All config checks passed")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
