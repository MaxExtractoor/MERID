"""
Background WebSocket Service for Kalshi Market Data

Provides persistent WebSocket connections with automatic startup,
reconnection, and market data distribution to all consumers.
"""

import asyncio
import threading
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from pathlib import Path

from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from merid.event_venues.kalshi.orderbook import LocalOrderbook
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MarketSubscription:
    """Track market subscription state"""
    ticker: str
    subscribers: Set[str]  # Connection IDs
    orderbook: LocalOrderbook
    last_update: float


class KalshiWebSocketService:
    """
    Background service managing Kalshi WebSocket connections and market data.
    
    Features:
    - Automatic startup on service initialization
    - Persistent connections with reconnection logic
    - Market subscription management
    - Orderbook state maintenance
    - Event distribution to subscribers
    """
    
    def __init__(self, config: Optional[Any] = None):
        # Use unified config by default
        self.config = config or get_kalshi_config()
        self._ws: Optional[KalshiWebSocket] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        
        # Market subscriptions
        self._subscriptions: Dict[str, MarketSubscription] = {}
        self._subscribed_tickers: Set[str] = set()
        
        # Statistics
        self._messages_received = 0
        self._reconnect_count = 0
        self._start_time: Optional[float] = None
        
        # Event callbacks
        self._event_callbacks: List[callable] = []
        
    def add_event_callback(self, callback: callable) -> None:
        """Add callback for WebSocket events"""
        self._event_callbacks.append(callback)
        
    def remove_event_callback(self, callback: callable) -> None:
        """Remove event callback"""
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)
    
    def subscribe_market(self, ticker: str, connection_id: str = "default") -> bool:
        """
        Subscribe to market data for a ticker.
        
        Args:
            ticker: Market ticker symbol
            connection_id: Unique identifier for subscriber
            
        Returns:
            True if subscription successful, False if error
        """
        try:
            if ticker not in self._subscriptions:
                self._subscriptions[ticker] = MarketSubscription(
                    ticker=ticker,
                    subscribers=set(),
                    orderbook=LocalOrderbook(ticker),
                    last_update=0.0
                )
            
            self._subscriptions[ticker].subscribers.add(connection_id)
            logger.info(f"Subscribed {connection_id} to {ticker}")
            
            # If WebSocket is running, subscribe immediately
            if self._ws and self._running:
                asyncio.run_coroutine_threadsafe(
                    self._subscribe_ticker(ticker), 
                    self._loop
                )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to subscribe to {ticker}: {e}")
            return False
    
    def unsubscribe_market(self, ticker: str, connection_id: str = "default") -> bool:
        """Unsubscribe from market data"""
        try:
            if ticker in self._subscriptions:
                self._subscriptions[ticker].subscribers.discard(connection_id)
                
                # Remove subscription if no subscribers left
                if not self._subscriptions[ticker].subscribers:
                    del self._subscriptions[ticker]
                    logger.info(f"Removed subscription for {ticker}")
                    
                    # Unsubscribe from WebSocket if running
                    if self._ws and self._running:
                        asyncio.run_coroutine_threadsafe(
                            self._unsubscribe_ticker(ticker),
                            self._loop
                        )
                return True
                
        except Exception as e:
            logger.error(f"Failed to unsubscribe from {ticker}: {e}")
            return False
    
    def get_orderbook(self, ticker: str) -> Optional[Dict]:
        """Get current orderbook for ticker"""
        if ticker in self._subscriptions:
            return self._subscriptions[ticker].orderbook.to_dict()
        return None
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return {
            "running": self._running,
            "connected": self._ws is not None,
            "subscribed_tickers": list(self._subscribed_tickers),
            "total_subscriptions": len(self._subscriptions),
            "messages_received": self._messages_received,
            "reconnect_count": self._reconnect_count,
            "uptime_seconds": (asyncio.get_event_loop().time() - self._start_time) if self._start_time else 0
        }
    
    async def _subscribe_ticker(self, ticker: str) -> None:
        """Subscribe to ticker via WebSocket"""
        try:
            if self._ws and ticker not in self._subscribed_tickers:
                await self._ws.subscribe_orderbook(ticker)
                self._subscribed_tickers.add(ticker)
                logger.info(f"WebSocket subscribed to {ticker}")
        except Exception as e:
            logger.error(f"Failed to subscribe {ticker} via WebSocket: {e}")
    
    async def _unsubscribe_ticker(self, ticker: str) -> None:
        """Unsubscribe from ticker via WebSocket"""
        try:
            if self._ws and ticker in self._subscribed_tickers:
                await self._ws.unsubscribe(ticker)
                self._subscribed_tickers.discard(ticker)
                logger.info(f"WebSocket unsubscribed from {ticker}")
        except Exception as e:
            logger.error(f"Failed to unsubscribe {ticker} via WebSocket: {e}")
    
    async def _handle_websocket_message(self, msg: Dict) -> None:
        """Handle incoming WebSocket message"""
        self._messages_received += 1
        
        try:
            msg_type = msg.get("type", "")
            ticker = msg.get("ticker", "")
            
            if msg_type == "orderbook_snapshot":
                if ticker in self._subscriptions:
                    self._subscriptions[ticker].orderbook.apply_snapshot(msg.get("data", {}))
                    self._subscriptions[ticker].last_update = asyncio.get_event_loop().time()
                    
            elif msg_type == "orderbook_delta":
                if ticker in self._subscriptions:
                    self._subscriptions[ticker].orderbook.apply_delta(msg.get("data", {}))
                    self._subscriptions[ticker].last_update = asyncio.get_event_loop().time()
                    
            elif msg_type == "trade":
                # Handle trade updates
                pass
                
            # Notify callbacks — support both sync and async callables
            for callback in self._event_callbacks:
                try:
                    result = callback(msg)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Event callback failed: {e}")
                    
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")
    
    async def _websocket_loop(self) -> None:
        """Main WebSocket event loop"""
        self._running = True
        self._start_time = asyncio.get_event_loop().time()

        try:
            # Initialize WebSocket
            self._ws = KalshiWebSocket(self.config)
            await asyncio.wait_for(self._ws.connect(), timeout=10.0)

            # Derive and set essential tickers for load shedding protection
            # This prevents queue overflow by protecting active position tickers
            # CRITICAL-FIX: Always set essential tickers; use fallback if derivation fails
            try:
                await self._ws.derive_essential_tickers_from_positions()
                logger.info("WebSocket essential tickers configured for load shedding")
            except Exception as _ete:
                logger.warning(f"Essential tickers derivation failed: {_ete} — using emergency fallback")
                # Emergency fallback: minimal BTC/ETH 15m set
                # HARDENING-FIX: Import from canonical asset list instead of hardcoding
                from merid.event_venues.kalshi.kalshi_crypto_15m_profile import get_all_active_tickers
                emergency_tickers = get_all_active_tickers()[:2]  # Use first 2 tickers (BTC, ETH)
                self._ws.set_essential_tickers(emergency_tickers)
                logger.critical(f"Using emergency essential tickers: {emergency_tickers}")

            # Subscribe to all currently subscribed tickers
            for ticker in self._subscriptions:
                await self._subscribe_ticker(ticker)

            logger.info("WebSocket service started successfully")
            
            # Main message loop
            await self._ws.listen(self._handle_websocket_message)
            
        except Exception as e:
            logger.error(f"WebSocket loop error: {e}")
            self._reconnect_count += 1
            
            # Reconnection logic
            while self._running:
                try:
                    logger.info("Attempting to reconnect WebSocket...")
                    await asyncio.sleep(5)  # Backoff
                    
                    self._ws = KalshiWebSocket(self.config)
                    await asyncio.wait_for(self._ws.connect(), timeout=10.0)
                    
                    # CRITICAL-FIX: Re-derive essential tickers on reconnect
                    try:
                        await self._ws.derive_essential_tickers_from_positions()
                    except Exception as _ete:
                        # HARDENING-FIX: Import from canonical asset list instead of hardcoding
                        from merid.event_venues.kalshi.kalshi_crypto_15m_profile import get_all_active_tickers
                        emergency_tickers = get_all_active_tickers()[:2]  # Use first 2 tickers (BTC, ETH)
                        self._ws.set_essential_tickers(emergency_tickers)
                        logger.warning(f"Using emergency essential tickers after reconnect: {emergency_tickers}")
                    
                    # Resubscribe to all tickers
                    for ticker in self._subscriptions:
                        await self._subscribe_ticker(ticker)
                    
                    logger.info("WebSocket reconnected successfully")
                    break
                    
                except Exception as reconnect_error:
                    logger.error(f"Reconnect failed: {reconnect_error}")
                    self._reconnect_count += 1
                    await asyncio.sleep(10)  # Longer backoff
    
    def _run_in_thread(self) -> None:
        """Run the event loop in a background thread"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        
        try:
            self._loop.run_until_complete(self._websocket_loop())
        except Exception as e:
            logger.error(f"WebSocket thread error: {e}")
        finally:
            self._loop.close()
    
    def start(self) -> None:
        """Start the WebSocket service in background thread"""
        if self._running:
            logger.warning("WebSocket service already running")
            return
        
        logger.info("Starting Kalshi WebSocket service...")
        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()
    
    async def stop_async(self) -> None:
        """Stop the WebSocket service (async version)"""
        self._running = False
        
        if self._ws:
            await self._ws.close()
            self._ws = None
        
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    def stop(self) -> None:
        """Stop the WebSocket service"""
        if not self._running:
            return
        
        logger.info("Stopping Kalshi WebSocket service...")
        
        if self._loop:
            asyncio.run_coroutine_threadsafe(self.stop_async(), self._loop)
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        
        self._running = False
        logger.info("WebSocket service stopped")


# Global service instance
_websocket_service: Optional[KalshiWebSocketService] = None
_service_lock = threading.Lock()


def get_websocket_service() -> KalshiWebSocketService:
    """Get singleton WebSocket service instance"""
    global _websocket_service
    
    if _websocket_service is None:
        with _service_lock:
            if _websocket_service is None:
                _websocket_service = KalshiWebSocketService()
                _websocket_service.start()
    
    return _websocket_service


def start_websocket_service() -> KalshiWebSocketService:
    """Start and return WebSocket service"""
    service = get_websocket_service()
    if not service._running:
        service.start()
    return service


def stop_websocket_service() -> None:
    """Stop WebSocket service"""
    global _websocket_service
    
    if _websocket_service is not None:
        _websocket_service.stop()
        _websocket_service = None
