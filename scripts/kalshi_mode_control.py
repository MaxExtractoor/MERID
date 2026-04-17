"""Kalshi Mode Control - Simple script to flip between paper and live modes.

This demonstrates how to control Kalshi trading modes using environment variables
and settings. The promotion report is now permissive, so only these settings
control whether Kalshi can trade.

Usage:
    python scripts/kalshi_mode_control.py --mode paper
    python scripts/kalshi_mode_control.py --mode live
    python scripts/kalshi_mode_control.py --status
"""

import os
import sys
import argparse
from pathlib import Path

def show_current_settings():
    """Show current Kalshi settings."""
    print("=== Current Kalshi Settings ===")
    
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    try:
        from merid.settings import settings
        
        print(f"KALSHI_ONLY: {settings.KALSHI_ONLY}")
        print(f"MERID_ENABLE_REAL_PREDICTION_MARKETS: {settings.MERID_ENABLE_REAL_PREDICTION_MARKETS}")
        print(f"MERID_PM_TRADING_MODE: {settings.MERID_PM_TRADING_MODE}")
        print(f"MERID_PM_LIVE_ENABLED: {settings.MERID_PM_LIVE_ENABLED}")
        print(f"is_live_trading: {settings.is_live_trading}")
        print()
        print(f"kalshi_pm_paper_enabled: {settings.kalshi_pm_paper_enabled}")
        print(f"kalshi_pm_live_enabled: {settings.kalshi_pm_live_enabled}")
        print()
        
        # Show what this means
        if settings.kalshi_pm_paper_enabled:
            print("✅ Kalshi PAPER trading is ENABLED")
        else:
            print("❌ Kalshi PAPER trading is DISABLED")
            
        if settings.kalshi_pm_live_enabled:
            print("✅ Kalshi LIVE trading is ENABLED")
        else:
            print("❌ Kalshi LIVE trading is DISABLED")
            
    except Exception as e:
        print(f"Error loading settings: {e}")
        print("\nEnvironment variables:")
        for key in ["KALSHI_ONLY", "MERID_ENABLE_REAL_PREDICTION_MARKETS", 
                   "MERID_PM_TRADING_MODE", "MERID_PM_LIVE_ENABLED", "MERID_LIVE_TRADING"]:
            value = os.environ.get(key, "NOT_SET")
            print(f"{key}: {value}")

def set_paper_mode():
    """Set environment for paper trading."""
    print("=== Setting Kalshi PAPER Mode ===")
    
    env_vars = {
        "KALSHI_ONLY": "true",
        "MERID_ENABLE_REAL_PREDICTION_MARKETS": "true", 
        "MERID_PM_TRADING_MODE": "paper",
        "MERID_PM_LIVE_ENABLED": "false",
        "MERID_LIVE_TRADING": "false",
    }
    
    print("Set these environment variables:")
    for key, value in env_vars.items():
        print(f"export {key}={value}")
        os.environ[key] = value
    
    print("\n✅ Kalshi PAPER mode configured")
    print("📝 Restart MERID loop to apply changes")

def set_live_mode():
    """Set environment for live trading."""
    print("=== Setting Kalshi LIVE Mode ===")
    
    env_vars = {
        "KALSHI_ONLY": "true",
        "MERID_ENABLE_REAL_PREDICTION_MARKETS": "true",
        "MERID_PM_TRADING_MODE": "paper",  # Keep paper as base, live controlled by MERID_PM_LIVE_ENABLED
        "MERID_PM_LIVE_ENABLED": "true",
        "MERID_LIVE_TRADING": "true",
        # Risk limits for live
        "MERID_PM_MAX_NOTIONAL_PER_MARKET": "500",
        "MERID_PM_MAX_DAILY_LOSS": "200", 
        "MERID_PM_MAX_TOTAL_NOTIONAL": "2000",
    }
    
    print("Set these environment variables:")
    for key, value in env_vars.items():
        print(f"export {key}={value}")
        os.environ[key] = value
    
    print("\n✅ Kalshi LIVE mode configured")
    print("⚠️  WARNING: This enables REAL trading with real money!")
    print("📝 Restart MERID loop to apply changes")

def main():
    parser = argparse.ArgumentParser(description="Kalshi Mode Control")
    parser.add_argument("--mode", choices=["paper", "live", "status"], 
                       default="status", help="Mode to set or check")
    
    args = parser.parse_args()
    
    if args.mode == "status":
        show_current_settings()
    elif args.mode == "paper":
        set_paper_mode()
    elif args.mode == "live":
        set_live_mode()

if __name__ == "__main__":
    main()
