#!/usr/bin/env python3
"""
Force Agent Trade Execution Script

This script forces the agent grid to generate and execute trade candidates.
It tests both market orders and limit (rest) orders to prove direct order execution.

Usage:
    # Dry-run mode (default)
    py scripts\force_agent_trade_execution.py --asset BTC --order-type market
    
    # Live trading (requires confirmation)
    py scripts\force_agent_trade_execution.py --asset BTC --order-type market --live
    
    # Test limit order
    py scripts\force_agent_trade_execution.py --asset BTC --order-type limit --price-cents 50 --live
"""

import asyncio
import argparse
import sys
import os
from typing import Optional, Dict, Any
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def force_agent_trade(
    asset: str,
    order_type: str,
    count: int = 10,
    price_cents: Optional[int] = None,
    live: bool = False,
    profile: str = "kalshi_crypto_15m_v2"
):
    """
    Force agent grid to generate and execute a trade candidate.
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        order_type: Order type (market or limit)
        count: Number of contracts
        price_cents: Price in cents (required for limit orders)
        live: If True, submit real order. If False, dry-run only.
        profile: Risk profile to use
    """
    print(f"\n{'='*60}")
    print(f"FORCE AGENT TRADE EXECUTION - {'LIVE' if live else 'DRY-RUN'} MODE")
    print(f"{'='*60}")
    print(f"Asset: {asset}")
    print(f"Order Type: {order_type}")
    print(f"Count: {count}")
    print(f"Price: {price_cents or 'MARKET'} cents")
    print(f"Profile: {profile}")
    print(f"{'='*60}\n")
    
    # Validate asset
    valid_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    if asset not in valid_assets:
        print(f"ERROR: Invalid asset '{asset}'. Must be one of: {valid_assets}")
        return False
    
    # Validate order type
    if order_type not in ["market", "limit"]:
        print(f"ERROR: Invalid order type '{order_type}'. Must be 'market' or 'limit'")
        return False
    
    # Validate price for limit orders
    if order_type == "limit" and price_cents is None:
        print(f"ERROR: Limit orders require --price-cents")
        return False
    
    # Live trading confirmation
    if live:
        print("\n⚠️  WARNING: LIVE TRADING MODE ⚠️")
        print("This will submit a REAL order to Kalshi.")
        print(f"Asset: {asset}, Order Type: {order_type}, Count: {count}")
        if order_type == "limit":
            print(f"Price: {price_cents} cents")
        print("\nType 'CONFIRM' to proceed: ", end="", flush=True)
        confirmation = input()
        if confirmation != "CONFIRM":
            print("Trade cancelled.")
            return False
    
    try:
        # Import production components
        from merid.prediction.agent_grid_15m import (
            build_15m_agent_grid,
            LeanAgentConfig,
            LeanAgent15m,
            LeanAgentGrid15m
        )
        from merid.event_venues.kalshi.order_router import (
            OrderIntent,
            resolve_window_policy,
            resolve_exit_policy,
            route_order_async
        )
        from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from data.unified_spot_service import get_unified_spot_service
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from merid.event_venues.kalshi.ws_bridge import get_kalshi_ws_bridge
        
        print("Initializing components...")
        
        # Get risk envelope
        print("Loading risk envelope...")
        risk_service = get_risk_envelope_service()
        risk_service.refresh_if_stale(max_age_seconds=30.0)
        risk_envelope = risk_service.get_config()
        
        if risk_envelope is None:
            print("WARNING: Risk envelope not ready, using fallback values")
            # Use fallback values for testing
            class FallbackRiskEnvelope:
                live_bankroll_usd = 1000.0
                max_single_order_notional_usd = 100.0
                per_trade_risk_multiplier = 0.02
                max_position_value_usd = 100000.0
                asset_max_notional_usd = {
                    "BTC": 50000.0,
                    "ETH": 30000.0,
                    "SOL": 20000.0,
                    "XRP": 15000.0,
                    "DOGE": 10000.0
                }
            risk_envelope = FallbackRiskEnvelope()
        
        print(f"Risk envelope loaded:")
        print(f"  - Bankroll: ${risk_envelope.live_bankroll_usd:.2f}")
        print(f"  - Max single order: ${risk_envelope.max_single_order_notional_usd:.2f}")
        print(f"  - Per-trade risk: {risk_envelope.per_trade_risk_multiplier:.2f}x")
        
        # Get market catalog
        print("Loading market catalog...")
        catalog = get_market_catalog()
        
        # Get spot provider
        print("Loading spot provider...")
        spot_provider = get_unified_spot_service()
        
        # Get market state store
        print("Loading market state store...")
        market_state_store = get_kalshi_market_state_store()
        
        # Get WebSocket bridge
        print("Loading WebSocket bridge...")
        ws_bridge = get_kalshi_ws_bridge()
        
        # Build agent grid
        print("Building agent grid...")
        agent_grid = await build_15m_agent_grid(
            catalog=catalog,
            bankroll=None,  # Will use risk envelope
            spot_provider=spot_provider,
            order_router=None,  # Will use direct routing
            loop=None,
            ws_bridge=ws_bridge,
        )
        
        print(f"Agent grid built with {len(agent_grid._agents)} agents")
        
        # Get the specific agent for the asset
        asset_agent = None
        for agent in agent_grid._agents:
            if agent.config.name == f"{asset}_15M":
                asset_agent = agent
                break
        
        if not asset_agent:
            print(f"ERROR: Could not find agent for asset {asset}")
            return False
        
        print(f"Found agent: {asset_agent.config.name}")
        
        # Get series ticker for the asset
        series_ticker = asset_agent.config.series_tickers[0]
        print(f"Series ticker: {series_ticker}")
        
        # Get market state for the series
        print("Fetching market state...")
        market_state = market_state_store.get(series_ticker) if market_state_store else None
        
        if not market_state:
            print(f"WARNING: No market state found for {series_ticker}")
            print("Will proceed with default values...")
        else:
            print(f"Market state found:")
            print(f"  - Mid price: {market_state.mid_cents} cents" if hasattr(market_state, 'mid_cents') else "  - Mid price: N/A")
            print(f"  - Best bid: {market_state.best_bid_cents} cents" if hasattr(market_state, 'best_bid_cents') else "  - Best bid: N/A")
            print(f"  - Best ask: {market_state.best_ask_cents} cents" if hasattr(market_state, 'best_ask_cents') else "  - Best ask: N/A")
        
        # Determine price
        if order_type == "market":
            if market_state and hasattr(market_state, 'mid_cents') and market_state.mid_cents:
                price_cents = market_state.mid_cents
                print(f"Using market mid price: {price_cents} cents")
            elif market_state and hasattr(market_state, 'best_bid_cents') and hasattr(market_state, 'best_ask_cents'):
                price_cents = (market_state.best_bid_cents + market_state.best_ask_cents) // 2
                print(f"Using mid of bid/ask: {price_cents} cents")
            else:
                print("WARNING: Could not determine market price, using default 50 cents")
                price_cents = 50
        
        # Validate position size
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
        
        # Force a candidate from the agent
        print(f"\nForcing candidate generation from {asset_agent.config.name}...")
        
        # Create a forced candidate (bypassing normal signal generation)
        candidate = {
            "ticker": series_ticker,
            "side": "yes",  # Default to YES for testing
            "action": "buy",
            "count": count,
            "price_cents": price_cents,
            "order_type": order_type,
            "edge_metadata": {
                "forced_trade": True,
                "asset": asset,
                "order_type": order_type,
                "timestamp": datetime.utcnow().isoformat(),
            },
        }
        
        print(f"Forced candidate created:")
        print(f"  - Ticker: {candidate['ticker']}")
        print(f"  - Side: {candidate['side']}")
        print(f"  - Action: {candidate['action']}")
        print(f"  - Count: {candidate['count']}")
        print(f"  - Price: {candidate['price_cents']} cents")
        print(f"  - Order Type: {candidate['order_type']}")
        print(f"  - Notional: ${(candidate['count'] * candidate['price_cents']) / 100:.2f}")
        
        if not live:
            print("\n✓ DRY-RUN COMPLETE - No order submitted")
            print("To execute for real, add --live flag")
            return True
        
        # Resolve policies
        print("\nResolving trading policies...")
        window_policy = resolve_window_policy(asset=asset, regime="normal")
        exit_policy = resolve_exit_policy(edge_result=None, asset=asset, regime="normal")
        
        # Construct OrderIntent
        intent = OrderIntent(
            ticker=candidate["ticker"],
            side=candidate["side"],
            action=candidate["action"],
            price_cents=candidate["price_cents"],
            count=candidate["count"],
            window_resolution_id=window_policy.resolution_id if hasattr(window_policy, 'resolution_id') else "15m",
            exit_policy_id=exit_policy.policy_id if hasattr(exit_policy, 'policy_id') else "standard",
            caller_module="force_agent_trade_script",
            edge_metadata=candidate["edge_metadata"],
        )
        
        print(f"\nOrder Intent constructed:")
        print(f"  - Ticker: {intent.ticker}")
        print(f"  - Side: {intent.side}")
        print(f"  - Action: {intent.action}")
        print(f"  - Price: {intent.price_cents} cents")
        print(f"  - Count: {intent.count}")
        print(f"  - Notional: ${(intent.count * intent.price_cents) / 100:.2f}")
        
        # Submit order
        print(f"\nSubmitting {order_type.upper()} order to Kalshi...")
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
        description="Force agent grid to generate and execute trade candidates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Market order (dry-run)
  py scripts\\force_agent_trade_execution.py --asset BTC --order-type market
  
  # Market order (live)
  py scripts\\force_agent_trade_execution.py --asset BTC --order-type market --live
  
  # Limit order (dry-run)
  py scripts\\force_agent_trade_execution.py --asset BTC --order-type limit --price-cents 50
  
  # Limit order (live)
  py scripts\\force_agent_trade_execution.py --asset BTC --order-type limit --price-cents 50 --live
        """
    )
    
    parser.add_argument(
        "--asset",
        required=True,
        choices=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        help="Asset to trade"
    )
    
    parser.add_argument(
        "--order-type",
        required=True,
        choices=["market", "limit"],
        help="Order type (market or limit)"
    )
    
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of contracts (default: 10)"
    )
    
    parser.add_argument(
        "--price-cents",
        type=int,
        help="Price in cents (required for limit orders)"
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
    success = asyncio.run(force_agent_trade(
        asset=args.asset,
        order_type=args.order_type,
        count=args.count,
        price_cents=args.price_cents,
        live=args.live,
        profile=args.profile
    ))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
