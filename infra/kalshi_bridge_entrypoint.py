#!/usr/bin/env python3
"""
Kalshi WebSocket Bridge Entrypoint
Connects to Kalshi WS with RSA-PSS auth, routes events to NATS event bus.
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid_core.kalshi.ws_bridge import KalshiWebSocketBridge
from merid_core.event_bus.nats_adapter import NATSEventBus


async def main():
    # Configuration from environment
    api_key_id = os.getenv("KALSHI_API_KEY_ID")
    private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    kalshi_env = os.getenv("KALSHI_ENV", "demo")
    event_bus_url = os.getenv("EVENT_BUS_URL", "nats://localhost:4222")
    markets = os.getenv("MARKETS", "").split(",")
    
    if not api_key_id or not private_key_path:
        raise ValueError("KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH required")
    
    if not markets or markets == [""]:
        raise ValueError("MARKETS environment variable required (comma-separated)")
    
    print(f"[Bridge] Starting Kalshi WS Bridge")
    print(f"[Bridge] Environment: {kalshi_env}")
    print(f"[Bridge] Markets: {markets}")
    print(f"[Bridge] Event Bus: {event_bus_url}")
    
    # Initialize event bus
    event_bus = NATSEventBus(event_bus_url)
    await event_bus.connect()
    print(f"[Bridge] Connected to event bus")
    
    # Initialize Kalshi bridge
    bridge = KalshiWebSocketBridge(
        key_id=api_key_id,
        private_key_path=private_key_path,
        env=kalshi_env,
        event_bus=event_bus
    )
    
    bridge.set_markets(markets)
    
    print(f"[Bridge] Starting WS connection to Kalshi...")
    
    try:
        await bridge.run()
    except KeyboardInterrupt:
        print(f"[Bridge] Shutting down...")
        await bridge.stop()
        await event_bus.disconnect()
    except Exception as e:
        print(f"[Bridge] Fatal error: {e}")
        await bridge.stop()
        await event_bus.disconnect()
        raise


if __name__ == "__main__":
    asyncio.run(main())
