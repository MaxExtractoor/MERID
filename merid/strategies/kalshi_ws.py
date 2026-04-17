"""
Kalshi WebSocket Real-Time Market Updates

WebSocket client for Kalshi real-time market data with authentication.
"""

import os
import json
import websockets
import asyncio
import logging
import hmac
import hashlib
import time
from typing import List, Dict, Any, Callable, Optional
import threading

logger = logging.getLogger("kalshi_ws")

# Kalshi WebSocket configuration - read from env to support demo/live modes
KALSHI_WS_URL = os.getenv("KALSHI_WS_URL", "wss://demo-api.kalshi.co/trade-api/ws/v2")
API_KEY = os.getenv("KALSHI_API_KEY")
API_SECRET = os.getenv("KALSHI_API_SECRET", "").encode()

class KalshiWebSocketClient:
    """Production-ready Kalshi WebSocket client with reconnection and error handling."""
    
    def __init__(self, market_tickers: List[str], 
                 message_handler: Callable[[Dict[str, Any]], None] = None,
                 reconnect_interval: int = 5,
                 max_reconnect_attempts: int = 10):
        """
        Initialize Kalshi WebSocket client.
        
        Args:
            market_tickers: List of market tickers to subscribe to
            message_handler: Callback function for incoming messages
            reconnect_interval: Seconds between reconnection attempts
            max_reconnect_attempts: Maximum reconnection attempts
        """
        self.market_tickers = market_tickers
        self.message_handler = message_handler or self._default_message_handler
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        
        self._running = False
        self._websocket = None
        self._task = None
        self._reconnect_count = 0
        
        # Event callbacks
        self.on_connect = None
        self.on_disconnect = None
        self.on_error = None
        
    def _default_message_handler(self, data: Dict[str, Any]) -> None:
        """Default message handler - logs incoming data."""
        logger.info("WS update: %s", data)
        
    def _generate_auth_payload(self) -> Dict[str, Any]:
        """Generate authentication payload for Kalshi WebSocket."""
        if not API_KEY:
            raise ValueError("KALSHI_API_KEY environment variable not set")
        
        # Kalshi auth pattern (adjust based on actual API requirements)
        ts = int(time.time())
        msg = f"{ts}"
        
        if API_SECRET:
            sig = hmac.new(API_SECRET, msg.encode(), hashlib.sha256).hexdigest()
            auth_payload = {
                "type": "auth",
                "api_key": API_KEY,
                "timestamp": ts,
                "signature": sig
            }
        else:
            # Alternative: use token-based auth
            auth_payload = {
                "type": "auth",
                "token": API_KEY  # If using token instead of HMAC
            }
        
        return auth_payload
    
    def _generate_subscribe_payload(self) -> Dict[str, Any]:
        """Generate subscription payload for market tickers."""
        return {
            "type": "subscribe",
            "channels": [
                {
                    "name": "orderbook",
                    "markets": self.market_tickers
                },
                {
                    "name": "trades",
                    "markets": self.market_tickers
                }
            ]
        }
    
    async def _handle_websocket_messages(self):
        """Handle incoming WebSocket messages."""
        try:
            async for raw in self._websocket:
                try:
                    data = json.loads(raw)
                    
                    # Handle different message types
                    msg_type = data.get("type", "")
                    
                    if msg_type == "auth_success":
                        logger.info("WebSocket authentication successful")
                        if self.on_connect:
                            self.on_connect()
                        self._reconnect_count = 0  # Reset reconnection count on successful connect
                        
                    elif msg_type == "auth_error":
                        logger.error("WebSocket authentication failed: %s", data)
                        if self.on_error:
                            self.on_error(data)
                        break
                        
                    elif msg_type == "subscription_success":
                        logger.info("WebSocket subscription successful: %s", data)
                        
                    elif msg_type == "error":
                        logger.error("WebSocket error: %s", data)
                        if self.on_error:
                            self.on_error(data)
                        
                    elif msg_type in ["orderbook", "trade", "quote"]:
                        # Market data messages
                        self.message_handler(data)
                        
                    else:
                        # Unknown message type
                        logger.debug("Unknown message type: %s", data)
                        
                except json.JSONDecodeError as e:
                    logger.error("Failed to decode JSON message: %s", e)
                except Exception as e:
                    logger.exception("Error handling WebSocket message: %s")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            if self.on_disconnect:
                self.on_disconnect()
                
        except Exception as e:
            logger.exception("WebSocket error: %s")
            if self.on_error:
                self.on_error({"error": str(e)})
    
    async def _connect_and_run(self):
        """Connect to WebSocket and run message handler."""
        try:
            logger.info(f"Connecting to Kalshi WebSocket: {KALSHI_WS_URL}")
            
            async with websockets.connect(
                KALSHI_WS_URL, 
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10
            ) as websocket:
                self._websocket = websocket
                
                # Authenticate
                auth_payload = self._generate_auth_payload()
                await websocket.send(json.dumps(auth_payload))
                logger.info("WebSocket authentication sent")
                
                # Subscribe to markets
                sub_payload = self._generate_subscribe_payload()
                await websocket.send(json.dumps(sub_payload))
                logger.info("WebSocket subscription sent for %d markets", len(self.market_tickers))
                
                # Handle messages
                await self._handle_websocket_messages()
                
        except Exception as e:
            logger.exception("WebSocket connection error: %s")
            if self.on_error:
                self.on_error({"error": str(e)})
            raise
    
    async def _run_with_reconnect(self):
        """Run WebSocket client with automatic reconnection."""
        while self._running and self._reconnect_count < self.max_reconnect_attempts:
            try:
                await self._connect_and_run()
                
                if not self._running:
                    break
                    
                # Connection closed, attempt reconnection
                self._reconnect_count += 1
                logger.warning(f"WebSocket disconnected, reconnecting in {self.reconnect_interval}s (attempt {self._reconnect_count}/{self.max_reconnect_attempts})")
                
                await asyncio.sleep(self.reconnect_interval)
                
            except Exception as e:
                logger.exception(f"WebSocket error (attempt {self._reconnect_count}): {e}")
                
                if not self._running:
                    break
                    
                self._reconnect_count += 1
                
                if self._reconnect_count >= self.max_reconnect_attempts:
                    logger.error("Maximum reconnection attempts reached")
                    break
                    
                await asyncio.sleep(self.reconnect_interval)
        
        logger.info("WebSocket client stopped")
    
    async def start(self):
        """Start the WebSocket client."""
        if self._running:
            logger.warning("WebSocket client already running")
            return
        
        self._running = True
        self._reconnect_count = 0
        
        self._task = asyncio.create_task(self._run_with_reconnect())
        logger.info("Kalshi WebSocket client started")
    
    async def stop(self):
        """Stop the WebSocket client."""
        if not self._running:
            return
        
        self._running = False
        
        if self._websocket:
            await self._websocket.close()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Kalshi WebSocket client stopped")
    
    def is_running(self) -> bool:
        """Check if WebSocket client is running."""
        return self._running
    
    def get_reconnect_count(self) -> int:
        """Get current reconnection attempt count."""
        return self._reconnect_count

# Convenience function for simple usage
async def kalshi_ws_client(market_tickers: List[str], 
                           message_handler: Callable[[Dict[str, Any]], None] = None):
    """
    Simple Kalshi WebSocket client function.
    
    Args:
        market_tickers: List of market tickers to subscribe to
        message_handler: Callback function for incoming messages
    """
    client = KalshiWebSocketClient(market_tickers, message_handler)
    await client.start()

# Example usage:
"""
import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

def handle_market_data(data):
    if data.get("type") == "orderbook":
        print(f"Orderbook update for {data.get('market')}")
    elif data.get("type") == "trade":
        print(f"Trade: {data.get('market')} @ {data.get('price')}")

def on_connect():
    print("Connected to Kalshi WebSocket")

def on_disconnect():
    print("Disconnected from Kalshi WebSocket")

def on_error(error):
    print(f"WebSocket error: {error}")

async def main():
    # Create client with event handlers
    client = KalshiWebSocketClient(
        market_tickers=["KXBTC15M-EXAMPLE", "KXETH15M-EXAMPLE"],
        message_handler=handle_market_data
    )
    
    # Set event callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_error = on_error
    
    # Start client
    await client.start()
    
    # Run for 1 hour
    await asyncio.sleep(3600)
    
    # Stop client
    await client.stop()

if __name__ == "__main__":
    asyncio.run(main())
"""

# Thread-based wrapper for non-async environments
class KalshiWebSocketThread:
    """Thread-based wrapper for Kalshi WebSocket client."""
    
    def __init__(self, market_tickers: List[str], 
                 message_handler: Callable[[Dict[str, Any]], None] = None):
        self.client = KalshiWebSocketClient(market_tickers, message_handler)
        self._thread = None
        self._loop = None
        
    def _run_async_client(self):
        """Run async client in new thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            self._loop.run_until_complete(self.client.start())
        except Exception as e:
            logger.exception(f"WebSocket thread error: {e}")
        finally:
            self._loop.close()
    
    def start(self):
        """Start WebSocket client in background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("WebSocket thread already running")
            return
        
        self._thread = threading.Thread(target=self._run_async_thread, daemon=True)
        self._thread.start()
        logger.info("Kalshi WebSocket thread started")
    
    def stop(self):
        """Stop WebSocket client."""
        if not self._thread or not self._thread.is_alive():
            return
        
        # Schedule stop on the event loop
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.client.stop(), self._loop)
        
        # Wait for thread to finish
        self._thread.join(timeout=5)
        logger.info("Kalshi WebSocket thread stopped")
    
    def is_running(self) -> bool:
        """Check if WebSocket thread is running."""
        return self._thread and self._thread.is_alive()

# Example thread usage:
"""
# In synchronous code:
ws_thread = KalshiWebSocketThread(
    market_tickers=["KXBTC15M-EXAMPLE"],
    message_handler=handle_market_data
)

ws_thread.start()

# Run for some time
time.sleep(3600)

ws_thread.stop()
"""
