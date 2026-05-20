#!/usr/bin/env python3
"""Test script to verify live order routing works."""

import asyncio
import time

async def test_order_route():
    print('=== TESTING LIVE ORDER ROUTING ===')
    print()
    
    # Import required modules
    from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent
    from merid.prediction.venue_gate import get_venue_gate
    from trading.trade_mode import get_trade_mode
    
    # Check venue gate
    gate = get_venue_gate()
    print(f'VenueGate: mode={gate.mode}, live_enabled={gate.live_enabled}, simulate={gate.should_simulate_fill()}')
    
    # Check trade mode  
    mode = get_trade_mode()
    print(f'TradeMode: {mode}')
    print()
    
    # Create a test order intent (small test order)
    intent = OrderIntent(
        ticker='KXBTC15M-250430-1900',
        side='yes',
        action='buy',
        price_cents=50,
        count=1,
        source='test_script',
        agent_id='test_agent',
        snapshot_ts=time.time(),
        decision_trace_id='test_trace_001',
    )
    
    print(f'OrderIntent: ticker={intent.ticker}, side={intent.side}, price={intent.price_cents}c, count={intent.count}')
    print()
    
    # Try to route the order
    print('Routing order...')
    try:
        result = await route_order_async(intent)
        print(f'Result status: {result.status}')
        print(f'Result mode: {result.mode}')
        print(f'Result reason: {result.reason}')
        print(f'Result fill: {result.fill}')
        print(f'Result latency_ms: {result.latency_ms}')
        
        if result.status == 'rejected':
            print()
            print('*** ORDER WAS REJECTED ***')
            print(f'Rejection reason: {result.reason}')
            
    except Exception as e:
        print(f'Exception during routing: {e}')
        import traceback
        traceback.print_exc()
    
    print()
    print('=== END TEST ===')

if __name__ == '__main__':
    asyncio.run(test_order_route())
