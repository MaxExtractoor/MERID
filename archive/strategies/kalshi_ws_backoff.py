"""
Advanced Retry Logic with Exponential Backoff for Kalshi WebSocket

Resilient WebSocket client with jitter, capped backoff, and specific closure code handling.
"""

import asyncio
import json
import logging
import random
import websockets
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import time
import threading
from contextlib import asynccontextmanager

import os

logger = logging.getLogger("kalshi_ws")

class WebSocketCloseCode(Enum):
    """WebSocket close codes for better error handling."""
    NORMAL_CLOSURE = 1000
    GOING_AWAY = 1001
    PROTOCOL_ERROR = 1002
    UNSUPPORTED_DATA = 1003
    NO_STATUS_RECEIVED = 1005
    ABNORMAL_CLOSURE = 1006
    INVALID_FRAME_PAYLOAD_DATA = 1007
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    MANDATORY_EXTENSION = 1010
    INTERNAL_SERVER_ERROR = 1011
    SERVICE_RESTART = 1012
    TRY_AGAIN_LATER = 1013
    TLS_HANDSHAKE = 1015

@dataclass
class BackoffConfig:
    """Configuration for exponential backoff with jitter."""
    base_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: bool = True
    max_retries: int = 10
    retryable_codes: List[int] = None
    
    def __post_init__(self):
        if self.retryable_codes is None:
            # Default retryable close codes
            self.retryable_codes = [
                WebSocketCloseCode.ABNORMAL_CLOSURE.value,
                WebSocketCloseCode.SERVICE_RESTART.value,
                WebSocketCloseCode.TRY_AGAIN_LATER.value,
                WebSocketCloseCode.INTERNAL_SERVER_ERROR.value
            ]

class KalshiWebSocketAdvanced:
    """
    Advanced Kalshi WebSocket client with sophisticated retry logic.
    """
    
    def __init__(self,
                 ws_url: str = None,
                 api_key: Optional[str] = None,
                 api_secret: Optional[str] = None,
                 backoff_config: Optional[BackoffConfig] = None,
                 ping_interval: int = 20,
                 ping_timeout: int = 10,
                 message_timeout: int = 30):
        """
        Initialize advanced WebSocket client.
        
        Args:
            ws_url: WebSocket URL (defaults to KALSHI_WS_URL env var or demo endpoint)
            api_key: Kalshi API key
            api_secret: Kalshi API secret
            backoff_config: Backoff configuration
            ping_interval: Ping interval in seconds
            ping_timeout: Ping timeout in seconds
            message_timeout: Message timeout in seconds
        """
        self.ws_url = ws_url or os.getenv("KALSHI_WS_URL", "wss://demo-api.kalshi.co/trade-api/ws/v2")
        self.api_key = api_key
        self.api_secret = api_secret
        self.backoff_config = backoff_config or BackoffConfig()
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.message_timeout = message_timeout
        
        # Connection state
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.is_connected = False
        self.reconnect_count = 0
        self.last_error: Optional[Exception] = None
        self.last_close_code: Optional[int] = None
        
        # Message handling
        self.message_handlers: Dict[str, List[Callable]] = {}
        self.message_queue = asyncio.Queue()
        
        # Statistics
        self.connection_attempts = 0
        self.successful_connections = 0
        self.total_messages_received = 0
        self.total_bytes_received = 0
        self.last_activity_time: Optional[float] = None
        
        # Control flags
        self._should_stop = False
        self._connection_lock = threading.Lock()
        
        logger.info(f"Advanced Kalshi WebSocket client initialized: {ws_url}")
    
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
    
    def calculate_backoff_delay(self, attempt: int) -> float:
        """
        Calculate exponential backoff delay with jitter.
        
        Args:
            attempt: Current attempt number
            
        Returns:
            Delay in seconds
        """
        # Exponential backoff
        delay = self.backoff_config.base_delay * (self.backoff_config.multiplier ** attempt)
        
        # Cap at maximum delay
        delay = min(delay, self.backoff_config.max_delay)
        
        # Add jitter if enabled
        if self.backoff_config.jitter:
            jitter = random.uniform(0, delay * 0.1)  # 10% jitter
            delay += jitter
        
        return delay
    
    def should_retry(self, error: Exception) -> bool:
        """
        Determine if we should retry based on the error.
        
        Args:
            error: Exception that occurred
            
        Returns:
            True if should retry, False otherwise
        """
        # Check if we've exceeded max retries
        if self.reconnect_count >= self.backoff_config.max_retries:
            logger.error(f"Max retries ({self.backoff_config.max_retries}) exceeded")
            return False
        
        # Check specific error types
        if isinstance(error, websockets.exceptions.ConnectionClosedError):
            close_code = getattr(error, 'code', None)
            if close_code in self.backoff_config.retryable_codes:
                logger.info(f"Retryable close code: {close_code}")
                return True
            else:
                logger.warning(f"Non-retryable close code: {close_code}")
                return False
        
        # Check for network errors
        if isinstance(error, (ConnectionError, OSError)):
            logger.info("Network error - will retry")
            return True
        
        # Check for timeout errors
        if "timeout" in str(error).lower():
            logger.info("Timeout error - will retry")
            return True
        
        # Default to retry for unknown errors
        logger.warning(f"Unknown error type: {type(error).__name__} - will retry")
        return True
    
    async def connect_with_retry(self) -> bool:
        """
        Connect with advanced retry logic.
        
        Returns:
            True if connection successful, False otherwise
        """
        with self._connection_lock:
            self.connection_attempts += 1
            
            while self.reconnect_count < self.backoff_config.max_retries:
                try:
                    logger.info(f"Connection attempt {self.reconnect_count + 1}/{self.backoff_config.max_retries}")
                    
                    # Set connection options
                    extra_headers = {}
                    if self.api_key:
                        extra_headers["Authorization"] = f"Bearer {self.api_key}"
                    
                    # Establish connection
                    self.websocket = await websockets.connect(
                        self.ws_url,
                        ping_interval=self.ping_interval,
                        ping_timeout=self.ping_timeout,
                        extra_headers=extra_headers,
                        close_timeout=self.message_timeout
                    )
                    
                    self.is_connected = True
                    self.successful_connections += 1
                    self.reconnect_count = 0  # Reset on success
                    self.last_activity_time = time.time()
                    
                    logger.info("WebSocket connection established successfully")
                    return True
                    
                except Exception as e:
                    self.last_error = e
                    self.reconnect_count += 1
                    
                    if not self.should_retry(e):
                        logger.error(f"Non-retryable error: {e}")
                        break
                    
                    # Calculate backoff delay
                    delay = self.calculate_backoff_delay(self.reconnect_count - 1)
                    
                    logger.warning(f"Connection failed: {e}. Retrying in {delay:.1f}s...")
                    
                    # Wait before retrying
                    await asyncio.sleep(delay)
            
            logger.error(f"Failed to connect after {self.reconnect_count} attempts")
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
        
        self.is_connected = False
        self.websocket = None
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """
        Send message through WebSocket with timeout.
        
        Args:
            message: Message to send
        """
        if not self.websocket or not self.is_connected:
            raise ConnectionError("WebSocket not connected")
        
        try:
            message_str = json.dumps(message)
            await asyncio.wait_for(
                self.websocket.send(message_str),
                timeout=self.message_timeout
            )
            logger.debug(f"Message sent: {message.get('type', 'unknown')}")
        except asyncio.TimeoutError:
            logger.error("Message send timeout")
            raise
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
    
    async def handle_message(self, message_str: str) -> None:
        """
        Handle incoming WebSocket message.
        
        Args:
            message_str: Raw message string
        """
        try:
            data = json.loads(message_str)
            message_type = data.get("type", "unknown")
            
            # Update statistics
            self.total_messages_received += 1
            self.total_bytes_received += len(message_str.encode('utf-8'))
            self.last_activity_time = time.time()
            
            # Call specific handlers
            if message_type in self.message_handlers:
                for handler in self.message_handlers[message_type]:
                    try:
                        await handler(data)
                    except Exception as e:
                        logger.error(f"Error in message handler for {message_type}: {e}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def message_listener(self) -> None:
        """
        Listen for incoming messages with timeout handling.
        """
        while not self._should_stop and self.websocket:
            try:
                async for message in self.websocket:
                    if self._should_stop:
                        break
                    await self.handle_message(message)
                    
            except websockets.exceptions.ConnectionClosed as e:
                self.last_close_code = getattr(e, 'code', None)
                logger.warning(f"WebSocket connection closed: {e.code}")
                break
            except Exception as e:
                logger.error(f"Error in message listener: {e}")
                break
    
    async def monitor_connection(self) -> None:
        """
        Monitor connection health and send periodic pings.
        """
        while not self._should_stop:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                if not self.is_connected or not self.websocket:
                    continue
                
                # Check last activity
                if self.last_activity_time:
                    idle_time = time.time() - self.last_activity_time
                    if idle_time > 60:  # No activity for 1 minute
                        logger.warning(f"Connection idle for {idle_time:.1f}s")
                
                # Log statistics
                logger.debug(f"Connection stats: {self.successful_connections} successful, "
                             f"{self.total_messages_received} messages received")
                
            except Exception as e:
                logger.error(f"Error in connection monitoring: {e}")
    
    async def run_with_advanced_backoff(self, market_tickers: List[str]) -> None:
        """
        Run WebSocket client with advanced backoff and monitoring.
        
        Args:
            market_tickers: List of market tickers to subscribe to
        """
        self._should_stop = False

        # Start monitoring task
        monitor_task = asyncio.create_task(self.monitor_connection(), name="kalshi-ws-backoff-monitor")
        monitor_task.add_done_callback(
            lambda t: logger.error(
                "kalshi-ws-backoff monitor task crashed: %s", t.exception()
            ) if not t.cancelled() and t.exception() else None
        )
        
        while not self._should_stop:
            try:
                # Connect with retry logic
                if not await self.connect_with_retry():
                    logger.error("Failed to establish connection")
                    break
                
                # Subscribe to markets
                await self.subscribe_markets(market_tickers)
                
                # Start message listener
                await self.message_listener()
                
            except Exception as e:
                self.last_error = e
                logger.exception(f"WebSocket error: {e}")
                
                # Wait before retrying
                delay = self.calculate_backoff_delay(self.reconnect_count)
                await asyncio.sleep(delay)
        
        # Clean up monitoring task
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        
        logger.info("WebSocket client stopped")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get connection statistics.
        
        Returns:
            Statistics dictionary
        """
        return {
            "connection_attempts": self.connection_attempts,
            "successful_connections": self.successful_connections,
            "reconnect_count": self.reconnect_count,
            "total_messages_received": self.total_messages_received,
            "total_bytes_received": self.total_bytes_received,
            "is_connected": self.is_connected,
            "last_activity_time": self.last_activity_time,
            "last_error": str(self.last_error) if self.last_error else None,
            "last_close_code": self.last_close_code
        }

# Convenience function for simple usage
async def run_kalshi_ws_advanced(market_tickers: List[str],
                               api_key: Optional[str] = None,
                               api_secret: Optional[str] = None,
                               backoff_config: Optional[BackoffConfig] = None) -> None:
    """
    Simple function to run Kalshi WebSocket with advanced retry logic.
    
    Args:
        market_tickers: List of market tickers to subscribe to
        api_key: Kalshi API key
        api_secret: Kalshi API secret
        backoff_config: Backoff configuration
    """
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Create WebSocket client
    ws_client = KalshiWebSocketAdvanced(
        api_key=api_key,
        api_secret=api_secret,
        backoff_config=backoff_config
    )
    
    # Define default message handler
    async def default_handler(data):
        logger.info(f"Received message: {data.get('type', 'unknown')}")
    
    ws_client.add_message_handler("orderbook", default_handler)
    ws_client.add_message_handler("trades", default_handler)
    
    # Run WebSocket client
    await ws_client.run_with_advanced_backoff(market_tickers)

# Example usage:
"""
import asyncio
import logging

async def handle_orderbook_message(data):
    \"\"\"Handle orderbook updates with advanced processing.\"\"\"
    if data.get("type") == "orderbook":
        market = data.get("market")
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        
        print(f"Orderbook update for {market}:")
        print(f"  Best bid: {bids[0] if bids else 'None'}")
        print(f"  Best ask: {asks[0] if asks else 'None'}")

async def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Create custom backoff configuration
    backoff_config = BackoffConfig(
        base_delay=0.5,
        max_delay=30.0,
        multiplier=1.5,
        jitter=True,
        max_retries=5
    )
    
    # Create WebSocket client
    ws_client = KalshiWebSocketAdvanced(
        api_key="your_api_key",
        api_secret="your_api_secret",
        backoff_config=backoff_config
    )
    
    # Add message handlers
    ws_client.add_message_handler("orderbook", handle_orderbook_message)
    
    # Define connection event handlers
    async def on_connect():
        print("Connected to Kalshi WebSocket")
    
    async def on_disconnect():
        print("Disconnected from Kalshi WebSocket")
    
    async def on_error(error):
        print(f"WebSocket error: {error}")
    
    # Set event handlers (if implemented)
    # ws_client.on_connect = on_connect
    # ws_client.on_disconnect = on_disconnect
    # ws_client.on_error = on_error
    
    # Run WebSocket client
    await ws_client.run_with_advanced_backoff(["KXBTC15M-EXAMPLE", "KXETH15M-EXAMPLE"])
    
    # Print statistics
    stats = ws_client.get_statistics()
    print(f"Connection statistics: {stats}")

# Run the client
asyncio.run(main())

# Or use the simple function:
asyncio.run(run_kalshi_ws_advanced(
    ["KXBTC15M-EXAMPLE"],
    api_key="your_api_key",
    api_secret="your_api_secret",
    backoff_config=BackoffConfig(max_retries=3)
))
"""
