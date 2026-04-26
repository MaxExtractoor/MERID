"""Test script to verify all consensus bypass mechanisms are disabled."""

import os
import sys

# Set bypass attempts to verify they are rejected
os.environ["MERID_CRYPTO_MM_CONSENSUS_MODE"] = "bypass"
os.environ["MERID_PM_BYPASS_SWARM_CONSENSUS_AGENTS"] = "BTC_15M,ETH_HOURLY"

sys.path.insert(0, ".")

def test_crypto_edge_production_rejects_bypass():
    """Test that crypto_edge_production forces bypass to full mode."""
    from merid.prediction.crypto_edge_production import get_crypto_edge_runtime
    
    runtime = get_crypto_edge_runtime()
    
    # Bypass mode should be rejected and forced to "full"
    assert runtime.mm_consensus_mode != "bypass", \
        f"CRITICAL: mm_consensus_mode is '{runtime.mm_consensus_mode}' but should never be 'bypass'"
    
    assert runtime.mm_consensus_mode in ("full", "soft"), \
        f"CRITICAL: mm_consensus_mode must be 'full' or 'soft', got '{runtime.mm_consensus_mode}'"
    
    print(f"✓ crypto_edge_production: mm_consensus_mode = '{runtime.mm_consensus_mode}' (bypass rejected)")
    return True

def test_settings_rejects_bypass():
    """Test that settings forces bypass to full mode at startup."""
    from merid.settings import settings
    
    # Settings should have rejected bypass and set to "full"
    assert settings.MERID_CRYPTO_MM_CONSENSUS_MODE != "bypass", \
        f"CRITICAL: MERID_CRYPTO_MM_CONSENSUS_MODE is '{settings.MERID_CRYPTO_MM_CONSENSUS_MODE}' but should never be 'bypass'"
    
    assert settings.MERID_CRYPTO_MM_CONSENSUS_MODE in ("full", "soft"), \
        f"CRITICAL: MERID_CRYPTO_MM_CONSENSUS_MODE must be 'full' or 'soft', got '{settings.MERID_CRYPTO_MM_CONSENSUS_MODE}'"
    
    print(f"✓ settings: MERID_CRYPTO_MM_CONSENSUS_MODE = '{settings.MERID_CRYPTO_MM_CONSENSUS_MODE}' (bypass rejected)")
    return True

def test_swarm_consensus_bypassed_returns_false():
    """Test that _swarm_consensus_bypassed always returns False."""
    from merid.prediction.agent_grid_config import parse_agent_config
    from merid.prediction.trading_agent import KalshiTradingAgent
    from unittest.mock import MagicMock
    
    # Create agent config with bypass_swarm_consensus=True
    raw_config = {
        "name": "TEST_BYPASS",
        "assets": ["BTC"],
        "timeframes": ["15m"],
        "bypass_swarm_consensus": True,  # Attempt to bypass
    }
    
    config = parse_agent_config(raw_config)
    
    # Create a mock agent to test the method
    agent = MagicMock()
    agent.config = config
    agent.logger = MagicMock()
    
    # The method should always return False
    result = KalshiTradingAgent._swarm_consensus_bypassed(agent)
    
    assert result == False, \
        f"CRITICAL: _swarm_consensus_bypassed() returned {result} but should always be False"
    
    # Should have logged a security warning
    agent.logger.warning.assert_called()
    warning_call = agent.logger.warning.call_args_list[0]
    assert "[SECURITY]" in str(warning_call), "Should log [SECURITY] warning for bypass attempt"
    
    print(f"✓ _swarm_consensus_bypassed() returned False (bypass attempt blocked)")
    return True

def main():
    """Run all safety tests."""
    print("="*60)
    print("SAFETY TEST: Verifying all consensus bypass mechanisms are DISABLED")
    print("="*60)
    print()
    
    tests = [
        ("crypto_edge_production rejects bypass", test_crypto_edge_production_rejects_bypass),
        ("settings rejects bypass", test_settings_rejects_bypass),
        ("_swarm_consensus_bypassed returns False", test_swarm_consensus_bypassed_returns_false),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"✗ {name}: FAILED - {e}")
            failed += 1
    
    print()
    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60)
    
    if failed > 0:
        print("\n🚨 CRITICAL SAFETY ISSUES DETECTED! DO NOT DEPLOY! 🚨")
        sys.exit(1)
    else:
        print("\n✅ All bypass mechanisms are properly disabled. Execution guard is bulletproof.")
        sys.exit(0)

if __name__ == "__main__":
    main()
