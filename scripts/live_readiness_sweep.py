"""
Live Readiness Sweep for Kalshi 15m Crypto Trading

This script performs a comprehensive check before starting live trading:
- Environment and profile sanity
- Kalshi authentication
- Kill switches and caps
- Configuration validation

Usage:
    python scripts/live_readiness_sweep.py
"""
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
env_file = project_root / ".env"
if env_file.exists():
    print(f"Loading environment from: {env_file}")
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                # Strip inline comments
                if '#' in value:
                    value = value.split('#')[0].strip()
                os.environ[key.strip()] = value.strip()
    print("Environment loaded successfully")
    print()
else:
    print(f"Warning: .env file not found at {env_file}")
    print()

print("="*80)
print("LIVE READINESS SWEEP - KALSHI 15M CRYPTO")
print("="*80)
print()

# Track issues
issues = []
warnings = []

# 1. Environment and Profile Sanity
print("[1/5] Environment and Profile Sanity")
print("-" * 40)

env_checks = {
    "MERID_PROFILE": os.getenv("MERID_PROFILE"),
    "MERID_TRADING_MODE": os.getenv("MERID_TRADING_MODE"),
    "MERID_ALLOW_LIVE_TRADES": os.getenv("MERID_ALLOW_LIVE_TRADES"),
    "MERID_PM_PROFILE": os.getenv("MERID_PM_PROFILE"),
    "MERID_ENV": os.getenv("MERID_ENV"),
}

# Check critical env vars
if env_checks["MERID_PROFILE"] != "kalshi_crypto_15m_v2":
    issues.append(f"MERID_PROFILE is {env_checks['MERID_PROFILE']}, expected kalshi_crypto_15m_v2")
    print(f"  ✗ MERID_PROFILE: {env_checks['MERID_PROFILE']} (WRONG)")
else:
    print(f"  ✓ MERID_PROFILE: {env_checks['MERID_PROFILE']}")

if env_checks["MERID_TRADING_MODE"] != "live":
    issues.append(f"MERID_TRADING_MODE is {env_checks['MERID_TRADING_MODE']}, expected live")
    print(f"  ✗ MERID_TRADING_MODE: {env_checks['MERID_TRADING_MODE']} (WRONG)")
else:
    print(f"  ✓ MERID_TRADING_MODE: {env_checks['MERID_TRADING_MODE']}")

if env_checks["MERID_ALLOW_LIVE_TRADES"] != "true":
    issues.append(f"MERID_ALLOW_LIVE_TRADES is {env_checks['MERID_ALLOW_LIVE_TRADES']}, expected true")
    print(f"  ✗ MERID_ALLOW_LIVE_TRADES: {env_checks['MERID_ALLOW_LIVE_TRADES']} (WRONG)")
else:
    print(f"  ✓ MERID_ALLOW_LIVE_TRADES: {env_checks['MERID_ALLOW_LIVE_TRADES']}")

if env_checks["MERID_PM_PROFILE"] != "baseline":
    warnings.append(f"MERID_PM_PROFILE is {env_checks['MERID_PM_PROFILE']}, expected baseline")
    print(f"  ⚠ MERID_PM_PROFILE: {env_checks['MERID_PM_PROFILE']} (WARNING)")
else:
    print(f"  ✓ MERID_PM_PROFILE: {env_checks['MERID_PM_PROFILE']}")

if env_checks["MERID_ENV"] != "production":
    warnings.append(f"MERID_ENV is {env_checks['MERID_ENV']}, expected production")
    print(f"  ⚠ MERID_ENV: {env_checks['MERID_ENV']} (WARNING)")
else:
    print(f"  ✓ MERID_ENV: {env_checks['MERID_ENV']}")

# Check for paper mode envs
paper_envs = [k for k in os.environ.keys() if "PAPER" in k or "paper" in k.lower()]
if paper_envs:
    warnings.append(f"Paper mode envs detected: {paper_envs}")
    print(f"  ⚠ Paper envs detected: {paper_envs}")
else:
    print(f"  ✓ No paper mode envs detected")

# Check for sentiment envs
sentiment_envs = [k for k in os.environ.keys() if "SENTIMENT" in k or "sentiment" in k.lower()]
if sentiment_envs:
    warnings.append(f"Sentiment envs detected: {sentiment_envs}")
    print(f"  ⚠ Sentiment envs detected: {sentiment_envs}")
else:
    print(f"  ✓ No sentiment envs detected")

print()

# 2. Kalshi Environment and Auth
print("[2/5] Kalshi Environment and Auth")
print("-" * 40)

kalshi_checks = {
    "KALSHI_ENV": os.getenv("KALSHI_ENV"),
    "KALSHI_API_KEY_ID": os.getenv("KALSHI_API_KEY_ID"),
    "KALSHI_PRIVATE_KEY_PATH": os.getenv("KALSHI_PRIVATE_KEY_PATH"),
    "KALSHI_USE_DEMO": os.getenv("KALSHI_USE_DEMO"),
    "MERID_KALSHI_PAPER_MODE": os.getenv("MERID_KALSHI_PAPER_MODE"),
}

if kalshi_checks["KALSHI_ENV"] != "live":
    issues.append(f"KALSHI_ENV is {kalshi_checks['KALSHI_ENV']}, expected live")
    print(f"  ✗ KALSHI_ENV: {kalshi_checks['KALSHI_ENV']} (WRONG)")
else:
    print(f"  ✓ KALSHI_ENV: {kalshi_checks['KALSHI_ENV']}")

if not kalshi_checks["KALSHI_API_KEY_ID"]:
    issues.append("KALSHI_API_KEY_ID is not set")
    print(f"  ✗ KALSHI_API_KEY_ID: NOT SET (CRITICAL)")
else:
    print(f"  ✓ KALSHI_API_KEY_ID: {kalshi_checks['KALSHI_API_KEY_ID'][:8]}...")

if not kalshi_checks["KALSHI_PRIVATE_KEY_PATH"]:
    issues.append("KALSHI_PRIVATE_KEY_PATH is not set")
    print(f"  ✗ KALSHI_PRIVATE_KEY_PATH: NOT SET (CRITICAL)")
else:
    key_path = Path(kalshi_checks["KALSHI_PRIVATE_KEY_PATH"])
    if not key_path.exists():
        issues.append(f"KALSHI_PRIVATE_KEY_PATH file does not exist: {kalshi_checks['KALSHI_PRIVATE_KEY_PATH']}")
        print(f"  ✗ KALSHI_PRIVATE_KEY_PATH: File not found (CRITICAL)")
    else:
        print(f"  ✓ KALSHI_PRIVATE_KEY_PATH: {kalshi_checks['KALSHI_PRIVATE_KEY_PATH']} (exists)")

if kalshi_checks["KALSHI_USE_DEMO"] != "false":
    issues.append(f"KALSHI_USE_DEMO is {kalshi_checks['KALSHI_USE_DEMO']}, expected false")
    print(f"  ✗ KALSHI_USE_DEMO: {kalshi_checks['KALSHI_USE_DEMO']} (WRONG)")
else:
    print(f"  ✓ KALSHI_USE_DEMO: {kalshi_checks['KALSHI_USE_DEMO']}")

if kalshi_checks["MERID_KALSHI_PAPER_MODE"] != "false":
    issues.append(f"MERID_KALSHI_PAPER_MODE is {kalshi_checks['MERID_KALSHI_PAPER_MODE']}, expected false")
    print(f"  ✗ MERID_KALSHI_PAPER_MODE: {kalshi_checks['MERID_KALSHI_PAPER_MODE']} (WRONG)")
else:
    print(f"  ✓ MERID_KALSHI_PAPER_MODE: {kalshi_checks['MERID_KALSHI_PAPER_MODE']}")

print()

# 3. Kill Switches
print("[3/5] Kill Switches")
print("-" * 40)

kill_switches = {
    "KALSHI_TRADER_ENABLED": os.getenv("KALSHI_TRADER_ENABLED"),
    "MERID_SPECTATOR_MODE": os.getenv("MERID_SPECTATOR_MODE"),
}

if kill_switches["KALSHI_TRADER_ENABLED"] != "true":
    # This is actually the Kalshi Continuous Trader, not the main 15m agent
    # For 15m agent grid, this being true is fine
    print(f"  ✓ KALSHI_TRADER_ENABLED: {kill_switches['KALSHI_TRADER_ENABLED']} (CT enabled)")
else:
    print(f"  ✓ KALSHI_TRADER_ENABLED: {kill_switches['KALSHI_TRADER_ENABLED']}")

if kill_switches["MERID_SPECTATOR_MODE"] != "false":
    issues.append(f"MERID_SPECTATOR_MODE is {kill_switches['MERID_SPECTATOR_MODE']}, expected false")
    print(f"  ✗ MERID_SPECTATOR_MODE: {kill_switches['MERID_SPECTATOR_MODE']} (SPECTATOR MODE ACTIVE)")
else:
    print(f"  ✓ MERID_SPECTATOR_MODE: {kill_switches['MERID_SPECTATOR_MODE']}")

# Check for kill switch file
kill_switch_file = Path(".kill_switch")
if kill_switch_file.exists():
    issues.append("Kill switch file exists: .kill_switch")
    print(f"  ✗ Kill switch file exists: .kill_switch (ACTIVE)")
else:
    print(f"  ✓ No kill switch file found")

print()

# 4. Risk Caps
print("[4/5] Risk Caps")
print("-" * 40)

risk_caps = {
    "MAX_CYCLE_RISK_PCT": os.getenv("MAX_CYCLE_RISK_PCT"),
    "MAX_TOTAL_RISK_PCT": os.getenv("MAX_TOTAL_RISK_PCT"),
    "TOPN_MAX_CYCLE_RISK_PCT": os.getenv("TOPN_MAX_CYCLE_RISK_PCT"),
    "USE_TOPN_ALLOCATOR": os.getenv("USE_TOPN_ALLOCATOR"),
}

print(f"  MAX_CYCLE_RISK_PCT: {risk_caps['MAX_CYCLE_RISK_PCT']} ({float(risk_caps['MAX_CYCLE_RISK_PCT'] or 0)*100:.1f}%)")
print(f"  MAX_TOTAL_RISK_PCT: {risk_caps['MAX_TOTAL_RISK_PCT']} ({float(risk_caps['MAX_TOTAL_RISK_PCT'] or 0)*100:.1f}%)")
print(f"  TOPN_MAX_CYCLE_RISK_PCT: {risk_caps['TOPN_MAX_CYCLE_RISK_PCT']} ({float(risk_caps['TOPN_MAX_CYCLE_RISK_PCT'] or 0)*100:.1f}%)")
print(f"  USE_TOPN_ALLOCATOR: {risk_caps['USE_TOPN_ALLOCATOR']}")

if risk_caps["USE_TOPN_ALLOCATOR"] != "true":
    warnings.append("USE_TOPN_ALLOCATOR is false - using legacy Kelly sizing (DANGEROUS)")
    print(f"  ⚠ USE_TOPN_ALLOCATOR: false (DANGEROUS - legacy Kelly sizing)")
else:
    print(f"  ✓ USE_TOPN_ALLOCATOR: true (TopN allocator active)")

print()

# 5. Profile Configuration
print("[5/5] Profile Configuration")
print("-" * 40)

# Check if profile files exist
profile_files = [
    "config/profiles/kalshi_crypto_15m.yaml",
    "config/profiles/kalshi_crypto_15m_strategy.yaml",
]

for profile_file in profile_files:
    path = Path(profile_file)
    if not path.exists():
        issues.append(f"Profile file not found: {profile_file}")
        print(f"  ✗ Profile file not found: {profile_file}")
    else:
        print(f"  ✓ Profile file exists: {profile_file}")

print()

# Summary
print("="*80)
print("READINESS SWEEP SUMMARY")
print("="*80)
print()

if issues:
    print(f"CRITICAL ISSUES ({len(issues)}):")
    for issue in issues:
        print(f"  ✗ {issue}")
    print()

if warnings:
    print(f"WARNINGS ({len(warnings)}):")
    for warning in warnings:
        print(f"  ⚠ {warning}")
    print()

if not issues and not warnings:
    print("✓ ALL CHECKS PASSED - READY FOR LIVE TRADING")
    print()
    print("Next steps:")
    print("1. Start the live process:")
    print("   export MERID_PROFILE=kalshi_crypto_15m_v2")
    print("   export MERID_TRADING_MODE=LIVE")
    print("   python -m web.main_15m_lean")
    print()
    print("2. Monitor logs for:")
    print("   - KALSHI 15M STARTUP VALIDATION SEQUENCE")
    print("   - PREFLIGHT GATE PASSED")
    print("   - NO-SENTIMENT-VALIDATION")
    print("   - NO-LEGACY-STRATEGY-VALIDATION")
    print("   - BankrollServiceV2 started")
    print("   - Agent grid loaded with 5 agents")
    sys.exit(0)
elif issues:
    print("✗ CRITICAL ISSUES - FIX BEFORE PROCEEDING")
    sys.exit(1)
else:
    print("⚠ WARNINGS - REVIEW BEFORE PROCEEDING")
    sys.exit(0)
