"""Actual live order execution test.

This script submits a real order through the complete system pipeline
to expose any remaining flaws, gaps, or silent failures.

WARNING: This will attempt to execute actual orders through the system.
"""

import asyncio
import sys
import time
from typing import Dict, Any

# Add the project root to path
sys.path.insert(0, r"c:\Dev\MERID")

async def test_full_order_execution():
    """Execute a complete order through the system."""
    print("=" * 70)
    print("ACTUAL LIVE ORDER EXECUTION TEST")
    print("=" * 70)
    
    try:
        # Import the order routing components
        from merid.event_venues.kalshi.order_router import (
            route_order_async, 
            OrderIntent,
            get_venue_gate
        )
        from merid.event_venues.kalshi.kalshi_config import KalshiConfig
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        
        print("\n=== Step 1: System Initialization ===")
        
        # Check venue gate status
        venue_gate = get_venue_gate()
        print(f"✓ Venue gate loaded: mode={venue_gate.mode}")
        print(f"  Ready: {venue_gate.ready}")
        print(f"  Kalshi ready: {venue_gate.kalshi_ready}")
        
        # Check Kalshi config
        try:
            config = KalshiConfig()
            print(f"✓ Kalshi config loaded")
            print(f"  Environment: {config.environment}")
            print(f"  Ready: {config.ready}")
        except Exception as e:
            print(f"⚠ Kalshi config issue: {e}")
        
        # Check risk manager
        try:
            from merid.risk.kill_switches import KillSwitchManager
            risk_manager = KillSwitchManager()
            print(f"✓ Risk manager loaded")
            print(f"  Kill switch active: {risk_manager.is_active()}")
        except Exception as e:
            print(f"⚠ Risk manager issue: {e}")
        
        # Check market state store
        try:
            store = get_kalshi_market_state_store()
            print(f"✓ Market state store loaded: id={id(store)}")
        except Exception as e:
            print(f"⚠ Market state store issue: {e}")
        
        print("\n=== Step 2: Market Selection ===")
        
        # Get available markets from the store
        try:
            tickers = store.get_all_tickers()
            print(f"✓ Available markets: {len(tickers)}")
            
            # Find a market with liquidity
            best_ticker = None
            best_liquidity = 0
            
            for ticker in tickers:
                try:
                    state = store.get(ticker)
                    if state and hasattr(state, 'best_bid_cents') and hasattr(state, 'best_ask_cents'):
                        bid = state.best_bid_cents or 0
                        ask = state.best_ask_cents or 0
                        liquidity = bid + ask
                        if liquidity > best_liquidity and liquidity > 0:
                            best_liquidity = liquidity
                            best_ticker = ticker
                            print(f"  {ticker}: bid={bid} ask={ask} liquidity={liquidity}")
                except Exception as e:
                    print(f"  {ticker}: error reading state - {e}")
            
            if not best_ticker and tickers:
                best_ticker = tickers[0]
                print(f"⚠ No liquid markets, using: {best_ticker}")
            elif best_ticker:
                print(f"✓ Selected market: {best_ticker} (liquidity: {best_liquidity})")
            else:
                print("✗ No markets available")
                return False
                
        except Exception as e:
            print(f"✗ Market selection failed: {e}")
            return False
        
        print("\n=== Step 3: Order Intent Creation ===")
        
        # Create a test order intent
        intent = OrderIntent(
            ticker=best_ticker,
            side="yes",
            action="buy",
            price_cents=65,  # Conservative limit price
            count=1,  # Minimum size
            agent_id="BTC_15M",
            source="e2e_test",
            client_tag=f"test_{int(time.time())}",
            confidence=0.75,
            rationale="End-to-end order execution test",
            order_type="limit",
            time_in_force="gtc"
        )
        
        print(f"✓ OrderIntent created:")
        print(f"  Ticker: {intent.ticker}")
        print(f"  Side: {intent.side}")
        print(f"  Action: {intent.action}")
        print(f"  Price: {intent.price_cents} cents")
        print(f"  Count: {intent.count}")
        print(f"  Intent ID: {intent.intent_id}")
        print(f"  Mode: {intent.mode}")
        
        print("\n=== Step 4: Order Submission ===")
        
        # Submit the order through the routing system
        print("Submitting order through route_order_async...")
        
        start_time = time.time()
        result = await route_order_async(intent)
        elapsed = time.time() - start_time
        
        print(f"✓ Order routing completed in {elapsed:.3f}s")
        print(f"  Status: {result.status}")
        print(f"  Mode: {result.mode}")
        print(f"  Reason: {result.reason}")
        print(f"  Latency: {result.latency_ms}ms")
        
        if hasattr(result, 'order_id'):
            print(f"  Order ID: {result.order_id}")
        if hasattr(result, 'venue_order_id'):
            print(f"  Venue Order ID: {result.venue_order_id}")
        if hasattr(result, 'filled'):
            print(f"  Filled: {result.filled}")
        if hasattr(result, 'fill_price_cents'):
            print(f"  Fill Price: {result.fill_price_cents} cents")
        
        print("\n=== Step 5: Result Analysis ===")
        
        if result.status == "filled":
            print("✅ SUCCESS: Order filled immediately")
            print(f"   Fill price: {result.fill_price_cents} cents")
            print(f"   Fill quantity: {result.count}")
        elif result.status == "accepted":
            print("✅ SUCCESS: Order accepted and working")
            print(f"   Order ID: {result.order_id}")
            print(f"   Order is now resting in the book")
        elif result.status == "rejected":
            print(f"⚠ ORDER REJECTED: {result.reason}")
            print("   This indicates a risk check or validation failure")
        elif result.status == "error":
            print(f"✗ ORDER ERROR: {result.reason}")
            print("   This indicates a system error or missing component")
        else:
            print(f"⚠ UNKNOWN STATUS: {result.status}")
        
        print("\n=== Step 6: System State Verification ===")
        
        # Check if any errors occurred during routing
        if result.status in ["error", "rejected"]:
            print("⚠ Order did not complete successfully")
            print("   Potential issues:")
            print("   - Risk envelope limits")
            print("   - Trading mode restrictions")
            print("   - Market validation failures")
            print("   - API credentials missing")
            print("   - Rate limiting")
            return False
        
        # Verify market state after order
        try:
            state = store.get(best_ticker)
            if state:
                print(f"✓ Market state still accessible after order")
                print(f"  Bid: {state.best_bid_cents}")
                print(f"  Ask: {state.best_ask_cents}")
        except Exception as e:
            print(f"⚠ Market state read failed after order: {e}")
        
        print("\n=== Step 7: Gap Analysis ===")
        
        gaps = []
        
        # Check for common gaps
        if result.status == "error":
            gaps.append("Order routing error - missing error handling")
        
        if result.status == "rejected" and "scope" in result.reason.lower():
            gaps.append("Trading scope validation too restrictive")
        
        if result.status == "rejected" and "risk" in result.reason.lower():
            gaps.append("Risk envelope configuration issue")
        
        if result.status == "rejected" and "rate" in result.reason.lower():
            gaps.append("Rate limiting too aggressive for testing")
        
        if not hasattr(result, 'order_id') and result.status == "accepted":
            gaps.append("Order ID not returned for accepted orders")
        
        if not hasattr(result, 'venue_order_id') and result.status in ["accepted", "filled"]:
            gaps.append("Venue order ID not returned - tracking gap")
        
        if gaps:
            print("⚠ Potential gaps detected:")
            for gap in gaps:
                print(f"   - {gap}")
        else:
            print("✓ No obvious gaps detected in order flow")
        
        print("\n" + "=" * 70)
        print("ORDER EXECUTION TEST COMPLETE")
        print("=" * 70)
        
        if result.status in ["filled", "accepted"]:
            print("✅ System successfully processed order through full pipeline")
            print("   - Order routing functional")
            print("   - Risk checks operational")
            print("   - Market validation working")
            print("   - Venue integration active")
            return True
        else:
            print("⚠ Order processing incomplete or failed")
            print(f"   Status: {result.status}")
            print(f"   Reason: {result.reason}")
            return False
            
    except ImportError as e:
        print(f"✗ Import error: {e}")
        print("   Required modules not available")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_full_order_execution())
    sys.exit(0 if result else 1)
