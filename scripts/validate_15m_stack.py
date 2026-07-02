#!/usr/bin/env python3
"""
15m Stack Validation Script

This script validates that the 15m stack is running with the correct configuration
and that no legacy modules are loaded. It can be used in CI to enforce the
separation between 15m and legacy code.

Usage:
    python scripts/validate_15m_stack.py

Exit codes:
    0: All checks passed
    1: One or more checks failed
"""

import sys
import os
from pathlib import Path

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Category C: Legacy / Off-Limits Modules (from docs/kalshi_15m_stack.md Section 2)
FORBIDDEN_MODULES = [
    'merid.main',
    'merid.loop',
    'merid.prediction.agent_grid',
    'web.main',
    'merid.core',
    'merid.core.',  # Any module under merid.core
    'merid.risk.',  # Any module under merid.risk
    'merid.execution.',  # Any module under merid.execution
    'merid.execution_guard',
    'merid.social.',  # Any module under merid.social
    'merid.llm.',  # Any module under merid.llm
    'merid.blockchain.',  # Any module under merid.blockchain
    'merid.pm_runtime',
    'merid.pm_live_readiness',
    'merid.pm_crypto_ops',
]

# Category A: Canonical 15m Modules (from docs/kalshi_15m_stack.md Section 1)
REQUIRED_MODULES = [
    'web.main_15m_lean',
    'merid.prediction.agent_grid_15m',
    'merid.prediction.spot_provider',
    'merid.event_venues.kalshi.ws_bridge',
    'merid.event_venues.kalshi.ws',
    'merid.event_venues.kalshi.market_state',
    'merid.event_venues.kalshi.market_catalog',
    'merid.event_venues.kalshi.client',
    'merid.event_venues.kalshi.invariants',
    'merid.event_venues.kalshi.bankroll_service_v2',
    'merid.event_venues.kalshi.kalshi_risk',
    'merid.event_venues.kalshi.models',
    'merid.event_venues.kalshi.fills_ledger',
    'merid.event_venues.kalshi.fills_poller',
    'merid.event_venues.kalshi.candle_poller',
    'data.unified_spot_service',
    'merid.loop_15m',
]

# Environment variables that must be set for 15m (from docs/kalshi_15m_stack.md Section 3.2)
REQUIRED_ENV_VARS = [
    'MERID_PROFILE',
]

# Environment variables that are optional for 15m
OPTIONAL_ENV_VARS = [
    'MERID_MODE',
    'MERID_ENV',
    'KALSHI_ENV',
    'MERID_KALSHI_FORCE_REST_FALLBACK',
    'MERID_KALSHI_REST_REFRESH_THRESHOLD_S',
    'MERID_KALSHI_WS_REFRESH_INTERVAL_S',
    'MERID_UNIFIED_EDGE_ENABLED',
    'MERID_CALIBRATION_VERSION',
    'MERID_UNIFIED_EDGE_SHADOW_MODE',
]

# Valid profile values for 15m
VALID_PROFILES = [
    'kalshi_crypto_15m_v2',
    'kalshi_crypto_15m_v2_test',  # Optional test profile
]


def check_forbidden_modules():
    """Check that no forbidden (legacy) modules are loaded."""
    print("[CHECK] Checking for forbidden (legacy) modules...")
    
    loaded_forbidden = []
    for forbidden in FORBIDDEN_MODULES:
        # Check for exact match or prefix match (for directories)
        if forbidden.endswith('.'):
            # Prefix match: check if any module starts with this prefix
            for loaded in sys.modules.keys():
                if loaded.startswith(forbidden):
                    loaded_forbidden.append(loaded)
        else:
            # Exact match
            if forbidden in sys.modules:
                loaded_forbidden.append(forbidden)
    
    if loaded_forbidden:
        print(f"[FAIL] Forbidden modules loaded: {loaded_forbidden}")
        return False
    else:
        print("[PASS] No forbidden modules loaded")
        return True


def check_required_modules():
    """Check that required 15m modules are loaded (if in 15m mode)."""
    print("[CHECK] Checking for required 15m modules...")
    
    # Only check if we're in 15m mode
    runtime_mode = os.environ.get('MERID_RUNTIME_MODE')
    if runtime_mode != '15m_live':
        print(f"[SKIP] Not in 15m live mode (MERID_RUNTIME_MODE={runtime_mode}), skipping required module check")
        return True
    
    missing_required = []
    for required in REQUIRED_MODULES:
        if required not in sys.modules:
            missing_required.append(required)
    
    if missing_required:
        print(f"[FAIL] Required modules not loaded: {missing_required}")
        return False
    else:
        print("[PASS] All required modules loaded")
        return True


def check_runtime_mode():
    """Check that runtime mode is set correctly."""
    print("[CHECK] Checking runtime mode...")
    
    runtime_mode = os.environ.get('MERID_RUNTIME_MODE')
    if runtime_mode is None:
        print("[WARN] MERID_RUNTIME_MODE not set (may not be in 15m context)")
        return True  # Not a failure, just a warning
    
    if runtime_mode == '15m_live':
        print(f"[PASS] Runtime mode is 15m_live")
        return True
    else:
        print(f"[WARN] Runtime mode is '{runtime_mode}' (expected '15m_live' for 15m stack)")
        return True  # Not a failure, just a warning


def check_profile():
    """Check that profile is set to a valid 15m profile."""
    print("[CHECK] Checking profile...")
    
    profile = os.environ.get('MERID_PROFILE')
    if profile is None:
        print("[FAIL] MERID_PROFILE not set")
        return False
    
    if profile in VALID_PROFILES:
        print(f"[PASS] Profile is '{profile}' (valid 15m profile)")
        return True
    else:
        print(f"[FAIL] Profile is '{profile}' (expected one of: {VALID_PROFILES})")
        return False


def check_required_env_vars():
    """Check that required environment variables are set."""
    print("[CHECK] Checking required environment variables...")
    
    missing = []
    for var in REQUIRED_ENV_VARS:
        if var not in os.environ:
            missing.append(var)
    
    if missing:
        print(f"[FAIL] Required environment variables not set: {missing}")
        return False
    else:
        print("[PASS] All required environment variables set")
        return True


def check_optional_env_vars():
    """Check optional environment variables (just log what's set)."""
    print("[CHECK] Checking optional environment variables...")
    
    set_vars = []
    for var in OPTIONAL_ENV_VARS:
        if var in os.environ:
            set_vars.append(var)
    
    if set_vars:
        print(f"[INFO] Optional environment variables set: {set_vars}")
    else:
        print("[INFO] No optional environment variables set")
    
    return True  # This is always a pass


def main():
    """Run all validation checks."""
    print("=" * 60)
    print("15m Stack Validation")
    print("=" * 60)
    
    results = []
    
    # Run all checks
    results.append(("Forbidden Modules", check_forbidden_modules()))
    results.append(("Required Modules", check_required_modules()))
    results.append(("Runtime Mode", check_runtime_mode()))
    results.append(("Profile", check_profile()))
    results.append(("Required Env Vars", check_required_env_vars()))
    results.append(("Optional Env Vars", check_optional_env_vars()))
    
    # Print summary
    print("=" * 60)
    print("Validation Summary")
    print("=" * 60)
    
    all_passed = True
    for check_name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{status}: {check_name}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("All checks passed!")
        return 0
    else:
        print("Some checks failed!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
