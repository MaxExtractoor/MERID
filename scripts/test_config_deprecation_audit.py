#!/usr/bin/env python3
"""
Config Deprecation Audit Test

Validates that deprecated config files are properly marked and that
kalshi_crypto_15m_v2.yaml is the single source of truth for 15m crypto stack.

This test ensures:
1. Deprecated configs have proper deprecation notices
2. Production config (kalshi_crypto_15m_v2.yaml) contains all necessary values
3. No conflicting values between deprecated and production configs
"""

import sys
from pathlib import Path
import yaml

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))


def test_deprecated_configs_have_notices():
    """Test that deprecated config files have proper deprecation notices."""
    
    deprecated_configs = [
        "config/profiles/trade_hold_live.yaml",
        "config/kalshi_15m_thresholds.yaml",
        "config/risk_limits.yaml",
        "config/live_session_guardrails.yaml",
    ]
    
    for config_path in deprecated_configs:
        full_path = repo_root / config_path
        if not full_path.exists():
            print(f"❌ FAIL: {config_path} does not exist")
            continue
        
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for deprecation notice
        if "DEPRECATED" not in content and "kalshi_crypto_15m_v2" not in content:
            print(f"❌ FAIL: {config_path} missing deprecation notice")
            return False
        
        # Check for single source of truth reference
        if "kalshi_crypto_15m_v2.yaml" not in content:
            print(f"❌ FAIL: {config_path} missing reference to kalshi_crypto_15m_v2.yaml")
            return False
        
        print(f"✅ PASS: {config_path} has proper deprecation notice")
    
    return True


def test_production_config_completeness():
    """Test that production config has all necessary sections."""
    
    production_config = repo_root / "config/profiles/kalshi_crypto_15m_v2.yaml"
    
    if not production_config.exists():
        print("❌ FAIL: Production config kalshi_crypto_15m_v2.yaml does not exist")
        return False
    
    with open(production_config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    # Check for critical sections
    required_sections = [
        "profile_name",
        "risk_policy",
        "guardrails",
        "throttling",
        "assets",
        "price_range",
        "signal_mode",
    ]
    
    for section in required_sections:
        if section not in config:
            print(f"❌ FAIL: Production config missing required section: {section}")
            return False
    
    # Check for fixed $1 exposure cap
    if "risk_policy" in config:
        if "fixed_exposure_cap_usd" not in config["risk_policy"]:
            print("❌ FAIL: Production config missing fixed_exposure_cap_usd")
            return False
        if config["risk_policy"]["fixed_exposure_cap_usd"] != 1.00:
            print(f"❌ FAIL: fixed_exposure_cap_usd is {config['risk_policy']['fixed_exposure_cap_usd']}, expected 1.00")
            return False
    
    # Check for all 5 assets
    required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    if "assets" in config:
        for asset in required_assets:
            if asset not in config["assets"]:
                print(f"❌ FAIL: Production config missing asset: {asset}")
                return False
    
    print("✅ PASS: Production config has all required sections")
    return True


def test_spread_threshold_alignment():
    """Test that spread thresholds are aligned across configs."""
    
    production_config = repo_root / "config/profiles/kalshi_crypto_15m_v2.yaml"
    threshold_config = repo_root / "config/kalshi_15m_thresholds.yaml"
    
    with open(production_config, "r", encoding="utf-8") as f:
        prod_config = yaml.safe_load(f)
    
    with open(threshold_config, "r", encoding="utf-8") as f:
        thresh_config = yaml.safe_load(f)
    
    # Check production config has canonical spread
    if "guardrails" in prod_config:
        prod_spread = prod_config["guardrails"].get("max_spread_cents")
        if prod_spread != 100:
            print(f"⚠️  WARNING: Production max_spread_cents is {prod_spread}, expected 100 (crisis regime)")
    
    # Check threshold config has been updated to 30c
    if "spread_thresholds" in thresh_config:
        default_spread = thresh_config["spread_thresholds"].get("default", {}).get("max_spread_cents")
        if default_spread != 30:
            print(f"❌ FAIL: Threshold config default spread is {default_spread}, expected 30")
            return False
    
    print("✅ PASS: Spread thresholds are aligned")
    return True


def test_trade_hold_config_disabled():
    """Test that trade_hold_live.yaml is disabled."""
    
    trade_hold_config = repo_root / "config/profiles/trade_hold_live.yaml"
    
    with open(trade_hold_config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    if config.get("enabled", True) != False:
        print("❌ FAIL: trade_hold_live.yaml is not disabled")
        return False
    
    print("✅ PASS: trade_hold_live.yaml is disabled")
    return True


def main():
    """Run all config deprecation audit tests."""
    
    print("=" * 60)
    print("Config Deprecation Audit Test")
    print("=" * 60)
    print()
    
    tests = [
        ("Deprecated configs have notices", test_deprecated_configs_have_notices),
        ("Production config completeness", test_production_config_completeness),
        ("Spread threshold alignment", test_spread_threshold_alignment),
        ("Trade hold config disabled", test_trade_hold_config_disabled),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\nRunning: {test_name}")
        print("-" * 60)
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ FAIL: {test_name} raised exception: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All config deprecation audit tests passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
