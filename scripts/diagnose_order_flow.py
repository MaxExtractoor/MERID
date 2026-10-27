#!/usr/bin/env python3
"""
Diagnostic script to check the order flow pipeline and identify where orders are being blocked.
This script checks each stage of the pipeline: signal generation -> order routing -> risk gates -> execution.
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def check_signal_generation():
    """Check if agents are generating signals."""
    print("Checking signal generation...")
    try:
        from merid.prediction.agent_grid_15m import AgentGrid15M
        from config.profiles.kalshi_crypto_15m_v2 import kalshi_crypto_15m_v2
        
        # Check if agent grid is initialized
        print("  Agent grid status: Checking initialization...")
        # This would require accessing the running instance
        print("  WARNING: Cannot check running instance without proper endpoint access")
        return False
    except Exception as e:
        print(f"  Error checking signal generation: {e}")
        return False

async def check_order_router():
    """Check if order router is receiving signals."""
    print("Checking order router...")
    try:
        from merid.event_venues.kalshi.order_router import OrderRouter
        print("  Order router module loaded successfully")
        print("  WARNING: Cannot check running instance without proper endpoint access")
        return False
    except Exception as e:
        print(f"  Error checking order router: {e}")
        return False

async def check_risk_gates():
    """Check risk gate status."""
    print("Checking risk gates...")
    try:
        from merid.event_venues.kalshi.pre_trade_gate import PreTradeGate
        print("  Pre-trade gate module loaded successfully")
        print("  WARNING: Cannot check running instance without proper endpoint access")
        return False
    except Exception as e:
        print(f"  Error checking risk gates: {e}")
        return False

async def check_window_limits():
    """Check window-based risk limits."""
    print("Checking window-based risk limits...")
    try:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15MRiskEnvelope
        envelope = KalshiCrypto15MRiskEnvelope()
        print(f"  Per-agent window limit: {envelope.agent_max_notional_pct * 100}%")
        print(f"  Total venue window limit: {envelope.venue_max_total_notional_pct * 100}%")
        print(f"  Current window exposure: Cannot check without runtime access")
        return True
    except Exception as e:
        print(f"  Error checking window limits: {e}")
        return False

async def check_market_data():
    """Check if market data is flowing."""
    print("Checking market data flow...")
    try:
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        print("  Market catalog module loaded successfully")
        print("  WARNING: Cannot check running instance without proper endpoint access")
        return False
    except Exception as e:
        print(f"  Error checking market data: {e}")
        return False

async def check_websocket():
    """Check WebSocket connection status."""
    print("Checking WebSocket connection...")
    try:
        from kalshi.ws_bridge import WSBridge
        print("  WebSocket bridge module loaded successfully")
        print("  WARNING: Cannot check running instance without proper endpoint access")
        return False
    except Exception as e:
        print(f"  Error checking WebSocket: {e}")
        return False

async def main():
    """Run all diagnostic checks."""
    print("="*60)
    print("ORDER FLOW DIAGNOSTIC")
    print("="*60)
    print()
    
    results = {}
    
    # Check each stage of the pipeline
    results['signal_generation'] = await check_signal_generation()
    print()
    results['order_router'] = await check_order_router()
    print()
    results['risk_gates'] = await check_risk_gates()
    print()
    results['window_limits'] = await check_window_limits()
    print()
    results['market_data'] = await check_market_data()
    print()
    results['websocket'] = await check_websocket()
    print()
    
    print("="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    print("NOTE: Most checks require runtime access to the running server.")
    print("Recommendation: Monitor server logs for signal generation and order flow.")
    print()
    print("Key log patterns to watch for:")
    print("  - SIGNAL: Agent opinion generation")
    print("  - ORDER: Order router calls")
    print("  - REJECT: Order rejections at gates")
    print("  - FILL: Order executions")
    print("  - WINDOW: Window limit violations")

if __name__ == "__main__":
    asyncio.run(main())
