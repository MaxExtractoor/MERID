#!/usr/bin/env python3
"""
Standalone Kalshi WebSocket test client for diagnostic purposes.

This script connects to Kalshi WebSocket and subscribes to orderbook_delta
for a single ticker to verify that Kalshi is actually sending events.

Usage:
    python scripts/kalshi_ws_test_client.py

This helps distinguish between:
- Kalshi not sending events (server-side issue)
- MERID client not receiving events (client-side wiring issue)
"""

import asyncio
import json
import websockets
import time
from pathlib import Path
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from datetime import datetime, timezone

# Configuration
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
PRIVATE_KEY_PATH = Path("C:/Dev/MERID/kalshi_private_key.pem")
API_KEY_ID = "18e1cc92-101c-4118-8135-4c3fc27b9fd8"
TEST_TICKER = "KXBTC15M-26JUN092330-30"


def create_signature(private_key_path: str, timestamp: str) -> str:
    """Create RSA-PSS signature for Kalshi WebSocket authentication."""
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=None
        )

    method = "GET"
    path = "/trade-api/ws/v2"
    msg_string = timestamp + method + path

    signature = private_key.sign(
        msg_string.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    return signature.hex()


async def main():
    """Main test client."""
    print(f"[{datetime.now(timezone.utc)}] Starting Kalshi WS test client")
    print(f"[{datetime.now(timezone.utc)}] Target ticker: {TEST_TICKER}")
    print(f"[{datetime.now(timezone.utc)}] WS URL: {WS_URL}")

    # Create authentication signature
    timestamp = str(int(time.time() * 1000) + 5000)
    signature = create_signature(PRIVATE_KEY_PATH, timestamp)

    print(f"[{datetime.now(timezone.utc)}] Authentication signature created")

    # Prepare headers
    headers = {
        "Kalshi-Api-Key-Id": API_KEY_ID,
        "Kalshi-Api-Signature": signature,
        "Kalshi-Api-Timestamp": timestamp,
    }

    print(f"[{datetime.now(timezone.utc)}] Connecting to WebSocket...")

    try:
        # Use additional_headers instead of extra_headers for websockets compatibility
        async with websockets.connect(WS_URL, additional_headers=headers) as ws:
            print(f"[{datetime.now(timezone.utc)}] Connected successfully")

            # Send subscription
            sub_message = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": [TEST_TICKER],
                },
            }

            print(f"[{datetime.now(timezone.utc)}] Sending subscription: {json.dumps(sub_message, indent=2)}")
            await ws.send(json.dumps(sub_message))
            print(f"[{datetime.now(timezone.utc)}] Subscription sent")

            # Listen for messages
            message_count = 0
            orderbook_count = 0
            start_time = time.time()

            print(f"[{datetime.now(timezone.utc)}] Listening for messages (60s timeout)...")
            print(f"[{datetime.now(timezone.utc)}] {'='*60}")

            while time.time() - start_time < 60:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    message_count += 1

                    try:
                        data = json.loads(msg)
                        msg_type = data.get("type", "unknown")

                        print(f"[{datetime.now(timezone.utc)}] MSG #{message_count}: type={msg_type}")

                        if msg_type in ("orderbook_snapshot", "orderbook_delta"):
                            orderbook_count += 1
                            ticker = data.get("msg", {}).get("market_ticker", "unknown")
                            print(f"[{datetime.now(timezone.utc)}]   ORDERBOOK: ticker={ticker} count={orderbook_count}")

                        if msg_type in ("subscribed", "ok"):
                            print(f"[{datetime.now(timezone.utc)}]   SUBSCRIPTION CONFIRMED: {data}")

                        if msg_type == "error":
                            print(f"[{datetime.now(timezone.utc)}]   ERROR: {data}")

                    except json.JSONDecodeError:
                        print(f"[{datetime.now(timezone.utc)}]   RAW (non-JSON): {msg[:100]}")

                except asyncio.TimeoutError:
                    print(f"[{datetime.now(timezone.utc)}] No message for 5s (still listening...)")

            print(f"[{datetime.now(timezone.utc)}] {'='*60}")
            print(f"[{datetime.now(timezone.utc)}] Test completed")
            print(f"[{datetime.now(timezone.utc)}] Total messages: {message_count}")
            print(f"[{datetime.now(timezone.utc)}] Orderbook messages: {orderbook_count}")

            if orderbook_count > 0:
                print(f"[{datetime.now(timezone.utc)}] ✓ SUCCESS: Kalshi IS sending orderbook events")
            else:
                print(f"[{datetime.now(timezone.utc)}] ✗ FAILURE: Kalshi NOT sending orderbook events")
                print(f"[{datetime.now(timezone.utc)}] Possible causes:")
                print(f"[{datetime.now(timezone.utc)}]   - Market is closed/paused")
                print(f"[{datetime.now(timezone.utc)}]   - Ticker is invalid")
                print(f"[{datetime.now(timezone.utc)}]   - Kalshi server issue")

    except Exception as e:
        print(f"[{datetime.now(timezone.utc)}] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
