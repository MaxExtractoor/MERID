"""
Diagnostic script to identify why agents are not trading.

This script checks:
1. Server logs for trade attempts and rejections
2. Market state for all 5 assets
3. Price band configuration and rejections
4. Signal generation status
5. Risk envelope limits
6. Position limits
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def print_section(title):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def check_price_band_config():
    """Check price band configuration across the stack."""
    print_section("PRICE BAND CONFIGURATION")
    
    # Check profile config
    try:
        import yaml
        profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        price_range = profile.get("price_range", {})
        print(f"Profile price_range:")
        print(f"  min_price_cents: {price_range.get('min_price_cents', 'NOT SET')}")
        print(f"  max_price_cents: {price_range.get('max_price_cents', 'NOT SET')}")
        print(f"  description: {price_range.get('description', 'NOT SET')}")
    except Exception as e:
        print(f"ERROR reading profile: {e}")
    
    # Check agent_grid fallback
    try:
        with open(project_root / "merid" / "prediction" / "agent_grid_15m.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        # Find fallback values
        import re
        min_match = re.search(r"ENTRY_MIN_PRICE_CENTS\s*=\s*(\d+)", code)
        max_match = re.search(r"ENTRY_MAX_PRICE_CENTS\s*=\s*(\d+)", code)
        
        print(f"\nAgent grid fallback:")
        print(f"  ENTRY_MIN_PRICE_CENTS: {min_match.group(1) if min_match else 'NOT FOUND'}")
        print(f"  ENTRY_MAX_PRICE_CENTS: {max_match.group(1) if max_match else 'NOT FOUND'}")
    except Exception as e:
        print(f"ERROR reading agent_grid: {e}")
    
    # Check order router min price
    try:
        with open(project_root / "merid" / "event_venues" / "kalshi" / "order_router.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        # Find min price check
        import re
        min_price_match = re.search(r"if intent\.price_cents < (\d+)", code)
        
        print(f"\nOrder router min price check:")
        print(f"  Minimum price_cents: {min_price_match.group(1) if min_price_match else 'NOT FOUND'}")
    except Exception as e:
        print(f"ERROR reading order_router: {e}")

def check_market_state():
    """Check market state for all 5 assets."""
    print_section("MARKET STATE")
    
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from merid.event_venues.kalshi.market_state_store import get_market_state_store
        
        catalog = get_market_catalog()
        state_store = get_market_state_store()
        
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            print(f"\n{asset}:")
            try:
                # Get active 15m market
                market = catalog.get_current_15m_market(asset)
                if market:
                    ticker = market.market.market_id
                    print(f"  Active ticker: {ticker}")
                    
                    # Get market state
                    state = state_store.get(ticker)
                    if state:
                        print(f"  Best bid: {state.best_bid}c")
                        print(f"  Best ask: {state.best_ask}c")
                        print(f"  Mid price: {state.mid_price}c")
                        print(f"  Depth YES: {state.depth_yes}")
                        print(f"  Depth NO: {state.depth_no}")
                        print(f"  Book initialized: {state.book_initialized}")
                        print(f"  Staleness: {state.staleness_ms}ms")
                    else:
                        print(f"  ERROR: No market state found")
                else:
                    print(f"  ERROR: No active 15m market found")
            except Exception as e:
                print(f"  ERROR: {e}")
    except Exception as e:
        print(f"ERROR checking market state: {e}")

def check_risk_envelope():
    """Check risk envelope configuration."""
    print_section("RISK ENVELOPE")
    
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        profile_adapter = get_active_profile()
        if profile_adapter:
            profile = profile_adapter.profile
            print(f"Profile: {profile_adapter.profile_name}")
            print(f"Operation mode: {profile.operation_mode}")
            print(f"Daily loss limit: {profile.daily_loss_limit_pct}%")
            print(f"Per trade risk: {profile.per_trade_risk_pct}%")
            print(f"Kelly fraction: {profile.kelly_fraction}")
            
            print(f"\nPer-asset caps:")
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                cap = profile.get_asset_cap(asset)
                if cap:
                    print(f"  {asset}: {cap.max_notional_usd:.2f} USD ({cap.target_pct}%)")
        else:
            print("ERROR: No active profile found")
    except Exception as e:
        print(f"ERROR checking risk envelope: {e}")

def check_entry_window():
    """Check entry window configuration."""
    print_section("ENTRY WINDOW CONFIGURATION")
    
    try:
        with open(project_root / "merid" / "prediction" / "agent_grid_15m.py", "r", encoding="utf-8") as f:
            code = f.read()
        
        # Find entry window check
        import re
        window_match = re.search(r"if (\d+) <= time_to_expiry <= (\d+):", code)
        
        if window_match:
            print(f"Entry window: {window_match.group(1)}s - {window_match.group(2)}s")
            print(f"  ({int(window_match.group(1))/60:.1f}min - {int(window_match.group(2))/60:.1f}min)")
        else:
            print("ERROR: Entry window not found in code")
    except Exception as e:
        print(f"ERROR checking entry window: {e}")

def check_recent_logs():
    """Check recent logs for trade attempts and rejections."""
    print_section("RECENT LOG ANALYSIS")
    
    log_files = [
        project_root / "logs" / "merid.log",
        project_root / "logs" / "kalshi.log",
    ]
    
    for log_file in log_files:
        if log_file.exists():
            print(f"\nChecking {log_file.name}:")
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    # Get last 100 lines
                    recent_lines = lines[-100:]
                    
                    # Count key events
                    signal_count = sum(1 for line in recent_lines if "SIGNAL-GENERATED" in line)
                    candidate_count = sum(1 for line in recent_lines if "CANDIDATE-GENERATED" in line)
                    reject_count = sum(1 for line in recent_lines if "REJECTED" in line)
                    price_violation_count = sum(1 for line in recent_lines if "MIN-PRICE-VIOLATION" in line)
                    edge_skip_count = sum(1 for line in recent_lines if "EDGE-SKIP" in line)
                    
                    print(f"  SIGNAL-GENERATED: {signal_count}")
                    print(f"  CANDIDATE-GENERATED: {candidate_count}")
                    print(f"  REJECTED: {reject_count}")
                    print(f"  MIN-PRICE-VIOLATION: {price_violation_count}")
                    print(f"  EDGE-SKIP: {edge_skip_count}")
                    
                    # Show last few rejection reasons
                    if reject_count > 0:
                        print(f"\n  Last 5 rejections:")
                        rejections = [line for line in recent_lines if "REJECTED" in line][-5:]
                        for line in rejections:
                            print(f"    {line.strip()}")
            except Exception as e:
                print(f"  ERROR reading log: {e}")
        else:
            print(f"\n{log_file.name}: Not found")

def main():
    """Run all diagnostic checks."""
    print("\n" + "=" * 80)
    print("  NO TRADE DIAGNOSTIC SCRIPT")
    print(f"  Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    check_price_band_config()
    check_entry_window()
    check_market_state()
    check_risk_envelope()
    check_recent_logs()
    
    print("\n" + "=" * 80)
    print("  DIAGNOSTIC COMPLETE")
    print("=" * 80)
    print("\nReview the output above to identify the root cause of no trades.")

if __name__ == "__main__":
    main()
