#!/usr/bin/env python3
"""
Manual Trade Execution Script for Kalshi 15m Crypto Trading

This script allows manual execution of trades using the production infrastructure.
It uses the same risk envelope, order routing, and validation as the live system.

SAFETY FEATURES:
- Dry-run mode by default (no real orders placed)
- Explicit confirmation required for live trading
- Full risk envelope validation
- Position size calculation from risk envelope
- Support for all 5 crypto assets (BTC/ETH/SOL/XRP/DOGE)

Usage:
    # Dry-run (default)
    python scripts/execute_manual_trade.py --asset BTC --side yes --count 10
    
    # Live trading (requires confirmation)
    python scripts/execute_manual_trade.py --asset BTC --side yes --count 10 --live
    
    # Specify price and ticker
    python scripts/execute_manual_trade.py --asset BTC --ticker KXBTCD-26JUN111330-30 --side yes --count 10 --price-cents 50 --live
"""

import asyncio
import argparse
import sys
import os
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def execute_manual_trade(
    asset: str,
    side: str,
    count: int,
    ticker: Optional[str] = None,
    price_cents: Optional[int] = None,
    live: bool = False,
    profile: str = "kalshi_crypto_15m_v2"
):
    """
    Execute a manual trade using production infrastructure.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        side: Order side (yes/no)
        count: Number of contracts
        ticker: Optional specific ticker (auto-detected if not provided)
        price_cents: Optional price in cents (auto-detected from market state if not provided)
        live: If True, submit real order. If False, dry-run only.
        profile: Risk profile to use
    """
    print(f"\n{'='*60}")
    print(f"MANUAL TRADE EXECUTION - {'LIVE' if live else 'DRY-RUN'} MODE")
    print(f"{'='*60}")
    print(f"Asset: {asset}")
    print(f"Side: {side}")
    print(f"Count: {count}")
    print(f"Ticker: {ticker or 'AUTO-DETECT'}")
    print(f"Price: {price_cents or 'AUTO-DETECT'} cents")
    print(f"Profile: {profile}")
    print(f"{'='*60}\n")
    
    # Validate asset
    valid_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    if asset not in valid_assets:
        print(f"ERROR: Invalid asset '{asset}'. Must be one of: {valid_assets}")
        return False
    
    # Validate side
    if side not in ["yes", "no"]:
        print(f"ERROR: Invalid side '{side}'. Must be 'yes' or 'no'")
        return False
    
    # Validate count
    if count <= 0:
        print(f"ERROR: Count must be positive, got {count}")
        return False
    
    # Live trading confirmation
    if live:
        print("\n⚠️  WARNING: LIVE TRADING MODE ⚠️")
        print("This will submit a REAL order to Kalshi.")
        print(f"Asset: {asset}, Side: {side}, Count: {count}")
        print("\nType 'CONFIRM' to proceed: ", end="", flush=True)
        confirmation = input()
        if confirmation != "CONFIRM":
            print("Trade cancelled.")
            return False
    
    try:
        # Import production components
        from merid.event_venues.kalshi.order_router import (
            resolve_window_policy,
            resolve_exit_policy,
            route_order_async
        )
        from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from data.unified_spot_service import get_unified_spot_service
        from merid.schemas.arbitrage import OrderIntent
        
        # Get risk envelope
        print("Loading risk envelope...")
        risk_service = get_risk_envelope_service()
        risk_service.refresh_if_stale(max_age_seconds=30.0)
        risk_envelope = risk_service.get_config()
        
        print(f"Risk envelope loaded:")
        print(f"  - Bankroll: ${risk_envelope.live_bankroll_usd:.2f}")
        print(f"  - Max single order: ${risk_envelope.max_single_order_notional_usd:.2f}")
        print(f"  - Per-trade risk: {risk_envelope.per_trade_risk_multiplier:.2f}x")
        
        # Get base position size
        base_size = risk_envelope.get_base_position_size()
        print(f"  - Base position size: {base_size} contracts")
        
        # Validate position size against risk envelope
        if price_cents:
            position_notional = (count * price_cents) / 100.0
            max_notional = risk_envelope.max_single_order_notional_usd
            
            if position_notional > max_notional:
                print(f"\n⚠️  WARNING: Position notional ${position_notional:.2f} exceeds max ${max_notional:.2f}")
                if live:
                    print("Trade cancelled due to risk limit.")
                    return False
                else:
                    print("Proceeding with dry-run...")
            
            # Check per-asset cap
            asset_max = risk_envelope.asset_max_notional_usd.get(asset, float('inf'))
            if position_notional > asset_max:
                print(f"\n⚠️  WARNING: Position notional ${position_notional:.2f} exceeds asset max ${asset_max:.2f}")
                if live:
                    print("Trade cancelled due to asset risk limit.")
                    return False
        
        # Auto-detect ticker if not provided
        if not ticker:
            # Use series ticker for the asset
            ticker_map = {
                "BTC": "KXBTC15M",
                "ETH": "KXETH15M",
                "SOL": "KXSOL15M",
                "XRP": "KXXRP15M",
                "DOGE": "KXDOGE15M"
            }
            ticker = ticker_map.get(asset)
            print(f"Auto-detected ticker: {ticker}")
        
        # Auto-detect price if not provided
        if not price_cents:
            print("Fetching market state for price...")
            market_state_store = get_kalshi_market_state_store()
            market_state = market_state_store.get(ticker) if market_state_store else None
            
            if market_state and market_state.mid_cents:
                price_cents = market_state.mid_cents
                print(f"Auto-detected price: {price_cents} cents")
            elif market_state and market_state.best_bid_cents and market_state.best_ask_cents:
                price_cents = (market_state.best_bid_cents + market_state.best_ask_cents) // 2
                print(f"Auto-detected price (mid of bid/ask): {price_cents} cents")
            else:
                print("WARNING: Could not auto-detect price, using default 50 cents")
                price_cents = 50
        
        # Resolve policies
        print("Resolving trading policies...")
        window_policy = resolve_window_policy(asset=asset, regime="normal")
        exit_policy = resolve_exit_policy(edge_result=None, asset=asset, regime="normal")
        
        # Construct OrderIntent
        intent = OrderIntent(
            ticker=ticker,
            side=side,
            action="buy",
            price_cents=price_cents,
            count=count,
            window_resolution_id=window_policy.resolution_id if hasattr(window_policy, 'resolution_id') else "15m",
            exit_policy_id=exit_policy.policy_id if hasattr(exit_policy, 'policy_id') else "standard",
            caller_module="manual_trade_script",
            edge_metadata={
                "manual_trade": True,
                "asset": asset,
                "side": side,
            },
        )
        
        print(f"\nOrder Intent constructed:")
        print(f"  - Ticker: {intent.ticker}")
        print(f"  - Side: {intent.side}")
        print(f"  - Action: {intent.action}")
        print(f"  - Price: {intent.price_cents} cents")
        print(f"  - Count: {intent.count}")
        print(f"  - Notional: ${(intent.count * intent.price_cents) / 100:.2f}")
        
        if not live:
            print("\n✓ DRY-RUN COMPLETE - No order submitted")
            print("To execute for real, add --live flag")
            return True
        
        # Submit order
        print("\nSubmitting order to Kalshi...")
        result = await route_order_async(intent)
        
        print(f"\nOrder result: {result}")
        print("✓ Trade executed successfully")
        return True
        
    except Exception as e:
        print(f"\nERROR: Failed to execute trade: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Execute manual trade using production infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run (default)
  python scripts/execute_manual_trade.py --asset BTC --side yes --count 10
  
  # Live trading
  python scripts/execute_manual_trade.py --asset BTC --side yes --count 10 --live
  
  # With specific ticker and price
  python scripts/execute_manual_trade.py --asset BTC --ticker KXBTCD-26JUN111330-30 --side yes --count 10 --price-cents 50 --live
        """
    )
    
    parser.add_argument(
        "--asset",
        required=True,
        choices=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        help="Asset to trade"
    )
    
    parser.add_argument(
        "--side",
        required=True,
        choices=["yes", "no"],
        help="Order side (yes = buy YES contracts, no = buy NO contracts)"
    )
    
    parser.add_argument(
        "--count",
        required=True,
        type=int,
        help="Number of contracts to trade"
    )
    
    parser.add_argument(
        "--ticker",
        help="Specific ticker (auto-detected from asset if not provided)"
    )
    
    parser.add_argument(
        "--price-cents",
        type=int,
        help="Price in cents (auto-detected from market state if not provided)"
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Submit real order (default is dry-run)"
    )
    
    parser.add_argument(
        "--profile",
        default="kalshi_crypto_15m_v2",
        help="Risk profile to use (default: kalshi_crypto_15m_v2)"
    )
    
    args = parser.parse_args()
    
    # Run async execution
    success = asyncio.run(execute_manual_trade(
        asset=args.asset,
        side=args.side,
        count=args.count,
        ticker=args.ticker,
        price_cents=args.price_cents,
        live=args.live,
        profile=args.profile
    ))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
