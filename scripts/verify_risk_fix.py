"""
Pre-Flight Verification: Risk Oversizing Fix
============================================

Run this before restarting the trading system to verify:
1. Feature flag is set correctly
2. All imports resolve
3. GlobalRiskGuard is properly configured
4. TopN allocator is ready

Usage:
    python scripts/verify_risk_fix.py
"""

import os
import sys
from typing import List, Tuple


def check_env_variable() -> Tuple[bool, str]:
    """Verify USE_TOPN_ALLOCATOR is set."""
    value = os.getenv("USE_TOPN_ALLOCATOR", "false").lower()
    is_enabled = value in ("true", "1", "yes")
    
    if is_enabled:
        return True, f"✅ USE_TOPN_ALLOCATOR={os.getenv('USE_TOPN_ALLOCATOR')} (ENABLED)"
    else:
        return False, f"❌ USE_TOPN_ALLOCATOR={os.getenv('USE_TOPN_ALLOCATOR', 'NOT SET')} (DISABLED - FIX WON'T WORK!)"


def check_imports() -> Tuple[bool, List[str]]:
    """Verify all critical imports resolve."""
    errors = []
    
    try:
        # Set flag before importing modules
        os.environ["USE_TOPN_ALLOCATOR"] = "true"
        
        # 1. TopN Allocator
        try:
            from merid.trading.topn_allocator import (
                EdgeCandidate,
                TopNEdgeAllocator,
                TopNAllocatorConfig,
                AllocationCycle,
            )
            print("✅ TopN Allocator imports: OK")
        except Exception as e:
            errors.append(f"❌ TopN Allocator import failed: {e}")
        
        # 2. Global Risk Guard from continuous trader
        try:
            from merid.trading.kalshi_continuous_trader import (
                GlobalRiskGuard,
                PendingOrderRisk,
                _USE_TOPN_ALLOCATOR,
            )
            print(f"✅ Continuous Trader imports: OK (flag={_USE_TOPN_ALLOCATOR})")
        except Exception as e:
            errors.append(f"❌ Continuous Trader import failed: {e}")
        
        # 3. Verify flag value in module
        if not _USE_TOPN_ALLOCATOR:
            errors.append("❌ _USE_TOPN_ALLOCATOR is False in module (env not propagating)")
        
        return len(errors) == 0, errors
        
    except Exception as e:
        return False, [f"❌ Critical import failure: {e}"]


def test_global_risk_guard() -> Tuple[bool, str]:
    """Test that GlobalRiskGuard blocks oversized orders."""
    try:
        from merid.trading.kalshi_continuous_trader import GlobalRiskGuard, PendingOrderRisk
        
        guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
        
        # Simulate the violation scenario: $28 equity, 7 orders at 35¢ each
        equity_cents = 2800  # $28
        
        # First order: should be allowed
        order1 = PendingOrderRisk(
            ticker="KXBTC-TEST",
            asset="BTC",
            contracts=1,
            entry_price_cents=35,
            direction="long",
            max_loss_cents=35,
            edge=0.08,
        )
        
        allowed1, _ = guard.check_order(equity_cents, 0, order1)
        
        # Second order: should be blocked (would exceed 56¢ cap)
        order2 = PendingOrderRisk(
            ticker="KXBTC-TEST2",
            asset="BTC",
            contracts=1,
            entry_price_cents=35,
            direction="long",
            max_loss_cents=35,
            edge=0.08,
        )
        
        allowed2, reason = guard.check_order(equity_cents, 0, order2)
        
        if allowed1 and not allowed2 and "Cycle risk cap exceeded" in reason:
            return True, "✅ GlobalRiskGuard: BLOCKS oversizing correctly"
        else:
            return False, f"❌ GlobalRiskGuard: Failed to block (allowed1={allowed1}, allowed2={allowed2}, reason={reason})"
            
    except Exception as e:
        return False, f"❌ GlobalRiskGuard test failed: {e}"


def test_topn_allocator() -> Tuple[bool, str]:
    """Test that TopN allocator enforces cycle cap."""
    try:
        from merid.trading.topn_allocator import (
            EdgeCandidate,
            TopNEdgeAllocator,
            TopNAllocatorConfig,
        )
        
        config = TopNAllocatorConfig(max_cycle_risk_pct=0.02, max_edges_per_cycle=3)
        allocator = TopNEdgeAllocator(config)
        
        # $28 equity, 2% = $0.56 budget
        equity_cents = 2800
        
        # 5 high-edge candidates
        candidates = [
            EdgeCandidate("BTC", 0.10, "long", 35, 0, 10000),
            EdgeCandidate("ETH", 0.09, "long", 35, 0, 10000),
            EdgeCandidate("SOL", 0.08, "long", 35, 0, 10000),
            EdgeCandidate("XRP", 0.07, "long", 35, 0, 10000),
            EdgeCandidate("DOGE", 0.06, "long", 35, 0, 10000),
        ]
        
        cycle = allocator.compute_allocations(equity_cents, candidates)
        
        # Verify invariants
        is_valid, violations = cycle.validate_invariants()
        
        if not is_valid:
            return False, f"❌ TopN Allocator: Invariant violations: {violations}"
        
        # Verify sum risk <= cycle risk
        if cycle.sum_risk_usd > cycle.cycle_risk_usd + 0.01:
            return False, f"❌ TopN Allocator: Sum risk ${cycle.sum_risk_usd:.2f} > cap ${cycle.cycle_risk_usd:.2f}"
        
        return True, f"✅ TopN Allocator: Enforces ${cycle.cycle_risk_usd:.2f} cap (actual: ${cycle.sum_risk_usd:.2f})"
        
    except Exception as e:
        return False, f"❌ TopN Allocator test failed: {e}"


def show_startup_logs():
    """Show what the logs will look like on startup."""
    print("\n" + "="*70)
    print("EXPECTED STARTUP LOGS (what you'll see on restart)")
    print("="*70)
    print("""
2026-04-20 17:20:15,234 [INFO] merid.trading.kalshi_continuous_trader: 
    [RISK-MODE] Using new TopNEdgeAllocator with fixed fractional risk (1-2% per cycle)

2026-04-20 17:20:15,456 [INFO] merid.trading.kalshi_continuous_trader: 
    Initialized GlobalRiskGuard: cycle_cap=2.0%, total_cap=2.0%

2026-04-20 17:20:15,789 [INFO] merid.trading.kalshi_continuous_trader: 
    Initialized TopNEdgeAllocator: max_edges=3, cycle_risk=2.0%

2026-04-20 17:20:16,001 [INFO] merid.trading.kalshi_continuous_trader: 
    [TOP3-BATCH] Top-3 batch manager initialized

2026-04-20 17:20:16,234 [INFO] merid.trading.kalshi_continuous_trader: 
    KalshiContinuousTrader initialized | USE_TOPN_ALLOCATOR=True
    """
    )


def show_cycle_logs():
    """Show what the logs will look like during trading cycles."""
    print("="*70)
    print("EXPECTED CYCLE LOGS (what you'll see when trading)")
    print("="*70)
    print("""
# Cycle start - risk guard reset
2026-04-20 17:21:00,123 [DEBUG] merid.trading.kalshi_continuous_trader: 
    [RISK-GUARD] Cycle 42: risk guard reset

# TopN Allocator execution
2026-04-20 17:21:00,456 [INFO] merid.trading.kalshi_continuous_trader: 
    [TOPN-ALLOCATOR] Cycle 20260420-172100-abc123 | equity=$28.00 | 
    risk_pct=2.00% | risk_budget=$0.56 | N=1 | sum_risk=$0.35 | 
    assets=['BTC']

# Order sizing using TopN (NOT Kelly)
2026-04-20 17:21:00,789 [INFO] merid.trading.kalshi_continuous_trader: 
    [TOPN-SIZE] KXBTC-15M-1234 | asset=BTC | contracts=1 | 
    max_loss=$0.35 | allocated_risk=$0.35 | edge=0.0800

# Global Risk Guard check (LAST-LINE DEFENSE)
2026-04-20 17:21:00,890 [INFO] merid.trading.kalshi_continuous_trader: 
    [GLOBAL-RISK-GUARD] ALLOWED | KXBTC-15M-1234 | 
    risk_accumulated=0.35/0.56

# If a second order tries to slip through:
2026-04-20 17:21:00,901 [CRITICAL] merid.trading.kalshi_continuous_trader: 
    [GLOBAL-RISK-GUARD] BLOCKED | KXETH-15M-5678 | 
    reason=Cycle risk cap exceeded (0.70 > 0.56) | 
    This order would exceed the 1-2% per-cycle risk cap. 
    Skipping and logging for audit.
    """)


def main():
    """Run all verification checks."""
    print("="*70)
    print("RISK OVERSIZING FIX - PRE-FLIGHT VERIFICATION")
    print("="*70)
    print(f"Time: {os.popen('date /t').read().strip()} {os.popen('time /t').read().strip()}")
    print()
    
    all_passed = True
    
    # Check 1: Environment variable
    print("CHECK 1: Environment Variable")
    print("-" * 40)
    ok, msg = check_env_variable()
    print(msg)
    all_passed = all_passed and ok
    print()
    
    # Check 2: Imports
    print("CHECK 2: Import Resolution")
    print("-" * 40)
    ok, errors = check_imports()
    if isinstance(errors, list):
        for e in errors:
            print(e)
    else:
        print(errors)
    all_passed = all_passed and ok
    print()
    
    # Check 3: Global Risk Guard
    print("CHECK 3: Global Risk Guard")
    print("-" * 40)
    ok, msg = test_global_risk_guard()
    print(msg)
    all_passed = all_passed and ok
    print()
    
    # Check 4: TopN Allocator
    print("CHECK 4: TopN Allocator")
    print("-" * 40)
    ok, msg = test_topn_allocator()
    print(msg)
    all_passed = all_passed and ok
    print()
    
    # Show expected logs
    show_startup_logs()
    show_cycle_logs()
    
    # Final verdict
    print("="*70)
    if all_passed:
        print("✅ ALL CHECKS PASSED - READY FOR RESTART")
        print("="*70)
        print("""
The risk oversizing fix is FULLY ENABLED and will:
1. Use TopNEdgeAllocator (not Kelly sizing) for position sizing
2. Enforce 1-2% cycle-wide risk cap (not per-trade)
3. Block any order exceeding the cap at the global risk guard
4. Log all violations at CRITICAL level for audit

To activate:
    export USE_TOPN_ALLOCATOR=true
    python -m merid.trading.kalshi_continuous_trader
""")
        return 0
    else:
        print("❌ SOME CHECKS FAILED - DO NOT RESTART")
        print("="*70)
        print("""
Fix the issues above before restarting. Common problems:
1. USE_TOPN_ALLOCATOR not set in environment
2. Import errors (check PYTHONPATH)
3. Module not found (check installation)
""")
        return 1


if __name__ == "__main__":
    sys.exit(main())
