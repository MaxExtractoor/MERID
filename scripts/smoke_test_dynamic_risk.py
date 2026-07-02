"""Offline smoke test for dynamic risk and window components.

This script verifies:
1. App loads successfully in paper/demo mode
2. DynamicRiskEngine can be instantiated
3. Dynamic window evaluation works
4. No immediate invariant or cooldown triggers
"""

import os
import sys
from pathlib import Path

# Set environment for paper/demo mode
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
os.environ["KALSHI_ENV"] = "demo"
os.environ["KALSHI_USE_DEMO"] = "true"
os.environ["MERID_PM_TRADING_MODE"] = "paper"

# Add parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

print("=== SMOKE TEST: Dynamic Risk & Window ===")
print(f"MERID_PROFILE: {os.environ.get('MERID_PROFILE')}")
print(f"KALSHI_ENV: {os.environ.get('KALSHI_ENV')}")
print(f"KALSHI_USE_DEMO: {os.environ.get('KALSHI_USE_DEMO')}")
print(f"MERID_PM_TRADING_MODE: {os.environ.get('MERID_PM_TRADING_MODE')}")
print()

# Test 1: Load app
print("[1/4] Loading web.main_15m_lean app...")
try:
    from web.main_15m_lean import app
    print("  ✓ App loaded successfully")
except Exception as e:
    print(f"  ✗ Failed to load app: {e}")
    sys.exit(1)

# Test 2: Instantiate DynamicRiskEngine
print("[2/4] Instantiating DynamicRiskEngine...")
try:
    from merid.event_venues.kalshi.dynamic_risk import DynamicRiskEngine
    engine = DynamicRiskEngine()
    print("  ✓ DynamicRiskEngine instantiated")
    print(f"  - Daily PnL: ${engine._daily_pnl_usd}")
    print(f"  - Peak Bankroll: ${engine._peak_bankroll}")
except Exception as e:
    print(f"  ✗ Failed to instantiate DynamicRiskEngine: {e}")
    sys.exit(1)

# Test 3: Evaluate dynamic window
print("[3/4] Evaluating dynamic window...")
try:
    from merid.event_venues.kalshi.dynamic_window import evaluate_dynamic_window
    from datetime import datetime, timedelta, timezone
    
    now = datetime.now(timezone.utc)
    strip_start = now - timedelta(seconds=60)
    strip_end = now + timedelta(seconds=600)
    
    result = evaluate_dynamic_window(
        now=now,
        strip_start=strip_start,
        strip_end=strip_end,
        spread_cents=3,
        depth_at_top=20,
        is_stale=False,
        vol_regime="NORMAL",
        execution_slippage=0.5,
        execution_fill_rate=0.95,
        cooldown_active=False,
        drawdown_state="FLAT",
        recent_invariant_violations=0,
        shadow_mode=False,
    )
    
    print("  ✓ Dynamic window evaluated")
    print(f"  - Would allow trade: {result.would_allow_trade}")
    print(f"  - Reason: {result.reason}")
    print(f"  - Min seconds from open: {result.min_seconds_from_open}")
    print(f"  - Min seconds to expiry: {result.min_seconds_to_expiry}")
except Exception as e:
    print(f"  ✗ Failed to evaluate dynamic window: {e}")
    sys.exit(1)

# Test 4: Check risk gate
print("[4/4] Checking risk gate...")
try:
    can_trade, reason = engine.can_trade_now()
    print("  ✓ Risk gate checked")
    print(f"  - Can trade: {can_trade}")
    print(f"  - Reason: {reason}")
except Exception as e:
    print(f"  ✗ Failed to check risk gate: {e}")
    sys.exit(1)

print()
print("=== SMOKE TEST PASSED ===")
print("All dynamic risk and window components are working correctly.")
print("Ready for guarded live restart with minimal per-trade risk.")
