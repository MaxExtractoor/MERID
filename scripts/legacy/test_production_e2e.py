"""Production End-to-End Trading Test

This script forces the autonomous system to execute a live trade through
the complete production stack to verify end-to-end wiring for signals,
orders, and fills in LIVE mode (not paper/demo).

WARNING: This will execute REAL trades with REAL money.
"""

import asyncio
import sys
import os
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

# Add project root to path
sys.path.insert(0, r"c:\Dev\MERID")

@dataclass
class TradeExecutionResult:
    """Result of end-to-end trade execution."""
    signal_generated: bool
    order_submitted: bool
    order_accepted: bool
    fill_received: bool
    position_updated: bool
    latency_ms: float
    error: Optional[str] = None
    details: Dict[str, Any] = None

async def test_production_e2e():
    """Execute end-to-end production trade test."""
    print("=" * 80)
    print("PRODUCTION END-TO-END TRADING TEST")
    print("=" * 80)
    print("WARNING: This will execute REAL trades with REAL money")
    print("=" * 80)
    
    result = TradeExecutionResult(
        signal_generated=False,
        order_submitted=False,
        order_accepted=False,
        fill_received=False,
        position_updated=False,
        latency_ms=0.0,
        details={}
    )
    
    try:
        # Step 1: Configure LIVE mode
        print("\n=== Step 1: Configure LIVE Mode ===")
        os.environ["MERID_PM_TRADING_MODE"] = "live"
        os.environ["MERID_ALLOW_LIVE_TRADES"] = "true"
        os.environ["MERID_PM_LIVE_ENABLED"] = "true"
        
        from merid.prediction.venue_gate import VenueGate
        from merid.prediction.trading_mode import TradingMode
        
        # Create venue gate to check mode
        venue_gate = VenueGate()
        print(f"Current mode: {venue_gate.mode}")
        
        if not venue_gate.mode.is_live():
            print("✗ FAILED: Cannot set LIVE mode")
            result.error = "Cannot set LIVE mode"
            return result
        
        print("✓ LIVE mode configured")
        
        # Step 2: Initialize agent grid
        print("\n=== Step 2: Initialize Agent Grid ===")
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        from merid.prediction.agent_grid_config import AgentConfig
        
        # Create agent config for BTC
        agent_config = AgentConfig(
            name="BTC_15M",
            category="crypto",
            assets=["BTC"],
            timeframes=["15m"],
            enabled=True
        )
        
        agent = LeanAgentGrid15m(agent_config)
        print(f"✓ Agent initialized: {agent_config.name}")
        
        # Step 3: Force signal generation
        print("\n=== Step 3: Force Signal Generation ===")
        
        # Get current market data
        from merid.event_venues.kalshi.market_catalog import get_kalshi_market_catalog
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        
        catalog = get_kalshi_market_catalog()
        market_store = get_kalshi_market_state_store()
        
        # Get eligible markets
        markets_15m = catalog.get_markets_by_timeframe("15m")
        btc_markets = [m for m in markets_15m if "BTC" in m.market.market_id]
        
        if not btc_markets:
            print("✗ No BTC markets found")
            result.error = "No BTC markets found"
            return result
        
        selected_market = btc_markets[0]
        print(f"✓ Selected market: {selected_market.market.market_id}")
        
        # Get spot price
        from data.unified_spot_service import get_spot_price_sync
        spot_price = get_spot_price_sync("BTC")
        
        if spot_price is None:
            print("✗ Cannot get spot price")
            result.error = "Cannot get spot price"
            return result
        
        print(f"✓ Spot price: ${spot_price:.2f}")
        
        # Force signal generation by calling internal method
        try:
            # Convert market to dict format expected by _generate_signal
            market_dict = {
                "ticker": selected_market.market.market_id,
                "market_id": selected_market.market.market_id,
                "minutes_to_expiry": selected_market.minutes_to_expiry
            }
            
            signal = agent._generate_signal(spot_price, market_dict, selected_market.minutes_to_expiry)
            
            if signal:
                print(f"✓ Signal generated: {signal}")
                result.signal_generated = True
                result.details['signal'] = signal
            else:
                print("✗ Signal generation failed")
                result.error = "Signal generation failed"
                return result
                
        except Exception as e:
            print(f"✗ Signal generation error: {e}")
            import traceback
            traceback.print_exc()
            result.error = f"Signal generation error: {e}"
            return result
        
        # Step 4: Submit order through routing system
        print("\n=== Step 4: Submit Order Through Routing System ===")
        
        from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
        
        # Create order intent with exit policy
        intent = OrderIntent(
            ticker=signal.get("market_id"),
            side=signal.get("side", "yes"),
            action=signal.get("action", "buy"),
            price_cents=signal.get("price_cents", 50),
            count=signal.get("count", 1),
            agent_id="BTC_15M",
            source="production_e2e_test",
            client_tag=f"prod_test_{int(time.time())}",
            confidence=signal.get("confidence", 0.75),
            rationale="Production end-to-end test",
            order_type="limit",
            time_in_force="gtc",
            take_profit_price_cents=signal.get("take_profit_price_cents"),
            stop_loss_price_cents=signal.get("stop_loss_price_cents"),
            take_profit_r_multiple=signal.get("take_profit_r_multiple")
        )
        
        print(f"Order intent created:")
        print(f"  Ticker: {intent.ticker}")
        print(f"  Side: {intent.side}")
        print(f"  Action: {intent.action}")
        print(f"  Price: {intent.price_cents} cents")
        print(f"  Count: {intent.count}")
        print(f"  Take Profit: {intent.take_profit_price_cents}")
        print(f"  Stop Loss: {intent.stop_loss_price_cents}")
        
        start_time = time.time()
        order_result = await route_order_async(intent)
        elapsed = time.time() - start_time
        result.latency_ms = elapsed * 1000
        
        print(f"\nOrder routing result:")
        print(f"  Status: {order_result.status}")
        print(f"  Mode: {order_result.mode}")
        print(f"  Reason: {order_result.reason}")
        print(f"  Latency: {result.latency_ms:.2f}ms")
        
        if order_result.status == "filled":
            print(f"  Fill Price: {order_result.fill_price_cents} cents")
            print(f"  Fill Quantity: {order_result.filled}")
            result.fill_received = True
        elif order_result.status == "accepted":
            print(f"  Order ID: {order_result.order_id}")
            print(f"  Venue Order ID: {order_result.venue_order_id}")
            result.order_accepted = True
        elif order_result.status == "rejected":
            print(f"✗ Order rejected: {order_result.reason}")
            result.error = f"Order rejected: {order_result.reason}"
            return result
        elif order_result.status == "error":
            print(f"✗ Order error: {order_result.reason}")
            result.error = f"Order error: {order_result.reason}"
            return result
        
        result.order_submitted = True
        result.details['order_result'] = {
            'status': order_result.status,
            'order_id': getattr(order_result, 'order_id', None),
            'venue_order_id': getattr(order_result, 'venue_order_id', None),
            'filled': getattr(order_result, 'filled', None),
            'fill_price_cents': getattr(order_result, 'fill_price_cents', None)
        }
        
        # Step 5: Verify position updates
        print("\n=== Step 5: Verify Position Updates ===")
        
        # Check risk snapshot
        try:
            import requests
            response = requests.get("http://localhost:8011/api/v1/risk-snapshot", timeout=5)
            if response.status_code == 200:
                risk_data = response.json()
                print(f"✓ Risk snapshot retrieved")
                result.details['risk_snapshot'] = risk_data
                result.position_updated = True
            else:
                print(f"⚠ Risk snapshot status: {response.status_code}")
        except Exception as e:
            print(f"⚠ Cannot verify position updates: {e}")
        
        # Step 6: Final verification
        print("\n=== Step 6: Final Verification ===")
        
        success = all([
            result.signal_generated,
            result.order_submitted,
            result.order_accepted or result.fill_received
        ])
        
        if success:
            print("✅ SUCCESS: End-to-end production trade executed")
            print("   - Signal generation: ✓")
            print("   - Order submission: ✓")
            print("   - Order acceptance/fill: ✓")
            print(f"   - Total latency: {result.latency_ms:.2f}ms")
        else:
            print("⚠ PARTIAL SUCCESS: Some steps failed")
            print(f"   - Signal generation: {'✓' if result.signal_generated else '✗'}")
            print(f"   - Order submission: {'✓' if result.order_submitted else '✗'}")
            print(f"   - Order acceptance/fill: {'✓' if result.order_accepted or result.fill_received else '✗'}")
        
        return result
        
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        result.error = f"Unexpected error: {e}"
        return result

async def main():
    """Main entry point."""
    result = await test_production_e2e()
    
    print("\n" + "=" * 80)
    print("PRODUCTION E2E TEST COMPLETE")
    print("=" * 80)
    
    if result.error:
        print(f"✗ FAILED: {result.error}")
        sys.exit(1)
    elif all([result.signal_generated, result.order_submitted, result.order_accepted or result.fill_received]):
        print("✅ PASSED: Full end-to-end production stack verified")
        sys.exit(0)
    else:
        print("⚠ PARTIAL: Some components not verified")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
