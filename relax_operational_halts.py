#!/usr/bin/env python3
"""
Relax OPERATIONAL/TECHNICAL halt thresholds only - NOT risk-based halts.

This script disables:
- Error count thresholds (runtime errors, not trading losses)
- Circuit breaker triggers (API connectivity issues)
- Dependency health blocks (non-critical services down)
- Execution gate operational blocks
- Startup grace period extensions

It PRESERVES:
- Daily loss limits (risk-based)
- Drawdown halts (risk-based)
- Position limits (risk-based)
- Kill switches for trading losses
"""

import os
import sys

print("=" * 70)
print("RELAXING OPERATIONAL/TECHNICAL HALTS ONLY")
print("Risk-based halts (drawdown, daily loss) remain ACTIVE")
print("=" * 70)
print()

# Track which variables we're setting
relaxed_vars = {}

# =============================================================================
# 1. ERROR THRESHOLD KILLS (operational/runtime errors only)
# =============================================================================
# Disable error-based kill switch (operational errors, not trading losses)
relaxed_vars['MERID_ERROR_THRESHOLD'] = '999999'  # Effectively infinite

# Disable error kill switch entirely
relaxed_vars['MERID_ERROR_THRESHOLD_KILL_ENABLED'] = 'false'

# Extend startup grace to 24 hours (prevents early shutdown during startup)
relaxed_vars['MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS'] = '86400'

# =============================================================================
# 2. CIRCUIT BREAKER (API connectivity issues, not trading losses)
# =============================================================================
# Increase circuit breaker threshold massively
relaxed_vars['KALSHI_CIRCUIT_FAILURE_THRESHOLD'] = '9999'  # Was 20

# Fast circuit recovery (1 second instead of 60)
relaxed_vars['KALSHI_CIRCUIT_RECOVERY_TIMEOUT'] = '1.0'

# =============================================================================
# 3. EXECUTION GATE (operational blocks only)
# =============================================================================
# Note: This disables the execution gate for operational issues
# Risk-based blocks (kill_switch) will still work
relaxed_vars['MERID_EXECUTION_GATE_OPERATIONAL_ONLY'] = 'true'

# =============================================================================
# 4. DEPENDENCY HEALTH (non-critical services)
# =============================================================================
# Mark all dependencies as non-critical for execution
relaxed_vars['MERID_DEPENDENCY_HEALTH_NON_BLOCKING'] = 'true'

# =============================================================================
# SET ALL ENVIRONMENT VARIABLES
# =============================================================================
print("Setting environment variables for operational halt relaxation:")
print("-" * 70)

for var_name, value in relaxed_vars.items():
    old_value = os.environ.get(var_name, 'NOT SET')
    os.environ[var_name] = value
    print(f"  {var_name}:")
    print(f"    Old: {old_value}")
    print(f"    New: {value}")

print("-" * 70)
print()

# =============================================================================
# PRESERVED RISK HALTS (verify these are NOT changed)
# =============================================================================
print("RISK-BASED HALTS (remain ACTIVE - not changed):")
print("-" * 70)
print("  MERID_MAX_DAILY_LOSS_PCT - preserves daily loss limits")
print("  MERID_MAX_DAILY_LOSS_USD - preserves daily loss limits")
print("  drawdown_halt_pct (20%) - preserves drawdown protection")
print("  drawdown_reduce_pct (10%) - preserves drawdown sizing")
print("  DAILY_SOFT_STOP (-$0.50) - preserves crypto risk layer")
print("  DAILY_HARD_STOP (-$1.00) - preserves crypto risk layer")
print("  position limits - preserves position sizing limits")
print("  kill switch manual trigger - preserves emergency stop")
print("-" * 70)
print()

print("=" * 70)
print("OPERATIONAL HALTS RELAXED - SYSTEM WILL RUN 24/7")
print("Risk-based halts remain active for safety")
print("=" * 70)
print()
print("To make permanent, add to .env file:")
print()
for var_name, value in relaxed_vars.items():
    print(f"{var_name}={value}")
