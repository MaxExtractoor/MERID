"""
Kalshi WebSocket Bridge
Handles RSA-PSS authentication and WebSocket connection to Kalshi
Routes events to NATS event bus
"""

import asyncio
import json
from utils.logger import get_logger
import time
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import websockets
    from websockets.client import WebSocketClientProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    WebSocketClientProtocol = None

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

from merid_core.event_bus.nats_adapter import NATSEventBus

logger = get_logger(__name__)


class KalshiWebSocketBridge:
    """
    Kalshi WebSocket Bridge
    
    - Authenticates with Kalshi using RSA-PSS signatures
    - Maintains WebSocket connection
    - Subscribes to market data channels
    - Routes events to NATS topics
    
    Usage:
        bridge = KalshiWebSocketBridge(
            key_id="your_key_id",
            private_key_path="path/to/key.pem",
            env="demo"
        )
        await bridge.start()
    """
    
    def __init__(
        self,
        key_id: str,
        private_key_path: str,
        env: str = "demo",
        event_bus: Optional[NATSEventBus] = None
    ):
        if not WEBSOCKETS_AVAILABLE:
            raise ImportError("websockets not installed: pip install websockets")
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography not installed: pip install cryptography")
        
        self.key_id = key_id
        self.private_key_path = Path(private_key_path)
        self.env = env
        
        # WebSocket URLs
        if env == "demo":
            self.ws_url = "wss://demo-api.kalshi.co/trade-api/ws/v2"
        elif env == "prod":
            self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        else:
            raise ValueError(f"Invalid env: {env}. Must be 'demo' or 'prod'")
        
        self.event_bus = event_bus
        self.private_key: Optional[rsa.RSAPrivateKey] = None
        self.ws: Optional[WebSocketClientProtocol] = None
        self.markets: List[str] = []
        self.running = False
        
        # Statistics
        self.messages_received = 0
        self.messages_published = 0
        self.reconnect_count = 0
        self.last_message_time = 0
        
    def load_private_key(self) -> None:
        """Load RSA private key from PEM file"""
        if not self.private_key_path.exists():
            raise FileNotFoundError(f"Private key not found: {self.private_key_path}")
        
        with open(self.private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None
            )
        
        logger.info(f"Loaded private key from {self.private_key_path}")
    
    def sign_pss(self, text: str) -> str:
        """
        Sign text using RSA-PSS with SHA-256
        
        Args:
            text: Text to sign (timestamp + method + path)
        
        Returns:
            Base64-encoded signature
        """
        if self.private_key is None:
            raise RuntimeError("Private key not loaded")
        
        message = text.encode("utf-8")
        
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        
        return base64.b64encode(signature).decode("utf-8")
    
    def create_auth_headers(self) -> Dict[str, str]:
        """
        Create authentication headers for Kalshi WS connection
        
        Returns:
            Headers dict with KALSHI-ACCESS-* fields
        """
        # Timestamp in milliseconds
        timestamp = str(int(time.time() * 1000))
        
        # Method and path (no query string)
        method = "GET"
        path = "/trade-api/ws/v2"
        
        # Pre-hash string: timestamp + method + path
        msg_string = timestamp + method + path
        
        # Sign with RSA-PSS
        signature = self.sign_pss(msg_string)
        
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp
        }
    
    async def connect(self) -> None:
        """Establish WebSocket connection with authentication"""
        if self.private_key is None:
            self.load_private_key()
        
        headers = self.create_auth_headers()
        
        logger.info(f"Connecting to Kalshi WebSocket: {self.ws_url}")
        
        try:
            self.ws = await websockets.connect(
                self.ws_url,
                extra_headers=headers,
                ping_interval=20,  # Send ping every 20s
                ping_timeout=10    # Wait 10s for pong
            )
            
            logger.info("Connected to Kalshi WebSocket")
            
        except Exception as e:
            logger.error(f"Failed to connect to Kalshi: {e}")
            raise
    
    async def subscribe_to_markets(self) -> None:
        """Subscribe to orderbook updates for configured markets"""
        if not self.ws:
            raise RuntimeError("Not connected to WebSocket")
        
        for idx, ticker in enumerate(self.markets, start=1):
            subscribe_msg = {
                "id": idx,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_ticker": ticker
                }
            }
            
            await self.ws.send(json.dumps(subscribe_msg))
            logger.info(f"Subscribed to orderbook_delta for {ticker} (msg_id={idx})")
    
    def set_markets(self, markets: List[str]) -> None:
        """Set list of markets to subscribe to"""
        self.markets = markets
        logger.info(f"Configured {len(markets)} markets: {', '.join(markets)}")
    
    async def handle_message(self, raw: str) -> None:
        """
        Handle incoming WebSocket message
        
        Routes to appropriate NATS topic based on message type
        """
        self.messages_received += 1
        self.last_message_time = int(time.time() * 1000)
        
        try:
            msg = json.loads(raw)
            msg_type = msg.get("type")
            
            if not msg_type:
                logger.warning(f"Message without type: {raw[:100]}")
                return
            
            if self.event_bus is None:
                logger.warning("Event bus not configured, dropping message type=%s", msg_type)
                return
            
            # Route to NATS topics
            if msg_type == "orderbook_snapshot":
                await self.event_bus.publish("kalshi.orderbook_snapshot", msg)
                self.messages_published += 1
                
            elif msg_type == "orderbook_delta":
                await self.event_bus.publish("kalshi.orderbook_delta", msg)
                self.messages_published += 1
                
            elif msg_type == "trade":
                await self.event_bus.publish("kalshi.trade", msg)
                self.messages_published += 1
                
            elif msg_type == "ticker":
                await self.event_bus.publish("kalshi.ticker", msg)
                self.messages_published += 1
                
            elif msg_type == "fill":
                await self.event_bus.publish("kalshi.fill", msg)
                self.messages_published += 1
                
            elif msg_type == "error":
                logger.error(f"Kalshi error message: {msg}")
                await self.event_bus.publish("kalshi.error", msg)
                
            else:
                logger.debug(f"Unhandled message type: {msg_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
    
    async def run(self) -> None:
        """Main event loop - receive and route messages"""
        self.running = True
        
        while self.running:
            try:
                if not self.ws:
                    await self.connect()
                    await self.subscribe_to_markets()
                
                # Receive messages
                async for message in self.ws:
                    await self.handle_message(message)
                    
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e}")
                self.reconnect_count += 1
                
                if self.running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)
                    self.ws = None
                else:
                    break
                    
            except Exception as e:
                logger.error(f"Error in event loop: {e}", exc_info=True)
                if self.running:
                    await asyncio.sleep(5)
                else:
                    break
    
    async def start(self) -> None:
        """Start the bridge"""
        if not self.event_bus:
            raise RuntimeError("Event bus not configured")
        
        if not self.event_bus.is_connected():
            await self.event_bus.connect()
        
        await self.run()
    
    async def stop(self) -> None:
        """Stop the bridge gracefully"""
        self.running = False
        
        if self.ws:
            await self.ws.close()
            logger.info("Closed WebSocket connection")
    
    def stats(self) -> Dict[str, Any]:
        """Get bridge statistics"""
        return {
            "messages_received": self.messages_received,
            "messages_published": self.messages_published,
            "reconnect_count": self.reconnect_count,
            "last_message_time": self.last_message_time,
            "markets": self.markets,
            "connected": self.ws is not None and not self.ws.closed,
        }


# Singleton instance
_bridge_instance: Optional[KalshiWebSocketBridge] = None


def get_ws_bridge(
    key_id: str,
    private_key_path: str,
    env: str = "demo",
    event_bus: Optional[NATSEventBus] = None
) -> KalshiWebSocketBridge:
    """Get singleton bridge instance"""
    global _bridge_instance
    
    if _bridge_instance is None:
        _bridge_instance = KalshiWebSocketBridge(
            key_id=key_id,
            private_key_path=private_key_path,
            env=env,
            event_bus=event_bus
        )
    
    return _bridge_instance
