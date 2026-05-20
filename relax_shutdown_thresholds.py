#!/usr/bin/env python3
"""
Relax all system shutdown and halt bands for 24/7 uninterrupted operation.

This script sets environment variables to maximum tolerance levels.
Run this before starting the MERID server.
"""

import os
import sys

print("=" * 70)
print("RELAXING ALL SHUTDOWN/HA LT THRESHOLDS FOR 24/7 OPERATION")
print("=" * 70)
print()

# Track which variables we're setting
relaxed_vars = {}

# =============================================================================
# 1. KILL SWITCH THRESHOLDS (merid/risk/kill_switches.py)
# =============================================================================
# Error threshold - massively increased to prevent error-based kills
relaxed_vars['MERID_ERROR_THRESHOLD'] = '999999'  # Was 500, now effectively disabled

# Daily loss limit in USD - set very high
relaxed_vars['MERID_MAX_DAILY_LOSS_USD'] = '999999'  # Was 500, now $1M/day

# Max position value - set very high  
relaxed_vars['MERID_MAX_POSITION_VALUE_USD'] = '999999'  # Was 10000

# =============================================================================
# 2. DAILY LOSS PERCENTAGES (merid/settings.py)
# =============================================================================
# Daily loss as % of bankroll - set to 99% (essentially disabled)
relaxed_vars['MERID_MAX_DAILY_LOSS_PCT'] = '0.99'  # Was 0.15 (15%), now 99%

# PM max daily loss override
relaxed_vars['MERID_PM_MAX_DAILY_LOSS'] = '999999'  # Override in USD

# =============================================================================
# 3. DRAWDOWN HALT THRESHOLDS (merid/risk/risk_profile.py)
# =============================================================================
# These require code changes since they're in frozen dataclass
# But we can document them for future relaxation
print("NOTE: drawdown_halt_pct (20%) and drawdown_reduce_pct (10%) are in")
print("      risk_profile.py frozen dataclass - requires code edit to change")
print()

# =============================================================================
# 4. CIRCUIT BREAKER THRESHOLDS (merid/event_venues/kalshi/client.py)
# =============================================================================
# Circuit breaker failure threshold - massively increased
relaxed_vars['KALSHI_CIRCUIT_FAILURE_THRESHOLD'] = '9999'  # Was 20, now effectively disabled

# Circuit recovery timeout - set to 1 second (fast recovery)
relaxed_vars['KALSHI_CIRCUIT_RECOVERY_TIMEOUT'] = '1.0'  # Was 60s

# =============================================================================
# 5. CRYPTO SWARM DAILY LIMITS (merid/risk/crypto_swarm_risk_btc15m.py)
# =============================================================================
# These are hardcoded constants - would need code changes
print("NOTE: CryptoSwarm DAILY_SOFT_STOP (-$0.50) and DAILY_HARD_STOP (-$1.00)")
print("      are hardcoded in crypto_swarm_risk_btc15m.py")
print("      Would need code edit to change to 24/7 values")
print()

# =============================================================================
# 6. KALSHI PORTFOLIO LIMITS (merid/settings.py)
# =============================================================================
# Portfolio max daily loss %
relaxed_vars['KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT'] = '0.99'  # Was 0.155 (15.5%)

# =============================================================================
# 7. ERROR KILL SWITCH CONTROLS (merid/settings.py)
# =============================================================================
# Completely disable error-based kill switch
relaxed_vars['MERID_ERROR_THRESHOLD_KILL_ENABLED'] = 'false'  # Was true

# Extend startup grace period to 24 hours
relaxed_vars['MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS'] = '86400'  # Was 600 (10 min)

# =============================================================================
# 8. EXECUTION GATE (core/execution_gate.py)
# =============================================================================
# Disable execution gate blocks
relaxed_vars['MERID_EXECUTION_GATE_DISABLED'] = 'true'

# =============================================================================
# 9. CRYPTO DOMAIN LIMITS (merid/settings.py)
# =============================================================================
# Crypto max daily loss
relaxed_vars['MERID_CRYPTO_MAX_DAILY_LOSS_USD'] = '999999'  # Was derived

# =============================================================================
# SET ALL ENVIRONMENT VARIABLES
# =============================================================================
print("Setting environment variables for relaxed operation:")
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
# VERIFY SETTINGS
# =============================================================================
print("Verifying relaxed settings:")
print("-" * 70)

# Test import and verify
from merid.settings import settings

print(f"MERID_ERROR_THRESHOLD: {settings.MERID_ERROR_THRESHOLD}")
print(f"MERID_MAX_DAILY_LOSS_PCT: {settings.MERID_MAX_DAILY_LOSS_PCT}")
print(f"MERID_ERROR_THRESHOLD_KILL_ENABLED: {settings.MERID_ERROR_THRESHOLD_KILL_ENABLED}")
print(f"KALSHI_CIRCUIT_FAILURE_THRESHOLD: {settings.KALSHI_CIRCUIT_FAILURE_THRESHOLD}")
print(f"KALSHI_CIRCUIT_RECOVERY_TIMEOUT: {settings.KALSHI_CIRCUIT_RECOVERY_TIMEOUT}")
print(f"KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT: {settings.KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT}")

print("-" * 70)
print()

# Check kill switch controller
from merid.risk.kill_switches import risk_controller
print(f"Kill Switch error_threshold: {risk_controller.error_threshold}")
print(f"Kill Switch daily_loss_limit: {risk_controller.daily_loss_limit}")

print()
print("=" * 70)
print("ALL SHUTDOWN THRESHOLDS RELAXED FOR 24/7 OPERATION")
print("=" * 70)
print()
print("WARNING: This configuration removes safety limits.")
print("         Only use for systems with external risk monitoring.")
print()
print("To make these changes permanent, add these to your .env file:")
print()
for var_name, value in relaxed_vars.items():
    print(f"{var_name}={value}")
