"""
Error Handling and Retries for Kalshi WebSocket

Reliable WebSocket client with automatic reconnection and exponential backoff.
"""

import asyncio
import json
import time
import logging
import websockets
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import threading
from contextlib import asynccontextmanager

import os

logger = logging.getLogger("kalshi_ws")

class WebSocketState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"

@dataclass
class WebSocketMessage:
    """WebSocket message data structure."""
    type: str
    data: Dict[str, Any]
    timestamp: float
    raw_message: str

class KalshiWebSocketReliable:
    """
    Reliable Kalshi WebSocket client with automatic reconnection and error handling.
    """
    
    def __init__(self,
                 ws_url: str = None,
                 api_key: Optional[str] = None,
                 api_secret: Optional[str] = None,
                 ping_interval: int = 20,
                 ping_timeout: int = 10,
                 max_reconnect_attempts: int = 10,
                 initial_backoff: float = 1.0,
                 max_backoff: float = 60.0):
        """
        Initialize reliable WebSocket client.
        
        Args:
            ws_url: WebSocket URL (defaults to KALSHI_WS_URL env var or demo endpoint)
            api_key: Kalshi API key
            api_secret: Kalshi API secret
            ping_interval: Ping interval in seconds
            ping_timeout: Ping timeout in seconds
            max_reconnect_attempts: Maximum reconnection attempts
            initial_backoff: Initial backoff delay in seconds
            max_backoff: Maximum backoff delay in seconds
        """
        self.ws_url = ws_url or os.getenv("KALSHI_WS_URL", "wss://demo-api.kalshi.co/trade-api/ws/v2")
        self.api_key = api_key
        self.api_secret = api_secret
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.max_reconnect_attempts = max_reconnect_attempts
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        
        # Connection state
        self.state = WebSocketState.DISCONNECTED
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.reconnect_count = 0
        self.last_error: Optional[Exception] = None
        
        # Message handling
        self.message_handlers: Dict[str, List[Callable]] = {}
        self.message_queue = asyncio.Queue(maxsize=4096)
        
        # Event callbacks
        self.on_connect: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_message: Optional[Callable] = None
        
        # Control flags
        self._should_stop = False
        self._reconnect_task: Optional[asyncio.Task] = None
        
        logger.info(f"Kalshi WebSocket client initialized: {ws_url}")
    
    def add_message_handler(self, message_type: str, handler: Callable) -> None:
        """
        Add message handler for specific message type.
        
        Args:
            message_type: Message type to handle
            handler: Handler function
        """
        if message_type not in self.message_handlers:
            self.message_handlers[message_type] = []
        
        self.message_handlers[message_type].append(handler)
        logger.debug(f"Added handler for message type: {message_type}")
    
    def remove_message_handler(self, message_type: str, handler: Callable) -> None:
        """
        Remove message handler for specific message type.
        
        Args:
            message_type: Message type to handle
            handler: Handler function to remove
        """
        if message_type in self.message_handlers:
            try:
                self.message_handlers[message_type].remove(handler)
                logger.debug(f"Removed handler for message type: {message_type}")
            except ValueError:
                pass
    
    async def connect(self) -> bool:
        """
        Establish WebSocket connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        if self.state in [WebSocketState.CONNECTING, WebSocketState.CONNECTED]:
            logger.warning("Already connected or connecting")
            return True
        
        self.state = WebSocketState.CONNECTING
        
        try:
            # Set connection options
            extra_headers = {}
            if self.api_key:
                extra_headers["Authorization"] = f"Bearer {self.api_key}"
            
            # Establish connection
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_timeout,
                extra_headers=extra_headers
            )
            
            self.state = WebSocketState.CONNECTED
            self.reconnect_count = 0
            
            logger.info("WebSocket connection established")
            
            # Call connect callback
            if self.on_connect:
                await self.on_connect()
            
            return True
            
        except Exception as e:
            self.state = WebSocketState.ERROR
            self.last_error = e
            logger.error(f"WebSocket connection failed: {e}")
            
            # Call error callback
            if self.on_error:
                await self.on_error(e)
            
            return False
    
    async def disconnect(self) -> None:
        """
        Close WebSocket connection gracefully.
        """
        self._should_stop = True
        
        if self.websocket:
            try:
                await self.websocket.close()
                logger.info("WebSocket connection closed gracefully")
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")
        
        self.state = WebSocketState.DISCONNECTED
        self.websocket = None
        
        # Call disconnect callback
        if self.on_disconnect:
            await self.on_disconnect()
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """
        Send message through WebSocket.
        
        Args:
            message: Message to send
        """
        if not self.websocket or self.state != WebSocketState.CONNECTED:
            raise ConnectionError("WebSocket not connected")
        
        try:
            message_str = json.dumps(message)
            await self.websocket.send(message_str)
            logger.debug(f"Message sent: {message.get('type', 'unknown')}")
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            raise
    
    async def subscribe_markets(self, market_tickers: List[str]) -> None:
        """
        Subscribe to market updates.
        
        Args:
            market_tickers: List of market tickers to subscribe to
        """
        subscription_message = {
            "type": "subscribe",
            "channels": [{
                "name": "orderbook",
                "markets": market_tickers
            }]
        }
        
        await self.send_message(subscription_message)
        logger.info(f"Subscribed to {len(market_tickers)} markets")
    
    async def subscribe_trades(self, market_tickers: List[str]) -> None:
        """
        Subscribe to trade updates.
        
        Args:
            market_tickers: List of market tickers to subscribe to
        """
        subscription_message = {
            "type": "subscribe",
            "channels": [{
                "name": "trades",
                "markets": market_tickers
            }]
        }
        
        await self.send_message(subscription_message)
        logger.info(f"Subscribed to trades for {len(market_tickers)} markets")
    
    async def handle_message(self, message_str: str) -> None:
        """
        Handle incoming WebSocket message.
        
        Args:
            message_str: Raw message string
        """
        try:
            data = json.loads(message_str)
            message_type = data.get("type", "unknown")
            
            # Create message object
            message = WebSocketMessage(
                type=message_type,
                data=data,
                timestamp=time.time(),
                raw_message=message_str
            )
            
            # Add to queue
            await self.message_queue.put(message)
            
            # Call general message callback
            if self.on_message:
                await self.on_message(message)
            
            # Call specific handlers
            if message_type in self.message_handlers:
                for handler in self.message_handlers[message_type]:
                    try:
                        await handler(message)
                    except Exception as e:
                        logger.error(f"Error in message handler for {message_type}: {e}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def message_listener(self) -> None:
        """
        Listen for incoming messages.
        """
        while not self._should_stop and self.websocket:
            try:
                async for message in self.websocket:
                    if self._should_stop:
                        break
                    await self.handle_message(message)
                    
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                break
            except Exception as e:
                logger.error(f"Error in message listener: {e}")
                break
    
    async def reconnect_with_backoff(self) -> bool:
        """
        Reconnect with exponential backoff.
        
        Returns:
            True if reconnection successful, False otherwise
        """
        if self.reconnect_count >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts ({self.max_reconnect_attempts}) reached")
            return False
        
        # Calculate backoff delay
        backoff = min(
            self.initial_backoff * (2 ** self.reconnect_count),
            self.max_backoff
        )
        
        self.reconnect_count += 1
        self.state = WebSocketState.RECONNECTING
        
        logger.info(f"Reconnecting in {backoff:.1f}s (attempt {self.reconnect_count}/{self.max_reconnect_attempts})")
        
        # Wait before reconnecting
        await asyncio.sleep(backoff)
        
        # Attempt reconnection
        return await self.connect()
    
    async def run(self, market_tickers: List[str]) -> None:
        """
        Run WebSocket client with automatic reconnection.
        
        Args:
            market_tickers: List of market tickers to subscribe to
        """
        self._should_stop = False
        
        while not self._should_stop:
            try:
                # Connect if not connected
                if self.state != WebSocketState.CONNECTED:
                    if not await self.connect():
                        if not await self.reconnect_with_backoff():
                            break
                        continue
                
                # Subscribe to markets
                await self.subscribe_markets(market_tickers)
                
                # Reset reconnect count on successful connection
                self.reconnect_count = 0
                
                # Listen for messages
                await self.message_listener()
                
            except Exception as e:
                self.last_error = e
                logger.exception(f"WebSocket error: {e}")
                
                # Call error callback
                if self.on_error:
                    await self.on_error(e)
                
                # Try to reconnect
                if not await self.reconnect_with_backoff():
                    break
        
        logger.info("WebSocket client stopped")
    
    async def get_message(self, timeout: Optional[float] = None) -> Optional[WebSocketMessage]:
        """
        Get message from queue.
        
        Args:
            timeout: Timeout in seconds
            
        Returns:
            WebSocket message or None if timeout
        """
        try:
            return await asyncio.wait_for(self.message_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
    
    def get_state(self) -> WebSocketState:
        """Get current connection state."""
        return self.state
    
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self.state == WebSocketState.CONNECTED

# Convenience function for simple usage
async def run_kalshi_ws(market_tickers: List[str],
                       api_key: Optional[str] = None,
                       api_secret: Optional[str] = None,
                       message_handler: Optional[Callable] = None) -> None:
    """
    Simple function to run Kalshi WebSocket with basic error handling.
    
    Args:
        market_tickers: List of market tickers to subscribe to
        api_key: Kalshi API key
        api_secret: Kalshi API secret
        message_handler: Optional message handler function
    """
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Create WebSocket client
    ws_client = KalshiWebSocketReliable(
        api_key=api_key,
        api_secret=api_secret
    )
    
    # Add message handler if provided
    if message_handler:
        ws_client.add_message_handler("orderbook", message_handler)
        ws_client.add_message_handler("trades", message_handler)
    
    # Define default message handler
    async def default_handler(message: WebSocketMessage):
        logger.info(f"Received {message.type}: {message.data}")
    
    if not message_handler:
        ws_client.add_message_handler("orderbook", default_handler)
        ws_client.add_message_handler("trades", default_handler)
    
    # Run WebSocket client
    await ws_client.run(market_tickers)

# Example usage:
"""
import asyncio
import logging

async def handle_orderbook_message(message: WebSocketMessage):
    \"\"\"Handle orderbook updates.\"\"\"
    if message.type == "orderbook":
        data = message.data
        market = data.get("market")
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        
        print(f"Orderbook update for {market}:")
        print(f"  Best bid: {bids[0] if bids else 'None'}")
        print(f"  Best ask: {asks[0] if asks else 'None'}")

async def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Create WebSocket client
    ws_client = KalshiWebSocketReliable(
        api_key="your_api_key",
        api_secret="your_api_secret"
    )
    
    # Add message handlers
    ws_client.add_message_handler("orderbook", handle_orderbook_message)
    
    # Define callbacks
    async def on_connect():
        print("Connected to Kalshi WebSocket")
    
    async def on_disconnect():
        print("Disconnected from Kalshi WebSocket")
    
    async def on_error(error):
        print(f"WebSocket error: {error}")
    
    # Set callbacks
    ws_client.on_connect = on_connect
    ws_client.on_disconnect = on_disconnect
    ws_client.on_error = on_error
    
    # Run WebSocket client
    await ws_client.run(["KXBTC15M-EXAMPLE", "KXETH15M-EXAMPLE"])

# Run the client
asyncio.run(main())

# Or use the simple function:
asyncio.run(run_kalshi_ws(
    ["KXBTC15M-EXAMPLE"],
    api_key="your_api_key",
    api_secret="your_api_secret"
))
"""
