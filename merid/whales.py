"""
MERID Whale Detection System

Real-time Solana SPL token whale monitoring with WebSocket broadcasting.
Integrates with PredictionMarketAggregator for unified market intelligence.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

import websockets
from websockets.exceptions import ConnectionClosed, InvalidHandshake, WebSocketException

if TYPE_CHECKING:
    from fastapi import WebSocket

# Import Sentry for error tracking
try:
    import sentry_sdk
    from sentry_sdk import start_transaction, start_span
except ImportError:
    sentry_sdk = None
    start_transaction = lambda *args, **kwargs: None
    start_span = lambda *args, **kwargs: None

from contextlib import nullcontext

logger = logging.getLogger("merid.whales")


def get_sentry_transaction():
    """Get a Sentry transaction context manager, falling back to nullcontext if Sentry is disabled."""
    try:
        if start_transaction is None:
            return nullcontext()
        test_result = start_transaction(op="test", name="test")
        if test_result is None:
            return nullcontext()
        return start_transaction(op="whale_detection", name="solana_whale_alert")
    except (ImportError, RuntimeError, TypeError):
        return nullcontext()


def get_sentry_span(op="parse", description="operation"):
    """Get a Sentry span context manager, falling back to nullcontext if Sentry is disabled."""
    try:
        if start_span is None:
            return nullcontext()
        test_result = start_span(op="test", description="test")
        if test_result is None:
            return nullcontext()
        return start_span(op=op, description=description)
    except (ImportError, RuntimeError, TypeError):
        return nullcontext()


def capture_sentry_exception(e: Exception) -> None:
    """Capture exception in Sentry if available, otherwise log it."""
    try:
        if sentry_sdk is not None:
            sentry_sdk.capture_exception(e)
        else:
            logger.exception("Solana whale listener error", exc_info=e)
    except (ImportError, RuntimeError):
        logger.exception("Solana whale listener error (Sentry unavailable)", exc_info=e)


@dataclass
class WhaleEvent:
    """Whale event data structure."""
    mint: str
    owner: str
    amount: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_type: str = "whale"
    threshold: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type,
            "mint": self.mint,
            "owner": self.owner,
            "amount": self.amount,
            "timestamp": self.timestamp.isoformat(),
            "threshold": self.threshold,
        }


@dataclass
class WhaleMonitorConfig:
    """Configuration for WhaleMonitor."""
    solana_ws_url: str = field(default_factory=lambda: os.getenv("SOLANA_WS_URL", "wss://api.mainnet-beta.solana.com"))
    mint_address: str = field(default_factory=lambda: os.getenv("WHALE_MINT_ADDRESS", "Base58MintPubkeyHere"))
    whale_threshold: float = field(default_factory=lambda: float(os.getenv("WHALE_THRESHOLD", "100000")))
    spl_token_program: str = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    
    # Backoff configuration
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1
    
    # Health monitoring
    health_check_interval_seconds: float = 30.0
    connection_timeout_seconds: float = 10.0
    max_reconnect_attempts: Optional[int] = None  # None = unlimited


class WhaleMonitor:
    """
    Encapsulated Solana whale monitoring with configurable backoff and health checks.
    
    Replaces global mutable state with instance-based management.
    """
    
    def __init__(self, config: Optional[WhaleMonitorConfig] = None) -> None:
        self.config = config or WhaleMonitorConfig()
        self._ws_clients: Set[WebSocket] = set()
        self._shutdown_event = asyncio.Event()
        self._reconnect_count = 0
        self._last_event_time: Optional[datetime] = None
        self._event_history: deque[WhaleEvent] = deque(maxlen=1000)
        self._current_backoff = self.config.initial_backoff_seconds
        self._listener_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._is_running = False
        
    @property
    def client_count(self) -> int:
        """Get current number of connected WebSocket clients."""
        return len(self._ws_clients)
    
    @property
    def is_running(self) -> bool:
        """Check if the monitor is currently running."""
        return self._is_running
    
    @property
    def last_event_time(self) -> Optional[datetime]:
        """Get timestamp of last whale event."""
        return self._last_event_time
    
    def add_client(self, websocket: WebSocket) -> None:
        """Add a WebSocket client to receive whale alerts."""
        self._ws_clients.add(websocket)
        logger.info(f"Added whale client. Total clients: {self.client_count}")
    
    def remove_client(self, websocket: WebSocket) -> None:
        """Remove a WebSocket client from whale alerts."""
        self._ws_clients.discard(websocket)
        logger.info(f"Removed whale client. Total clients: {self.client_count}")
    
    def get_recent_events(self, count: int = 100) -> list[WhaleEvent]:
        """Get recent whale events from history."""
        return list(self._event_history)[-count:]
    
    async def start(self, aggregator=None) -> None:
        """Start the whale monitor."""
        if self._is_running:
            logger.warning("WhaleMonitor already running")
            return
            
        self._is_running = True
        self._shutdown_event.clear()
        self._listener_task = asyncio.create_task(
            self._listener_loop(aggregator),
            name="whale_listener"
        )
        self._health_check_task = asyncio.create_task(
            self._health_check_loop(),
            name="whale_health_check"
        )
        logger.info(f"Started WhaleMonitor for mint: {self.config.mint_address}")
        logger.info(f"Whale threshold: {self.config.whale_threshold} tokens")
    
    async def stop(self) -> None:
        """Stop the whale monitor gracefully."""
        if not self._is_running:
            return
            
        logger.info("Stopping WhaleMonitor...")
        self._is_running = False
        self._shutdown_event.set()
        
        # Cancel tasks
        if self._listener_task:
            self._listener_task.cancel()
        if self._health_check_task:
            self._health_check_task.cancel()
            
        # Wait for cleanup
        tasks = [t for t in [self._listener_task, self._health_check_task] if t]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            
        # Clear clients
        self._ws_clients.clear()
        logger.info("WhaleMonitor stopped")
    
    async def _listener_loop(self, aggregator) -> None:
        """Main WebSocket listener loop with exponential backoff."""
        while not self._shutdown_event.is_set():
            try:
                await self._connect_and_listen(aggregator)
                # Reset backoff on successful connection
                self._current_backoff = self.config.initial_backoff_seconds
                self._reconnect_count = 0
            except asyncio.CancelledError:
                raise
            except WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
                capture_sentry_exception(e)
            except (RuntimeError, ConnectionError, ValueError) as e:
                logger.error(f"Unexpected error in listener loop: {e}")
                capture_sentry_exception(e)
            
            # Check if we should reconnect
            if self._shutdown_event.is_set():
                break
                
            if (self.config.max_reconnect_attempts is not None and 
                self._reconnect_count >= self.config.max_reconnect_attempts):
                logger.error("Max reconnect attempts reached, stopping monitor")
                break
            
            # Apply backoff with jitter
            await self._backoff()
    
    async def _backoff(self) -> None:
        """Apply exponential backoff with jitter."""
        jitter = self._current_backoff * self.config.jitter_factor * (2 * random.random() - 1)
        wait_time = self._current_backoff + jitter
        wait_time = min(wait_time, self.config.max_backoff_seconds)
        
        logger.info(f"Reconnecting in {wait_time:.1f}s (attempt {self._reconnect_count + 1})")
        await asyncio.wait_for(self._shutdown_event.wait(), timeout=wait_time)
        
        # Increase backoff for next time
        self._current_backoff = min(
            self._current_backoff * self.config.backoff_multiplier,
            self.config.max_backoff_seconds
        )
        self._reconnect_count += 1
    
    async def _connect_and_listen(self, aggregator) -> None:
        """Establish WebSocket connection and listen for events."""
        with get_sentry_transaction():
            async with websockets.connect(
                self.config.solana_ws_url,
                open_timeout=self.config.connection_timeout_seconds,
                close_timeout=self.config.connection_timeout_seconds,
            ) as ws:
                logger.info("Connected to Solana WebSocket")
                
                # Subscribe to SPL token program
                subscribe_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "programSubscribe",
                    "params": [
                        self.config.spl_token_program,
                        {
                            "encoding": "jsonParsed",
                            "commitment": "processed",
                            "filters": [
                                {"dataSize": 165},
                                {"memcmp": {"offset": 0, "bytes": self.config.mint_address}}
                            ]
                        }
                    ]
                }
                
                await ws.send(json.dumps(subscribe_msg))
                logger.info("Subscribed to SPL token program")
                
                async for raw in ws:
                    if self._shutdown_event.is_set():
                        break
                    await self._process_message(raw, aggregator)
    
    async def _process_message(self, raw: str, aggregator) -> None:
        """Process a single WebSocket message."""
        with get_sentry_span(op="parse", description="parse_token_update"):
            try:
                msg = json.loads(raw)
                
                # Extract account data
                value = msg.get("params", {}).get("result", {}).get("value")
                if not value:
                    return
                
                account_data = (
                    value.get("account", {})
                         .get("data", {})
                         .get("parsed", {})
                         .get("info", {})
                )
                
                amount = account_data.get("tokenAmount", {}).get("uiAmount")
                owner = account_data.get("owner")
                
                if amount is None or owner is None:
                    return
                
                # Check whale threshold
                if amount >= self.config.whale_threshold:
                    await self._handle_whale_event(owner, amount, aggregator)
                    
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode JSON message: {e}")
            except KeyError as e:
                logger.warning(f"Missing expected key in message: {e}")
            except (ValueError, TypeError, RuntimeError) as e:
                logger.error(f"Error processing whale message: {e}")
                capture_sentry_exception(e)
    
    async def _handle_whale_event(self, owner: str, amount: float, aggregator) -> None:
        """Handle detected whale event."""
        with get_sentry_span(op="broadcast", description="broadcast_whale"):
            whale_event = WhaleEvent(
                mint=self.config.mint_address,
                owner=owner,
                amount=amount,
                threshold=self.config.whale_threshold,
            )
            
            # Track event
            self._last_event_time = datetime.utcnow()
            self._event_history.append(whale_event)
            
            # Store in aggregator
            if aggregator and hasattr(aggregator, 'record_whale_event'):
                try:
                    aggregator.record_whale_event(whale_event.to_dict())
                except (AttributeError, TypeError, RuntimeError) as e:
                    logger.error(f"Failed to record whale event in aggregator: {e}")
            
            # Broadcast to clients
            await self._broadcast(whale_event.to_dict())
            
            logger.info(f"Whale detected: {amount} tokens from {owner[:8]}...")
    
    async def _broadcast(self, alert: Dict[str, Any]) -> None:
        """Broadcast whale alert to all connected WebSocket clients."""
        if not self._ws_clients:
            return
        
        dead: list[WebSocket] = []
        for ws in list(self._ws_clients):
            try:
                await ws.send_json(alert)
            except ConnectionClosed:
                dead.append(ws)
            except (RuntimeError, ConnectionError) as e:
                logger.warning(f"Failed to send whale alert to client: {e}")
                dead.append(ws)
        
        # Remove dead connections
        for ws in dead:
            self._ws_clients.discard(ws)
        
        if self._ws_clients:
            logger.info(f"Broadcasted whale alert to {len(self._ws_clients)} clients")
    
    async def _health_check_loop(self) -> None:
        """Periodic health check for connection and client status."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.config.health_check_interval_seconds
                )
            except asyncio.TimeoutError:
                # Health check interval passed
                if self._is_running:
                    self._log_health_status()
    
    def _log_health_status(self) -> None:
        """Log current health status of the monitor."""
        status = {
            "running": self._is_running,
            "clients": self.client_count,
            "reconnect_count": self._reconnect_count,
            "last_event": self._last_event_time.isoformat() if self._last_event_time else None,
            "event_history_size": len(self._event_history),
            "current_backoff": self._current_backoff,
        }
        logger.debug(f"WhaleMonitor health: {status}")


# Global instance for backward compatibility
_default_monitor: Optional[WhaleMonitor] = None


def get_whale_monitor(config: Optional[WhaleMonitorConfig] = None) -> WhaleMonitor:
    """Get or create the default WhaleMonitor instance."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = WhaleMonitor(config)
    return _default_monitor


# Legacy API for backward compatibility
ws_clients: Set[Any] = set()


async def solana_whale_listener(aggregator=None) -> None:
    """
    Legacy entry point - starts the default whale monitor.
    
    Args:
        aggregator: PredictionMarketAggregator instance for event storage
    """
    monitor = get_whale_monitor()
    await monitor.start(aggregator)
    # Keep running until cancelled
    try:
        while monitor.is_running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        await monitor.stop()
        raise


async def broadcast_whale(alert: Dict[str, Any]) -> None:
    """Legacy broadcast function - uses default monitor."""
    monitor = get_whale_monitor()
    await monitor._broadcast(alert)


def add_whale_client(websocket: WebSocket) -> None:
    """Legacy client addition - uses default monitor."""
    # Track in legacy set for compatibility
    ws_clients.add(websocket)
    # Also add to monitor
    monitor = get_whale_monitor()
    monitor.add_client(websocket)


def remove_whale_client(websocket: WebSocket) -> None:
    """Legacy client removal - uses default monitor."""
    ws_clients.discard(websocket)
    monitor = get_whale_monitor()
    monitor.remove_client(websocket)


def get_whale_client_count() -> int:
    """Legacy client count - uses default monitor."""
    monitor = get_whale_monitor()
    return monitor.client_count
