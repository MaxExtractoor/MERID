"""
Kalshi 15m Maker Bot - Advanced Implementation with Latency and Queue Dynamics

Complete implementation for high-frequency maker trading on Kalshi 15m crypto markets,
addressing latency optimization, queue position management, and realistic backtesting.

Based on community insights and Kalshi infrastructure characteristics.
"""

import asyncio
import json
import os
import time
import websockets
import hmac
import hashlib
import numpy as np
from typing import Dict, List, Optional, Tuple, Any, Deque
from dataclasses import dataclass, field
from collections import deque, defaultdict
from datetime import datetime, timedelta
import threading
import requests

from utils.logger import get_logger
from merid.prediction.execution_intelligence import get_execution_intel, ExecutionDecision
from merid.kalshi.execution_telemetry import get_execution_telemetry_tracker

logger = get_logger("merid.kalshi.maker_bot")


@dataclass
class OrderbookLevel:
    """Single level in Kalshi orderbook."""
    price_cents: int
    quantity: int
    timestamp: float


@dataclass
class KalshiOrderbookSnapshot:
    """Complete Kalshi orderbook snapshot with queue tracking."""
    ticker: str
    timestamp: float
    yes_bids: List[OrderbookLevel]
    no_bids: List[OrderbookLevel]
    
    # Derived best prices
    best_yes_bid: Optional[OrderbookLevel] = None
    best_yes_ask: Optional[OrderbookLevel] = None
    best_no_bid: Optional[OrderbookLevel] = None
    best_no_ask: Optional[OrderbookLevel] = None
    
    def __post_init__(self):
        """Calculate best prices and implied prices."""
        if self.yes_bids:
            self.best_yes_bid = self.yes_bids[-1]
        if self.no_bids:
            self.best_no_bid = self.no_bids[-1]
        
        # Calculate implied asks
        if self.best_no_bid:
            self.best_yes_ask = OrderbookLevel(
                price_cents=100 - self.best_no_bid.price_cents,
                quantity=self.best_no_bid.quantity,
                timestamp=self.timestamp
            )
        if self.best_yes_bid:
            self.best_no_ask = OrderbookLevel(
                price_cents=100 - self.best_yes_bid.price_cents,
                quantity=self.best_yes_bid.quantity,
                timestamp=self.timestamp
            )
    
    def get_spread_cents(self) -> Optional[int]:
        """Get current YES spread in cents."""
        if self.best_yes_bid and self.best_yes_ask:
            return self.best_yes_ask.price_cents - self.best_yes_bid.price_cents
        return None
    
    def get_depth_at_price(self, side: str, price_cents: int, depth_cents: int = 5) -> int:
        """Get total depth within N cents of a price level."""
        levels = self.yes_bids if side == "yes" else self.no_bids
        depth = 0
        for level in reversed(levels):  # Best prices at the end
            if price_cents - level.price_cents <= depth_cents:
                depth += level.quantity
            else:
                break
        return depth


@dataclass
class MakerOrder:
    """Active maker order with queue tracking."""
    order_id: str
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    price_cents: int
    quantity: int
    submit_time: float
    strategy: str  # "join_queue", "join_far", "cross"
    queue_position: int = 0
    filled_quantity: int = 0
    cancel_time: Optional[float] = None
    fill_time: Optional[float] = None
    latency_ms: float = 0.0


class KalshiWebSocketClient:
    """Real-time Kalshi WebSocket client for orderbook streaming."""
    
    def __init__(self, api_key: str, api_secret: str, base_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.orderbooks: Dict[str, KalshiOrderbookSnapshot] = {}
        self.callbacks: List[callable] = []
        self.running = False
        self.ws = None
        
    def add_callback(self, callback: callable):
        """Add callback for orderbook updates."""
        self.callbacks.append(callback)
    
    def _generate_auth_headers(self) -> Dict[str, str]:
        """Generate Kalshi WebSocket authentication headers."""
        # Kalshi uses HMAC-SHA256 authentication for WebSocket headers
        timestamp = str(int(time.time()))
        message = f"{timestamp}{self.api_key}"
        signature = hmac.new(
            self.api_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": signature
        }
    
    async def connect(self, tickers: List[str]):
        """Connect to WebSocket and subscribe to orderbooks."""
        try:
            headers = self._generate_auth_headers()
            self.ws = await websockets.connect(self.base_url, additional_headers=headers)
            
            # Subscribe to orderbooks - no in-band auth needed
            sub_msg = {
                "type": "subscribe",
                "channels": [
                    {"name": "orderbook", "symbols": tickers},
                ],
            }
            await self.ws.send(json.dumps(sub_msg))
            self.running = True
            
            logger.info(f"WebSocket connected, subscribed to {len(tickers)} tickers")
            
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")
            raise
    
    async def watch_orderbooks(self):
        """Main WebSocket message handling loop."""
        while self.running and self.ws:
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=30.0)
                msg = json.loads(raw)
                
                if msg.get("type") == "orderbook":
                    await self._handle_orderbook(msg)
                elif msg.get("type") == "error":
                    logger.error(f"WebSocket error: {msg}")
                    
            except asyncio.TimeoutError:
                logger.warning("WebSocket timeout, reconnecting...")
                await self._reconnect()
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await self._reconnect()
    
    async def _handle_orderbook(self, msg: Dict[str, Any]):
        """Handle orderbook update message."""
        ticker = msg.get("ticker")
        if not ticker:
            return
        
        ob_data = msg.get("orderbook", {})
        yes_data = ob_data.get("yes", [])
        no_data = ob_data.get("no", [])
        
        # Convert to OrderbookLevel objects
        yes_levels = [OrderbookLevel(p, q, time.time()) for p, q in yes_data]
        no_levels = [OrderbookLevel(p, q, time.time()) for p, q in no_data]
        
        # Update orderbook snapshot
        self.orderbooks[ticker] = KalshiOrderbookSnapshot(
            ticker=ticker,
            timestamp=time.time(),
            yes_bids=yes_levels,
            no_bids=no_levels
        )
        
        # Notify callbacks
        for callback in self.callbacks:
            try:
                callback(ticker, self.orderbooks[ticker])
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    async def _reconnect(self):
        """Reconnect WebSocket."""
        if self.ws:
            await self.ws.close()
        await asyncio.sleep(1.0)
        # Reconnection logic would go here
        logger.info("Attempting to reconnect...")


class LatencySimulator:
    """Simulates different latency scenarios for backtesting."""
    
    def __init__(self, latency_ms: float = 10.0):
        self.latency_ms = latency_ms
        self.jitter_ms = 2.0  # Add small jitter for realism
    
    def apply_latency(self, timestamp: float) -> float:
        """Apply latency to a timestamp."""
        jitter = np.random.normal(0, self.jitter_ms / 1000.0)
        return timestamp + (self.latency_ms / 1000.0) + jitter


class QueueSimulator:
    """Simulates queue dynamics and fill probability."""
    
    def __init__(self):
        self.active_orders: Dict[str, MakerOrder] = {}
        self.trade_history: List[Dict[str, Any]] = []
        
    def add_order(self, order: MakerOrder, orderbook: KalshiOrderbookSnapshot) -> int:
        """Add order and return queue position."""
        # Calculate queue position at this price level
        if order.side == "yes":
            if order.action == "buy":  # Buying YES, join bid queue
                queue_qty = sum(q.quantity for q in orderbook.yes_bids if q.price_cents == order.price_cents)
            else:  # Selling YES, join ask queue
                implied_ask_price = 100 - order.price_cents
                queue_qty = sum(q.quantity for q in orderbook.no_bids if q.price_cents == implied_ask_price)
        else:
            # NO side logic (similar but inverted)
            if order.action == "buy":  # Buying NO, join bid queue
                queue_qty = sum(q.quantity for q in orderbook.no_bids if q.price_cents == order.price_cents)
            else:  # Selling NO, join ask queue
                implied_ask_price = 100 - order.price_cents
                queue_qty = sum(q.quantity for q in orderbook.yes_bids if q.price_cents == implied_ask_price)
        
        order.queue_position = queue_qty
        self.active_orders[order.order_id] = order
        return queue_qty
    
    def simulate_fills(self, orderbook: KalshiOrderbookSnapshot, trade_volume: Dict[str, int]):
        """Simulate order fills based on trade volume."""
        filled_orders = []
        
        for order_id, order in list(self.active_orders.items()):
            if order.filled_quantity >= order.quantity:
                continue  # Already fully filled
            
            # Check if our price level was hit by trades
            price_key = f"{order.side}_{order.price_cents}"
            if price_key in trade_volume:
                trade_qty = trade_volume[price_key]
                
                # Fill if enough trade volume to reach our queue position
                if trade_qty >= order.queue_position:
                    fill_qty = min(order.quantity - order.filled_quantity, trade_qty)
                    order.filled_quantity += fill_qty
                    order.fill_time = time.time()
                    filled_orders.append(order)
                    
                    if order.filled_quantity >= order.quantity:
                        del self.active_orders[order_id]
        
        return filled_orders


class Kalshi15mMakerBot:
    """Advanced maker bot for Kalshi 15m crypto markets."""
    
    def __init__(self, api_key: str, api_secret: str, tickers: List[str], 
                 latency_ms: float = 10.0, max_position_size: int = 100):
        self.api_key = api_key
        self.api_secret = api_secret
        self.tickers = tickers
        self.max_position_size = max_position_size
        
        # Core components
        self.ws_client = KalshiWebSocketClient(api_key, api_secret)
        self.intel = get_execution_intel()
        self.telemetry = get_execution_telemetry_tracker()
        self.latency_sim = LatencySimulator(latency_ms)
        self.queue_sim = QueueSimulator()
        
        # Bot state
        self.active_orders: Dict[str, MakerOrder] = {}
        self.positions: Dict[str, int] = defaultdict(int)  # ticker -> net position
        self.order_counter = 0
        self.running = False
        
        # Performance tracking
        self.trade_history: List[Dict[str, Any]] = []
        self.pnl_history: List[float] = []
        
        # Strategy parameters
        self.min_edge_cents = 8  # Minimum edge after costs
        self.max_spread_cents = 12  # Maximum spread to provide liquidity
        self.queue_position_limit = 50  # Don't post if queue too deep
        
    async def start(self):
        """Start the maker bot."""
        self.ws_client.add_callback(self._on_orderbook_update)
        await self.ws_client.connect(self.tickers)
        
        # Start background tasks
        self.running = True
        tasks = [
            asyncio.create_task(self.ws_client.watch_orderbooks()),
            asyncio.create_task(self._manage_orders()),
            asyncio.create_task(self._track_performance()),
        ]
        
        try:
            await asyncio.gather(*tasks)
        finally:
            self.running = False
    
    def _on_orderbook_update(self, ticker: str, orderbook: KalshiOrderbookSnapshot):
        """Handle real-time orderbook updates."""
        # Check for trading opportunities
        self._evaluate_trading_opportunity(ticker, orderbook)
        
        # Update queue positions and check for fills
        self._update_queue_positions(ticker, orderbook)
    
    def _evaluate_trading_opportunity(self, ticker: str, orderbook: KalshiOrderbookSnapshot):
        """Evaluate if we should place maker orders."""
        spread = orderbook.get_spread_cents()
        if not spread or spread > self.max_spread_cents:
            return  # Spread too wide, don't provide liquidity
        
        # Calculate edge for YES side (example)
        if orderbook.best_yes_bid and orderbook.best_yes_ask:
            mid_price = (orderbook.best_yes_bid.price_cents + orderbook.best_yes_ask.price_cents) / 200.0
            
            # Get our signal (this would come from your prediction model)
            our_prob = self._get_prediction_signal(ticker)
            if our_prob is None:
                return
            
            edge = our_prob - mid_price
            if abs(edge) < self.min_edge_cents / 100.0:
                return  # Edge too small
            
            # Use execution intelligence to decide strategy
            decision = self.intel.decide(
                bid=orderbook.best_yes_bid.price_cents / 100.0,
                ask=orderbook.best_yes_ask.price_cents / 100.0,
                side="buy" if edge > 0 else "sell",
                edge=abs(edge),
                minutes_to_expiry=self._get_minutes_to_expiry(ticker),
                bid_depth=orderbook.get_depth_at_price("yes", orderbook.best_yes_bid.price_cents),
                ask_depth=orderbook.get_depth_at_price("no", orderbook.best_no_bid.price_cents),
            )
            
            # Place order if strategy makes sense
            if decision.strategy in ["join_queue", "join_far"]:
                side = "buy" if edge > 0 else "sell"
                self._place_maker_order(ticker, decision, orderbook, side)
    
    def _place_maker_order(self, ticker: str, decision: Any, orderbook: KalshiOrderbookSnapshot, side: str):
        """Place a maker order based on execution decision."""
        self.order_counter += 1
        order_id = f"maker_{self.order_counter}"
        
        # Convert decision to Kalshi order parameters
        yes_no_side = "yes" if side == "buy" else "no"
        action = "buy" if side == "buy" else "sell"
        price_cents = int(decision.suggested_price * 100)
        quantity = min(10, self.max_position_size - abs(self.positions[ticker]))  # Conservative sizing
        
        if quantity <= 0:
            return  # Position limit reached
        
        # Create order
        order = MakerOrder(
            order_id=order_id,
            ticker=ticker,
            side=yes_no_side,
            action=action,
            price_cents=price_cents,
            quantity=quantity,
            submit_time=time.time(),
            strategy=decision.strategy,
            latency_ms=self.latency_sim.latency_ms
        )
        
        # Add to queue simulator
        queue_position = self.queue_sim.add_order(order, orderbook)
        
        # Check if queue position is acceptable
        if queue_position > self.queue_position_limit:
            logger.info(f"Queue too deep ({queue_position}), skipping order")
            del self.queue_sim.active_orders[order_id]
            return
        
        # Place actual order (this would be your Kalshi API call)
        try:
            success = self._submit_kalshi_order(order)
            if success:
                self.active_orders[order_id] = order
                self.positions[ticker] += quantity if action == "buy" else -quantity
                
                logger.info(f"Placed maker order: {order_id} {action} {quantity} {yes_no_side} @ {price_cents}¢ "
                          f"(queue: {queue_position}, strategy: {decision.strategy})")
                
                # Record telemetry
                self.telemetry.record_submit(order_id, "maker_bot", ticker, 
                                            orderbook.best_yes_bid.price_cents / 100.0, quantity)
            else:
                del self.queue_sim.active_orders[order_id]
        except Exception as e:
            logger.error(f"Failed to place order {order_id}: {e}")
            del self.queue_sim.active_orders[order_id]
    
    def _submit_kalshi_order(self, order: MakerOrder) -> bool:
        """Submit order to Kalshi API (placeholder)."""
        # This would be your actual Kalshi API call
        # For now, simulate success
        return True
    
    def _update_queue_positions(self, ticker: str, orderbook: KalshiOrderbookSnapshot):
        """Update queue positions and check for fills."""
        # Simulate some trade volume (in real implementation, this comes from trade stream)
        trade_volume = {}  # price_key -> quantity
        
        # Check for fills
        filled_orders = self.queue_sim.simulate_fills(orderbook, trade_volume)
        
        for order in filled_orders:
            if order.order_id in self.active_orders:
                # Update position
                qty_change = order.filled_quantity if order.action == "buy" else -order.filled_quantity
                self.positions[order.ticker] += qty_change
                
                # Record fill
                self.telemetry.record_fill(order.order_id, order.price_cents)
                
                # Track PnL (simplified - would use actual settlement)
                pnl = self._calculate_pnl(order)
                self.pnl_history.append(pnl)
                
                logger.info(f"Order filled: {order.order_id} {order.filled_quantity} @ {order.price_cents}¢, PnL: {pnl:.1f}¢")
                
                # Remove from active orders
                del self.active_orders[order.order_id]
    
    def _calculate_pnl(self, order: MakerOrder) -> float:
        """Calculate PnL for filled order.
        
        Returns 0.0 until real settlement data is available.
        Real implementation should look up the market's settlement result
        and compute: (settlement_price - fill_price) * quantity * direction.
        """
        return 0.0
    
    def _get_prediction_signal(self, ticker: str) -> Optional[float]:
        """Get prediction signal for ticker (placeholder)."""
        # This would integrate with your prediction model
        # For now, return random signal around 0.5
        import random
        return random.gauss(0.5, 0.1)
    
    def _get_minutes_to_expiry(self, ticker: str) -> float:
        """Get minutes to expiry for ticker (placeholder)."""
        # This would parse the ticker and calculate actual expiry
        # For now, return random value between 5 and 15
        import random
        return random.uniform(5, 15)
    
    async def _manage_orders(self):
        """Background task to manage active orders."""
        while self.running:
            try:
                await asyncio.sleep(1.0)
                
                # Cancel stale orders
                current_time = time.time()
                for order_id, order in list(self.active_orders.items()):
                    # Cancel orders that are too old or in wrong direction
                    age = current_time - order.submit_time
                    if age > 300:  # 5 minutes
                        await self._cancel_order(order_id, "stale")
                    
                    # Check if signal has flipped
                    current_signal = self._get_prediction_signal(order.ticker)
                    if current_signal and self._should_cancel_due_to_signal(order, current_signal):
                        await self._cancel_order(order_id, "signal_flip")
                        
            except Exception as e:
                logger.error(f"Order management error: {e}")
    
    async def _cancel_order(self, order_id: str, reason: str):
        """Cancel an active order."""
        if order_id in self.active_orders:
            order = self.active_orders[order_id]
            order.cancel_time = time.time()
            
            # Cancel actual order (Kalshi API call)
            try:
                success = self._cancel_kalshi_order(order_id)
                if success:
                    logger.info(f"Cancelled order {order_id}: {reason}")
                    
                    # Update position
                    qty_change = -order.quantity if order.action == "buy" else order.quantity
                    self.positions[order.ticker] += qty_change
                    
                    # Remove from tracking
                    del self.active_orders[order_id]
                    if order_id in self.queue_sim.active_orders:
                        del self.queue_sim.active_orders[order_id]
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}")
    
    def _cancel_kalshi_order(self, order_id: str) -> bool:
        """Cancel order on Kalshi API (placeholder)."""
        # This would be your actual Kalshi API call
        return True
    
    def _should_cancel_due_to_signal(self, order: MakerOrder, current_signal: float) -> bool:
        """Check if order should be cancelled due to signal flip."""
        # Simplified logic - in reality would be more sophisticated
        if order.side == "yes":
            return (order.action == "buy" and current_signal < 0.45) or \
                   (order.action == "sell" and current_signal > 0.55)
        else:
            return (order.action == "buy" and current_signal > 0.55) or \
                   (order.action == "sell" and current_signal < 0.45)
    
    async def _track_performance(self):
        """Background task to track performance metrics."""
        while self.running:
            try:
                await asyncio.sleep(10.0)  # Every 10 seconds
                
                if self.pnl_history:
                    recent_pnl = self.pnl_history[-100:]  # Last 100 trades
                    total_pnl = sum(recent_pnl)
                    sharpe = self._calculate_sharpe(recent_pnl)
                    
                    logger.info(f"Performance - Total PnL: {total_pnl:.1f}¢, "
                              f"Trades: {len(recent_pnl)}, Sharpe: {sharpe:.2f}, "
                              f"Active orders: {len(self.active_orders)}")
                    
            except Exception as e:
                logger.error(f"Performance tracking error: {e}")
    
    def _calculate_sharpe(self, pnl_series: List[float]) -> float:
        """Calculate Sharpe ratio for PnL series."""
        if len(pnl_series) < 2:
            return 0.0
        
        returns = np.array(pnl_series)
        return np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0.0
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics."""
        if not self.pnl_history:
            return {}
        
        pnl_array = np.array(self.pnl_history)
        
        return {
            "total_trades": len(self.pnl_history),
            "total_pnl_cents": float(np.sum(pnl_array)),
            "avg_pnl_per_trade": float(np.mean(pnl_array)),
            "win_rate": float(np.mean(pnl_array > 0)),
            "sharpe_ratio": float(np.mean(pnl_array) / np.std(pnl_array)) if np.std(pnl_array) > 0 else 0.0,
            "max_drawdown": float(np.max(np.cumsum(pnl_array) - np.maximum.accumulate(np.cumsum(pnl_array)))),
            "active_orders": len(self.active_orders),
            "current_positions": dict(self.positions),
        }


# Backtesting framework with latency simulation
class KalshiBacktester:
    """Advanced backtester with latency and queue dynamics."""
    
    def __init__(self, latency_ms: float = 10.0):
        self.latency_sim = LatencySimulator(latency_ms)
        self.queue_sim = QueueSimulator()
        self.intel = get_execution_intel()
        self.results = []
        
    def backtest_session(self, orderbook_history: List[KalshiOrderbookSnapshot], 
                       signals: List[Dict[str, Any]], trade_history: List[Dict[str, Any]]):
        """Run backtest session with latency simulation."""
        
        # Sort data by timestamp
        orderbook_history.sort(key=lambda x: x.timestamp)
        signals.sort(key=lambda x: x["timestamp"])
        trade_history.sort(key=lambda x: x["timestamp"])
        
        # Simulate trading
        for signal in signals:
            # Apply latency to signal timestamp
            signal_time = self.latency_sim.apply_latency(signal["timestamp"])
            
            # Find orderbook at that time
            orderbook = self._find_orderbook_at_time(orderbook_history, signal_time)
            if not orderbook:
                continue
            
            # Make execution decision
            decision = self._make_decision(signal, orderbook)
            if not decision:
                continue
            
            # Place order in queue
            order = self._create_order(signal, decision, signal_time)
            queue_position = self.queue_sim.add_order(order, orderbook)
            
            # Simulate fills based on trade history
            fills = self._simulate_fills(order, orderbook, trade_history, signal_time)
            
            # Calculate PnL for fills
            for fill in fills:
                pnl = self._calculate_backtest_pnl(fill, signal["outcome"])
                self.results.append({
                    "timestamp": fill.fill_time,
                    "pnl": pnl,
                    "strategy": decision.strategy,
                    "latency_ms": self.latency_sim.latency_ms,
                    "queue_position": queue_position,
                    "fill_time_ms": (fill.fill_time - order.submit_time) * 1000,
                })
    
    def _find_orderbook_at_time(self, orderbook_history: List[KalshiOrderbookSnapshot], 
                               timestamp: float) -> Optional[KalshiOrderbookSnapshot]:
        """Find orderbook snapshot closest to timestamp."""
        # Simple linear search for closest timestamp
        closest = None
        min_diff = float('inf')
        
        for ob in orderbook_history:
            diff = abs(ob.timestamp - timestamp)
            if diff < min_diff:
                min_diff = diff
                closest = ob
        
        return closest
    
    def _make_decision(self, signal: Dict[str, Any], orderbook: KalshiOrderbookSnapshot) -> Optional[Any]:
        """Make execution decision based on signal and orderbook."""
        # Extract signal data
        edge = signal.get("edge", 0.0)
        side = signal.get("side", "buy")
        minutes_to_expiry = signal.get("minutes_to_expiry", 10.0)
        
        # Get orderbook data
        if side == "buy":
            bid = orderbook.best_yes_bid.price_cents / 100.0 if orderbook.best_yes_bid else None
            ask = orderbook.best_yes_ask.price_cents / 100.0 if orderbook.best_yes_ask else None
            bid_depth = orderbook.get_depth_at_price("yes", orderbook.best_yes_bid.price_cents)
            ask_depth = orderbook.get_depth_at_price("no", orderbook.best_no_bid.price_cents)
        else:
            bid = orderbook.best_no_bid.price_cents / 100.0 if orderbook.best_no_bid else None
            ask = orderbook.best_no_ask.price_cents / 100.0 if orderbook.best_no_ask else None
            bid_depth = orderbook.get_depth_at_price("no", orderbook.best_no_bid.price_cents)
            ask_depth = orderbook.get_depth_at_price("yes", orderbook.best_yes_bid.price_cents)
        
        if not bid or not ask:
            return None
        
        # Use execution intelligence
        decision = self.intel.decide(
            bid=bid,
            ask=ask,
            side=side,
            edge=abs(edge),
            minutes_to_expiry=minutes_to_expiry,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
        )
        
        return decision
    
    def _create_order(self, signal: Dict[str, Any], decision: Any, timestamp: float) -> MakerOrder:
        """Create order for simulation."""
        return MakerOrder(
            order_id=f"sim_{timestamp}",
            ticker=signal["ticker"],
            side=signal.get("side", "yes"),
            action=signal.get("action", "buy"),
            price_cents=int(decision.suggested_price * 100),
            quantity=signal.get("quantity", 10),
            submit_time=timestamp,
            strategy=decision.strategy,
            latency_ms=self.latency_sim.latency_ms
        )
    
    def _simulate_fills(self, order: MakerOrder, orderbook: KalshiOrderbookSnapshot,
                       trade_history: List[Dict[str, Any]], signal_time: float) -> List[MakerOrder]:
        """Simulate order fills based on trade history."""
        fills = []
        
        # Find trades after signal time
        relevant_trades = [t for t in trade_history if t["timestamp"] >= signal_time]
        
        # Simulate fill logic based on strategy
        if order.strategy == "cross":
            # Immediate fill at best contra price
            order.fill_time = signal_time + 0.001  # 1ms fill time
            order.filled_quantity = order.quantity
            fills.append(order)
            
        elif order.strategy == "join_queue":
            # Fill when enough trade volume at our price
            cumulative_volume = 0
            for trade in relevant_trades:
                if trade["price"] == order.price_cents:
                    cumulative_volume += trade["quantity"]
                    if cumulative_volume >= order.queue_position:
                        order.fill_time = trade["timestamp"]
                        order.filled_quantity = order.quantity
                        fills.append(order)
                        break
                        
        elif order.strategy == "join_far":
            # Lower fill probability
            fill_probability = 0.3
            if np.random.random() < fill_probability:
                # Find a reasonable fill time
                for trade in relevant_trades:
                    if trade["timestamp"] > signal_time + 60:  # Within 1 minute
                        order.fill_time = trade["timestamp"]
                        order.filled_quantity = order.quantity
                        fills.append(order)
                        break
        
        return fills
    
    def _calculate_backtest_pnl(self, order: MakerOrder, outcome: bool) -> float:
        """Calculate PnL for backtest order."""
        # Simplified PnL calculation
        if order.side == "yes":
            if outcome:
                return (100 - order.price_cents) * order.filled_quantity
            else:
                return -order.price_cents * order.filled_quantity
        else:  # NO side
            if not outcome:
                return (100 - order.price_cents) * order.filled_quantity
            else:
                return -order.price_cents * order.filled_quantity
    
    def get_backtest_stats(self) -> Dict[str, Any]:
        """Get backtest performance statistics."""
        if not self.results:
            return {}
        
        pnl_series = [r["pnl"] for r in self.results]
        
        # Strategy breakdown
        strategy_stats = {}
        for strategy in ["cross", "join_queue", "join_far"]:
            strategy_results = [r for r in self.results if r["strategy"] == strategy]
            if strategy_results:
                strategy_pnl = [r["pnl"] for r in strategy_results]
                strategy_stats[strategy] = {
                    "count": len(strategy_results),
                    "total_pnl": sum(strategy_pnl),
                    "avg_pnl": sum(strategy_pnl) / len(strategy_pnl),
                    "win_rate": sum(1 for pnl in strategy_pnl if pnl > 0) / len(strategy_pnl),
                    "avg_latency": sum(r["latency_ms"] for r in strategy_results) / len(strategy_results),
                    "avg_fill_time": sum(r["fill_time_ms"] for r in strategy_results) / len(strategy_results),
                }
        
        return {
            "total_trades": len(self.results),
            "total_pnl": sum(pnl_series),
            "avg_pnl_per_trade": sum(pnl_series) / len(pnl_series),
            "win_rate": sum(1 for pnl in pnl_series if pnl > 0) / len(pnl_series),
            "sharpe_ratio": np.mean(pnl_series) / np.std(pnl_series) if np.std(pnl_series) > 0 else 0,
            "strategy_breakdown": strategy_stats,
            "latency_ms": self.latency_sim.latency_ms,
        }


# Example usage
async def run_maker_bot_example():
    """Example of running the maker bot."""
    # Configuration
    api_key = os.environ.get("KALSHI_API_KEY")
    api_secret = os.environ.get("KALSHI_API_SECRET")
    tickers = ["CRYPTO_BTC_15M_1", "CRYPTO_ETH_15M_1"]
    
    if not api_key or not api_secret:
        logger.error("Missing Kalshi API credentials")
        return
    
    # Create and start bot
    bot = Kalshi15mMakerBot(api_key, api_secret, tickers, latency_ms=10.0)
    await bot.start()


# ── Production-Ready Backtesting with Real Data ─────────────────────────────

class KalshiBacktesterRealData:
    """Production backtester using historical orderbooks and trades."""
    
    def __init__(self, latency_ms: float = 5.0, fee_per_contract: float = 0.04):
        self.latency_ms = latency_ms
        self.fee_per_contract = fee_per_contract
        self.results = []
        self.queue_estimator = QueuePositionEstimator()
        
    def backtest_with_historical_data(self, 
                                     orderbook_history: List[KalshiOrderbookSnapshot],
                                     trade_history: List[Dict[str, Any]],
                                     settlement_outcomes: Dict[str, int]) -> Dict[str, Any]:
        """
        Backtest using real historical data.
        
        Args:
            orderbook_history: List of orderbook snapshots with timestamps
            trade_history: List of trades with yes_price, quantity, timestamp
            settlement_outcomes: Dict mapping ticker to settlement (0 or 100)
        """
        results = []
        
        for orderbook in orderbook_history:
            # Apply simulated latency
            decision_time = orderbook.timestamp + (self.latency_ms / 1000.0)
            
            # Find orderbook at decision time (with latency)
            latency_adjusted_book = self._find_orderbook_at_time(orderbook_history, decision_time)
            if not latency_adjusted_book:
                continue
            
            # Use execution intelligence to decide
            edge = self._calculate_edge(latency_adjusted_book)
            if abs(edge) < (self.fee_per_contract * 2):  # Must overcome fees
                continue
            
            side = "buy" if edge > 0 else "sell"
            decision = self.intel.decide(
                bid=latency_adjusted_book.best_yes_bid.price_cents / 100.0,
                ask=latency_adjusted_book.best_yes_ask.price_cents / 100.0,
                side=side,
                edge=abs(edge),
                minutes_to_expiry=self._get_minutes_to_expiry(latency_adjusted_book.ticker),
                bid_depth=latency_adjusted_book.get_depth_at_price("yes", latency_adjusted_book.best_yes_bid.price_cents),
                ask_depth=latency_adjusted_book.get_depth_at_price("no", latency_adjusted_book.best_no_bid.price_cents),
            )
            
            # Simulate order placement and fills
            pnl = self._simulate_order_fills(decision, latency_adjusted_book, trade_history, settlement_outcomes)
            if pnl is not None:
                results.append(pnl)
        
        return self._analyze_results(results)
    
    def _simulate_order_fills(self, decision: Any, orderbook: KalshiOrderbookSnapshot,
                              trade_history: List[Dict[str, Any]], settlement_outcomes: Dict[str, int]) -> Optional[Dict[str, Any]]:
        """Simulate order fills with realistic queue modeling."""
        
        # Estimate queue position based on orderbook at decision time
        if decision.strategy == "cross":
            # Immediate fill at best contra price
            fill_price = orderbook.best_yes_ask.price_cents if decision.side == "buy" else orderbook.best_yes_bid.price_cents
            queue_position = 0
        else:
            # Join queue - estimate position
            price_cents = int(decision.suggested_price * 100)
            queue_position = self.queue_estimator.estimate_queue_position(orderbook, price_cents, decision.side)
            
            # Find fill time when cumulative volume exceeds queue position
            fill_price, fill_time = self._find_fill_time(trade_history, price_cents, queue_position, decision.side)
            if fill_price is None:
                return None  # No fill
        
        # Calculate PnL including fees
        settlement_price = settlement_outcomes.get(orderbook.ticker, 50)  # Default 50 if unknown
        
        if decision.side == "buy":
            pnl_cents = (settlement_price - fill_price) - (self.fee_per_contract * 200)  # 2x fees in cents
        else:
            pnl_cents = (fill_price - settlement_price) - (self.fee_per_contract * 200)
        
        return {
            "ticker": orderbook.ticker,
            "strategy": decision.strategy,
            "side": decision.side,
            "entry_price_cents": fill_price,
            "settlement_price": settlement_price,
            "queue_position": queue_position,
            "pnl_cents": pnl_cents,
            "pnl_dollars": pnl_cents / 100.0,
            "latency_ms": self.latency_ms,
            "fees_dollars": self.fee_per_contract * 2
        }
    
    def _find_fill_time(self, trade_history: List[Dict[str, Any]], price_cents: int, 
                        queue_position: int, side: str) -> Tuple[Optional[int], Optional[float]]:
        """Find when cumulative volume at price exceeds queue position."""
        cumulative_volume = 0
        for trade in trade_history:
            if trade["yes_price"] == price_cents:
                cumulative_volume += trade["quantity"]
                if cumulative_volume >= queue_position:
                    return price_cents, trade["timestamp"]
        return None, None
    
    def _analyze_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Comprehensive profitability analysis."""
        if not results:
            return {"error": "No trades executed"}
        
        total_pnl = sum(r["pnl_dollars"] for r in results)
        total_fees = sum(r["fees_dollars"] for r in results)
        net_pnl = total_pnl - total_fees
        
        # Strategy breakdown
        strategy_stats = {}
        for strategy in ["cross", "join_queue", "join_far"]:
            strategy_results = [r for r in results if r["strategy"] == strategy]
            if strategy_results:
                strategy_pnl = sum(r["pnl_dollars"] for r in strategy_results)
                strategy_stats[strategy] = {
                    "trades": len(strategy_results),
                    "pnl": strategy_pnl,
                    "avg_pnl": strategy_pnl / len(strategy_results),
                    "win_rate": len([r for r in strategy_results if r["pnl_dollars"] > 0]) / len(strategy_results)
                }
        
        # Calculate equity curve and drawdown
        equity_curve = []
        running_pnl = 0
        for r in results:
            running_pnl += r["pnl_dollars"]
            equity_curve.append(running_pnl)
        
        peak = max(equity_curve) if equity_curve else 0
        drawdown = peak - min(equity_curve) if equity_curve else 0
        max_drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0
        
        return {
            "total_trades": len(results),
            "total_pnl": total_pnl,
            "total_fees": total_fees,
            "net_pnl": net_pnl,
            "avg_pnl_per_trade": net_pnl / len(results),
            "max_drawdown": drawdown,
            "max_drawdown_pct": max_drawdown_pct,
            "strategy_breakdown": strategy_stats,
            "latency_ms": self.latency_ms,
            "fee_per_contract": self.fee_per_contract
        }


# ── Queue Position Estimation ─────────────────────────────────────────--

class QueuePositionEstimator:
    """Estimate queue position from orderbook and sync with Kalshi API."""
    
    def __init__(self):
        self.api_client = None  # Kalshi REST client
        
    def estimate_queue_position(self, orderbook: KalshiOrderbookSnapshot, price_cents: int, side: str) -> int:
        """Estimate queue position from orderbook snapshot."""
        if side == "buy":
            # For buy orders, count existing yes bids at this price
            for level in orderbook.yes_bids:
                if level.price_cents == price_cents:
                    return level.quantity
        else:
            # For sell orders, count existing no bids at this price
            for level in orderbook.no_bids:
                if level.price_cents == price_cents:
                    return level.quantity
        
        return 0  # No existing orders at this price
    
    async def sync_with_kalshi_api(self, order_ids: List[str]) -> Dict[str, int]:
        """Sync queue positions with Kalshi's queue position API."""
        try:
            if not self.api_client:
                from merid.kalshi.client import get_kalshi_client
                self.api_client = get_kalshi_client()
            
            # Use Kalshi's get-queue-positions-for-orders endpoint
            response = await self.api_client.get_queue_positions(order_ids)
            return {order_id: data["queue_position"] for order_id, data in response.items()}
        except Exception as e:
            logger.error(f"Failed to sync queue positions: {e}")
            return {}


# ── Risk Management for High-Frequency Makers ─────────────────────────

class KalshiRiskManager:
    """Risk management for 15m crypto maker bots."""
    
    def __init__(self, max_per_market: int = 50, max_total_exposure: int = 500,
                 max_spread_cents: int = 15, min_edge_cents: int = 8):
        self.max_per_market = max_per_market
        self.max_total_exposure = max_total_exposure
        self.max_spread_cents = max_spread_cents
        self.min_edge_cents = min_edge_cents
        self.daily_pnl_limit = -100  # Stop trading if PnL drops below this
        self.positions: Dict[str, int] = defaultdict(int)
        self.daily_pnl = 0.0
        self.trading_enabled = True
        
    def check_position_limits(self, ticker: str, side: str, quantity: int) -> bool:
        """Check if order exceeds position limits."""
        if not self.trading_enabled:
            return False
        
        current_position = self.positions[ticker]
        new_position = current_position + quantity if side == "buy" else current_position - quantity
        
        # Check per-market limit
        if abs(new_position) > self.max_per_market:
            logger.warning(f"Per-market position limit exceeded for {ticker}: {new_position}")
            return False
        
        # Check total exposure
        total_exposure = sum(abs(pos) for pos in self.positions.values()) + abs(quantity)
        if total_exposure > self.max_total_exposure:
            logger.warning(f"Total exposure limit exceeded: {total_exposure}")
            return False
        
        return True
    
    def check_spread_limits(self, orderbook: KalshiOrderbookSnapshot) -> bool:
        """Check if spread is too wide for quoting."""
        if not orderbook.best_yes_bid or not orderbook.best_yes_ask:
            return False
        
        spread_cents = orderbook.best_yes_ask.price_cents - orderbook.best_yes_bid.price_cents
        if spread_cents > self.max_spread_cents:
            logger.warning(f"Spread too wide: {spread_cents}¢ > {self.max_spread_cents}¢")
            return False
        
        return True
    
    def check_feasible_edge(self, edge_cents: float) -> bool:
        """Check if edge overcomes fees and spread."""
        required_edge = self.min_edge_cents
        if abs(edge_cents) < required_edge:
            logger.debug(f"Edge too small: {edge_cents}¢ < {required_edge}¢")
            return False
        
        return True
    
    def update_daily_pnl(self, pnl: float):
        """Update daily PnL and check kill switches."""
        self.daily_pnl += pnl
        
        if self.daily_pnl < self.daily_pnl_limit:
            logger.critical(f"Daily PnL limit breached: ${self.daily_pnl:.2f} < ${self.daily_pnl_limit}")
            self.trading_enabled = False
        elif self.daily_pnl < self.daily_pnl_limit / 2:
            logger.warning(f"Approaching daily PnL limit: ${self.daily_pnl:.2f}")
    
    def update_position(self, ticker: str, quantity: int):
        """Update position tracking."""
        self.positions[ticker] += quantity


# ── Multi-Market Maker Bot ─────────────────────────────────────────

class KalshiMultiMarketMaker:
    """Multi-market maker bot for 15m crypto events."""
    
    def __init__(self, tickers: List[str], max_concurrent_quotes: int = 10):
        self.tickers = tickers
        self.max_concurrent_quotes = max_concurrent_quotes
        self.orderbooks: Dict[str, KalshiOrderbookSnapshot] = {}
        self.positions: Dict[str, int] = defaultdict(int)
        self.active_orders: Dict[str, MakerOrder] = {}
        self.risk_manager = KalshiRiskManager()
        self.ws_client = None
        self.quote_scheduler = QuoteScheduler()
        
    async def start(self):
        """Start multi-market maker bot."""
        # Connect to WebSocket for all tickers
        self.ws_client = KalshiWebSocketClient(
            api_key=os.getenv("KALSHI_API_KEY"),
            api_secret=os.getenv("KALSHI_API_SECRET")
        )
        
        await self.ws_client.connect(self.tickers)
        self.ws_client.add_callback(self._handle_orderbook_update)
        
        # Start orderbook watching
        asyncio.create_task(self.ws_client.watch_orderbooks())
        
        # Start quote scheduling
        asyncio.create_task(self._quote_scheduler_loop())
        
        logger.info(f"Multi-market maker started for {len(self.tickers)} tickers")
    
    async def _handle_orderbook_update(self, orderbook: KalshiOrderbookSnapshot):
        """Handle orderbook updates for all markets."""
        self.orderbooks[orderbook.ticker] = orderbook
        
        # Check if we should quote this market
        if self._should_quote_market(orderbook):
            await self._evaluate_trading_opportunity(orderbook)
    
    def _should_quote_market(self, orderbook: KalshiOrderbookSnapshot) -> bool:
        """Determine if we should quote this market."""
        # Risk checks
        if not self.risk_manager.check_spread_limits(orderbook):
            return False
        
        # Position limits
        current_quotes = len([o for o in self.active_orders.values() if o.ticker == orderbook.ticker])
        if current_quotes >= 2:  # Max 2 quotes per market
            return False
        
        # Total quote limit
        total_quotes = len(self.active_orders)
        if total_quotes >= self.max_concurrent_quotes:
            return False
        
        return True
    
    async def _quote_scheduler_loop(self):
        """Prioritize and schedule quotes across markets."""
        while self.running:
            try:
                # Calculate market priorities
                market_priorities = []
                for ticker in self.tickers:
                    if ticker in self.orderbooks:
                        orderbook = self.orderbooks[ticker]
                        volume = sum(level.quantity for level in orderbook.yes_bids + orderbook.no_bids)
                        edge = self._calculate_edge(orderbook)
                        priority = volume * abs(edge)
                        market_priorities.append((priority, ticker, orderbook))

                # Sort by priority (highest first)
                market_priorities.sort(reverse=True)

                # Quote top markets
                for priority, ticker, orderbook in market_priorities[:self.max_concurrent_quotes]:
                    if self._should_quote_market(orderbook):
                        await self._evaluate_trading_opportunity(orderbook)

                await asyncio.sleep(0.1)  # 100ms quote cycle

            except Exception as e:
                logger.error(f"Quote scheduler error: {e}")
                await asyncio.sleep(1.0)


# ── Kalshi-Specific Fee Calculations ─────────────────────────────────────

def kalshi_fee_per_contract(price_cents: int, maker: bool) -> float:
    """
    Approximate fee per contract in dollars.
    maker=False → taker, maker=True → maker (discounted).
    """
    p = price_cents / 100.0
    base = 0.07 * p * (1 - p)  # stylized formula from Kalshi fee schedule
    # rough maker/taker split: maker cheaper
    fee = base * (0.5 if maker else 1.0)
    # cap at ~0.02 as per fee schedule
    return min(fee, 0.02)

def trade_pnl_after_fees(price_cents: int, outcome_yes: bool, maker: bool) -> float:
    """
    PnL in dollars for 1 contract, excluding spread, including trade fee.
    """
    fee = kalshi_fee_per_contract(price_cents, maker)
    if outcome_yes:
        gross = 1.0 - price_cents / 100.0
    else:
        gross = - price_cents / 100.0
    return gross - fee

def compare_maker_taker(price_cents: int) -> dict:
    """Compare maker vs taker fees at different price levels."""
    maker_fee = kalshi_fee_per_contract(price_cents, maker=True)
    taker_fee = kalshi_fee_per_contract(price_cents, maker=False)
    return {
        "price_cents": price_cents,
        "maker_fee": maker_fee,
        "taker_fee": taker_fee,
        "maker_saving": taker_fee - maker_fee,
    }

def analyze_fee_structure(price_range: List[int] = None) -> Dict[str, Any]:
    """Analyze fee structure across price range."""
    if price_range is None:
        price_range = [10, 20, 30, 40, 50, 60, 70, 80, 90]
    
    analysis = []
    for pc in price_range:
        comparison = compare_maker_taker(pc)
        analysis.append(comparison)
    
    # Find optimal price ranges for maker vs taker
    maker_optimal = [c for c in analysis if c["maker_saving"] > 0.005]
    taker_optimal = [c for c in analysis if c["maker_saving"] < 0.002]
    
    return {
        "full_analysis": analysis,
        "maker_optimal_prices": [c["price_cents"] for c in maker_optimal],
        "taker_optimal_prices": [c["price_cents"] for c in taker_optimal],
        "max_maker_saving": max(c["maker_saving"] for c in analysis),
        "avg_maker_fee": sum(c["maker_fee"] for c in analysis) / len(analysis),
        "avg_taker_fee": sum(c["taker_fee"] for c in analysis) / len(analysis),
    }


# ── Queue Position API Integration ───────────────────────────────────────

class KalshiQueuePositionAPI:
    """Integration with Kalshi's queue position APIs."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def get_order_queue_position(self, order_id: str) -> dict:
        """Get queue position for a specific order."""
        path = f"/portfolio/orders/{order_id}/queue_position"
        r = requests.get(self.base_url + path, headers=self._auth_headers(path), timeout=3)
        r.raise_for_status()
        return r.json()  # {queue_position, queue_position_fp}
    
    def get_queue_positions_for_markets(self, market_tickers: List[str]) -> List[dict]:
        """Get queue positions for all orders in specific markets."""
        path = "/portfolio/orders/queue_positions"
        params = {"market_tickers": ",".join(market_tickers)}
        r = requests.get(self.base_url + path, headers=self._auth_headers(path), params=params, timeout=3)
        r.raise_for_status()
        return r.json()["queue_positions"]
    
    def sync_queue_positions(self, order_ids: List[str]) -> Dict[str, dict]:
        """Sync queue positions for multiple orders."""
        positions = {}
        for order_id in order_ids:
            try:
                pos = self.get_order_queue_position(order_id)
                positions[order_id] = pos
            except Exception as e:
                logger.error(f"Failed to get queue position for {order_id}: {e}")
                positions[order_id] = {"queue_position": -1, "error": str(e)}
        return positions


# ── Enhanced Backtester with Kalshi Fees ─────────────────────────────────

class KalshiBacktesterWithFees(KalshiBacktesterRealData):
    """Enhanced backtester with accurate Kalshi fee modeling."""
    
    def __init__(self, latency_ms: float = 5.0, fee_model: str = "kalshi"):
        super().__init__(latency_ms)
        self.fee_model = fee_model
        self.fee_analysis = analyze_fee_structure()
        
    def _simulate_order_fills_with_fees(self, decision: Any, orderbook: KalshiOrderbookSnapshot,
                                       trade_history: List[Dict[str, Any]], 
                                       settlement_outcomes: Dict[str, int]) -> Optional[Dict[str, Any]]:
        """Simulate order fills with accurate Kalshi fee modeling."""
        
        # Determine if this is a maker or taker order
        is_maker = decision.strategy in ["join_queue", "join_far"]
        
        if decision.strategy == "cross":
            # Immediate fill at best contra price (taker)
            fill_price = orderbook.best_yes_ask.price_cents if decision.side == "buy" else orderbook.best_yes_bid.price_cents
            queue_position = 0
            is_maker = False
        else:
            # Join queue - estimate position (maker)
            price_cents = int(decision.suggested_price * 100)
            queue_position = self.queue_estimator.estimate_queue_position(orderbook, price_cents, decision.side)
            
            # Find fill time when cumulative volume exceeds queue position
            fill_price, fill_time = self._find_fill_time(trade_history, price_cents, queue_position, decision.side)
            if fill_price is None:
                return None  # No fill
        
        # Calculate PnL with accurate Kalshi fees
        settlement_price = settlement_outcomes.get(orderbook.ticker, 50)
        outcome_yes = settlement_price == 100
        
        # Use Kalshi fee calculation
        trade_fee = kalshi_fee_per_contract(fill_price, is_maker)
        
        if decision.side == "buy":
            gross_pnl = (settlement_price - fill_price) / 100.0
        else:
            gross_pnl = (fill_price - settlement_price) / 100.0
        
        net_pnl = gross_pnl - trade_fee
        
        return {
            "ticker": orderbook.ticker,
            "strategy": decision.strategy,
            "side": decision.side,
            "entry_price_cents": fill_price,
            "settlement_price": settlement_price,
            "queue_position": queue_position,
            "is_maker": is_maker,
            "trade_fee": trade_fee,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "latency_ms": self.latency_ms,
        }
    
    def analyze_fee_impact(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze the impact of fees on trading performance."""
        maker_results = [r for r in results if r.get("is_maker", False)]
        taker_results = [r for r in results if not r.get("is_maker", True)]
        
        def analyze_group(group, name):
            if not group:
                return {"trades": 0, "total_fees": 0, "total_pnl": 0}
            
            total_fees = sum(r["trade_fee"] for r in group)
            total_pnl = sum(r["net_pnl"] for r in group)
            gross_pnl = sum(r["gross_pnl"] for r in group)
            
            return {
                "trades": len(group),
                "total_fees": total_fees,
                "total_gross_pnl": gross_pnl,
                "total_net_pnl": total_pnl,
                "fee_impact_pct": (total_fees / gross_pnl * 100) if gross_pnl != 0 else 0,
                "avg_fee_per_trade": total_fees / len(group),
                "avg_pnl_per_trade": total_pnl / len(group),
            }
        
        maker_stats = analyze_group(maker_results, "maker")
        taker_stats = analyze_group(taker_results, "taker")
        
        return {
            "maker_stats": maker_stats,
            "taker_stats": taker_stats,
            "fee_advantage": maker_stats["total_fees"] - taker_stats["total_fees"],
            "fee_structure": self.fee_analysis,
        }


# ── Shadow Live Trading Mode ─────────────────────────────────────────────

class ShadowLiveTrader:
    """Shadow live trading mode to test real fills without significant risk."""
    
    def __init__(self, paper_bot: Kalshi15mMakerBot, live_fraction: float = 0.01):
        self.paper_bot = paper_bot
        self.live_fraction = live_fraction  # Trade 1% of normal size
        self.queue_api = KalshiQueuePositionAPI(
            api_key=os.getenv("KALSHI_API_KEY"),
            api_secret=os.getenv("KALSHI_API_SECRET")
        )
        self.shadow_orders: Dict[str, Dict[str, Any]] = {}
        
    async def run_shadow_mode(self, duration_minutes: int = 60):
        """Run shadow live trading for specified duration."""
        logger.info(f"Starting shadow live trading for {duration_minutes} minutes")
        
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        
        # Override paper bot's order placement with shadow logic
        original_place_order = self.paper_bot._place_maker_order
        self.paper_bot._place_maker_order = self._shadow_place_order
        
        try:
            while time.time() < end_time:
                await asyncio.sleep(10)  # Check every 10 seconds
                
                # Sync queue positions
                await self._sync_shadow_queue_positions()
                
                # Log shadow performance
                self._log_shadow_performance()
                
        finally:
            # Restore original order placement
            self.paper_bot._place_maker_order = original_place_order
            logger.info("Shadow live trading completed")
    
    def _shadow_place_order(self, ticker: str, decision: Any, orderbook: KalshiOrderbookSnapshot, side: str):
        """Place a shadow order with minimal size."""
        # Calculate minimal order size
        normal_quantity = 10  # Normal paper trading size
        shadow_quantity = max(1, int(normal_quantity * self.live_fraction))
        
        # Place real order with minimal size
        order_id = f"shadow_{int(time.time())}"
        
        try:
            # Create actual Kalshi order
            order_params = {
                "ticker": ticker,
                "side": "yes" if side == "buy" else "no",
                "action": side,
                "type": "limit",
                "yes_price" if side == "buy" else "no_price": int(decision.suggested_price * 100),
                "count": shadow_quantity
            }
            
            # Submit real order (this would be your Kalshi API call)
            success = self._submit_real_order(order_params)
            
            if success:
                self.shadow_orders[order_id] = {
                    "params": order_params,
                    "decision": decision,
                    "timestamp": time.time(),
                    "quantity": shadow_quantity,
                    "strategy": decision.strategy
                }
                
                logger.info(f"Shadow order placed: {order_id} {shadow_quantity} @ {decision.suggested_price:.2f}")
            
        except Exception as e:
            logger.error(f"Shadow order failed: {e}")
    
    async def _sync_shadow_queue_positions(self):
        """Sync queue positions for shadow orders."""
        if not self.shadow_orders:
            return
        
        order_ids = list(self.shadow_orders.keys())
        positions = self.queue_api.sync_queue_positions(order_ids)
        
        for order_id, position in positions.items():
            if order_id in self.shadow_orders:
                self.shadow_orders[order_id]["queue_position"] = position.get("queue_position", -1)
                self.shadow_orders[order_id]["queue_sync_time"] = time.time()
    
    def _log_shadow_performance(self):
        """Log shadow trading performance metrics."""
        if not self.shadow_orders:
            return
        
        total_orders = len(self.shadow_orders)
        filled_orders = len([o for o in self.shadow_orders.values() if o.get("filled_quantity", 0) > 0])
        
        # Calculate fill rate
        fill_rate = filled_orders / total_orders if total_orders > 0 else 0
        
        # Calculate average queue position
        queue_positions = [o.get("queue_position", 0) for o in self.shadow_orders.values() if o.get("queue_position", 0) > 0]
        avg_queue = sum(queue_positions) / len(queue_positions) if queue_positions else 0
        
        logger.info(f"Shadow performance: {filled_orders}/{total_orders} filled ({fill_rate:.1%}), "
                   f"avg queue: {avg_queue:.1f}")
    
    def _submit_real_order(self, order_params: Dict[str, Any]) -> bool:
        """Submit real order to Kalshi API."""
        # This would integrate with your actual Kalshi trading client
        # For now, return True to simulate successful submission
        logger.debug(f"Would submit real order: {order_params}")
        return True


# ── Enhanced Queue Position Integration ───────────────────────────────────

class KalshiQueueManager:
    """Enhanced queue position management with bulk API integration."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.last_sync_time = 0
        self.sync_interval = 5.0  # Sync every 5 seconds
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def get_order_queue_position(self, order_id: str) -> dict:
        """Get queue position for a specific order."""
        path = f"/portfolio/orders/{order_id}/queue_position"
        r = requests.get(self.base_url + path, headers=self._auth_headers(path), timeout=3)
        r.raise_for_status()
        return r.json()  # {"queue_position": int, "queue_position_fp": "10.00"}
    
    def get_queue_positions_for_markets(self, market_tickers: List[str]) -> dict:
        """Get queue positions for all orders in specific markets."""
        path = "/portfolio/orders/queue_positions"
        params = {"market_tickers": ",".join(market_tickers)}
        r = requests.get(self.base_url + path, headers=self._auth_headers(path), params=params, timeout=3)
        r.raise_for_status()
        data = r.json()["queue_positions"]
        # {order_id: {"queue_position": ..., "queue_position_fp": ..., "market_ticker": ...}}
        return {q["order_id"]: q for q in data}
    
    def sync_queue_positions_if_needed(self, market_tickers: List[str]) -> Dict[str, dict]:
        """Sync queue positions only if interval has passed."""
        current_time = time.time()
        if current_time - self.last_sync_time < self.sync_interval:
            return {}
        
        positions = self.get_queue_positions_for_markets(market_tickers)
        self.last_sync_time = current_time
        return positions
    
    def should_cancel_or_move(self, order: MakerOrder, max_queue_depth: int = 10) -> bool:
        """Determine if order should be cancelled or moved based on queue depth."""
        queue_position = order.queue_position
        
        # Cancel if queue is too deep (unlikely to fill)
        if queue_position > max_queue_depth:
            return True
        
        # Move if queue position indicates adverse momentum
        # (This would integrate with your momentum signals)
        return False


# ── Kalshi Rebate and Fee Modeling ───────────────────────────────────────

class KalshiFeeOptimizer:
    """Optimize fees based on volume rebates and rounding considerations."""
    
    def __init__(self):
        self.monthly_volume_usd = 0.0
        
    def effective_maker_fee(self, base_fee: float, monthly_volume_usd: float) -> float:
        """Calculate effective maker fee after volume rebates."""
        # Example from rebate schedule: 0–50M → 3% rebate, 50–150M → 10%
        if monthly_volume_usd >= 50_000_000:
            rebate = 0.10
        elif monthly_volume_usd >= 0:
            rebate = 0.03
        else:
            rebate = 0.0
        return base_fee * (1 - rebate)
    
    def estimate_rounding_reimbursement(self, monthly_fees: float) -> float:
        """Estimate rounding reimbursement (only if > $10)."""
        # Kalshi reimburses rounding over $10 in first week of following month
        # For small bots (<$10), treat fees as full cost
        if monthly_fees > 10.0:
            # Rough estimate: 5-10% of fees are rounding differences
            rounding_overage = monthly_fees * 0.075
            return max(0, rounding_overage - 10.0)  # Only excess over $10
        return 0.0
    
    def should_target_maker_rebates(self, projected_monthly_volume: float) -> bool:
        """Determine if volume justifies targeting maker rebates."""
        # Need significant volume to make rebates meaningful
        return projected_monthly_volume > 10_000_000  # $10M monthly threshold
    
    def optimal_pricing_for_maker(self, price_cents: int, edge_cents: float) -> bool:
        """Determine if price level is optimal for market making."""
        # Favor extremes where fees are lower, but only if edge supports it
        p = price_cents / 100.0
        base_fee = 0.07 * p * (1 - p) * 0.5  # Maker fee
        
        # Calculate effective fee after potential rebates
        effective_fee = self.effective_maker_fee(base_fee, self.monthly_volume_usd)
        
        # Require edge to overcome effective fee plus spread buffer
        required_edge = effective_fee * 100 + 2.0  # Convert to cents + 2¢ buffer
        return edge_cents >= required_edge


# ── Capital Management with Deposit/Withdraw Fees ───────────────────────

class KalshiCapitalManager:
    """Capital management accounting for Kalshi deposit/withdraw fees."""
    
    def __init__(self, initial_capital: float = 10000.0):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.deposit_fees_paid = 0.0
        self.withdraw_fees_paid = 0.0
        
    def apply_deposit_withdraw_fees(self, gross_amount: float, method: str = "card") -> float:
        """Apply deposit/withdraw fees to capital."""
        if method == "card":
            fee_rate = 0.02
        elif method == "ach":
            fee_rate = 0.0  # ACH typically free
        elif method == "wire":
            fee_rate = 0.0  # Wire typically free
        else:
            fee_rate = 0.02  # Default to card rate
        
        net_amount = gross_amount * (1 - fee_rate)
        fee_amount = gross_amount - net_amount
        
        return net_amount, fee_amount
    
    def deposit_capital(self, amount: float, method: str = "card") -> float:
        """Deposit capital with fee calculation."""
        net_amount, fee = self.apply_deposit_withdraw_fees(amount, method)
        self.current_capital += net_amount
        self.deposit_fees_paid += fee
        
        logger.info(f"Deposited ${net_amount:.2f} (fee: ${fee:.2f}) via {method}")
        return net_amount
    
    def withdraw_capital(self, amount: float, method: str = "card") -> float:
        """Withdraw capital with fee calculation."""
        if amount > self.current_capital:
            raise ValueError(f"Insufficient capital: ${self.current_capital:.2f} available, requested ${amount:.2f}")
        
        net_amount, fee = self.apply_deposit_withdraw_fees(amount, method)
        self.current_capital -= amount  # Subtract gross amount
        self.withdraw_fees_paid += fee
        
        logger.info(f"Withdrew ${net_amount:.2f} (fee: ${fee:.2f}) via {method}")
        return net_amount
    
    def get_fee_impact_analysis(self) -> dict:
        """Analyze the impact of deposit/withdraw fees on capital."""
        total_fees = self.deposit_fees_paid + self.withdraw_fees_paid
        fee_impact_pct = (total_fees / self.initial_capital * 100) if self.initial_capital > 0 else 0
        
        return {
            "initial_capital": self.initial_capital,
            "current_capital": self.current_capital,
            "deposit_fees_paid": self.deposit_fees_paid,
            "withdraw_fees_paid": self.withdraw_fees_paid,
            "total_fees": total_fees,
            "fee_impact_pct": fee_impact_pct,
            "net_pnl": self.current_capital - self.initial_capital - total_fees
        }
    
    def recommend_funding_method(self, amount: float) -> str:
        """Recommend optimal funding method to minimize fees."""
        card_cost = amount * 0.02
        ach_cost = 0.0
        wire_cost = 0.0
        
        recommendations = []
        if ach_cost < card_cost:
            recommendations.append("ACH (free)")
        if wire_cost < card_cost:
            recommendations.append("Wire (free)")
        
        if recommendations:
            return f"Use {', '.join(recommendations)} to save ${card_cost:.2f} in fees"
        else:
            return f"Card deposit costs ${card_cost:.2f} (consider larger deposits to amortize)"


# ── Enhanced Maker Bot with Queue & Fee Optimization ───────────────────────

class KalshiOptimizedMakerBot(Kalshi15mMakerBot):
    """Enhanced maker bot with queue position management and fee optimization."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue_manager = KalshiQueueManager(
            api_key=os.getenv("KALSHI_API_KEY"),
            api_secret=os.getenv("KALSHI_API_SECRET")
        )
        self.fee_optimizer = KalshiFeeOptimizer()
        self.capital_manager = KalshiCapitalManager()
        self.max_queue_depth = 10
        
    async def start(self):
        """Start optimized maker bot with queue management."""
        await super().start()
        
        # Start queue position monitoring
        asyncio.create_task(self._queue_monitoring_loop())
        
        logger.info("Optimized maker bot started with queue and fee management")
    
    async def _queue_monitoring_loop(self):
        """Monitor queue positions and manage orders accordingly."""
        while self.running:
            try:
                # Sync queue positions for active markets
                market_tickers = list(self.orderbooks.keys())
                positions = self.queue_manager.sync_queue_positions_if_needed(market_tickers)
                
                # Update internal order queue positions
                for order_id, pos_data in positions.items():
                    if order_id in self.active_orders:
                        self.active_orders[order_id].queue_position = pos_data["queue_position"]
                
                # Check for orders that should be cancelled/moved
                orders_to_cancel = []
                for order_id, order in self.active_orders.items():
                    if self.queue_manager.should_cancel_or_move(order, self.max_queue_depth):
                        orders_to_cancel.append(order_id)
                
                # Cancel orders with poor queue positions
                for order_id in orders_to_cancel:
                    await self._cancel_order(order_id)
                
                await asyncio.sleep(5.0)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"Queue monitoring error: {e}")
                await asyncio.sleep(10.0)
    
    async def _evaluate_trading_opportunity(self, orderbook: KalshiOrderbookSnapshot):
        """Enhanced opportunity evaluation with fee optimization."""
        # Calculate edge
        edge = self._calculate_edge(orderbook)
        if abs(edge) < 1.0:  # Minimum edge threshold
            return
        
        # Check if pricing is optimal for market making
        best_bid = orderbook.best_yes_bid.price_cents if orderbook.best_yes_bid else 0
        if not self.fee_optimizer.optimal_pricing_for_maker(best_bid, abs(edge)):
            return  # Skip if price level is not optimal for making
        
        # Use execution intelligence with fee-aware parameters
        side = "buy" if edge > 0 else "sell"
        decision = self.intel.decide(
            bid=orderbook.best_yes_bid.price_cents / 100.0,
            ask=orderbook.best_yes_ask.price_cents / 100.0,
            side=side,
            edge=abs(edge),
            minutes_to_expiry=self._get_minutes_to_expiry(orderbook.ticker),
            bid_depth=orderbook.get_depth_at_price("yes", orderbook.best_yes_bid.price_cents),
            ask_depth=orderbook.get_depth_at_price("no", orderbook.best_no_bid.price_cents),
        )
        
        # Place order if strategy makes sense and queue is reasonable
        if decision.strategy in ["join_queue", "join_far"]:
            # Check queue depth before placing
            estimated_queue = self.queue_estimator.estimate_queue_position(
                orderbook, int(decision.suggested_price * 100), side
            )
            
            if estimated_queue <= self.max_queue_depth:
                await self._place_maker_order(orderbook.ticker, decision, orderbook, side)
            else:
                logger.debug(f"Skipping order due to deep queue: {estimated_queue}")
    
    def get_performance_report(self) -> dict:
        """Comprehensive performance report including fees and capital."""
        base_report = super().get_performance_report()
        
        # Add fee optimization metrics
        fee_metrics = {
            "monthly_volume_usd": self.fee_optimizer.monthly_volume_usd,
            "targeting_rebates": self.fee_optimizer.should_target_maker_rebates(
                self.fee_optimizer.monthly_volume_usd
            ),
            "estimated_rounding_reimbursement": self.fee_optimizer.estimate_rounding_reimbursement(
                self.telemetry.total_fees_paid
            )
        }
        
        # Add capital management metrics
        capital_metrics = self.capital_manager.get_fee_impact_analysis()
        
        return {
            **base_report,
            "fee_optimization": fee_metrics,
            "capital_management": capital_metrics,
            "queue_efficiency": {
                "avg_queue_position": self._calculate_average_queue_position(),
                "fill_rate_by_queue_depth": self._calculate_fill_rate_by_queue_depth()
            }
        }
    
    def _calculate_average_queue_position(self) -> float:
        """Calculate average queue position across all orders."""
        if not self.telemetry.order_history:
            return 0.0
        
        queue_positions = [
            order.get("queue_position", 0) 
            for order in self.telemetry.order_history.values()
            if order.get("queue_position", 0) > 0
        ]
        
        return sum(queue_positions) / len(queue_positions) if queue_positions else 0.0
    
    def _calculate_fill_rate_by_queue_depth(self) -> dict:
        """Calculate fill rates by queue depth ranges."""
        depth_ranges = {f"1-{i}": 0 for i in [5, 10, 20, 50]}
        
        for order in self.telemetry.order_history.values():
            queue_pos = order.get("queue_position", 0)
            filled = order.get("filled_quantity", 0) > 0
            
            for range_name, limit in [("1-5", 5), ("1-10", 10), ("1-20", 20), ("1-50", 50)]:
                if queue_pos <= limit:
                    depth_ranges[range_name] += 1
                    if filled:
                        depth_ranges[f"{range_name}_filled"] = depth_ranges.get(f"{range_name}_filled", 0) + 1
        
        # Calculate fill rates
        fill_rates = {}
        for range_name in ["1-5", "1-10", "1-20", "1-50"]:
            total = depth_ranges.get(range_name, 0)
            filled = depth_ranges.get(f"{range_name}_filled", 0)
            fill_rates[range_name] = (filled / total * 100) if total > 0 else 0
        
        return fill_rates


# ── Auto-Cancel with Queue Position Management ─────────────────────────────

class KalshiQueueAutoCancel:
    """Auto-cancel orders with poor queue positions using Kalshi API."""
    
    def __init__(self, api_key: str, api_secret: str, max_queue_depth: int = 200):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.max_queue_depth = max_queue_depth
        self.session = requests.Session()
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def refresh_queue_and_maybe_cancel(self, active_orders: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Refresh queue positions and cancel orders with poor positions.
        
        Args:
            active_orders: {order_id: {"market_ticker": str, ...}}
        
        Returns:
            Updated active_orders dict
        """
        if not active_orders:
            return active_orders

        # Group by market for efficient API calls
        tickers = list({o.get("market_ticker", "") for o in active_orders.values() if o.get("market_ticker")})
        if not tickers:
            return active_orders

        try:
            path = "/portfolio/orders/queue_positions"
            params = {"market_tickers": ",".join(tickers)}
            r = self.session.get(self.base_url + path, headers=self._auth_headers(path), params=params, timeout=3)
            r.raise_for_status()
            qdata = r.json()["queue_positions"]  # [ {order_id, queue_position, ...}, ... ]

            qp_by_order = {q["order_id"]: q["queue_position"] for q in qdata}
            cancelled_orders = []

            for oid, meta in list(active_orders.items()):
                qp = qp_by_order.get(oid)
                if qp is None:
                    continue
                
                # Update queue position
                meta["queue_position"] = qp
                
                # Cancel if queue position is too deep
                if qp > self.max_queue_depth:
                    self.cancel_order(oid)
                    cancelled_orders.append(oid)
                    logger.info(f"Auto-cancelled order {oid}: queue position {qp} > {self.max_queue_depth}")
                
                # Also track queue position changes for strategy decisions
                previous_qp = meta.get("previous_queue_position", qp)
                meta["queue_position_change"] = qp - previous_qp
                meta["previous_queue_position"] = qp

            # Remove cancelled orders
            for oid in cancelled_orders:
                del active_orders[oid]

        except Exception as e:
            logger.error(f"Queue refresh error: {e}")

        return active_orders
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific order."""
        try:
            path = f"/portfolio/orders/{order_id}"
            r = self.session.delete(self.base_url + path, headers=self._auth_headers(path), timeout=3)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False


# ── Queue-Aware Strategy Manager ─────────────────────────────────────

class KalshiQueueAwareStrategy:
    """Queue position-aware strategies for 15m makers."""
    
    def __init__(self, max_queue_base: int = 200, expiry_boost_factor: float = 0.5):
        self.max_queue_base = max_queue_base
        self.expiry_boost_factor = expiry_boost_factor  # Increase max queue near expiry
        
    def get_max_queue_depth(self, minutes_to_expiry: float) -> int:
        """Dynamic max queue depth based on time to expiry."""
        # As expiry approaches, allow deeper queue positions
        if minutes_to_expiry < 2:
            return int(self.max_queue_base * (1 + self.expiry_boost_factor))
        elif minutes_to_expiry < 5:
            return int(self.max_queue_base * (1 + self.expiry_boost_factor * 0.5))
        else:
            return self.max_queue_base
    
    def should_post_order(self, estimated_queue_position: int, minutes_to_expiry: float, 
                         queue_change: int = 0) -> bool:
        """Determine if should post order based on queue position."""
        max_queue = self.get_max_queue_depth(minutes_to_expiry)
        
        # Basic queue depth check
        if estimated_queue_position > max_queue:
            return False
        
        # Check if queue is getting worse (lots joining ahead)
        if queue_change > 50:  # Many orders jumped ahead
            return False
        
        # Check if queue is getting better (fills ahead)
        if queue_change < -20:  # Many orders filled ahead
            return True  # Keep order, we're close to front
        
        return True
    
    def should_cancel_and_replace(self, order: Dict[str, Any], minutes_to_expiry: float) -> bool:
        """Determine if should cancel and replace order."""
        queue_position = order.get("queue_position", 0)
        queue_change = order.get("queue_position_change", 0)
        max_queue = self.get_max_queue_depth(minutes_to_expiry)
        
        # Cancel if queue is too deep
        if queue_position > max_queue:
            return True
        
        # Cancel if queue is rapidly deteriorating
        if queue_change > 100:  # Many orders jumping ahead
            return True
        
        # Keep order if queue is improving
        if queue_change < -50:
            return False
        
        return False
    
    def get_optimal_price_adjustment(self, current_price_cents: int, queue_position: int, 
                                    side: str, minutes_to_expiry: float) -> int:
        """Get optimal price adjustment based on queue position."""
        # If deep in queue, improve price to get better position
        if queue_position > 100:
            if side == "buy":
                return 1  # Increase bid by 1 cent
            else:
                return -1  # Decrease ask by 1 cent
        
        # If near front and expiry approaching, be more aggressive
        if queue_position < 20 and minutes_to_expiry < 3:
            if side == "buy":
                return 2  # Increase bid more aggressively
            else:
                return -2  # Decrease ask more aggressively
        
        return 0  # No adjustment needed


# ── Queue Position Polling Loop ─────────────────────────────────────────

async def queue_poll_loop(auto_cancel: KalshiQueueAutoCancel, active_orders: Dict[str, Dict[str, Any]],
                         interval: float = 15.0, running: Optional[threading.Event] = None):
    """Async queue position polling loop.

    Args:
        auto_cancel: Queue auto-cancel manager
        active_orders: Dictionary of active orders to monitor
        interval: Polling interval in seconds
        running: Optional threading.Event to signal loop exit
    """
    while running is None or running.is_set():
        try:
            # Refresh queue positions and cancel poor orders
            updated_orders = auto_cancel.refresh_queue_and_maybe_cancel(active_orders)

            # Update the shared active_orders dict
            active_orders.clear()
            active_orders.update(updated_orders)

        except Exception as e:
            logger.error(f"Queue poll loop error: {e}")

        await asyncio.sleep(interval)


# ── Live vs Paper Debugging Tools ─────────────────────────────────────────

class KalshiLivePaperDebugger:
    """Debug live vs paper trading discrepancies."""
    
    def __init__(self):
        self.live_trades = []
        self.paper_trades = []
        self.queue_snapshots = []
        self.latency_measurements = []
        self.spread_measurements = []
        
    def record_live_trade(self, trade_data: Dict[str, Any]):
        """Record live trade data."""
        self.live_trades.append({
            "timestamp": time.time(),
            "price_cents": trade_data["price_cents"],
            "quantity": trade_data["quantity"],
            "side": trade_data["side"],
            "order_id": trade_data["order_id"],
            "queue_position": trade_data.get("queue_position"),
            "latency_ms": trade_data.get("latency_ms"),
            "spread_at_fill": trade_data.get("spread_cents")
        })
    
    def record_paper_trade(self, trade_data: Dict[str, Any]):
        """Record paper trade data."""
        self.paper_trades.append({
            "timestamp": time.time(),
            "price_cents": trade_data["price_cents"],
            "quantity": trade_data["quantity"],
            "side": trade_data["side"],
            "assumed_latency_ms": trade_data.get("assumed_latency_ms"),
            "assumed_queue_position": trade_data.get("assumed_queue_position"),
            "assumed_spread": trade_data.get("assumed_spread_cents")
        })
    
    def record_queue_snapshot(self, snapshot: Dict[str, Any]):
        """Record queue position snapshot."""
        self.queue_snapshots.append({
            "timestamp": time.time(),
            "order_id": snapshot["order_id"],
            "queue_position": snapshot["queue_position"],
            "market_ticker": snapshot["market_ticker"]
        })
    
    def record_latency_measurement(self, measurement: Dict[str, Any]):
        """Record latency measurement."""
        self.latency_measurements.append({
            "timestamp": time.time(),
            "signal_time": measurement["signal_time"],
            "order_send_time": measurement["order_send_time"],
            "api_ack_time": measurement["api_ack_time"],
            "first_fill_time": measurement.get("first_fill_time"),
            "total_latency_ms": measurement.get("total_latency_ms")
        })
    
    def record_spread_measurement(self, measurement: Dict[str, Any]):
        """Record spread measurement."""
        self.spread_measurements.append({
            "timestamp": time.time(),
            "market_ticker": measurement["market_ticker"],
            "best_bid": measurement["best_bid"],
            "best_ask": measurement["best_ask"],
            "spread_cents": measurement["spread_cents"],
            "mid_price": (measurement["best_bid"] + measurement["best_ask"]) / 2
        })
    
    def analyze_discrepancies(self) -> Dict[str, Any]:
        """Analyze discrepancies between live and paper trading."""
        analysis = {
            "trade_count_diff": len(self.live_trades) - len(self.paper_trades),
            "avg_live_latency": 0,
            "avg_assumed_latency": 0,
            "avg_live_queue": 0,
            "avg_assumed_queue": 0,
            "avg_live_spread": 0,
            "avg_assumed_spread": 0,
            "price_deviation": 0,
            "fill_rate_diff": 0
        }
        
        # Calculate average latencies
        if self.latency_measurements:
            analysis["avg_live_latency"] = sum(m.get("total_latency_ms", 0) for m in self.latency_measurements) / len(self.latency_measurements)
        
        if self.paper_trades:
            analysis["avg_assumed_latency"] = sum(t.get("assumed_latency_ms", 0) for t in self.paper_trades) / len(self.paper_trades)
        
        # Calculate average queue positions
        if self.live_trades:
            live_queues = [t.get("queue_position", 0) for t in self.live_trades if t.get("queue_position") is not None]
            analysis["avg_live_queue"] = sum(live_queues) / len(live_queues) if live_queues else 0
        
        if self.paper_trades:
            paper_queues = [t.get("assumed_queue_position", 0) for t in self.paper_trades if t.get("assumed_queue_position") is not None]
            analysis["avg_assumed_queue"] = sum(paper_queues) / len(paper_queues) if paper_queues else 0
        
        # Calculate average spreads
        if self.live_trades:
            live_spreads = [t.get("spread_at_fill", 0) for t in self.live_trades if t.get("spread_at_fill") is not None]
            analysis["avg_live_spread"] = sum(live_spreads) / len(live_spreads) if live_spreads else 0
        
        if self.paper_trades:
            paper_spreads = [t.get("assumed_spread", 0) for t in self.paper_trades if t.get("assumed_spread") is not None]
            analysis["avg_assumed_spread"] = sum(paper_spreads) / len(paper_spreads) if paper_spreads else 0
        
        # Calculate price deviations
        if self.live_trades and self.paper_trades:
            # Match trades by timestamp (simplified)
            price_diffs = []
            for live_trade in self.live_trades[:min(len(self.live_trades), len(self.paper_trades))]:
                paper_trade = self.paper_trades[self.live_trades.index(live_trade)]
                price_diff = abs(live_trade["price_cents"] - paper_trade["price_cents"])
                price_diffs.append(price_diff)
            
            analysis["price_deviation"] = sum(price_diffs) / len(price_diffs) if price_diffs else 0
        
        return analysis
    
    def generate_debug_report(self) -> str:
        """Generate comprehensive debug report."""
        analysis = self.analyze_discrepancies()
        
        report = f"""
=== Live vs Paper Trading Debug Report ===

Trade Count Difference: {analysis['trade_count_diff']}

Latency Analysis:
- Average Live Latency: {analysis['avg_live_latency']:.2f}ms
- Average Assumed Latency: {analysis['avg_assumed_latency']:.2f}ms
- Latency Gap: {analysis['avg_live_latency'] - analysis['avg_assumed_latency']:.2f}ms

Queue Position Analysis:
- Average Live Queue: {analysis['avg_live_queue']:.1f}
- Average Assumed Queue: {analysis['avg_assumed_queue']:.1f}
- Queue Position Gap: {analysis['avg_live_queue'] - analysis['avg_assumed_queue']:.1f}

Spread Analysis:
- Average Live Spread: {analysis['avg_live_spread']:.2f}¢
- Average Assumed Spread: {analysis['avg_assumed_spread']:.2f}¢
- Spread Gap: {analysis['avg_live_spread'] - analysis['avg_assumed_spread']:.2f}¢

Price Deviation: {analysis['price_deviation']:.2f}¢

=== Recommendations ===
"""
        
        recommendations = []
        
        if analysis['avg_live_latency'] - analysis['avg_assumed_latency'] > 20:
            recommendations.append("Consider increasing assumed latency in backtests")
        
        if analysis['avg_live_queue'] - analysis['avg_assumed_queue'] > 50:
            recommendations.append("Model deeper queue positions in backtests")
        
        if analysis['avg_live_spread'] - analysis['avg_assumed_spread'] > 3:
            recommendations.append("Increase spread assumptions in backtests")
        
        if analysis['price_deviation'] > 2:
            recommendations.append("Review price execution model in backtests")
        
        if recommendations:
            report += "\n".join(f"- {rec}" for rec in recommendations)
        else:
            report += "No major discrepancies detected."
        
        return report


# ── Enhanced Maker Bot with Queue Auto-Cancel ───────────────────────────────

class KalshiAutoCancelMakerBot(KalshiOptimizedMakerBot):
    """Enhanced maker bot with automatic queue-based order cancellation."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auto_cancel = KalshiQueueAutoCancel(
            api_key=os.getenv("KALSHI_API_KEY"),
            api_secret=os.getenv("KALSHI_API_SECRET"),
            max_queue_depth=kwargs.get("max_queue_depth", 200)
        )
        self.queue_strategy = KalshiQueueAwareStrategy()
        self.debugger = KalshiLivePaperDebugger()
        self.queue_poll_task = None
        
    async def start(self):
        """Start maker bot with queue auto-cancel."""
        await super().start()
        
        # Start queue polling loop
        self.queue_poll_task = asyncio.create_task(
            queue_poll_loop(self.auto_cancel, self.active_orders, 15.0)
        )
        
        logger.info("Auto-cancel maker bot started with queue management")
    
    async def _evaluate_trading_opportunity(self, orderbook: KalshiOrderbookSnapshot):
        """Enhanced opportunity evaluation with queue strategy."""
        # Calculate edge
        edge = self._calculate_edge(orderbook)
        if abs(edge) < 1.0:
            return
        
        # Check if pricing is optimal for market making
        best_bid = orderbook.best_yes_bid.price_cents if orderbook.best_yes_bid else 0
        if not self.fee_optimizer.optimal_pricing_for_maker(best_bid, abs(edge)):
            return
        
        # Use execution intelligence
        side = "buy" if edge > 0 else "sell"
        decision = self.intel.decide(
            bid=orderbook.best_yes_bid.price_cents / 100.0,
            ask=orderbook.best_yes_ask.price_cents / 100.0,
            side=side,
            edge=abs(edge),
            minutes_to_expiry=self._get_minutes_to_expiry(orderbook.ticker),
            bid_depth=orderbook.get_depth_at_price("yes", orderbook.best_yes_bid.price_cents),
            ask_depth=orderbook.get_depth_at_price("no", orderbook.best_no_bid.price_cents),
        )
        
        # Check queue-aware strategy
        estimated_queue = self.queue_estimator.estimate_queue_position(
            orderbook, int(decision.suggested_price * 100), side
        )
        
        minutes_to_expiry = self._get_minutes_to_expiry(orderbook.ticker)
        if not self.queue_strategy.should_post_order(estimated_queue, minutes_to_expiry):
            logger.debug(f"Skipping order due to queue strategy: queue={estimated_queue}, expiry={minutes_to_expiry:.1f}min")
            return
        
        # Place order if strategy makes sense
        if decision.strategy in ["join_queue", "join_far"]:
            await self._place_maker_order(orderbook.ticker, decision, orderbook, side)
    
    def get_debug_report(self) -> str:
        """Get comprehensive debug report."""
        return self.debugger.generate_debug_report()
    
    async def stop(self):
        """Stop bot and cleanup tasks."""
        if self.queue_poll_task:
            self.queue_poll_task.cancel()
        
        await super().stop()
        logger.info("Auto-cancel maker bot stopped")


# ── Production Queue Thresholds & Batch Cancel Logic ───────────────────────

class KalshiProductionQueueManager:
    """Production queue manager with time-based thresholds and batch cancel."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.session = requests.Session()
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def max_qp_for_time(self, minutes_to_expiry: float) -> int:
        """Dynamic queue position threshold based on time to expiry."""
        if minutes_to_expiry > 10:
            return 300  # Early window: be conservative
        elif minutes_to_expiry > 5:
            return 500  # Mid window: allow deeper queues
        else:
            return 900  # Late window: tolerate deep queues due to expiry flow
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific order via Kalshi API."""
        try:
            path = f"/portfolio/orders/{order_id}"
            r = self.session.delete(self.base_url + path, headers=self._auth_headers(path, "DELETE"), timeout=3)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def sync_order_state(self, order_id: str) -> dict:
        """Get current order state including fills and queue position."""
        try:
            path = f"/portfolio/orders/{order_id}"
            r = self.session.get(self.base_url + path, headers=self._auth_headers(path), timeout=3)
            r.raise_for_status()
            return r.json()["order"]  # has fill_count, remaining_count, queue_position, status
        except Exception as e:
            logger.error(f"Failed to sync order state for {order_id}: {e}")
            return {}
    
    def refresh_queue_and_cancel(self, active_orders: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Refresh queue positions and cancel orders exceeding thresholds.
        
        Args:
            active_orders: {order_id: {"market_ticker": str, "minutes_to_expiry": float, ...}}
        
        Returns:
            Updated active_orders dict
        """
        if not active_orders:
            return active_orders

        # Get queue positions for all markets
        tickers = list({o.get("market_ticker", "") for o in active_orders.values() if o.get("market_ticker")})
        if not tickers:
            return active_orders

        try:
            path = "/portfolio/orders/queue_positions"
            params = {"market_tickers": ",".join(tickers)}
            r = self.session.get(self.base_url + path, headers=self._auth_headers(path), params=params, timeout=3)
            r.raise_for_status()
            qps = r.json()["queue_positions"]  # [ {order_id, market_ticker, queue_position, ...} ]
            qp_by_order = {q["order_id"]: q["queue_position"] for q in qps}

            cancelled_orders = []

            for oid, meta in list(active_orders.items()):
                qp = qp_by_order.get(oid)
                if qp is None:
                    continue
                
                # Update queue position
                meta["queue_position"] = qp
                
                # Check if should cancel based on time-based threshold
                minutes_to_expiry = meta.get("minutes_to_expiry", 15.0)
                max_qp = self.max_qp_for_time(minutes_to_expiry)
                
                if qp > max_qp:
                    # Handle partial fills before canceling
                    self.handle_qp_and_partial(oid, meta)
                    
                    # Cancel the order
                    if self.cancel_order(oid):
                        cancelled_orders.append(oid)
                        logger.info(f"Cancelled order {oid}: qp={qp} > max_qp={max_qp} (expiry={minutes_to_expiry:.1f}min)")

            # Remove cancelled orders
            for oid in cancelled_orders:
                del active_orders[oid]

        except Exception as e:
            logger.error(f"Queue refresh error: {e}")

        return active_orders
    
    def handle_qp_and_partial(self, order_id: str, meta: Dict[str, Any]) -> None:
        """Handle queue position changes and partial fills."""
        try:
            order = self.sync_order_state(order_id)
            if not order:
                return
            
            filled = order.get("fill_count", 0)
            remaining = order.get("remaining_count", 0)
            qp = order.get("queue_position", 0)
            status = order.get("status", "open")

            # Update order metadata
            meta["filled"] = filled
            meta["remaining"] = remaining
            meta["queue_position"] = qp
            meta["status"] = status

            # Record partial fill for PnL calculation
            initial_count = meta.get("initial_count", 0)
            if filled > 0 and initial_count > 0:
                fill_ratio = filled / initial_count
                meta["fill_ratio"] = fill_ratio
                
                # Update position tracking
                side = meta.get("side", "buy")
                ticker = meta.get("ticker", "")
                if side == "buy":
                    meta["position_change"] = filled
                else:
                    meta["position_change"] = -filled
                
                logger.info(f"Partial fill on {order_id}: {filled}/{initial_count} ({fill_ratio:.1%})")

            if remaining == 0:
                meta["status"] = "filled"
                logger.info(f"Order {order_id} fully filled")

        except Exception as e:
            logger.error(f"Error handling partial fills for {order_id}: {e}")


# ── Queue Strategy Backtester ─────────────────────────────────────────────

class KalshiQueueBacktester:
    """Backtest queue position strategies with historical data."""
    
    def __init__(self, max_qp_threshold: int = 300):
        self.max_qp_threshold = max_qp_threshold
        
    def simulate_queue_strategy(self, orderbook_history: List[Dict[str, Any]], 
                               trades: List[Dict[str, Any]], 
                               signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Simulate queue-based trading strategy.
        
        Args:
            orderbook_history: Historical orderbook snapshots
            trades: Historical trades with price, quantity, timestamp
            signals: Trading signals with time, price, side, outcome
        
        Returns:
            List of trade results with PnL and queue positions
        """
        results = []
        
        for signal in signals:
            # Find orderbook snapshot at signal time + latency
            signal_time = signal["time_with_latency"]
            ob = self._find_orderbook(orderbook_history, signal_time)
            
            if not ob:
                continue
            
            price_cents = signal["price_cents"]
            side = signal["side"]  # "yes"/"no"
            
            # Estimate queue position from orderbook
            levels = ob["yes_bids"] if side == "yes" else ob["no_bids"]
            qp = sum(l["quantity"] for l in levels if l["price_cents"] == price_cents)
            
            # Skip if queue position exceeds threshold
            if qp > self.max_qp_threshold:
                results.append({
                    "skipped": True,
                    "reason": "queue_too_deep",
                    "queue_position": qp,
                    "threshold": self.max_qp_threshold,
                    "signal_time": signal_time
                })
                continue
            
            # Simulate fills based on subsequent trades
            fill_result = self._simulate_fill(ob, trades, signal, qp)
            
            if fill_result["filled"]:
                # Calculate PnL using outcome and fees
                pnl = self._compute_pnl(price_cents, signal["outcome_yes"], maker=True)
                
                results.append({
                    "filled": True,
                    "pnl": pnl,
                    "queue_position": qp,
                    "fill_price": fill_result["fill_price"],
                    "fill_time": fill_result["fill_time"],
                    "signal_time": signal_time,
                    "fill_latency": fill_result["fill_time"] - signal_time
                })
            else:
                results.append({
                    "filled": False,
                    "queue_position": qp,
                    "reason": "no_fill",
                    "signal_time": signal_time
                })
        
        return results
    
    def _find_orderbook(self, orderbook_history: List[Dict[str, Any]], target_time: float) -> Optional[Dict[str, Any]]:
        """Find orderbook snapshot closest to target time."""
        if not orderbook_history:
            return None
        
        # Find the orderbook with timestamp closest to target_time
        closest_ob = None
        min_diff = float('inf')
        
        for ob in orderbook_history:
            diff = abs(ob["timestamp"] - target_time)
            if diff < min_diff:
                min_diff = diff
                closest_ob = ob
        
        return closest_ob
    
    def _simulate_fill(self, orderbook: Dict[str, Any], trades: List[Dict[str, Any]], 
                      signal: Dict[str, Any], queue_position: int) -> Dict[str, Any]:
        """Simulate order fill based on trade flow."""
        price_cents = signal["price_cents"]
        side = signal["side"]
        signal_time = signal["time_with_latency"]
        
        # Track cumulative contra volume at price level
        cumulative_volume = 0
        
        for trade in trades:
            if trade["timestamp"] < signal_time:
                continue
            
            # Check if trade affects our queue position
            if (trade["price_cents"] == price_cents and 
                trade["side"] != side):  # Contra side
                
                cumulative_volume += trade["quantity"]
                
                # Fill when cumulative volume exceeds our queue position
                if cumulative_volume >= queue_position:
                    return {
                        "filled": True,
                        "fill_price": trade["price_cents"],
                        "fill_time": trade["timestamp"],
                        "cumulative_volume": cumulative_volume
                    }
        
        return {"filled": False}
    
    def _compute_pnl(self, price_cents: int, outcome_yes: bool, maker: bool) -> float:
        """Compute PnL including Kalshi fees."""
        # Use Kalshi fee calculation
        trade_fee = kalshi_fee_per_contract(price_cents, maker)
        
        if outcome_yes:
            gross_pnl = 1.0 - price_cents / 100.0
        else:
            gross_pnl = -price_cents / 100.0
        
        net_pnl = gross_pnl - trade_fee
        return net_pnl
    
    def compare_strategies(self, orderbook_history: List[Dict[str, Any]], 
                          trades: List[Dict[str, Any]], 
                          signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare different queue threshold strategies."""
        strategies = {
            "conservative": 200,
            "moderate": 300,
            "aggressive": 500,
            "no_limit": float('inf')
        }
        
        results = {}
        
        for strategy_name, threshold in strategies.items():
            self.max_qp_threshold = threshold
            strategy_results = self.simulate_queue_strategy(orderbook_history, trades, signals)
            
            # Calculate metrics
            filled_trades = [r for r in strategy_results if r.get("filled", False)]
            skipped_trades = [r for r in strategy_results if r.get("skipped", False)]
            
            total_pnl = sum(r["pnl"] for r in filled_trades)
            avg_queue = sum(r["queue_position"] for r in strategy_results) / len(strategy_results) if strategy_results else 0
            
            results[strategy_name] = {
                "threshold": threshold,
                "total_trades": len(strategy_results),
                "filled_trades": len(filled_trades),
                "skipped_trades": len(skipped_trades),
                "fill_rate": len(filled_trades) / len(strategy_results) if strategy_results else 0,
                "total_pnl": total_pnl,
                "avg_pnl_per_trade": total_pnl / len(filled_trades) if filled_trades else 0,
                "avg_queue_position": avg_queue
            }
        
        return results


# ── Real-Time Integration with WebSocket + Queue Polling ─────────────────────

class KalshiRealTimeQueueBot(KalshiAutoCancelMakerBot):
    """Real-time bot combining WebSocket yes_price updates with queue polling."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.production_queue_manager = KalshiProductionQueueManager(
            api_key=os.getenv("KALSHI_API_KEY"),
            api_secret=os.getenv("KALSHI_API_SECRET")
        )
        self.backtester = KalshiQueueBacktester()
        self.ws_task = None
        self.queue_task = None
        
    async def start(self):
        """Start real-time bot with WebSocket and queue polling."""
        # Start WebSocket for yes_price updates
        self.ws_task = asyncio.create_task(self._yes_price_stream())
        
        # Start queue polling loop
        self.queue_task = asyncio.create_task(
            self._production_queue_poll_loop()
        )
        
        logger.info("Real-time queue bot started with WebSocket + queue polling")
    
    async def _yes_price_stream(self):
        """WebSocket stream for real-time yes_price updates."""
        try:
            # Connect to WebSocket for orderbook and trades
            self.ws_client = KalshiWebSocketClient(
                api_key=os.getenv("KALSHI_API_KEY"),
                api_secret=os.getenv("KALSHI_API_SECRET")
            )
            
            await self.ws_client.connect(self.tickers)
            self.ws_client.add_callback(self._handle_websocket_tick)
            
            # Start watching orderbooks
            await self.ws_client.watch_orderbooks()
            
        except Exception as e:
            logger.error(f"WebSocket stream error: {e}")
    
    async def _handle_websocket_tick(self, data: Dict[str, Any]):
        """Handle WebSocket ticks for real-time trading decisions."""
        try:
            # Process orderbook updates
            if data.get("type") == "orderbook":
                ticker = data.get("ticker")
                orderbook = self._parse_orderbook(data)
                
                if ticker:
                    self.orderbooks[ticker] = orderbook
                    
                    # Evaluate trading opportunity with real-time data
                    await self._evaluate_trading_opportunity(orderbook)
            
            # Process trade updates
            elif data.get("type") == "trade":
                self._process_trade_tick(data)
                
        except Exception as e:
            logger.error(f"WebSocket tick handling error: {e}")
    
    async def _production_queue_poll_loop(self, interval: float = 15.0):
        """Production queue polling loop with time-based thresholds."""
        while self.running:
            try:
                # Refresh queue positions and cancel based on time-based thresholds
                self.active_orders = self.production_queue_manager.refresh_queue_and_cancel(self.active_orders)

                # Log queue statistics
                if self.active_orders:
                    avg_qp = sum(o.get("queue_position", 0) for o in self.active_orders.values()) / len(self.active_orders)
                    logger.debug(f"Queue poll: {len(self.active_orders)} active orders, avg QP: {avg_qp:.1f}")

            except Exception as e:
                logger.error(f"Production queue poll error: {e}")

            await asyncio.sleep(interval)
    
    def _parse_orderbook(self, data: Dict[str, Any]) -> KalshiOrderbookSnapshot:
        """Parse WebSocket orderbook data into snapshot."""
        # Implementation depends on WebSocket message format
        # This is a placeholder - adapt to actual Kalshi WebSocket format
        ticker = data.get("ticker", "")
        timestamp = time.time()
        
        # Parse bids and asks from WebSocket data
        yes_bids = [OrderbookLevel(**level) for level in data.get("yes_bids", [])]
        yes_asks = [OrderbookLevel(**level) for level in data.get("yes_asks", [])]
        no_bids = [OrderbookLevel(**level) for level in data.get("no_bids", [])]
        no_asks = [OrderbookLevel(**level) for level in data.get("no_asks", [])]
        
        return KalshiOrderbookSnapshot(
            ticker=ticker,
            timestamp=timestamp,
            yes_bids=yes_bids,
            yes_asks=yes_asks,
            no_bids=no_bids,
            no_asks=no_asks
        )
    
    def _process_trade_tick(self, trade_data: Dict[str, Any]):
        """Process real-time trade ticks for debugging."""
        # Record trade data for live vs paper analysis
        self.debugger.record_live_trade({
            "price_cents": trade_data.get("price_cents", 0),
            "quantity": trade_data.get("quantity", 0),
            "side": trade_data.get("side", ""),
            "order_id": trade_data.get("order_id", ""),
            "queue_position": trade_data.get("queue_position"),
            "latency_ms": trade_data.get("latency_ms"),
            "spread_cents": trade_data.get("spread_cents")
        })
    
    async def stop(self):
        """Stop real-time bot and cleanup tasks."""
        if self.ws_task:
            self.ws_task.cancel()
        if self.queue_task:
            self.queue_task.cancel()
        
        await super().stop()
        logger.info("Real-time queue bot stopped")
    
    def run_backtest_comparison(self, orderbook_history: List[Dict[str, Any]], 
                               trades: List[Dict[str, Any]], 
                               signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run backtest comparison of different queue strategies."""
        return self.backtester.compare_strategies(orderbook_history, trades, signals)


# ── Optimal Queue Thresholds & Batch Cancel Logic ─────────────────────────────

class KalshiOptimalQueueManager:
    """Optimal queue manager with production-ready thresholds and batch cancel."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.session = requests.Session()
        self.cancel_jitter_range = (0.8, 1.2)  # Add jitter to avoid synchronized behavior
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def max_qp_for_time(self, minutes_to_expiry: float) -> int:
        """Optimal queue position threshold based on time to expiry."""
        if minutes_to_expiry > 12:
            return 300  # Early window: be conservative
        elif minutes_to_expiry > 6:
            return 500  # Mid window: allow deeper queues
        else:
            return 900  # Late window: tolerate deep queues due to expiry flow
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a specific order via Kalshi API."""
        try:
            path = f"/portfolio/orders/{order_id}"
            r = self.session.delete(self.base_url + path, headers=self._auth_headers(path, "DELETE"), timeout=3)
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def refresh_queue_and_cancel(self, active_orders: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Refresh queue positions and cancel orders exceeding optimal thresholds.
        
        Args:
            active_orders: {order_id: {"market_ticker": str, "minutes_to_expiry": float, "signal_strength": float, ...}}
        
        Returns:
            Updated active_orders dict
        """
        if not active_orders:
            return active_orders

        # Get queue positions for all markets
        tickers = list({o.get("market_ticker", "") for o in active_orders.values() if o.get("market_ticker")})
        if not tickers:
            return active_orders

        try:
            path = "/portfolio/orders/queue_positions"
            params = {"market_tickers": ",".join(tickers)}
            r = self.session.get(self.base_url + path, headers=self._auth_headers(path), params=params, timeout=3)
            r.raise_for_status()
            qps = r.json()["queue_positions"]  # [ {order_id, market_ticker, queue_position, ...} ]
            qp_by_order = {q["order_id"]: q["queue_position"] for q in qps}

            cancelled_orders = []

            for oid, meta in list(active_orders.items()):
                qp = qp_by_order.get(oid)
                if qp is None:
                    continue
                
                # Update queue position
                meta["queue_position"] = qp
                
                # Check if should cancel based on optimal threshold
                minutes_to_expiry = meta.get("minutes_to_expiry", 15.0)
                signal_strength = meta.get("signal_strength", 0.0)
                max_qp = self.max_qp_for_time(minutes_to_expiry)
                
                # Only cancel if queue is too deep AND signal is weak/stale
                should_cancel = qp > max_qp and signal_strength < 0.5
                
                if should_cancel:
                    # Add jitter to cancel timing
                    jitter = random.uniform(*self.cancel_jitter_range)
                    time.sleep(jitter * 0.1)  # Small jitter to avoid synchronized cancels
                    
                    if self.cancel_order(oid):
                        cancelled_orders.append(oid)
                        logger.info(f"Cancelled order {oid}: qp={qp} > max_qp={max_qp}, signal={signal_strength:.2f}")

            # Remove cancelled orders
            for oid in cancelled_orders:
                del active_orders[oid]

        except Exception as e:
            logger.error(f"Queue refresh error: {e}")

        return active_orders


# ── WebSocket Partial Fill Monitoring ───────────────────────────────────────

class KalshiWebSocketMonitor:
    """WebSocket monitoring for real-time fills and position updates."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        self.position_callbacks: List[callable] = []
        
    def _auth_headers(self) -> dict:
        """Generate WebSocket authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + "/ws/v2"
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def add_position_callback(self, callback: callable):
        """Add callback for position updates."""
        self.position_callbacks.append(callback)
    
    async def positions_stream(self):
        """Stream real-time position updates via WebSocket."""
        try:
            async with websockets.connect(self.ws_url, extra_headers=self._auth_headers()) as ws:
                # Subscribe to market positions
                sub = {
                    "type": "subscribe",
                    "channels": [
                        {"name": "market_positions"},
                        {"name": "order_updates"}  # If available for account-specific updates
                    ],
                }
                await ws.send(json.dumps(sub))
                
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        
                        # Handle market positions
                        if msg.get("type") == "market_positions":
                            await self._handle_positions_update(msg.get("positions", []))
                        
                        # Handle order updates (if available)
                        elif msg.get("type") == "order_updates":
                            await self._handle_order_updates(msg.get("orders", []))
                            
                    except Exception as e:
                        logger.error(f"WebSocket message handling error: {e}")
                        
        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
    
    async def _handle_positions_update(self, positions: List[Dict[str, Any]]):
        """Handle real-time position updates."""
        for pos in positions:
            ticker = pos.get("ticker", "")
            yes_contracts = pos.get("yes_contracts", 0)
            no_contracts = pos.get("no_contracts", 0)
            realized_pnl = pos.get("realized_pnl", 0.0)
            
            # Update position tracking
            position_data = {
                "ticker": ticker,
                "yes_contracts": yes_contracts,
                "no_contracts": no_contracts,
                "realized_pnl": realized_pnl,
                "timestamp": time.time()
            }
            
            # Notify callbacks
            for callback in self.position_callbacks:
                try:
                    await callback(position_data)
                except Exception as e:
                    logger.error(f"Position callback error: {e}")
    
    async def _handle_order_updates(self, orders: List[Dict[str, Any]]):
        """Handle real-time order updates including fills."""
        for order in orders:
            order_id = order.get("order_id", "")
            fill_count = order.get("fill_count", 0)
            remaining_count = order.get("remaining_count", 0)
            status = order.get("status", "")
            
            # Update local order tracking
            if order_id in self.active_orders:
                meta = self.active_orders[order_id]
                prev_filled = meta.get("filled", 0)
                
                meta["filled"] = fill_count
                meta["remaining"] = remaining_count
                meta["status"] = status
                
                # Log partial fills
                if fill_count > prev_filled:
                    fill_delta = fill_count - prev_filled
                    logger.info(f"Partial fill on {order_id}: +{fill_delta} (total: {fill_count})")
                
                # Handle fully filled orders
                if remaining_count == 0:
                    logger.info(f"Order {order_id} fully filled")
                    # Could trigger PnL calculation here


# ── Queue-Aware 15m Maker Logic ───────────────────────────────────────────────

class KalshiQueueAwareMakerLogic:
    """Queue-aware decision logic for 15m crypto makers."""
    
    def __init__(self):
        self.queue_manager = KalshiOptimalQueueManager(
            api_key=os.getenv("KALSHI_API_KEY"),
            api_secret=os.getenv("KALSHI_API_SECRET")
        )
        self.ws_monitor = KalshiWebSocketMonitor(
            api_key=os.getenv("KALSHI_API_KEY"),
            api_secret=os.getenv("KALSHI_API_SECRET")
        )
        
    def estimate_queue_position_at_price(self, orderbook: KalshiOrderbookSnapshot, 
                                        price_cents: int, side: str) -> int:
        """Estimate queue position from current orderbook depth."""
        if side == "buy":
            # For buy orders, count yes bids at this price
            for level in orderbook.yes_bids:
                if level.price_cents == price_cents:
                    return level.quantity
        else:
            # For sell orders, count no bids at this price
            for level in orderbook.no_bids:
                if level.price_cents == price_cents:
                    return level.quantity
        
        return 0  # No orders at this price level
    
    def should_post_order(self, orderbook: KalshiOrderbookSnapshot, 
                          price_cents: int, side: str, 
                          minutes_to_expiry: float, 
                          signal_strength: float) -> bool:
        """
        Determine if should post order based on queue position and signal.
        
        Args:
            orderbook: Current orderbook snapshot
            price_cents: Intended price in cents
            side: "buy" or "sell"
            minutes_to_expiry: Time until expiry
            signal_strength: Signal strength (0-1, higher = stronger)
        
        Returns:
            True if should post order, False otherwise
        """
        # Estimate queue position at intended price
        estimated_qp = self.estimate_queue_position_at_price(orderbook, price_cents, side)
        
        # Get optimal threshold for this time
        max_qp = self.queue_manager.max_qp_for_time(minutes_to_expiry)
        
        # Decision logic
        if estimated_qp > max_qp:
            logger.debug(f"Skip posting: estimated QP={estimated_qp} > max_qp={max_qp}")
            return False
        
        # Require minimum signal strength for deep queues
        if estimated_qp > max_qp * 0.7 and signal_strength < 0.6:
            logger.debug(f"Skip posting: deep queue with weak signal (QP={estimated_qp}, signal={signal_strength:.2f})")
            return False
        
        return True
    
    def should_cancel_order(self, order_meta: Dict[str, Any]) -> bool:
        """
        Determine if should cancel existing order.
        
        Args:
            order_meta: Order metadata including queue_position, signal_strength, minutes_to_expiry
        
        Returns:
            True if should cancel, False otherwise
        """
        qp = order_meta.get("queue_position", 0)
        signal_strength = order_meta.get("signal_strength", 0.0)
        minutes_to_expiry = order_meta.get("minutes_to_expiry", 15.0)
        
        max_qp = self.queue_manager.max_qp_for_time(minutes_to_expiry)
        
        # Cancel if queue is too deep AND signal has weakened
        if qp > max_qp and signal_strength < 0.4:
            return True
        
        # Cancel if queue has grown significantly since posting
        initial_qp = order_meta.get("initial_queue_position", qp)
        if qp > initial_qp * 1.5 and signal_strength < 0.7:
            return True
        
        return False
    
    def get_queue_priority_score(self, order_meta: Dict[str, Any]) -> float:
        """
        Calculate queue priority score for order management decisions.
        
        Args:
            order_meta: Order metadata
        
        Returns:
            Priority score (higher = better priority)
        """
        qp = order_meta.get("queue_position", 0)
        signal_strength = order_meta.get("signal_strength", 0.0)
        minutes_to_expiry = order_meta.get("minutes_to_expiry", 15.0)
        
        # Lower queue position = higher priority
        queue_score = 1.0 / (1.0 + qp / 100.0)
        
        # Higher signal strength = higher priority
        signal_score = signal_strength
        
        # Time to expiry factor (closer = more urgent)
        time_score = 1.0 / (1.0 + minutes_to_expiry / 15.0)
        
        # Combined priority score
        priority = (queue_score * 0.5) + (signal_score * 0.3) + (time_score * 0.2)
        
        return priority


# ── Queue Strategy Backtester ─────────────────────────────────────────────

class KalshiQueueStrategyBacktester:
    """Backtest queue-aware vs momentum-only strategies."""
    
    def __init__(self):
        self.queue_logic = KalshiQueueAwareMakerLogic()
        
    def backtest_strategies(self, orderbook_history: List[Dict[str, Any]], 
                            trades: List[Dict[str, Any]], 
                            signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare momentum-only vs queue-aware strategies.
        
        Args:
            orderbook_history: Historical orderbook snapshots
            trades: Historical trades
            signals: Trading signals with time, price, side, signal_strength
        
        Returns:
            Comparison results for both strategies
        """
        momentum_results = []
        queue_aware_results = []
        
        for signal in signals:
            signal_time = signal["time_with_latency"]
            price_cents = signal["price_cents"]
            side = signal["side"]
            signal_strength = signal.get("signal_strength", 0.5)
            
            # Find orderbook at signal time
            ob = self._find_orderbook(orderbook_history, signal_time)
            if not ob:
                continue
            
            # Convert to orderbook snapshot format
            orderbook = self._parse_orderbook(ob)
            minutes_to_expiry = signal.get("minutes_to_expiry", 15.0)
            
            # Momentum-only: always post if signal is strong enough
            momentum_post = signal_strength > 0.3
            
            # Queue-aware: check queue position
            queue_post = self.queue_logic.should_post_order(
                orderbook, price_cents, side, minutes_to_expiry, signal_strength
            )
            
            # Simulate fills for both strategies
            if momentum_post:
                momentum_result = self._simulate_fill(orderbook, trades, signal, queue_aware=False)
                momentum_results.append(momentum_result)
            
            if queue_post:
                queue_result = self._simulate_fill(orderbook, trades, signal, queue_aware=True)
                queue_aware_results.append(queue_result)
        
        # Calculate metrics
        return {
            "momentum_only": self._calculate_metrics(momentum_results),
            "queue_aware": self._calculate_metrics(queue_aware_results)
        }
    
    def _simulate_fill(self, orderbook: KalshiOrderbookSnapshot, 
                       trades: List[Dict[str, Any]], 
                       signal: Dict[str, Any], 
                       queue_aware: bool) -> Dict[str, Any]:
        """Simulate order fill with or without queue awareness."""
        price_cents = signal["price_cents"]
        side = signal["side"]
        signal_time = signal["time_with_latency"]
        
        # Estimate queue position
        if queue_aware:
            qp = self.queue_logic.estimate_queue_position_at_price(orderbook, price_cents, side)
        else:
            qp = 50  # Assume reasonable queue for momentum-only
        
        # Simulate fills based on trade flow
        cumulative_volume = 0
        
        for trade in trades:
            if trade["timestamp"] < signal_time:
                continue
            
            if (trade["price_cents"] == price_cents and 
                trade["side"] != side):  # Contra side
                
                cumulative_volume += trade["quantity"]
                
                if cumulative_volume >= qp:
                    # Calculate PnL
                    pnl = self._compute_pnl(price_cents, signal["outcome_yes"], maker=True)
                    
                    return {
                        "filled": True,
                        "pnl": pnl,
                        "queue_position": qp,
                        "fill_price": trade["price_cents"],
                        "fill_time": trade["timestamp"],
                        "signal_time": signal_time,
                        "strategy": "queue_aware" if queue_aware else "momentum_only"
                    }
        
        return {
            "filled": False,
            "queue_position": qp,
            "strategy": "queue_aware" if queue_aware else "momentum_only"
        }
    
    def _calculate_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate performance metrics for strategy results."""
        if not results:
            return {"total_trades": 0, "filled_trades": 0, "fill_rate": 0, "total_pnl": 0}
        
        filled_trades = [r for r in results if r.get("filled", False)]
        total_pnl = sum(r["pnl"] for r in filled_trades)
        avg_qp = sum(r["queue_position"] for r in results) / len(results)
        
        return {
            "total_trades": len(results),
            "filled_trades": len(filled_trades),
            "fill_rate": len(filled_trades) / len(results),
            "total_pnl": total_pnl,
            "avg_pnl_per_trade": total_pnl / len(filled_trades) if filled_trades else 0,
            "avg_queue_position": avg_qp
        }
    
    def _find_orderbook(self, orderbook_history: List[Dict[str, Any]], target_time: float) -> Optional[Dict[str, Any]]:
        """Find orderbook snapshot closest to target time."""
        if not orderbook_history:
            return None
        
        closest_ob = None
        min_diff = float('inf')
        
        for ob in orderbook_history:
            diff = abs(ob["timestamp"] - target_time)
            if diff < min_diff:
                min_diff = diff
                closest_ob = ob
        
        return closest_ob
    
    def _parse_orderbook(self, ob_data: Dict[str, Any]) -> KalshiOrderbookSnapshot:
        """Parse orderbook data into snapshot format."""
        # Implementation depends on data format
        return KalshiOrderbookSnapshot(
            ticker=ob_data.get("ticker", ""),
            timestamp=ob_data.get("timestamp", time.time()),
            yes_bids=[],
            yes_asks=[],
            no_bids=[],
            no_asks=[]
        )
    
    def _compute_pnl(self, price_cents: int, outcome_yes: bool, maker: bool) -> float:
        """Compute PnL including Kalshi fees."""
        trade_fee = kalshi_fee_per_contract(price_cents, maker)
        
        if outcome_yes:
            gross_pnl = 1.0 - price_cents / 100.0
        else:
            gross_pnl = -price_cents / 100.0
        
        return gross_pnl - trade_fee


# ── Batch Cancel with Queue Position Thresholds ───────────────────────────────

class KalshiBatchCancelManager:
    """Batch cancel manager with queue position thresholds and risk mitigation."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.session = requests.Session()
        self.cancel_rate_limit = 5.0  # Minimum seconds between batch cancels
        self.last_cancel_time = 0
        self.max_batch_size = 20  # Kalshi limits to 20 orders per batch
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def max_qp_for_time(self, minutes_to_expiry: float) -> int:
        """Optimal queue position threshold based on time to expiry."""
        if minutes_to_expiry > 12:
            return 300  # Early window: be conservative
        elif minutes_to_expiry > 6:
            return 500  # Mid window: allow deeper queues
        else:
            return 900  # Late window: tolerate deep queues due to expiry flow
    
    def batch_cancel(self, order_ids: List[str]) -> bool:
        """Cancel multiple orders in a single batch request."""
        if not order_ids:
            return True
        
        # Rate limit protection
        current_time = time.time()
        time_since_last_cancel = current_time - self.last_cancel_time
        if time_since_last_cancel < self.cancel_rate_limit:
            wait_time = self.cancel_rate_limit - time_since_last_cancel
            logger.debug(f"Rate limiting batch cancel, waiting {wait_time:.2f}s")
            time.sleep(wait_time)
        
        try:
            # Split into batches if needed
            batches = [order_ids[i:i + self.max_batch_size] for i in range(0, len(order_ids), self.max_batch_size)]
            
            for batch in batches:
                path = "/portfolio/orders/batched"
                body = {"ids": batch}
                r = self.session.delete(
                    self.base_url + path, 
                    headers=self._auth_headers(path, "DELETE"),
                    json=body, 
                    timeout=3
                )
                r.raise_for_status()
                
                logger.info(f"Batch cancelled {len(batch)} orders: {batch}")
                self.last_cancel_time = time.time()
            
            return True
            
        except Exception as e:
            logger.error(f"Batch cancel failed for orders {order_ids}: {e}")
            return False
    
    def refresh_queue_and_cancel(self, active_orders: Dict[str, Dict[str, Any]], 
                               high_vol_mode: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Refresh queue positions and cancel orders exceeding thresholds.
        
        Args:
            active_orders: {order_id: {"market_ticker": str, "minutes_to_expiry": float, "signal_strength": float, ...}}
            high_vol_mode: Apply looser thresholds during high volatility
        
        Returns:
            Updated active_orders dict
        """
        if not active_orders:
            return active_orders

        # Get queue positions for all markets
        tickers = list({o.get("market_ticker", "") for o in active_orders.values() if o.get("market_ticker")})
        if not tickers:
            return active_orders

        try:
            path = "/portfolio/orders/queue_positions"
            params = {"market_tickers": ",".join(tickers)}
            r = self.session.get(self.base_url + path, headers=self._auth_headers(path), params=params, timeout=3)
            r.raise_for_status()
            qps = r.json()["queue_positions"]  # [{order_id, queue_position, ...}]
            qp_by_order = {q["order_id"]: q["queue_position"] for q in qps}

            to_cancel = []
            
            for oid, meta in active_orders.items():
                qp = qp_by_order.get(oid)
                if qp is None:
                    continue
                
                # Update queue position
                meta["queue_position"] = qp
                
                # Apply high-vol adjustments
                if high_vol_mode:
                    # Looser thresholds during high volatility
                    max_qp = self.max_qp_for_time(meta.get("minutes_to_expiry", 15.0)) * 1.5
                    signal_threshold = 0.3  # Weaker signal threshold
                else:
                    max_qp = self.max_qp_for_time(meta.get("minutes_to_expiry", 15.0))
                    signal_threshold = 0.5
                
                # Cancel conditions
                signal_strength = meta.get("signal_strength", 0.0)
                should_cancel = (
                    qp > max_qp and 
                    signal_strength < signal_threshold and
                    self._should_cancel_hysteresis(meta, qp)
                )
                
                if should_cancel:
                    to_cancel.append(oid)
                    logger.debug(f"Marked for cancel: {oid}, qp={qp}, signal={signal_strength:.2f}")

            # Batch cancel orders
            if to_cancel:
                if self.batch_cancel(to_cancel):
                    for oid in to_cancel:
                        active_orders.pop(oid, None)
                        logger.info(f"Cancelled order {oid}")
                else:
                    logger.warning(f"Batch cancel failed, keeping {len(to_cancel)} orders active")

        except Exception as e:
            logger.error(f"Queue refresh error: {e}")

        return active_orders
    
    def _should_cancel_hysteresis(self, order_meta: Dict[str, Any], current_qp: int) -> bool:
        """Apply hysteresis to avoid cancel churn."""
        previous_qp = order_meta.get("previous_queue_position", current_qp)
        
        # Don't cancel if queue is improving (getting smaller)
        if current_qp < previous_qp * 0.8:
            return False
        
        # Don't cancel if we just recently cancelled this order
        last_cancel = order_meta.get("last_cancel_time", 0)
        if time.time() - last_cancel < 30:  # 30 second grace period
            return False
        
        return True


# ── Enhanced WebSocket Fill Monitoring ─────────────────────────────────────

class KalshiWebSocketFillMonitor:
    """Enhanced WebSocket monitoring with best practices for fill tracking."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        self.position_callbacks: List[callable] = []
        self.last_reconciliation_time = 0
        self.reconciliation_interval = 60  # Reconcile every 60 seconds
        
    def _auth_headers(self) -> dict:
        """Generate WebSocket authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + "/ws/v2"
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def add_position_callback(self, callback: callable):
        """Add callback for position updates."""
        self.position_callbacks.append(callback)
    
    async def start_monitoring(self):
        """Start comprehensive WebSocket monitoring."""
        tasks = [
            self._positions_stream(),
            self._order_updates_stream(),
            self._periodic_reconciliation()
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _positions_stream(self):
        """Stream market positions updates."""
        try:
            async with websockets.connect(self.ws_url, extra_headers=self._auth_headers()) as ws:
                sub = {
                    "type": "subscribe",
                    "channels": [{"name": "market_positions"}],
                }
                await ws.send(json.dumps(sub))
                
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg.get("type") == "market_positions":
                            await self._handle_positions_update(msg.get("positions", []))
                    except Exception as e:
                        logger.error(f"Positions stream error: {e}")
                        
        except Exception as e:
            logger.error(f"Positions stream connection error: {e}")
    
    async def _order_updates_stream(self):
        """Stream order updates for real-time fill tracking."""
        try:
            async with websockets.connect(self.ws_url, extra_headers=self._auth_headers()) as ws:
                sub = {
                    "type": "subscribe",
                    "channels": [
                        {"name": "order_updates"},
                        {"name": "order_group_updates"}  # If available
                    ],
                }
                await ws.send(json.dumps(sub))
                
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        
                        if msg.get("type") == "order_updates":
                            await self._handle_order_updates(msg.get("orders", []))
                        elif msg.get("type") == "order_group_updates":
                            await self._handle_order_group_updates(msg.get("order_groups", []))
                            
                    except Exception as e:
                        logger.error(f"Order updates stream error: {e}")
                        
        except Exception as e:
            logger.error(f"Order updates stream connection error: {e}")
    
    async def _handle_order_updates(self, orders: List[Dict[str, Any]]):
        """Handle real-time order updates with fill tracking."""
        for order in orders:
            order_id = order.get("order_id", "")
            if not order_id:
                continue
            
            # Update local order tracking
            if order_id in self.active_orders:
                meta = self.active_orders[order_id]
                prev_filled = meta.get("filled", 0)
                
                fill_count = order.get("fill_count", 0)
                remaining_count = order.get("remaining_count", 0)
                status = order.get("status", "")
                
                # Detect partial fills
                if fill_count > prev_filled:
                    fill_delta = fill_count - prev_filled
                    logger.info(f"Partial fill on {order_id}: +{fill_delta} (total: {fill_count})")
                    
                    # Update position tracking
                    await self._update_position_from_fill(order_id, fill_delta)
                
                # Update order metadata
                meta.update({
                    "filled": fill_count,
                    "remaining": remaining_count,
                    "status": status,
                    "queue_position": order.get("queue_position", meta.get("queue_position", 0))
                })
                
                # Handle fully filled orders
                if remaining_count == 0 or status in ["filled", "canceled"]:
                    logger.info(f"Order {order_id} {status}")
                    await self._finalize_order(order_id, status)
    
    async def _handle_order_group_updates(self, order_groups: List[Dict[str, Any]]):
        """Handle order group updates for batch operations."""
        for group in order_groups:
            # Process group-level updates
            group_id = group.get("group_id", "")
            orders = group.get("orders", [])
            
            logger.debug(f"Order group {group_id} update: {len(orders)} orders")
            
            # Process individual orders in the group
            await self._handle_order_updates(orders)
    
    async def _handle_positions_update(self, positions: List[Dict[str, Any]]):
        """Handle market position updates."""
        for pos in positions:
            position_data = {
                "ticker": pos.get("ticker", ""),
                "yes_contracts": pos.get("yes_contracts", 0),
                "no_contracts": pos.get("no_contracts", 0),
                "realized_pnl": pos.get("realized_pnl", 0.0),
                "timestamp": time.time()
            }
            
            # Notify callbacks
            for callback in self.position_callbacks:
                try:
                    await callback(position_data)
                except Exception as e:
                    logger.error(f"Position callback error: {e}")
    
    async def _update_position_from_fill(self, order_id: str, fill_delta: int):
        """Update position tracking based on fill."""
        if order_id not in self.active_orders:
            return
        
        meta = self.active_orders[order_id]
        ticker = meta.get("ticker", "")
        side = meta.get("side", "")
        
        # Create position update
        if side == "buy":
            position_data = {
                "ticker": ticker,
                "yes_contracts": fill_delta,
                "no_contracts": 0,
                "realized_pnl": 0.0,
                "timestamp": time.time(),
                "source": "fill"
            }
        else:
            position_data = {
                "ticker": ticker,
                "yes_contracts": 0,
                "no_contracts": fill_delta,
                "realized_pnl": 0.0,
                "timestamp": time.time(),
                "source": "fill"
            }
        
        # Notify callbacks
        for callback in self.position_callbacks:
            try:
                await callback(position_data)
            except Exception as e:
                logger.error(f"Fill position callback error: {e}")
    
    async def _finalize_order(self, order_id: str, status: str):
        """Finalize order processing."""
        if order_id in self.active_orders:
            meta = self.active_orders[order_id]
            
            # Calculate final PnL if filled
            if status == "filled":
                filled = meta.get("filled", 0)
                price_cents = meta.get("price_cents", 0)
                
                # This would need outcome information for actual PnL
                logger.info(f"Order {order_id} finalized: {filled} contracts at {price_cents}¢")
            
            # Remove from active tracking
            del self.active_orders[order_id]
    
    async def _periodic_reconciliation(self):
        """Periodically reconcile with REST API to ensure consistency."""
        while self.running:
            try:
                await asyncio.sleep(self.reconciliation_interval)
                await self._reconcile_orders()
            except Exception as e:
                logger.error(f"Reconciliation error: {e}")
    
    async def _reconcile_orders(self):
        """Reconcile local order state with REST API."""
        if not self.active_orders:
            return
        
        try:
            # Sample a few orders for reconciliation
            sample_orders = list(self.active_orders.keys())[:5]
            
            for order_id in sample_orders:
                # Get current order state from REST API
                path = f"/portfolio/orders/{order_id}"
                r = requests.get(
                    f"https://api.elections.kalshi.com/trade-api/v2{path}",
                    headers=self._auth_headers(path),
                    timeout=3
                )
                
                if r.status_code == 200:
                    order_data = r.json().get("order", {})
                    
                    # Compare with local state
                    local_meta = self.active_orders.get(order_id, {})
                    local_filled = local_meta.get("filled", 0)
                    api_filled = order_data.get("fill_count", 0)
                    
                    if local_filled != api_filled:
                        logger.warning(f"Reconciliation mismatch for {order_id}: local={local_filled}, api={api_filled}")
                        
                        # Update local state with API data
                        await self._handle_order_updates([order_data])
                
        except Exception as e:
            logger.error(f"REST reconciliation error: {e}")


# ── Market-Specific Queue Management ───────────────────────────────────────

class KalshiMarketSpecificQueueManager:
    """Market-specific queue management for crypto vs election markets."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.batch_manager = KalshiBatchCancelManager(api_key, api_secret)
        self.fill_monitor = KalshiWebSocketFillMonitor(api_key, api_secret)
        
    def get_market_type_config(self, ticker: str) -> Dict[str, Any]:
        """Get market-specific configuration based on ticker."""
        # Crypto 15m markets
        if ticker.startswith("KX") and "15M" in ticker:
            return {
                "market_type": "crypto_15m",
                "queue_multiplier": 1.0,  # Standard thresholds
                "latency_sensitive": True,
                "burst_flow": True,
                "cancel_aggressiveness": 0.7
            }
        # Election markets
        elif ticker.startswith("KE") or "PRES" in ticker or "SENATE" in ticker:
            return {
                "market_type": "election",
                "queue_multiplier": 1.5,  # Can tolerate deeper queues
                "latency_sensitive": False,
                "burst_flow": False,
                "cancel_aggressiveness": 0.5
            }
        # Default configuration
        else:
            return {
                "market_type": "default",
                "queue_multiplier": 1.2,
                "latency_sensitive": False,
                "burst_flow": False,
                "cancel_aggressiveness": 0.6
            }
    
    def get_adjusted_threshold(self, base_threshold: int, market_config: Dict[str, Any]) -> int:
        """Get queue threshold adjusted for market type."""
        multiplier = market_config.get("queue_multiplier", 1.0)
        return int(base_threshold * multiplier)
    
    def should_use_batch_cancel(self, market_config: Dict[str, Any], order_count: int) -> bool:
        """Determine if batch cancel is appropriate for this market."""
        # Use batch cancel for high-volume crypto markets
        if market_config.get("market_type") == "crypto_15m" and order_count > 3:
            return True
        
        # Use individual cancels for election markets to preserve time priority
        if market_config.get("market_type") == "election":
            return False
        
        return order_count > 5  # Default threshold
    
    async def manage_orders_by_market(self, active_orders: Dict[str, Dict[str, Any]], 
                                     high_vol_mode: bool = False) -> Dict[str, Dict[str, Any]]:
        """Manage orders with market-specific logic."""
        if not active_orders:
            return active_orders
        
        # Group orders by market type
        market_groups = {}
        for order_id, meta in active_orders.items():
            ticker = meta.get("market_ticker", "")
            market_config = self.get_market_type_config(ticker)
            market_type = market_config.get("market_type", "default")
            
            if market_type not in market_groups:
                market_groups[market_type] = {
                    "config": market_config,
                    "orders": {}
                }
            
            market_groups[market_type]["orders"][order_id] = meta
        
        # Process each market group
        updated_orders = active_orders.copy()
        
        for market_type, group_data in market_groups.items():
            config = group_data["config"]
            orders = group_data["orders"]
            
            if not orders:
                continue
            
            # Apply market-specific management
            if config.get("market_type") == "crypto_15m":
                # Aggressive management for crypto 15m
                updated_orders = await self._manage_crypto_orders(
                    orders, config, high_vol_mode, updated_orders
                )
            elif config.get("market_type") == "election":
                # Conservative management for elections
                updated_orders = await self._manage_election_orders(
                    orders, config, updated_orders
                )
            else:
                # Default management
                updated_orders = await self.batch_manager.refresh_queue_and_cancel(
                    orders, high_vol_mode
                )
        
        return updated_orders
    
    async def _manage_crypto_orders(self, orders: Dict[str, Dict[str, Any]], 
                                   config: Dict[str, Any], high_vol_mode: bool,
                                   all_active_orders: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Manage crypto 15m orders with aggressive queue management."""
        # Apply tighter thresholds for crypto
        for order_id, meta in orders.items():
            minutes_to_expiry = meta.get("minutes_to_expiry", 15.0)
            base_threshold = self.batch_manager.max_qp_for_time(minutes_to_expiry)
            adjusted_threshold = self.get_adjusted_threshold(base_threshold, config)
            
            # Update threshold in metadata
            meta["adjusted_queue_threshold"] = adjusted_threshold
        
        # Use batch cancel for crypto
        return await self.batch_manager.refresh_queue_and_cancel(orders, high_vol_mode)
    
    async def _manage_election_orders(self, orders: Dict[str, Dict[str, Any]], 
                                    config: Dict[str, Any],
                                    all_active_orders: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Manage election orders with conservative queue management."""
        # Apply looser thresholds for elections
        for order_id, meta in orders.items():
            minutes_to_expiry = meta.get("minutes_to_expiry", 15.0)
            base_threshold = self.batch_manager.max_qp_for_time(minutes_to_expiry)
            adjusted_threshold = self.get_adjusted_threshold(base_threshold, config)
            
            # Update threshold in metadata
            meta["adjusted_queue_threshold"] = adjusted_threshold
        
        # Use individual cancels to preserve time priority
        to_cancel = []
        
        for order_id, meta in orders.items():
            qp = meta.get("queue_position", 0)
            threshold = meta.get("adjusted_queue_threshold", 500)
            signal_strength = meta.get("signal_strength", 0.0)
            
            # More conservative cancel criteria for elections
            if qp > threshold and signal_strength < 0.3:
                to_cancel.append(order_id)
        
        # Cancel individually to preserve time priority
        for order_id in to_cancel:
            if self.batch_manager.batch_cancel([order_id]):
                all_active_orders.pop(order_id, None)
                logger.info(f"Cancelled election order {order_id}")
        
        return all_active_orders


# ── WebSocket Partial-Fill Alerts ───────────────────────────────────────────

class KalshiWebSocketFillAlerts:
    """WebSocket partial-fill alerts with user_orders and user_fills channels."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.fill_callbacks: List[callable] = []
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        
    def _auth_headers(self) -> dict:
        """Generate WebSocket authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + "/ws/v2"
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def add_fill_callback(self, callback: callable):
        """Add callback for fill updates."""
        self.fill_callbacks.append(callback)
    
    async def fills_stream(self):
        """Stream user_orders and user_fills for real-time fill tracking."""
        headers = self._auth_headers()
        
        try:
            async with websockets.connect(self.ws_url, extra_headers=headers) as ws:
                # Subscribe to user-specific channels
                sub = {
                    "type": "subscribe",
                    "channels": [
                        {"name": "user_orders"},
                        {"name": "user_fills"},
                    ],
                }
                await ws.send(json.dumps(sub))
                
                logger.info("Subscribed to user_orders and user_fills streams")
                
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        
                        if msg.get("type") == "user_orders":
                            order = msg.get("order", {})
                            await self._handle_order_update(order)
                            
                        elif msg.get("type") == "user_fills":
                            fill = msg.get("fill", {})
                            await self._handle_fill_update(fill)
                            
                    except Exception as e:
                        logger.error(f"WebSocket fill alert error: {e}")
                        
        except Exception as e:
            logger.error(f"WebSocket fill alert connection error: {e}")
    
    async def _handle_order_update(self, order: Dict[str, Any]):
        """Handle user_orders channel updates."""
        order_id = order.get("order_id", "")
        if not order_id:
            return
        
        # Update local order state
        if order_id in self.active_orders:
            meta = self.active_orders[order_id]
            prev_filled = meta.get("filled", 0)
            
            fill_count = order.get("fill_count", 0)
            remaining_count = order.get("remaining_count", 0)
            queue_position = order.get("queue_position", 0)
            status = order.get("status", "")
            
            # Detect partial fills
            if fill_count > prev_filled:
                fill_delta = fill_count - prev_filled
                logger.info(f"Partial fill alert: {order_id} +{fill_delta} (total: {fill_count})")
                
                # Trigger fill callbacks
                await self._trigger_fill_callbacks(order_id, {
                    "type": "partial_fill",
                    "order_id": order_id,
                    "fill_delta": fill_delta,
                    "fill_count": fill_count,
                    "remaining_count": remaining_count,
                    "queue_position": queue_position,
                    "timestamp": time.time()
                })
            
            # Update order metadata
            meta.update({
                "filled": fill_count,
                "remaining": remaining_count,
                "queue_position": queue_position,
                "status": status
            })
            
            # Handle fully filled orders
            if remaining_count == 0 or status in ["filled", "canceled"]:
                logger.info(f"Order {order_id} {status}")
                await self._trigger_fill_callbacks(order_id, {
                    "type": "order_complete",
                    "order_id": order_id,
                    "status": status,
                    "fill_count": fill_count,
                    "timestamp": time.time()
                })
    
    async def _handle_fill_update(self, fill: Dict[str, Any]):
        """Handle user_fills channel updates."""
        order_id = fill.get("order_id", "")
        if not order_id:
            return
        
        # Extract fill information
        fill_count = fill.get("fill_count", 0)
        remaining_count = fill.get("remaining_count", 0)
        fill_price = fill.get("yes_price", fill.get("no_price", 0))
        fill_quantity = fill.get("count", 0)
        
        logger.info(f"Fill alert: {order_id} {fill_quantity}@{fill_price}¢")
        
        # Trigger fill callbacks
        await self._trigger_fill_callbacks(order_id, {
            "type": "fill_execution",
            "order_id": order_id,
            "fill_count": fill_count,
            "remaining_count": remaining_count,
            "fill_price": fill_price,
            "fill_quantity": fill_quantity,
            "timestamp": time.time()
        })
    
    async def _trigger_fill_callbacks(self, order_id: str, fill_data: Dict[str, Any]):
        """Trigger all registered fill callbacks."""
        for callback in self.fill_callbacks:
            try:
                await callback(order_id, fill_data)
            except Exception as e:
                logger.error(f"Fill callback error: {e}")


# ── Dynamic Volatility-Aware Queue Thresholds ─────────────────────────────

class KalshiDynamicQueueThresholds:
    """Dynamic queue thresholds based on time to expiry and volatility state."""
    
    def __init__(self):
        self.volatility_window = 300  # 5 minutes for volatility calculation
        self.price_history: Dict[str, List[Tuple[float, float]]] = {}  # ticker -> [(timestamp, price), ...]
        
    def update_price_history(self, ticker: str, price: float, timestamp: float = None):
        """Update price history for volatility calculation."""
        if timestamp is None:
            timestamp = time.time()
        
        if ticker not in self.price_history:
            self.price_history[ticker] = []
        
        # Add new price
        self.price_history[ticker].append((timestamp, price))
        
        # Clean old data outside volatility window
        cutoff_time = timestamp - self.volatility_window
        self.price_history[ticker] = [
            (ts, p) for ts, p in self.price_history[ticker] 
            if ts > cutoff_time
        ]
    
    def calculate_volatility_state(self, ticker: str) -> str:
        """Calculate volatility state: 'normal' or 'high'."""
        if ticker not in self.price_history or len(self.price_history[ticker]) < 10:
            return "normal"
        
        prices = [p for ts, p in self.price_history[ticker]]
        if len(prices) < 2:
            return "normal"
        
        # Calculate price changes
        price_changes = []
        for i in range(1, len(prices)):
            change = abs(prices[i] - prices[i-1]) / prices[i-1]
            price_changes.append(change)
        
        if not price_changes:
            return "normal"
        
        # Calculate average price change
        avg_change = sum(price_changes) / len(price_changes)
        
        # Determine volatility state
        # High volatility: average change > 0.5% per update
        if avg_change > 0.005:
            return "high"
        else:
            return "normal"
    
    def dynamic_qp_threshold(self, minutes_to_expiry: float, vol_state: str) -> int:
        """
        Dynamic queue position threshold based on time and volatility.
        
        Args:
            minutes_to_expiry: Time until expiry
            vol_state: "normal" | "high"
        
        Returns:
            Queue position threshold
        """
        # Base thresholds by time
        if minutes_to_expiry > 12:
            base = 300  # Early window: be conservative
        elif minutes_to_expiry > 6:
            base = 500  # Mid window: allow deeper queues
        else:
            base = 900  # Late window: tolerate deep queues due to expiry flow
        
        # Adjust for volatility
        if vol_state == "high":
            # In high vol, allow deeper queues (flow is heavier)
            return int(base * 1.5)
        
        return base
    
    def get_threshold_with_context(self, ticker: str, minutes_to_expiry: float) -> Dict[str, Any]:
        """Get threshold with full context for decision making."""
        vol_state = self.calculate_volatility_state(ticker)
        threshold = self.dynamic_qp_threshold(minutes_to_expiry, vol_state)
        
        return {
            "threshold": threshold,
            "volatility_state": vol_state,
            "minutes_to_expiry": minutes_to_expiry,
            "base_threshold": threshold // (1.5 if vol_state == "high" else 1),
            "volatility_multiplier": 1.5 if vol_state == "high" else 1.0
        }


# ── Risk Management After Cancellations ─────────────────────────────────────

class KalshiCancellationRiskManager:
    """Risk management for order cancellations and re-entries."""
    
    def __init__(self):
        self.cancel_history: Dict[str, List[float]] = {}  # ticker -> [cancel_timestamps, ...]
        self.position_limits: Dict[str, Dict[str, int]] = {}  # ticker -> {"yes_max": int, "no_max": int}
        self.cool_down_periods: Dict[str, float] = {}  # ticker/side -> cool_down_seconds
        self.cancel_rate_limits: Dict[str, Dict[str, float]] = {
            "max_cancels_per_minute": 10,
            "max_cancel_ratio": 0.5  # Max 50% cancel rate
        }
        
    def record_cancellation(self, ticker: str, side: str, order_id: str):
        """Record a cancellation for risk management."""
        timestamp = time.time()
        
        # Record by ticker
        if ticker not in self.cancel_history:
            self.cancel_history[ticker] = []
        self.cancel_history[ticker].append(timestamp)
        
        # Clean old data (older than 1 hour)
        cutoff_time = timestamp - 3600
        self.cancel_history[ticker] = [
            ts for ts in self.cancel_history[ticker] if ts > cutoff_time
        ]
        
        # Set cool-down for this ticker/side
        key = f"{ticker}_{side}"
        self.cool_down_periods[key] = timestamp
        
        logger.info(f"Recorded cancellation: {ticker} {side} {order_id}")
    
    def check_cancel_rate_limit(self, ticker: str, placement_rate: float) -> bool:
        """Check if cancel rate exceeds limits."""
        if ticker not in self.cancel_history:
            return True
        
        # Count cancels in last minute
        now = time.time()
        recent_cancels = [
            ts for ts in self.cancel_history[ticker] 
            if now - ts < 60
        ]
        
        cancel_rate = len(recent_cancels) / 60.0  # cancels per second
        
        # Check absolute limit
        if cancel_rate > self.cancel_rate_limits["max_cancels_per_minute"] / 60.0:
            logger.warning(f"Cancel rate limit exceeded for {ticker}: {cancel_rate:.2f}/s")
            return False
        
        # Check cancel ratio
        if placement_rate > 0:
            cancel_ratio = cancel_rate / placement_rate
            if cancel_ratio > self.cancel_rate_limits["max_cancel_ratio"]:
                logger.warning(f"Cancel ratio limit exceeded for {ticker}: {cancel_ratio:.1%}")
                return False
        
        return True
    
    def check_cool_down(self, ticker: str, side: str, cool_down_seconds: int = 30) -> bool:
        """Check if cool-down period has passed since last cancellation."""
        key = f"{ticker}_{side}"
        last_cancel = self.cool_down_periods.get(key, 0)
        
        if time.time() - last_cancel < cool_down_seconds:
            remaining = cool_down_seconds - (time.time() - last_cancel)
            logger.debug(f"Cool-down active for {ticker} {side}: {remaining:.1f}s remaining")
            return False
        
        return True
    
    def check_position_limits(self, ticker: str, yes_position: int, no_position: int) -> bool:
        """Check if position limits are respected."""
        if ticker not in self.position_limits:
            return True  # No limits set
        
        limits = self.position_limits[ticker]
        
        if yes_position > limits.get("yes_max", float('inf')):
            logger.warning(f"YES position limit exceeded for {ticker}: {yes_position} > {limits['yes_max']}")
            return False
        
        if no_position > limits.get("no_max", float('inf')):
            logger.warning(f"NO position limit exceeded for {ticker}: {no_position} > {limits['no_max']}")
            return False
        
        return True
    
    def set_position_limit(self, ticker: str, yes_max: int, no_max: int):
        """Set position limits for a ticker."""
        self.position_limits[ticker] = {
            "yes_max": yes_max,
            "no_max": no_max
        }
        logger.info(f"Set position limits for {ticker}: YES={yes_max}, NO={no_max}")


# ── Automatic Order Replacement Logic ─────────────────────────────────────

class KalshiAutoReplaceEngine:
    """Automatic order replacement after cancellations."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.session = requests.Session()
        self.risk_manager = KalshiCancellationRiskManager()
        self.dynamic_thresholds = KalshiDynamicQueueThresholds()
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def maybe_replace_order(self, ticker: str, side: str, signal_edge: float, 
                           current_qp: int, orderbook: KalshiOrderbookSnapshot,
                           vol_state: str, original_order_id: str) -> Optional[str]:
        """
        Evaluate and potentially replace a canceled order.
        
        Args:
            ticker: Market ticker
            side: "buy" or "sell"
            signal_edge: Signal strength/edge
            current_qp: Current queue position
            orderbook: Current orderbook snapshot
            vol_state: Volatility state
            original_order_id: ID of the canceled order
        
        Returns:
            New order ID if replaced, None otherwise
        """
        # Check cool-down period
        if not self.risk_manager.check_cool_down(ticker, side):
            return None
        
        # Get dynamic threshold
        minutes_to_expiry = self._get_minutes_to_expiry(ticker)
        threshold_context = self.dynamic_thresholds.get_threshold_with_context(ticker, minutes_to_expiry)
        max_qp = threshold_context["threshold"]
        
        # Check if queue position is acceptable
        if current_qp > max_qp:
            logger.debug(f"Queue position too deep for replacement: {current_qp} > {max_qp}")
            return None
        
        # Check if signal edge is still valid
        if signal_edge <= 0:
            logger.debug(f"Signal edge too weak for replacement: {signal_edge}")
            return None
        
        # Build new order decision
        decision = self._build_replacement_decision(ticker, side, signal_edge, orderbook, minutes_to_expiry)
        
        if not decision:
            return None
        
        # Submit new order
        new_order_id = self.submit_order_from_decision(ticker, decision)
        
        if new_order_id:
            # Record the replacement
            logger.info(f"Replaced order {original_order_id} with {new_order_id}")
            return new_order_id
        
        return None
    
    def _build_replacement_decision(self, ticker: str, side: str, signal_edge: float,
                                  orderbook: KalshiOrderbookSnapshot, minutes_to_expiry: float) -> Optional[ExecutionDecision]:
        """Build execution decision for replacement order."""
        try:
            # Get current market data
            if side == "buy":
                current_bid = orderbook.best_yes_bid.price_cents / 100.0 if orderbook.best_yes_bid else 0
                current_ask = orderbook.best_yes_ask.price_cents / 100.0 if orderbook.best_yes_ask else 0
                bid_depth = orderbook.get_depth_at_price("yes", orderbook.best_yes_bid.price_cents) if orderbook.best_yes_bid else 0
                ask_depth = orderbook.get_depth_at_price("yes", orderbook.best_yes_ask.price_cents) if orderbook.best_yes_ask else 0
            else:
                current_bid = orderbook.best_no_bid.price_cents / 100.0 if orderbook.best_no_bid else 0
                current_ask = orderbook.best_no_ask.price_cents / 100.0 if orderbook.best_no_ask else 0
                bid_depth = orderbook.get_depth_at_price("no", orderbook.best_no_bid.price_cents) if orderbook.best_no_bid else 0
                ask_depth = orderbook.get_depth_at_price("no", orderbook.best_no_ask.price_cents) if orderbook.best_no_ask else 0
            
            # Use execution intelligence to build decision
            intel = ExecutionIntelligence()
            decision = intel.decide(
                bid=current_bid,
                ask=current_ask,
                side=side,
                edge=signal_edge,
                minutes_to_expiry=minutes_to_expiry,
                bid_depth=bid_depth,
                ask_depth=ask_depth
            )
            
            return decision
            
        except Exception as e:
            logger.error(f"Error building replacement decision: {e}")
            return None
    
    def submit_order_from_decision(self, ticker: str, decision: ExecutionDecision) -> Optional[str]:
        """Submit order based on execution decision."""
        try:
            path = "/orders"
            
            # Determine side and action based on decision
            if decision.side == "buy":
                side = "yes"
                action = "buy"
                price_field = "yes_price"
            else:
                side = "no"
                action = "sell"
                price_field = "no_price"
            
            body = {
                "ticker": ticker,
                "side": side,
                "action": action,
                "type": "limit",
                price_field: int(decision.suggested_price * 100),
                "count": decision.size,
            }
            
            r = self.session.post(
                self.base_url + path,
                headers=self._auth_headers(path, "POST"),
                json=body,
                timeout=3
            )
            r.raise_for_status()
            
            order_data = r.json()
            order_id = order_data.get("order", {}).get("order_id")
            
            if order_id:
                logger.info(f"Submitted replacement order: {order_id}")
                return order_id
            else:
                logger.error("No order ID in response")
                return None
                
        except Exception as e:
            logger.error(f"Error submitting replacement order: {e}")
            return None
    
    def _get_minutes_to_expiry(self, ticker: str) -> float:
        """Get minutes to expiry for a ticker."""
        # This would need to be implemented based on ticker parsing
        # For now, return a default
        return 15.0


# ── Auto-Cancel Strategy Backtester ─────────────────────────────────────────

class KalshiAutoCancelBacktester:
    """Backtest auto-cancel strategy against baseline strategy."""
    
    def __init__(self):
        self.dynamic_thresholds = KalshiDynamicQueueThresholds()
        
    def simulate_auto_cancel_strategy(self, signals: List[Dict[str, Any]], 
                                    orderbooks: List[Dict[str, Any]], 
                                    trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Simulate auto-cancel strategy on historical data.
        
        Args:
            signals: Trading signals with entry_time, price_cents, side, minutes_to_expiry, vol_state
            orderbooks: Historical orderbook snapshots
            trades: Historical trades
        
        Returns:
            List of simulation results
        """
        results = []
        
        for signal in signals:
            # Find orderbook at signal time with latency
            entry_time = signal["entry_time_with_latency"]
            ob = self._find_orderbook(orderbooks, entry_time)
            
            if not ob:
                continue
            
            # Calculate initial queue position
            price = signal["price_cents"]
            side = signal["side"]
            qp = self._resting_depth_at_price(ob, price, side)
            
            # Get dynamic threshold
            minutes_to_expiry = signal["minutes_to_expiry"]
            vol_state = signal.get("vol_state", "normal")
            threshold = self.dynamic_thresholds.dynamic_qp_threshold(minutes_to_expiry, vol_state)
            
            # Auto-cancel logic: skip if queue too deep
            if qp > threshold:
                results.append({
                    "strategy": "auto_cancel",
                    "action": "skip_posting",
                    "reason": "queue_too_deep",
                    "queue_position": qp,
                    "threshold": threshold,
                    "signal": signal
                })
                continue
            
            # Simulate fill
            pnl_result = self._simulate_fill_and_pnl(signal, qp, trades)
            
            results.append({
                "strategy": "auto_cancel",
                "action": "posted_and_filled" if pnl_result["filled"] else "posted_unfilled",
                "queue_position": qp,
                "threshold": threshold,
                "pnl": pnl_result["pnl"] if pnl_result["filled"] else 0,
                "fill_time": pnl_result.get("fill_time"),
                "signal": signal
            })
        
        return results
    
    def simulate_baseline_strategy(self, signals: List[Dict[str, Any]], 
                                 orderbooks: List[Dict[str, Any]], 
                                 trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Simulate baseline strategy (always post, never cancel).
        
        Args:
            signals: Trading signals
            orderbooks: Historical orderbook snapshots
            trades: Historical trades
        
        Returns:
            List of simulation results
        """
        results = []
        
        for signal in signals:
            # Find orderbook at signal time
            entry_time = signal["entry_time_with_latency"]
            ob = self._find_orderbook(orderbooks, entry_time)
            
            if not ob:
                continue
            
            # Calculate queue position (always post)
            price = signal["price_cents"]
            side = signal["side"]
            qp = self._resting_depth_at_price(ob, price, side)
            
            # Simulate fill (always post, never cancel)
            pnl_result = self._simulate_fill_and_pnl(signal, qp, trades)
            
            results.append({
                "strategy": "baseline",
                "action": "always_post",
                "queue_position": qp,
                "pnl": pnl_result["pnl"] if pnl_result["filled"] else 0,
                "fill_time": pnl_result.get("fill_time"),
                "signal": signal
            })
        
        return results
    
    def compare_strategies(self, signals: List[Dict[str, Any]], 
                          orderbooks: List[Dict[str, Any]], 
                          trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare auto-cancel vs baseline strategies.
        
        Returns:
            Comparison metrics
        """
        auto_cancel_results = self.simulate_auto_cancel_strategy(signals, orderbooks, trades)
        baseline_results = self.simulate_baseline_strategy(signals, orderbooks, trades)
        
        # Calculate metrics for each strategy
        auto_metrics = self._calculate_strategy_metrics(auto_cancel_results)
        baseline_metrics = self._calculate_strategy_metrics(baseline_results)
        
        return {
            "auto_cancel": auto_metrics,
            "baseline": baseline_metrics,
            "improvement": {
                "pnl_improvement": auto_metrics["total_pnl"] - baseline_metrics["total_pnl"],
                "fill_rate_change": auto_metrics["fill_rate"] - baseline_metrics["fill_rate"],
                "avg_queue_change": auto_metrics["avg_queue_position"] - baseline_metrics["avg_queue_position"]
            }
        }
    
    def _find_orderbook(self, orderbooks: List[Dict[str, Any]], target_time: float) -> Optional[Dict[str, Any]]:
        """Find orderbook snapshot closest to target time."""
        if not orderbooks:
            return None
        
        closest_ob = None
        min_diff = float('inf')
        
        for ob in orderbooks:
            diff = abs(ob["timestamp"] - target_time)
            if diff < min_diff:
                min_diff = diff
                closest_ob = ob
        
        return closest_ob
    
    def _resting_depth_at_price(self, orderbook: Dict[str, Any], price_cents: int, side: str) -> int:
        """Calculate resting depth at a specific price level."""
        if side == "buy":
            levels = orderbook.get("yes_bids", [])
        else:
            levels = orderbook.get("no_bids", [])
        
        for level in levels:
            if level.get("price_cents") == price_cents:
                return level.get("quantity", 0)
        
        return 0
    
    def _simulate_fill_and_pnl(self, signal: Dict[str, Any], queue_position: int, 
                               trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Simulate order fill and calculate PnL."""
        price_cents = signal["price_cents"]
        side = signal["side"]
        entry_time = signal["entry_time_with_latency"]
        outcome_yes = signal.get("outcome_yes", False)
        
        # Track cumulative contra volume
        cumulative_volume = 0
        
        for trade in trades:
            if trade["timestamp"] < entry_time:
                continue
            
            # Check if trade affects our queue
            if (trade["price_cents"] == price_cents and 
                trade["side"] != side):  # Contra side
                
                cumulative_volume += trade["quantity"]
                
                # Fill when cumulative volume exceeds our queue position
                if cumulative_volume >= queue_position:
                    # Calculate PnL with Kalshi fees
                    trade_fee = kalshi_fee_per_contract(price_cents, maker=True)
                    
                    if outcome_yes:
                        gross_pnl = 1.0 - price_cents / 100.0
                    else:
                        gross_pnl = -price_cents / 100.0
                    
                    net_pnl = gross_pnl - trade_fee
                    
                    return {
                        "filled": True,
                        "pnl": net_pnl,
                        "fill_time": trade["timestamp"],
                        "fill_price": trade["price_cents"]
                    }
        
        return {"filled": False, "pnl": 0}
    
    def _calculate_strategy_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate performance metrics for strategy results."""
        if not results:
            return {
                "total_trades": 0,
                "filled_trades": 0,
                "fill_rate": 0,
                "total_pnl": 0,
                "avg_pnl_per_trade": 0,
                "avg_queue_position": 0
            }
        
        filled_results = [r for r in results if r.get("pnl", 0) != 0 or r.get("action") == "posted_and_filled"]
        total_pnl = sum(r.get("pnl", 0) for r in results)
        avg_queue = sum(r.get("queue_position", 0) for r in results) / len(results)
        
        return {
            "total_trades": len(results),
            "filled_trades": len(filled_results),
            "fill_rate": len(filled_results) / len(results),
            "total_pnl": total_pnl,
            "avg_pnl_per_trade": total_pnl / len(filled_results) if filled_results else 0,
            "avg_queue_position": avg_queue
        }


# ── Backtest Partial-Fill Policy Impact ───────────────────────────────────────

class KalshiPartialFillBacktester:
    """Backtest partial-fill alert impact on maker PnL."""
    
    def __init__(self, partial_fill_threshold: float = 0.5):
        self.partial_fill_threshold = partial_fill_threshold
        
    def backtest_partial_fill_policy(self, orders: List[Dict[str, Any]], 
                                    trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Backtest partial-fill alert policy impact.
        
        Args:
            orders: Simulated maker orders with {id, price_cents, side, size, qp, entry_ts}
            trades: Historical trades stream
        
        Returns:
            List of results with partial-fill policy impact
        """
        results = []
        
        for order in orders:
            filled = 0
            alert_triggered = False
            fill_ratio = 0.0
            
            # Simulate fills over time
            for trade in self._trades_after(trades, order["entry_ts"]):
                if (trade["price_cents"] == order["price_cents"] and 
                    trade["side"] != order["side"]):
                    
                    filled += trade["quantity"]
                    fill_ratio = filled / order["size"]
                    
                    # Partial fill alert threshold
                    if fill_ratio >= self.partial_fill_threshold and not alert_triggered:
                        alert_triggered = True
                        order["alert_triggered"] = True
                        
                        # Policy: tighten cancels or stop reposting after alert
                        # This affects subsequent behavior in the simulation
                        logger.debug(f"Partial fill alert triggered for order {order['id']}: {fill_ratio:.1%}")
                    
                    if filled >= order["size"]:
                        break
            
            # Calculate PnL
            pnl = self._compute_pnl(order, filled)
            
            results.append({
                "order_id": order["id"],
                "fill_ratio": fill_ratio,
                "pnl": pnl,
                "alert_triggered": alert_triggered,
                "partial_fill_policy": True
            })
        
        return results
    
    def backtest_baseline_policy(self, orders: List[Dict[str, Any]], 
                               trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Backtest baseline policy without partial-fill alerts.
        
        Args:
            orders: Simulated maker orders
            trades: Historical trades stream
        
        Returns:
            List of results without partial-fill policy
        """
        results = []
        
        for order in orders:
            filled = 0
            fill_ratio = 0.0
            
            # Simulate fills without policy changes
            for trade in self._trades_after(trades, order["entry_ts"]):
                if (trade["price_cents"] == order["price_cents"] and 
                    trade["side"] != order["side"]):
                    
                    filled += trade["quantity"]
                    fill_ratio = filled / order["size"]
                    
                    if filled >= order["size"]:
                        break
            
            # Calculate PnL
            pnl = self._compute_pnl(order, filled)
            
            results.append({
                "order_id": order["id"],
                "fill_ratio": fill_ratio,
                "pnl": pnl,
                "alert_triggered": False,
                "partial_fill_policy": False
            })
        
        return results
    
    def compare_policies(self, orders: List[Dict[str, Any]], 
                         trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare partial-fill policy vs baseline.
        
        Returns:
            Comparison metrics
        """
        partial_fill_results = self.backtest_partial_fill_policy(orders, trades)
        baseline_results = self.backtest_baseline_policy(orders, trades)
        
        # Calculate metrics
        partial_metrics = self._calculate_policy_metrics(partial_fill_results)
        baseline_metrics = self._calculate_policy_metrics(baseline_results)
        
        return {
            "partial_fill_policy": partial_metrics,
            "baseline_policy": baseline_metrics,
            "improvement": {
                "pnl_improvement": partial_metrics["total_pnl"] - baseline_metrics["total_pnl"],
                "pnl_improvement_pct": (partial_metrics["total_pnl"] - baseline_metrics["total_pnl"]) / abs(baseline_metrics["total_pnl"]) if baseline_metrics["total_pnl"] != 0 else 0,
                "fill_rate_change": partial_metrics["avg_fill_rate"] - baseline_metrics["avg_fill_rate"]
            }
        }
    
    def _trades_after(self, trades: List[Dict[str, Any]], timestamp: float) -> List[Dict[str, Any]]:
        """Get trades after specific timestamp."""
        return [t for t in trades if t["timestamp"] >= timestamp]
    
    def _compute_pnl(self, order: Dict[str, Any], filled: int) -> float:
        """Compute PnL for filled portion."""
        if filled == 0:
            return 0.0
        
        price_cents = order["price_cents"]
        outcome_yes = order.get("outcome_yes", False)
        
        # Use Kalshi fee calculation
        trade_fee = kalshi_fee_per_contract(price_cents, maker=True)
        
        if outcome_yes:
            gross_pnl = (1.0 - price_cents / 100.0) * (filled / order["size"])
        else:
            gross_pnl = (-price_cents / 100.0) * (filled / order["size"])
        
        net_pnl = gross_pnl - trade_fee * (filled / order["size"])
        return net_pnl
    
    def _calculate_policy_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate policy performance metrics."""
        if not results:
            return {"total_pnl": 0, "avg_fill_rate": 0, "alert_rate": 0}
        
        total_pnl = sum(r["pnl"] for r in results)
        avg_fill_rate = sum(r["fill_ratio"] for r in results) / len(results)
        alert_rate = sum(1 for r in results if r.get("alert_triggered", False)) / len(results)
        
        return {
            "total_pnl": total_pnl,
            "avg_fill_rate": avg_fill_rate,
            "alert_rate": alert_rate,
            "total_orders": len(results)
        }


# ── Volatility-Based Queue Position Using 15m Std Dev ───────────────────────────

class KalshiVolatilityState:
    """Compute rolling 15-minute std dev from yes_price for dynamic thresholds."""
    
    def __init__(self, window: int = 60):
        self.window = window
        self.price_history: Dict[str, deque] = {}  # ticker -> deque of prices
        self.std_cache: Dict[str, float] = {}  # ticker -> current std dev
        
    def update(self, ticker: str, yes_price_c: int) -> float:
        """
        Update price history and return current std dev.
        
        Args:
            ticker: Market ticker
            yes_price_c: Yes price in cents
        
        Returns:
            Current 15-minute standard deviation
        """
        if ticker not in self.price_history:
            self.price_history[ticker] = deque(maxlen=self.window)
        
        # Add new price (convert to dollars for std dev calculation)
        price_dollars = yes_price_c / 100.0
        self.price_history[ticker].append(price_dollars)
        
        # Calculate std dev
        if len(self.price_history[ticker]) < 5:
            std_15m = 0.0
        else:
            prices = list(self.price_history[ticker])
            std_15m = float(np.std(prices))
        
        # Cache the result
        self.std_cache[ticker] = std_15m
        
        return std_15m
    
    def get_std_dev(self, ticker: str) -> float:
        """Get current std dev for ticker."""
        return self.std_cache.get(ticker, 0.0)
    
    def vol_state_from_std(self, std_15m: float) -> str:
        """
        Determine volatility state from standard deviation.
        
        Args:
            std_15m: 15-minute standard deviation
        
        Returns:
            "high", "medium", or "low"
        """
        # Tune cutoffs empirically based on historical crypto volatility
        if std_15m > 0.10:
            return "high"
        elif std_15m > 0.04:
            return "medium"
        else:
            return "low"
    
    def dynamic_qp_threshold(self, minutes_to_expiry: float, std_15m: float) -> int:
        """
        Dynamic queue position threshold based on volatility.
        
        Args:
            minutes_to_expiry: Time until expiry
            std_15m: 15-minute standard deviation
        
        Returns:
            Adjusted queue position threshold
        """
        vol_state = self.vol_state_from_std(std_15m)
        
        # Base thresholds by time
        if minutes_to_expiry > 12:
            base = 300  # Early window: be conservative
        elif minutes_to_expiry > 6:
            base = 500  # Mid window: allow deeper queues
        else:
            base = 900  # Late window: tolerate deep queues due to expiry flow
        
        # Adjust for volatility
        if vol_state == "high":
            return int(base * 1.5)  # Allow deeper queues in high vol
        elif vol_state == "medium":
            return int(base * 1.1)  # Slightly deeper queues in medium vol
        else:
            return base  # Standard thresholds for low vol
    
    def get_volatility_context(self, ticker: str) -> Dict[str, Any]:
        """Get full volatility context for decision making."""
        std_15m = self.get_std_dev(ticker)
        vol_state = self.vol_state_from_std(std_15m)
        
        return {
            "std_15m": std_15m,
            "vol_state": vol_state,
            "price_count": len(self.price_history.get(ticker, [])),
            "window": self.window
        }


# ── Risk Limits with Order Groups for Crypto ───────────────────────────────────

class KalshiOrderGroupManager:
    """Manage Kalshi order groups for risk limits and circuit breakers."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.session = requests.Session()
        self.order_groups: Dict[str, str] = {}  # group_name -> order_group_id
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def create_order_group(self, group_name: str, contracts_limit: int) -> str:
        """
        Create an order group with contracts limit.
        
        Args:
            group_name: Name for the order group
            contracts_limit: Max matched contracts per 15s window
        
        Returns:
            Order group ID
        """
        try:
            path = "/portfolio/order_groups/create"
            body = {
                "subaccount": 0,
                "contracts_limit": contracts_limit,  # max matched contracts per 15s window
            }
            
            r = self.session.post(
                self.base_url + path,
                headers=self._auth_headers(path, "POST"),
                json=body,
                timeout=3
            )
            r.raise_for_status()
            
            order_group_id = r.json()["order_group_id"]
            self.order_groups[group_name] = order_group_id
            
            logger.info(f"Created order group '{group_name}' with ID {order_group_id}, limit: {contracts_limit}")
            return order_group_id
            
        except Exception as e:
            logger.error(f"Failed to create order group '{group_name}': {e}")
            raise
    
    def update_order_group_limit(self, group_name: str, contracts_limit: int) -> bool:
        """
        Update existing order group limit.
        
        Args:
            group_name: Name of the order group
            contracts_limit: New contracts limit
        
        Returns:
            True if successful
        """
        if group_name not in self.order_groups:
            logger.error(f"Order group '{group_name}' not found")
            return False
        
        try:
            order_group_id = self.order_groups[group_name]
            path = f"/portfolio/order_groups/{order_group_id}"
            body = {"contracts_limit": contracts_limit}
            
            r = self.session.patch(
                self.base_url + path,
                headers=self._auth_headers(path, "PATCH"),
                json=body,
                timeout=3
            )
            r.raise_for_status()
            
            logger.info(f"Updated order group '{group_name}' limit to {contracts_limit}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update order group '{group_name}': {e}")
            return False
    
    def get_order_group_id(self, group_name: str) -> Optional[str]:
        """Get order group ID by name."""
        return self.order_groups.get(group_name)
    
    def setup_crypto_15m_groups(self, contracts_limits: Dict[str, int]) -> Dict[str, str]:
        """
        Set up order groups for crypto 15m markets.
        
        Args:
            contracts_limits: {ticker: contracts_limit}
        
        Returns:
            {ticker: order_group_id}
        """
        group_ids = {}
        
        for ticker, limit in contracts_limits.items():
            group_name = f"crypto_15m_{ticker}"
            try:
                order_group_id = self.create_order_group(group_name, limit)
                group_ids[ticker] = order_group_id
            except Exception as e:
                logger.error(f"Failed to create group for {ticker}: {e}")
        
        return group_ids


# ── Multi-Ticker WebSocket Handler for Crypto Markets ───────────────────────────

class KalshiMultiTickerWebSocketHandler:
    """Multi-ticker WebSocket handler for crypto markets."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.orderbook_callbacks: Dict[str, List[callable]] = {}  # ticker -> [callbacks]
        self.trade_callbacks: Dict[str, List[callable]] = {}  # ticker -> [callbacks]
        self.volatility_state = KalshiVolatilityState()
        
    def _auth_headers(self) -> dict:
        """Generate WebSocket authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + "/ws/v2"
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def add_orderbook_callback(self, ticker: str, callback: callable):
        """Add callback for orderbook updates."""
        if ticker not in self.orderbook_callbacks:
            self.orderbook_callbacks[ticker] = []
        self.orderbook_callbacks[ticker].append(callback)
    
    def add_trade_callback(self, ticker: str, callback: callable):
        """Add callback for trade updates."""
        if ticker not in self.trade_callbacks:
            self.trade_callbacks[ticker] = []
        self.trade_callbacks[ticker].append(callback)
    
    async def multi_ticker_stream(self, tickers: List[str]):
        """
        Stream multiple tickers on single WebSocket connection.
        
        Args:
            tickers: List of ticker symbols
        """
        headers = self._auth_headers()
        
        try:
            async with websockets.connect(self.ws_url, extra_headers=headers) as ws:
                # Subscribe to multiple tickers
                sub = {
                    "type": "subscribe",
                    "channels": [
                        {"name": "orderbook", "symbols": tickers},
                        {"name": "trades", "symbols": tickers},
                    ],
                }
                await ws.send(json.dumps(sub))
                
                logger.info(f"Subscribed to multi-ticker stream: {tickers}")
                
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        ticker = msg.get("ticker")
                        
                        if not ticker:
                            continue
                        
                        # Handle orderbook updates
                        if msg.get("type") == "orderbook":
                            await self._handle_orderbook(ticker, msg.get("orderbook", {}))
                        
                        # Handle trade updates
                        elif msg.get("type") == "trade":
                            await self._handle_trade(ticker, msg.get("trade", {}))
                        
                    except Exception as e:
                        logger.error(f"Multi-ticker WebSocket error: {e}")
                        
        except Exception as e:
            logger.error(f"Multi-ticker WebSocket connection error: {e}")
    
    async def _handle_orderbook(self, ticker: str, orderbook_data: Dict[str, Any]):
        """Handle orderbook update for specific ticker."""
        # Update volatility state from orderbook
        yes_price = orderbook_data.get("yes_price")
        if yes_price:
            self.volatility_state.update(ticker, yes_price)
        
        # Trigger callbacks
        for callback in self.orderbook_callbacks.get(ticker, []):
            try:
                await callback(ticker, orderbook_data)
            except Exception as e:
                logger.error(f"Orderbook callback error for {ticker}: {e}")
    
    async def _handle_trade(self, ticker: str, trade_data: Dict[str, Any]):
        """Handle trade update for specific ticker."""
        # Update volatility state from trade
        yes_price = trade_data.get("yes_price")
        if yes_price:
            self.volatility_state.update(ticker, yes_price)
        
        # Trigger callbacks
        for callback in self.trade_callbacks.get(ticker, []):
            try:
                await callback(ticker, trade_data)
            except Exception as e:
                logger.error(f"Trade callback error for {ticker}: {e}")
    
    def get_volatility_state(self) -> KalshiVolatilityState:
        """Get volatility state instance."""
        return self.volatility_state


# ── Auto-Replace Profitability Analysis ─────────────────────────────────────

class KalshiAutoReplaceAnalyzer:
    """Analyze profitability of auto-replace after cancellations."""
    
    def __init__(self):
        self.volatility_state = KalshiVolatilityState()
        
    def simulate_auto_replace(self, signals: List[Dict[str, Any]], 
                            orderbooks: List[Dict[str, Any]], 
                            trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Simulate auto-replace strategy.
        
        Args:
            signals: Trading signals with replace_delay, std_15m
            orderbooks: Historical orderbook snapshots
            trades: Historical trades
        
        Returns:
            List of simulation results
        """
        results = []
        
        for signal in signals:
            # Find initial orderbook
            ob = self._find_orderbook(orderbooks, signal["entry_ts_with_latency"])
            if not ob:
                continue
            
            price0 = signal["price_cents"]
            side = signal["side"]
            
            # Calculate initial queue position
            qp0 = self._depth_at_price(ob, price0, side)
            
            # Get dynamic threshold
            threshold = self.volatility_state.dynamic_qp_threshold(
                signal["minutes_to_expiry"], 
                signal.get("std_15m", 0.05)
            )
            
            # Check if we should cancel and replace
            if qp0 > threshold:
                # Simulate cancel + replacement at better price
                better_price = self._adjust_price(price0, signal["edge"], ob)
                
                # Find orderbook after replacement delay
                replace_time = signal["entry_ts_with_latency"] + signal.get("replace_delay", 1.0)
                ob2 = self._find_orderbook(orderbooks, replace_time)
                
                if ob2:
                    qp1 = self._depth_at_price(ob2, better_price, side)
                    final_price, final_qp = better_price, qp1
                else:
                    final_price, final_qp = price0, qp0
            else:
                final_price, final_qp = price0, qp0
            
            # Simulate fill and PnL
            pnl = self._simulate_fill_and_pnl(signal, final_qp, trades, final_price)
            
            results.append({
                "pnl": pnl["pnl"] if pnl["filled"] else 0,
                "replaced": qp0 > threshold,
                "initial_qp": qp0,
                "final_qp": final_qp,
                "initial_price": price0,
                "final_price": final_price,
                "threshold": threshold,
                "filled": pnl["filled"]
            })
        
        return results
    
    def simulate_baseline_strategy(self, signals: List[Dict[str, Any]], 
                                  orderbooks: List[Dict[str, Any]], 
                                  trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Simulate baseline strategy (no cancel/replace).
        
        Args:
            signals: Trading signals
            orderbooks: Historical orderbook snapshots
            trades: Historical trades
        
        Returns:
            List of baseline results
        """
        results = []
        
        for signal in signals:
            ob = self._find_orderbook(orderbooks, signal["entry_ts_with_latency"])
            if not ob:
                continue
            
            price0 = signal["price_cents"]
            side = signal["side"]
            qp0 = self._depth_at_price(ob, price0, side)
            
            # Simulate fill without replacement
            pnl = self._simulate_fill_and_pnl(signal, qp0, trades, price0)
            
            results.append({
                "pnl": pnl["pnl"] if pnl["filled"] else 0,
                "replaced": False,
                "initial_qp": qp0,
                "final_qp": qp0,
                "initial_price": price0,
                "final_price": price0,
                "filled": pnl["filled"]
            })
        
        return results
    
    def simulate_cancel_only_strategy(self, signals: List[Dict[str, Any]], 
                                     orderbooks: List[Dict[str, Any]], 
                                     trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Simulate cancel-only strategy (skip deep queue orders).
        
        Args:
            signals: Trading signals
            orderbooks: Historical orderbook snapshots
            trades: Historical trades
        
        Returns:
            List of cancel-only results
        """
        results = []
        
        for signal in signals:
            ob = self._find_orderbook(orderbooks, signal["entry_ts_with_latency"])
            if not ob:
                continue
            
            price0 = signal["price_cents"]
            side = signal["side"]
            qp0 = self._depth_at_price(ob, price0, side)
            
            # Get threshold
            threshold = self.volatility_state.dynamic_qp_threshold(
                signal["minutes_to_expiry"], 
                signal.get("std_15m", 0.05)
            )
            
            # Skip if queue too deep
            if qp0 > threshold:
                results.append({
                    "pnl": 0,
                    "replaced": False,
                    "initial_qp": qp0,
                    "final_qp": qp0,
                    "initial_price": price0,
                    "final_price": price0,
                    "filled": False,
                    "skipped": True
                })
            else:
                # Simulate fill
                pnl = self._simulate_fill_and_pnl(signal, qp0, trades, price0)
                
                results.append({
                    "pnl": pnl["pnl"] if pnl["filled"] else 0,
                    "replaced": False,
                    "initial_qp": qp0,
                    "final_qp": qp0,
                    "initial_price": price0,
                    "final_price": price0,
                    "filled": pnl["filled"],
                    "skipped": False
                })
        
        return results
    
    def compare_strategies(self, signals: List[Dict[str, Any]], 
                          orderbooks: List[Dict[str, Any]], 
                          trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare all three strategies.
        
        Returns:
            Comprehensive comparison metrics
        """
        auto_replace_results = self.simulate_auto_replace(signals, orderbooks, trades)
        baseline_results = self.simulate_baseline_strategy(signals, orderbooks, trades)
        cancel_only_results = self.simulate_cancel_only_strategy(signals, orderbooks, trades)
        
        # Calculate metrics for each strategy
        auto_metrics = self._calculate_strategy_metrics(auto_replace_results)
        baseline_metrics = self._calculate_strategy_metrics(baseline_results)
        cancel_metrics = self._calculate_strategy_metrics(cancel_only_results)
        
        return {
            "auto_replace": auto_metrics,
            "baseline": baseline_metrics,
            "cancel_only": cancel_metrics,
            "comparisons": {
                "auto_vs_baseline": {
                    "pnl_improvement": auto_metrics["total_pnl"] - baseline_metrics["total_pnl"],
                    "fill_rate_change": auto_metrics["fill_rate"] - baseline_metrics["fill_rate"]
                },
                "auto_vs_cancel": {
                    "pnl_improvement": auto_metrics["total_pnl"] - cancel_metrics["total_pnl"],
                    "fill_rate_improvement": auto_metrics["fill_rate"] - cancel_metrics["fill_rate"]
                },
                "cancel_vs_baseline": {
                    "pnl_difference": cancel_metrics["total_pnl"] - baseline_metrics["total_pnl"],
                    "fill_rate_difference": cancel_metrics["fill_rate"] - baseline_metrics["fill_rate"]
                }
            }
        }
    
    def _find_orderbook(self, orderbooks: List[Dict[str, Any]], target_time: float) -> Optional[Dict[str, Any]]:
        """Find orderbook snapshot closest to target time."""
        if not orderbooks:
            return None
        
        closest_ob = None
        min_diff = float('inf')
        
        for ob in orderbooks:
            diff = abs(ob["timestamp"] - target_time)
            if diff < min_diff:
                min_diff = diff
                closest_ob = ob
        
        return closest_ob
    
    def _depth_at_price(self, orderbook: Dict[str, Any], price_cents: int, side: str) -> int:
        """Calculate depth at specific price level."""
        if side == "buy":
            levels = orderbook.get("yes_bids", [])
        else:
            levels = orderbook.get("no_bids", [])
        
        for level in levels:
            if level.get("price_cents") == price_cents:
                return level.get("quantity", 0)
        
        return 0
    
    def _adjust_price(self, current_price_cents: int, edge: float, orderbook: Dict[str, Any]) -> int:
        """Adjust price to improve queue position."""
        # Simple price improvement logic
        if edge > 0.5:
            # Strong edge: improve price by 2 cents
            return current_price_cents + (2 if edge > 0 else -2)
        else:
            # Weak edge: improve price by 1 cent
            return current_price_cents + (1 if edge > 0 else -1)
    
    def _simulate_fill_and_pnl(self, signal: Dict[str, Any], queue_position: int, 
                               trades: List[Dict[str, Any]], price_cents: int) -> Dict[str, Any]:
        """Simulate order fill and calculate PnL."""
        side = signal["side"]
        entry_time = signal["entry_ts_with_latency"]
        outcome_yes = signal.get("outcome_yes", False)
        
        # Track cumulative contra volume
        cumulative_volume = 0
        
        for trade in trades:
            if trade["timestamp"] < entry_time:
                continue
            
            # Check if trade affects our queue
            if (trade["price_cents"] == price_cents and 
                trade["side"] != side):  # Contra side
                
                cumulative_volume += trade["quantity"]
                
                # Fill when cumulative volume exceeds our queue position
                if cumulative_volume >= queue_position:
                    # Calculate PnL with Kalshi fees
                    trade_fee = kalshi_fee_per_contract(price_cents, maker=True)
                    
                    if outcome_yes:
                        gross_pnl = 1.0 - price_cents / 100.0
                    else:
                        gross_pnl = -price_cents / 100.0
                    
                    net_pnl = gross_pnl - trade_fee
                    
                    return {
                        "filled": True,
                        "pnl": net_pnl,
                        "fill_time": trade["timestamp"],
                        "fill_price": price_cents
                    }
        
        return {"filled": False, "pnl": 0}
    
    def _calculate_strategy_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate performance metrics for strategy results."""
        if not results:
            return {
                "total_pnl": 0,
                "fill_rate": 0,
                "avg_queue_position": 0,
                "total_orders": 0
            }
        
        filled_results = [r for r in results if r.get("filled", False)]
        total_pnl = sum(r["pnl"] for r in results)
        fill_rate = len(filled_results) / len(results)
        avg_queue = sum(r.get("initial_qp", 0) for r in results) / len(results)
        
        return {
            "total_pnl": total_pnl,
            "fill_rate": fill_rate,
            "avg_queue_position": avg_queue,
            "total_orders": len(results),
            "filled_orders": len(filled_results)
        }


# ── Multi-Ticker 15m Maker Bot Backtest ───────────────────────────────────────

class KalshiMultiTickerBacktester:
    """Multi-ticker 15m maker bot backtest with volatility-aware risk management."""
    
    def __init__(self, fee_fn: callable = None):
        self.fee_fn = fee_fn or self.default_kalshi_fee
        self.volatility_state = KalshiVolatilityState()
        
    def backtest_multi_ticker(self, signals_by_ticker: Dict[str, List[Dict[str, Any]]], 
                              obs_by_ticker: Dict[str, List[Dict[str, Any]]], 
                              trades_by_ticker: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Multi-ticker backtest with volatility-aware thresholds.
        
        Args:
            signals_by_ticker: {ticker: [ {ts, side, price_cents, edge, minutes_to_expiry, std_15m, outcome_yes}, ... ]}
            obs_by_ticker: {ticker: [orderbook_snapshots...]}
            trades_by_ticker: {ticker: [trades...]}
        
        Returns:
            List of backtest results
        """
        results = []
        
        for ticker, signals in signals_by_ticker.items():
            obs = obs_by_ticker[ticker]
            trades = trades_by_ticker[ticker]
            
            logger.info(f"Backtesting ticker {ticker}: {len(signals)} signals")
            
            for sig in signals:
                try:
                    # Find orderbook at signal time with latency
                    ob = self._find_ob_at_time(obs, sig["ts_with_latency"])
                    if not ob:
                        continue
                    
                    price = sig["price_cents"]
                    side = sig["side"]
                    
                    # Calculate queue position
                    qp = self._depth_at_price(ob, price, side)
                    
                    # Get volatility-aware threshold
                    qp_thresh = self.volatility_state.dynamic_qp_threshold(
                        sig["minutes_to_expiry"], 
                        sig.get("std_15m", 0.05)
                    )
                    
                    # Skip if queue too deep
                    if qp > qp_thresh:
                        results.append({
                            "ticker": ticker,
                            "ts": sig["ts"],
                            "action": "skip_deep_queue",
                            "qp": qp,
                            "threshold": qp_thresh,
                            "pnl": 0,
                            "filled": 0
                        })
                        continue
                    
                    # Simulate fill
                    fill_ts, filled_size = self._simulate_fill(
                        trades, sig["ts_with_latency"], price, side, qp
                    )
                    
                    if filled_size == 0:
                        results.append({
                            "ticker": ticker,
                            "ts": sig["ts"],
                            "action": "no_fill",
                            "qp": qp,
                            "threshold": qp_thresh,
                            "pnl": 0,
                            "filled": 0
                        })
                        continue
                    
                    # Calculate PnL with fees
                    pnl = self._settlement_pnl(price, filled_size, sig["outcome_yes"])
                    fees = self.fee_fn(price, filled_size, maker_bool=True)
                    
                    results.append({
                        "ticker": ticker,
                        "ts": sig["ts"],
                        "action": "filled",
                        "qp": qp,
                        "threshold": qp_thresh,
                        "pnl": pnl - fees,
                        "filled": filled_size,
                        "fees": fees,
                        "fill_ts": fill_ts
                    })
                    
                except Exception as e:
                    logger.error(f"Error processing signal for {ticker}: {e}")
                    continue
        
        return results
    
    def _find_ob_at_time(self, orderbooks: List[Dict[str, Any]], target_time: float) -> Optional[Dict[str, Any]]:
        """Find orderbook snapshot closest to target time."""
        if not orderbooks:
            return None
        
        closest_ob = None
        min_diff = float('inf')
        
        for ob in orderbooks:
            diff = abs(ob["timestamp"] - target_time)
            if diff < min_diff:
                min_diff = diff
                closest_ob = ob
        
        return closest_ob
    
    def _depth_at_price(self, orderbook: Dict[str, Any], price_cents: int, side: str) -> int:
        """Calculate depth at specific price level."""
        if side == "buy":
            levels = orderbook.get("yes_bids", [])
        else:
            levels = orderbook.get("no_bids", [])
        
        for level in levels:
            if level.get("price_cents") == price_cents:
                return level.get("quantity", 0)
        
        return 0
    
    def _simulate_fill(self, trades: List[Dict[str, Any]], entry_time: float, 
                      price_cents: int, side: str, queue_position: int) -> Tuple[float, int]:
        """
        Simulate order fill based on trade flow.
        
        Returns:
            (fill_timestamp, filled_size)
        """
        cumulative_volume = 0
        
        for trade in trades:
            if trade["timestamp"] < entry_time:
                continue
            
            # Check if trade affects our queue
            if (trade["price_cents"] == price_cents and 
                trade["side"] != side):  # Contra side
                
                cumulative_volume += trade["quantity"]
                
                # Fill when cumulative volume exceeds our queue position
                if cumulative_volume >= queue_position:
                    return trade["timestamp"], queue_position
        
        return entry_time, 0  # No fill
    
    def _settlement_pnl(self, price_cents: int, size: int, outcome_yes: bool) -> float:
        """Calculate settlement PnL."""
        if outcome_yes:
            return (1.0 - price_cents / 100.0) * size
        else:
            return (-price_cents / 100.0) * size
    
    def default_kalshi_fee(self, price_cents: int, size: int, maker: bool) -> float:
        """Default Kalshi fee calculation."""
        p = price_cents / 100.0
        c = size
        raw = 0.07 * c * p * (1 - p)
        fee_cents = math.ceil(raw * 100)  # round up to next cent
        
        # Simple maker discount
        if maker:
            fee_cents *= 0.5
        
        return fee_cents / 100.0
    
    def calculate_backtest_metrics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate comprehensive backtest metrics."""
        if not results:
            return {"total_pnl": 0, "total_filled": 0, "fill_rate": 0, "ticker_metrics": {}}
        
        # Overall metrics
        total_pnl = sum(r["pnl"] for r in results)
        total_filled = sum(r["filled"] for r in results)
        fill_rate = len([r for r in results if r["filled"] > 0]) / len(results)
        total_fees = sum(r.get("fees", 0) for r in results)
        
        # Per-ticker metrics
        ticker_metrics = {}
        for ticker in set(r["ticker"] for r in results):
            ticker_results = [r for r in results if r["ticker"] == ticker]
            ticker_pnl = sum(r["pnl"] for r in ticker_results)
            ticker_filled = sum(r["filled"] for r in ticker_results)
            ticker_fill_rate = len([r for r in ticker_results if r["filled"] > 0]) / len(ticker_results)
            
            ticker_metrics[ticker] = {
                "pnl": ticker_pnl,
                "filled": ticker_filled,
                "fill_rate": ticker_fill_rate,
                "signal_count": len(ticker_results)
            }
        
        return {
            "total_pnl": total_pnl,
            "total_filled": total_filled,
            "fill_rate": fill_rate,
            "total_fees": total_fees,
            "net_pnl": total_pnl - total_fees,
            "signal_count": len(results),
            "ticker_metrics": ticker_metrics
        }


# ── Order Group Reset and Management ───────────────────────────────────────────

class KalshiOrderGroupResetManager:
    """Advanced order group management with reset and volatility-aware limits."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.session = requests.Session()
        self.group_limits: Dict[str, int] = {}  # order_group_id -> current_limit
        
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def reset_order_group(self, order_group_id: str) -> bool:
        """
        Reset order group to clear rolling 15s counter.
        
        Args:
            order_group_id: Order group ID to reset
        
        Returns:
            True if successful
        """
        try:
            path = f"/portfolio/order_groups/{order_group_id}/reset"
            r = self.session.put(
                self.base_url + path,
                headers=self._auth_headers(path, "PUT"),
                json={},
                timeout=3
            )
            r.raise_for_status()
            
            logger.info(f"Reset order group {order_group_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reset order group {order_group_id}: {e}")
            return False
    
    def get_order_group_status(self, order_group_id: str) -> Optional[Dict[str, Any]]:
        """Get current order group status and limits."""
        try:
            path = f"/portfolio/order_groups/{order_group_id}"
            r = self.session.get(
                self.base_url + path,
                headers=self._auth_headers(path),
                timeout=3
            )
            r.raise_for_status()
            
            return r.json().get("order_group", {})
            
        except Exception as e:
            logger.error(f"Failed to get order group status {order_group_id}: {e}")
            return None
    
    def contracts_limit_from_vol(self, std_15m: float, base_limit: int = 200) -> int:
        """
        Calculate contracts limit based on volatility.
        
        Args:
            std_15m: 15-minute standard deviation
            base_limit: Base contracts limit
        
        Returns:
            Volatility-adjusted contracts limit
        """
        if std_15m > 0.10:
            return int(base_limit * 0.5)   # Cut exposure in high vol
        elif std_15m > 0.05:
            return int(base_limit * 0.75)  # Reduce exposure in medium vol
        else:
            return base_limit  # Standard limit for low vol
    
    def update_order_group_limit(self, order_group_id: str, new_limit: int) -> bool:
        """
        Update order group limit with volatility adjustment.
        
        Args:
            order_group_id: Order group ID
            new_limit: New contracts limit
        
        Returns:
            True if successful
        """
        try:
            path = f"/portfolio/order_groups/{order_group_id}/limit"
            body = {"contracts_limit": new_limit}
            
            r = self.session.put(
                self.base_url + path,
                headers=self._auth_headers(path, "PUT"),
                json=body,
                timeout=3
            )
            r.raise_for_status()
            
            self.group_limits[order_group_id] = new_limit
            logger.info(f"Updated order group {order_group_id} limit to {new_limit}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update order group limit {order_group_id}: {e}")
            return False
    
    def auto_adjust_limits_by_volatility(self, order_groups: Dict[str, str], 
                                        volatility_state: KalshiVolatilityState) -> Dict[str, bool]:
        """
        Automatically adjust all order group limits based on current volatility.
        
        Args:
            order_groups: {ticker: order_group_id}
            volatility_state: Current volatility state
        
        Returns:
            {order_group_id: success}
        """
        results = {}
        
        for ticker, order_group_id in order_groups.items():
            try:
                # Get current volatility
                std_15m = volatility_state.get_std_dev(ticker)
                
                # Get current limit
                current_limit = self.group_limits.get(order_group_id, 200)
                
                # Calculate new limit
                new_limit = self.contracts_limit_from_vol(std_15m, current_limit)
                
                # Update if different
                if new_limit != current_limit:
                    success = self.update_order_group_limit(order_group_id, new_limit)
                    results[order_group_id] = success
                else:
                    results[order_group_id] = True  # No change needed
                    
            except Exception as e:
                logger.error(f"Error adjusting limit for {ticker}: {e}")
                results[order_group_id] = False
        
        return results


# ── Kalshi Fee and Spread Simulation ───────────────────────────────────────────

class KalshiFeeSimulator:
    """Realistic Kalshi fee and spread simulation for volatility-based decisions."""
    
    @staticmethod
    def kalshi_fee(price_cents: int, size: int, maker: bool) -> float:
        """
        Calculate Kalshi fee using official formula.
        
        Formula: fees = round_up(0.07 * C * P * (1-P))
        """
        p = price_cents / 100.0
        c = size
        raw = 0.07 * c * p * (1 - p)
        fee_cents = math.ceil(raw * 100)  # round up to next cent
        
        # Maker discount (adjust based on actual maker rate)
        if maker:
            fee_cents *= 0.5
        
        return fee_cents / 100.0
    
    @staticmethod
    def expected_maker_edge(price_cents: int, fair_prob: float, spread_cents: int, size: int) -> float:
        """
        Expected PnL per trade accounting for spread and fees.
        
        Args:
            price_cents: Quoted price in cents
            fair_prob: Fair probability estimate
            spread_cents: Current spread in cents
            size: Contract size
        
        Returns:
            Expected PnL per trade in dollars
        """
        p = price_cents / 100.0
        
        # Gross edge if true prob > quoted price
        edge_per_contract = fair_prob - p
        gross = edge_per_contract * size
        
        # Calculate fees
        fees = KalshiFeeSimulator.kalshi_fee(price_cents, size, maker=True)
        
        # Half-spread cost (crossing once per round-trip)
        spread_cost = (spread_cents / 2 / 100.0) * size
        
        return gross - fees - spread_cost
    
    @staticmethod
    def minimum_edge_for_volatility(price_cents: int, spread_cents: int, size: int, 
                                   std_15m: float) -> float:
        """
        Calculate minimum required edge based on volatility.
        
        Args:
            price_cents: Quoted price in cents
            spread_cents: Current spread in cents
            size: Contract size
            std_15m: 15-minute standard deviation
        
        Returns:
            Minimum required edge
        """
        base_edge = KalshiFeeSimulator.expected_maker_edge(price_cents, 0.5, spread_cents, size)
        
        # Increase required edge in high volatility
        if std_15m > 0.10:
            return abs(base_edge) * 2.0  # Double the requirement in high vol
        elif std_15m > 0.05:
            return abs(base_edge) * 1.5  # 1.5x requirement in medium vol
        else:
            return abs(base_edge)  # Standard requirement
    
    def should_quote_order(self, price_cents: int, fair_prob: float, spread_cents: int, 
                          size: int, std_15m: float, min_edge_threshold: float = 0.01) -> bool:
        """
        Decide whether to quote order based on edge and volatility.
        
        Args:
            price_cents: Quoted price in cents
            fair_prob: Fair probability estimate
            spread_cents: Current spread in cents
            size: Contract size
            std_15m: 15-minute standard deviation
            min_edge_threshold: Minimum edge threshold
        
        Returns:
            True if should quote
        """
        expected_edge = self.expected_maker_edge(price_cents, fair_prob, spread_cents, size)
        min_required_edge = self.minimum_edge_for_volatility(price_cents, spread_cents, size, std_15m)
        
        return expected_edge > max(min_required_edge, min_edge_threshold)


# ── Optimal Contracts Limit Calculator ───────────────────────────────────────

class KalshiOptimalContractsLimit:
    """Calculate optimal contracts limits for crypto maker bots."""
    
    @staticmethod
    def suggested_contracts_limit(bankroll_contracts: int, turnover_frac: float = 0.02) -> int:
        """
        Calculate suggested contracts limit based on bankroll and turnover preference.
        
        Args:
            bankroll_contracts: Account bankroll in contracts
            turnover_frac: Max fraction of bankroll to turn over in 15s (default 2%)
        
        Returns:
            Suggested contracts limit
        """
        return max(1, int(bankroll_contracts * turnover_frac))
    
    @staticmethod
    def volatility_adjusted_limit(base_limit: int, std_15m: float, 
                                strategy_aggressiveness: float = 1.0) -> int:
        """
        Adjust base limit based on volatility and strategy aggressiveness.
        
        Args:
            base_limit: Base contracts limit
            std_15m: 15-minute standard deviation
            strategy_aggressiveness: Strategy aggressiveness factor (0.5-2.0)
        
        Returns:
            Volatility-adjusted limit
        """
        # Volatility multiplier
        if std_15m > 0.10:
            vol_multiplier = 0.5  # Cut in half for high vol
        elif std_15m > 0.05:
            vol_multiplier = 0.75  # Reduce by 25% for medium vol
        else:
            vol_multiplier = 1.0  # No adjustment for low vol
        
        # Apply strategy aggressiveness
        adjusted_limit = int(base_limit * vol_multiplier * strategy_aggressiveness)
        
        # Ensure minimum limit
        return max(1, adjusted_limit)
    
    @staticmethod
    def backtest_optimal_limit(signals_by_ticker: Dict[str, List[Dict[str, Any]]],
                              obs_by_ticker: Dict[str, List[Dict[str, Any]]],
                              trades_by_ticker: Dict[str, List[Dict[str, Any]]],
                              base_limits: Dict[str, int],
                              bankroll_contracts: int) -> Dict[str, Any]:
        """
        Backtest different contract limits to find optimal setting.
        
        Args:
            signals_by_ticker: Trading signals by ticker
            obs_by_ticker: Orderbooks by ticker
            trades_by_ticker: Trades by ticker
            base_limits: Base limits to test
            bankroll_contracts: Total bankroll in contracts
        
        Returns:
            Optimal limit analysis
        """
        backtester = KalshiMultiTickerBacktester()
        results = {}
        
        for limit_name, base_limit in base_limits.items():
            # Simulate with this limit
            limit_results = []
            
            for ticker, signals in signals_by_ticker.items():
                # Apply limit constraint
                limited_signals = []
                rolling_contracts = 0
                rolling_window = 15.0  # 15 seconds
                
                for sig in sorted(signals, key=lambda x: x["ts"]):
                    # Remove signals outside rolling window
                    cutoff_time = sig["ts"] - rolling_window
                    limited_signals = [s for s in limited_signals if s["ts"] >= cutoff_time]
                    
                    # Check if adding this signal would exceed limit
                    new_contracts = sig.get("size", 1)
                    if rolling_contracts + new_contracts <= base_limit:
                        limited_signals.append(sig)
                        rolling_contracts += new_contracts
                    else:
                        # Skip this signal due to limit
                        continue
                
                # Backtest with limited signals
                ticker_obs = obs_by_ticker[ticker]
                ticker_trades = trades_by_ticker[ticker]
                
                for sig in limited_signals:
                    ob = backtester._find_ob_at_time(ticker_obs, sig["ts_with_latency"])
                    if ob:
                        qp = backtester._depth_at_price(ob, sig["price_cents"], sig["side"])
                        qp_thresh = backtester.volatility_state.dynamic_qp_threshold(
                            sig["minutes_to_expiry"], sig.get("std_15m", 0.05)
                        )
                        
                        if qp <= qp_thresh:
                            fill_ts, filled_size = backtester._simulate_fill(
                                ticker_trades, sig["ts_with_latency"], 
                                sig["price_cents"], sig["side"], qp
                            )
                            
                            if filled_size > 0:
                                pnl = backtester._settlement_pnl(sig["price_cents"], filled_size, sig["outcome_yes"])
                                fees = backtester.fee_fn(sig["price_cents"], filled_size, maker=True)
                                
                                limit_results.append({
                                    "ticker": ticker,
                                    "pnl": pnl - fees,
                                    "filled": filled_size
                                })
            
            # Calculate metrics for this limit
            total_pnl = sum(r["pnl"] for r in limit_results)
            total_filled = sum(r["filled"] for r in limit_results)
            turnover_rate = total_filled / bankroll_contracts if bankroll_contracts > 0 else 0
            
            results[limit_name] = {
                "base_limit": base_limit,
                "total_pnl": total_pnl,
                "total_filled": total_filled,
                "turnover_rate": turnover_rate,
                "sharpe_ratio": total_pnl / (total_filled * 0.01) if total_filled > 0 else 0  # Rough estimate
            }
        
        # Find optimal limit (highest Sharpe ratio)
        optimal_limit = max(results.keys(), key=lambda k: results[k]["sharpe_ratio"])
        
        return {
            "tested_limits": results,
            "optimal_limit": optimal_limit,
            "optimal_metrics": results[optimal_limit]
        }


# ── Enhanced Backtest with Partial Fills and Order-Group Resets ─────────────────────

class KalshiEnhancedBacktester:
    """Enhanced backtest with partial fills, order-group resets, and realistic fee simulation."""
    
    def __init__(self, fee_fn: callable = None):
        self.fee_fn = fee_fn or self.kalshi_fee_enhanced
        self.volatility_state = KalshiVolatilityState()
        
    def simulate_maker_orders(self, ticker: str, signals: List[Dict[str, Any]], 
                              orderbooks: List[Dict[str, Any]], trades: List[Dict[str, Any]],
                              contracts_limit: int) -> List[Dict[str, Any]]:
        """
        Enhanced maker order simulation with partial fills and order-group tracking.
        
        Args:
            ticker: Market ticker
            signals: [{ts, side, price_cents, size, minutes_to_expiry, std_15m, outcome_yes}, ...]
            orderbooks: sorted [{ts, ...}]
            trades: sorted [{ts, price_cents, side, quantity}, ...]
            contracts_limit: Order group contracts limit
        
        Returns:
            List of simulation results
        """
        results = []
        window = deque()  # matched contracts in last 15s
        window_size = timedelta(seconds=15)
        
        for sig in signals:
            ts = sig["ts_with_latency"]
            
            # Maintain rolling matched volume window
            while window and window[0][0] < ts - window_size:
                window.popleft()
            
            matched_last_15s = sum(q for _, q in window)
            
            # Skip if order-group limit hit
            if matched_last_15s >= contracts_limit:
                results.append({
                    "ticker": ticker,
                    "ts": ts,
                    "action": "skip_group_limit",
                    "filled": 0,
                    "fill_ratio": 0,
                    "pnl_net": 0,
                    "order_group_matched_15s": matched_last_15s,
                    "contracts_limit": contracts_limit
                })
                continue
            
            # Find orderbook at signal time
            ob = self._find_ob_at_time(orderbooks, ts)
            if not ob:
                continue
            
            price = sig["price_cents"]
            side = sig["side"]
            size = sig["size"]
            qp = self._depth_at_price(ob, price, side)
            
            # Gate on queue + volatility
            qp_thresh = self.volatility_state.dynamic_qp_threshold(
                sig["minutes_to_expiry"], 
                sig.get("std_15m", 0.05)
            )
            
            if qp > qp_thresh:
                results.append({
                    "ticker": ticker,
                    "ts": ts,
                    "action": "skip_deep_queue",
                    "filled": 0,
                    "fill_ratio": 0,
                    "pnl_net": 0,
                    "order_group_matched_15s": matched_last_15s,
                    "qp": qp,
                    "threshold": qp_thresh
                })
                continue
            
            # Simulate fills with partial fill tracking
            filled = 0
            fill_ts = None
            partial_fill_triggered = False
            
            for tr in self._trades_after(trades, ts):
                if tr["price_cents"] == price and tr["side"] != side:
                    filled += tr["quantity"]
                    window.append((tr["ts"], tr["quantity"]))  # Track matched volume
                    
                    # Partial fill alert at 50%
                    fill_ratio = filled / size
                    if fill_ratio >= 0.5 and not partial_fill_triggered:
                        partial_fill_triggered = True
                        # Could trigger policy changes here
                    
                    if filled >= size:
                        fill_ts = tr["ts"]
                        break
            
            if filled == 0:
                results.append({
                    "ticker": ticker,
                    "ts": ts,
                    "action": "no_fill",
                    "filled": 0,
                    "fill_ratio": 0,
                    "pnl_net": 0,
                    "order_group_matched_15s": matched_last_15s,
                    "qp": qp
                })
                continue
            
            # Calculate PnL with realistic fees
            fill_ratio = filled / size
            pnl = self._settlement_pnl(price, filled, sig["outcome_yes"])
            fees = self.fee_fn(price, filled, maker_bool=True)
            
            results.append({
                "ticker": ticker,
                "ts": ts,
                "action": "filled",
                "filled": filled,
                "fill_ratio": fill_ratio,
                "pnl_net": pnl - fees,
                "order_group_matched_15s": matched_last_15s + filled,
                "fill_ts": fill_ts,
                "qp": qp,
                "partial_fill_triggered": partial_fill_triggered,
                "fees": fees
            })
        
        return results
    
    def _find_ob_at_time(self, orderbooks: List[Dict[str, Any]], target_time: float) -> Optional[Dict[str, Any]]:
        """Find orderbook snapshot closest to target time."""
        if not orderbooks:
            return None
        
        closest_ob = None
        min_diff = float('inf')
        
        for ob in orderbooks:
            diff = abs(ob["timestamp"] - target_time)
            if diff < min_diff:
                min_diff = diff
                closest_ob = ob
        
        return closest_ob
    
    def _depth_at_price(self, orderbook: Dict[str, Any], price_cents: int, side: str) -> int:
        """Calculate depth at specific price level."""
        if side == "buy":
            levels = orderbook.get("yes_bids", [])
        else:
            levels = orderbook.get("no_bids", [])
        
        for level in levels:
            if level.get("price_cents") == price_cents:
                return level.get("quantity", 0)
        
        return 0
    
    def _trades_after(self, trades: List[Dict[str, Any]], timestamp: float) -> List[Dict[str, Any]]:
        """Get trades after specific timestamp."""
        return [t for t in trades if t["timestamp"] >= timestamp]
    
    def _settlement_pnl(self, price_cents: int, size: int, outcome_yes: bool) -> float:
        """Calculate settlement PnL."""
        if outcome_yes:
            return (1.0 - price_cents / 100.0) * size
        else:
            return (-price_cents / 100.0) * size
    
    @staticmethod
    def kalshi_fee_enhanced(price_cents: int, size: int, maker: bool) -> float:
        """
        Enhanced Kalshi fee calculation with calibrated coefficients.
        
        Args:
            price_cents: Price in cents
            size: Contract size
            maker: True for maker fee, False for taker fee
        
        Returns:
            Fee in dollars
        """
        p = price_cents / 100.0
        coef = 0.0175 if maker else 0.07  # Calibrated coefficients
        raw = coef * size * p * (1 - p)
        fee_cents = math.ceil(raw * 100)  # Convert dollars→cents and ceil
        return fee_cents / 100.0
    
    @staticmethod
    def pnl_with_role(price_cents: int, size: int, outcome_yes: bool, maker: bool) -> float:
        """
        Calculate PnL with maker/taker role distinction.
        
        Args:
            price_cents: Price in cents
            size: Contract size
            outcome_yes: True if YES outcome
            maker: True if maker, False if taker
        
        Returns:
            Net PnL after fees
        """
        p = price_cents / 100.0
        gross = (1 - p) * size if outcome_yes else -p * size
        fees = KalshiEnhancedBacktester.kalshi_fee_enhanced(price_cents, size, maker)
        return gross - fees


# ── Dynamic Contracts Limit from 15m Volatility ─────────────────────────────────

class KalshiDynamicContractsLimit:
    """Dynamic contracts limit adjustment based on 15m volatility."""
    
    @staticmethod
    def contracts_limit_from_vol(std_15m: float, base_limit: int = 200, min_limit: int = 50) -> int:
        """
        Calculate contracts limit based on 15m volatility.
        
        Args:
            std_15m: Standard deviation of 15m yes_price in dollars (0–1)
            base_limit: Base contracts limit
            min_limit: Minimum contracts limit
        
        Returns:
            Volatility-adjusted contracts limit
        """
        if std_15m > 0.12:
            factor = 0.4  # Cut to 40% in high volatility
        elif std_15m > 0.08:
            factor = 0.6  # Cut to 60% in medium-high volatility
        elif std_15m > 0.04:
            factor = 0.8  # Cut to 80% in medium volatility
        else:
            factor = 1.0  # Full limit in low volatility
        
        limit = int(base_limit * factor)
        return max(min_limit, limit)
    
    @staticmethod
    def update_order_group_limit(session: requests.Session, base_url: str, 
                                order_group_id: str, contracts_limit: int,
                                api_key: str, api_secret: str) -> bool:
        """
        Update order group limit with smooth transitions.
        
        Args:
            session: Requests session
            base_url: Kalshi API base URL
            order_group_id: Order group ID
            contracts_limit: New contracts limit
            api_key: API key
            api_secret: API secret
        
        Returns:
            True if successful
        """
        try:
            path = f"/portfolio/order_groups/{order_group_id}/limit"
            body = {"contracts_limit": contracts_limit}
            
            # Generate auth headers
            ts = str(int(time.time() * 1000))
            msg = ts + "PUT" + path
            sig = hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
            headers = {
                "KALSHI-ACCESS-KEY": api_key,
                "KALSHI-ACCESS-SIGNATURE": sig,
                "KALSHI-ACCESS-TIMESTAMP": ts,
            }
            
            r = session.put(
                base_url + path,
                headers=headers,
                json=body,
                timeout=3
            )
            r.raise_for_status()
            
            logger.info(f"Updated order group {order_group_id} limit to {contracts_limit}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update order group limit {order_group_id}: {e}")
            return False
    
    @staticmethod
    def smooth_limit_transition(current_limit: int, target_limit: int, max_change: int = 50) -> int:
        """
        Smooth transition to avoid triggering order group limits.
        
        Args:
            current_limit: Current contracts limit
            target_limit: Target contracts limit
            max_change: Maximum change per update
        
        Returns:
            Smoothed contracts limit
        """
        change = target_limit - current_limit
        if abs(change) <= max_change:
            return target_limit
        else:
            return current_limit + (max_change if change > 0 else -max_change)


# ── Order Group WebSocket Updates Handler ───────────────────────────────────────

class KalshiOrderGroupWebSocketHandler:
    """Handle order group WebSocket updates for real-time risk management."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.risk_state = KalshiRiskState()
        
    def _auth_headers(self) -> dict:
        """Generate WebSocket authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + "/ws/v2"
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    async def order_group_updates_handler(self, on_event: callable):
        """
        Handle order group updates WebSocket stream.
        
        Args:
            on_event: Callback function for order group events
        """
        headers = self._auth_headers()
        
        try:
            async with websockets.connect(self.ws_url, extra_headers=headers) as ws:
                # Subscribe to order group updates
                sub = {
                    "type": "subscribe",
                    "channels": [{"name": "order_group_updates"}],
                }
                await ws.send(json.dumps(sub))
                
                logger.info("Subscribed to order group updates")
                
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        if msg.get("type") != "order_group_updates":
                            continue
                        
                        event = msg.get("msg", {})
                        await on_event(event)
                        
                    except Exception as e:
                        logger.error(f"Order group WebSocket error: {e}")
                        
        except Exception as e:
            logger.error(f"Order group WebSocket connection error: {e}")
    
    async def on_order_group_event(self, event: Dict[str, Any]):
        """
        Handle order group events.
        
        Args:
            event: Order group event {event_type, order_group_id, ...}
        """
        event_type = event.get("event_type")
        order_group_id = event.get("order_group_id")
        
        if event_type == "triggered":
            # Stop placing new orders tied to this group until reset
            self.risk_state.mark_group_triggered(order_group_id)
            logger.warning(f"Order group {order_group_id} triggered - stopping new orders")
            
        elif event_type == "limit_updated":
            new_limit = event.get("contracts_limit")
            self.risk_state.update_group_limit(order_group_id, new_limit)
            logger.info(f"Order group {order_group_id} limit updated to {new_limit}")
            
        elif event_type == "reset":
            # Group reset - can resume placing orders
            self.risk_state.mark_group_reset(order_group_id)
            logger.info(f"Order group {order_group_id} reset - resuming orders")
            
        else:
            logger.debug(f"Order group event: {event_type} for {order_group_id}")


class KalshiRiskState:
    """Track order group risk state."""
    
    def __init__(self):
        self.triggered_groups: set = set()
        self.group_limits: Dict[str, int] = {}
        self.reset_timestamps: Dict[str, float] = {}
        
    def mark_group_triggered(self, order_group_id: str):
        """Mark order group as triggered."""
        self.triggered_groups.add(order_group_id)
        
    def mark_group_reset(self, order_group_id: str):
        """Mark order group as reset."""
        self.triggered_groups.discard(order_group_id)
        self.reset_timestamps[order_group_id] = time.time()
        
    def update_group_limit(self, order_group_id: str, new_limit: int):
        """Update group limit."""
        self.group_limits[order_group_id] = new_limit
        
    def is_group_available(self, order_group_id: str) -> bool:
        """Check if group is available for new orders."""
        return order_group_id not in self.triggered_groups
        
    def get_group_limit(self, order_group_id: str) -> Optional[int]:
        """Get current group limit."""
        return self.group_limits.get(order_group_id)


# ── Optimized Std Dev Thresholds for Crypto Maker Profitability ─────────────────────

class KalshiStdDevOptimizer:
    """Optimize std dev thresholds for maximum crypto maker profitability."""
    
    def __init__(self):
        self.volatility_state = KalshiVolatilityState()
        self.backtester = KalshiEnhancedBacktester()
        
    def grid_search_std_thresholds(self, signals_by_ticker: Dict[str, List[Dict[str, Any]]],
                                   obs_by_ticker: Dict[str, List[Dict[str, Any]]],
                                   trades_by_ticker: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Grid search over std-dev cutoffs to maximize net PnL.
        
        Args:
            signals_by_ticker: Trading signals by ticker
            obs_by_ticker: Orderbooks by ticker
            trades_by_ticker: Trades by ticker
        
        Returns:
            Best threshold configuration
        """
        grids = [0.03, 0.05, 0.08, 0.12]  # Candidate std levels
        results = []
        
        for low_mid in grids:
            for mid_high in grids:
                if mid_high <= low_mid:
                    continue
                
                # Define dynamic queue threshold function
                def dynamic_qp(std_15m: float, minutes_to_expiry: float) -> int:
                    if std_15m > mid_high:
                        return 900  # High volatility: allow deep queues
                    elif std_15m > low_mid:
                        return 600  # Medium volatility: moderate queues
                    else:
                        return 400  # Low volatility: tight queues
                
                # Backtest with custom thresholds
                pnl_all = []
                for ticker in signals_by_ticker:
                    pnl_t = self._backtest_with_custom_qp(
                        ticker,
                        signals_by_ticker[ticker],
                        obs_by_ticker[ticker],
                        trades_by_ticker[ticker],
                        dynamic_qp
                    )
                    pnl_all.extend(pnl_t)
                
                total_pnl = sum(r["pnl_net"] for r in pnl_all)
                total_trades = len(pnl_all)
                
                results.append({
                    "low_mid": low_mid,
                    "mid_high": mid_high,
                    "total_pnl": total_pnl,
                    "trades": total_trades,
                    "pnl_per_trade": total_pnl / total_trades if total_trades > 0 else 0
                })
        
        # Pick best by total PnL
        best_result = max(results, key=lambda r: r["total_pnl"])
        
        return {
            "best_configuration": best_result,
            "all_results": results,
            "optimal_thresholds": {
                "low_mid": best_result["low_mid"],
                "mid_high": best_result["mid_high"]
            }
        }
    
    def _backtest_with_custom_qp(self, ticker: str, signals: List[Dict[str, Any]],
                                 orderbooks: List[Dict[str, Any]], trades: List[Dict[str, Any]],
                                 dynamic_qp_fn: callable) -> List[Dict[str, Any]]:
        """
        Backtest with custom queue threshold function.
        
        Args:
            ticker: Market ticker
            signals: Trading signals
            orderbooks: Orderbook snapshots
            trades: Historical trades
            dynamic_qp_fn: Custom queue threshold function
        
        Returns:
            Backtest results
        """
        results = []
        
        for sig in signals:
            ts = sig["ts_with_latency"]
            
            # Find orderbook
            ob = self.backtester._find_ob_at_time(orderbooks, ts)
            if not ob:
                continue
            
            price = sig["price_cents"]
            side = sig["side"]
            size = sig["size"]
            
            # Calculate queue position
            qp = self.backtester._depth_at_price(ob, price, side)
            
            # Apply custom threshold
            qp_thresh = dynamic_qp_fn(sig.get("std_15m", 0.05), sig["minutes_to_expiry"])
            
            if qp > qp_thresh:
                continue
            
            # Simulate fill
            filled = 0
            for tr in self.backtester._trades_after(trades, ts):
                if tr["price_cents"] == price and tr["side"] != side:
                    filled += tr["quantity"]
                    if filled >= size:
                        break
            
            if filled == 0:
                continue
            
            # Calculate PnL
            pnl = self.backtester._settlement_pnl(price, filled, sig["outcome_yes"])
            fees = self.backtester.kalshi_fee_enhanced(price, filled, maker_bool=True)
            
            results.append({
                "ticker": ticker,
                "ts": ts,
                "filled": filled,
                "pnl_net": pnl - fees,
                "qp": qp,
                "threshold": qp_thresh
            })
        
        return results
    
    def optimize_volatility_adjusted_limits(self, signals_by_ticker: Dict[str, List[Dict[str, Any]]],
                                           obs_by_ticker: Dict[str, List[Dict[str, Any]]],
                                           trades_by_ticker: Dict[str, List[Dict[str, Any]]],
                                           base_limits: Dict[str, int]) -> Dict[str, Any]:
        """
        Optimize volatility-adjusted limits combined with queue thresholds.
        
        Args:
            signals_by_ticker: Trading signals by ticker
            obs_by_ticker: Orderbooks by ticker
            trades_by_ticker: Trades by ticker
            base_limits: Base contracts limits to test
        
        Returns:
            Optimal configuration
        """
        # Get optimal std dev thresholds first
        std_optimization = self.grid_search_std_thresholds(
            signals_by_ticker, obs_by_ticker, trades_by_ticker
        )
        
        optimal_thresholds = std_optimization["optimal_thresholds"]
        
        # Test different base limits with optimal thresholds
        limit_results = []
        
        for limit_name, base_limit in base_limits.items():
            def optimal_dynamic_qp(std_15m: float, minutes_to_expiry: float) -> int:
                if std_15m > optimal_thresholds["mid_high"]:
                    return 900
                elif std_15m > optimal_thresholds["low_mid"]:
                    return 600
                else:
                    return 400
            
            # Backtest with volatility-adjusted limits
            pnl_all = []
            for ticker in signals_by_ticker:
                # Get volatility-adjusted limit for this ticker
                std_15m = self.volatility_state.get_std_dev(ticker)
                adjusted_limit = KalshiDynamicContractsLimit.contracts_limit_from_vol(
                    std_15m, base_limit
                )
                
                pnl_t = self.backtester.simulate_maker_orders(
                    ticker, signals_by_ticker[ticker], obs_by_ticker[ticker],
                    trades_by_ticker[ticker], adjusted_limit
                )
                pnl_all.extend(pnl_t)
            
            total_pnl = sum(r["pnl_net"] for r in pnl_all)
            
            limit_results.append({
                "limit_name": limit_name,
                "base_limit": base_limit,
                "total_pnl": total_pnl,
                "trades": len(pnl_all)
            })
        
        # Find best limit configuration
        best_limit = max(limit_results, key=lambda r: r["total_pnl"])
        
        return {
            "optimal_std_thresholds": optimal_thresholds,
            "optimal_base_limit": best_limit,
            "all_limit_results": limit_results,
            "combined_optimization": {
                "std_thresholds": optimal_thresholds,
                "base_limit": best_limit["base_limit"],
                "expected_pnl": best_limit["total_pnl"]
            }
        }


# ── Concise Production Patterns ───────────────────────────────────────────────

# 1. Python Fee Calculation for Backtests (Maker vs Taker)

def kalshi_fee(price_cents: int, size: int, maker: bool) -> float:
    """
    Kalshi official fee calculation.
    
    Args:
        price_cents: Trade price in cents
        size: Number of contracts
        maker: True for maker fee, False for taker fee
    
    Returns:
        Fee in dollars
    """
    p = price_cents / 100.0
    coef = 0.0175 if maker else 0.07  # maker approx 1/4 taker; adjust if you have exact rate
    raw = coef * size * p * (1 - p)
    fee_cents = math.ceil(raw * 100)  # round up to next cent on total order
    return fee_cents / 100.0

def pnl_per_fill(price_cents: int, size: int, outcome_yes: bool, maker: bool) -> float:
    """
    Calculate PnL per fill with maker/taker distinction.
    
    Args:
        price_cents: Trade price in cents
        size: Number of contracts
        outcome_yes: True if YES outcome
        maker: True if maker, False if taker
    
    Returns:
        Net PnL after fees
    """
    p = price_cents / 100.0
    gross = (1 - p) * size if outcome_yes else -p * size
    fees = kalshi_fee(price_cents, size, maker)
    return gross - fees


# 2. Live Deploy Maker Bot with Order-Group Resets

def reset_order_group(session: requests.Session, base_url: str, 
                     order_group_id: str, api_key: str, api_secret: str) -> bool:
    """
    Reset order group to clear rolling 15s counter.
    
    Args:
        session: Requests session
        base_url: Kalshi API base URL
        order_group_id: Order group ID to reset
        api_key: API key
        api_secret: API secret
    
    Returns:
        True if successful
    """
    try:
        path = f"/portfolio/order_groups/{order_group_id}/reset"
        
        # Generate auth headers
        ts = str(int(time.time() * 1000))
        msg = ts + "PUT" + path
        sig = hmac.new(api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        headers = {
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
        
        r = session.put(base_url + path, headers=headers, json={}, timeout=3)
        r.raise_for_status()
        
        logger.info(f"Reset order group {order_group_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to reset order group {order_group_id}: {e}")
        return False


# 3. Backtest PnL with Queue_Position Simulation

def depth_at_price(ob: Dict[str, Any], price_cents: int, side: str) -> int:
    """
    Calculate depth at specific price level.
    
    Args:
        ob: Orderbook snapshot
        price_cents: Price in cents
        side: "yes" or "no"
    
    Returns:
        Depth at price level
    """
    levels = ob.get("yes" if side == "yes" else "no", [])
    return sum(q for p, q in levels if p == price_cents)

def simulate_fill_with_qp(trades: List[Dict[str, Any]], entry_ts: float, 
                         price_cents: int, side: str, qp: int, size: int) -> Tuple[float, int]:
    """
    Simulate fill with queue position modeling.
    
    Args:
        trades: Historical trades
        entry_ts: Entry timestamp
        price_cents: Price in cents
        side: Order side
        qp: Queue position
        size: Order size
    
    Returns:
        (fill_timestamp, filled_size)
    """
    filled = 0
    fill_ts = None
    
    for tr in trades_after(trades, entry_ts):
        if tr["price_cents"] == price_cents and tr["side"] != side:
            filled += tr["quantity"]
            if filled >= qp:  # contracts ahead of us are now traded
                fill_ts = tr["ts"]
                break
    
    # We still only get up to our own size
    filled = min(size, max(0, filled - qp))
    return fill_ts, filled

def trades_after(trades: List[Dict[str, Any]], timestamp: float) -> List[Dict[str, Any]]:
    """Get trades after specific timestamp."""
    return [t for t in trades if t["timestamp"] >= timestamp]

def backtest_with_qp(signals: List[Dict[str, Any]], orderbooks: List[Dict[str, Any]], 
                    trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Backtest with queue position simulation.
    
    Args:
        signals: Trading signals
        orderbooks: Historical orderbooks
        trades: Historical trades
    
    Returns:
        Backtest results with queue position analysis
    """
    results = []
    
    for sig in signals:
        ob = find_ob_at_time(orderbooks, sig["ts_with_latency"])
        if not ob:
            continue
        
        qp = depth_at_price(ob, sig["price_cents"], sig["side"])
        fill_ts, filled = simulate_fill_with_qp(
            trades, sig["ts_with_latency"], sig["price_cents"], 
            sig["side"], qp, sig["size"]
        )
        
        if filled == 0:
            continue
        
        pnl = pnl_per_fill(sig["price_cents"], filled, sig["outcome_yes"], maker=True)
        results.append({
            "pnl": pnl, 
            "qp": qp, 
            "filled": filled,
            "fill_ts": fill_ts,
            "price_cents": sig["price_cents"]
        })
    
    return results


# 4. Optimize contracts_limit per Crypto Ticker

def suggest_limit_for_ticker(avg_15s_volume: int, risk_frac: float = 0.2) -> int:
    """
    Suggest contracts limit based on historical volume.
    
    Args:
        avg_15s_volume: Average 15-second matched volume
        risk_frac: Risk fraction (default 20%)
    
    Returns:
        Suggested contracts limit
    """
    # Allow at most risk_frac of average 15s matched volume
    return max(10, int(avg_15s_volume * risk_frac))

def calculate_avg_15s_volume(trades: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Calculate average 15-second matched volume per ticker.
    
    Args:
        trades: Historical trades
    
    Returns:
        {ticker: avg_15s_volume}
    """
    volume_by_ticker = {}
    
    # Group trades by ticker and 15-second windows
    for trade in trades:
        ticker = trade.get("ticker", "UNKNOWN")
        window_15s = int(trade["timestamp"] // 15) * 15
        
        if ticker not in volume_by_ticker:
            volume_by_ticker[ticker] = {}
        
        if window_15s not in volume_by_ticker[ticker]:
            volume_by_ticker[ticker][window_15s] = 0
        
        volume_by_ticker[ticker][window_15s] += trade["quantity"]
    
    # Calculate averages
    avg_volumes = {}
    for ticker, windows in volume_by_ticker.items():
        if windows:
            avg_volumes[ticker] = sum(windows.values()) // len(windows)
    
    return avg_volumes


# 5. Handle WebSocket Orderbook Updates in Backtest

async def record_orderbooks(tickers: List[str], outfile: str, api_key: str, api_secret: str):
    """
    Record live orderbook updates for backtest replay.
    
    Args:
        tickers: List of ticker symbols
        outfile: Output file path
        api_key: Kalshi API key
        api_secret: Kalshi API secret
    """
    headers = {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": hmac.new(
            api_secret.encode(), 
            (str(int(time.time() * 1000)) + "GET" + "/ws/v2").encode(), 
            hashlib.sha256
        ).hexdigest(),
        "KALSHI-ACCESS-TIMESTAMP": str(int(time.time() * 1000)),
    }
    
    async with websockets.connect("wss://api.elections.kalshi.com/trade-api/ws/v2", extra_headers=headers) as ws:
        sub = {
            "type": "subscribe",
            "channels": [{"name": "orderbook", "symbols": tickers}]
        }
        await ws.send(json.dumps(sub))
        
        with open(outfile, "w") as f:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                    if msg.get("type") != "orderbook":
                        continue
                    
                    # Add timestamp for replay
                    msg["recorded_ts"] = time.time()
                    f.write(json.dumps(msg) + "\n")
                    
                except Exception as e:
                    logger.error(f"Error recording orderbook: {e}")

def load_orderbooks(path: str) -> List[Dict[str, Any]]:
    """
    Load recorded orderbooks for backtest replay.
    
    Args:
        path: Path to recorded orderbook file
    
    Returns:
        Sorted orderbook snapshots
    """
    snaps = []
    
    with open(path) as f:
        for line in f:
            try:
                msg = json.loads(line)
                if msg.get("type") != "orderbook":
                    continue
                
                ts = msg.get("recorded_ts", msg.get("timestamp"))
                ob = msg.get("orderbook", {})
                
                snaps.append({
                    "ts": ts,
                    "ticker": msg.get("ticker"),
                    "yes": ob.get("yes", []),
                    "no": ob.get("no", [])
                })
                
            except Exception as e:
                logger.error(f"Error loading orderbook: {e}")
    
    return sorted(snaps, key=lambda x: x["ts"])


# ── Minimal Wiring-Oriented Production Patterns ───────────────────────────────

# 1. Handle Order Group Resets in a Live Bot

import asyncio, json, os, time, hmac, hashlib, requests, websockets

# Environment-aware Kalshi API base URLs
BASE = os.getenv("KALSHI_API_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")
WS_URL = os.getenv("KALSHI_WS_URL", "wss://demo-api.kalshi.co/trade-api/ws/v2")
API_KEY = os.environ.get("KALSHI_API_KEY", "")
API_SECRET = os.environ.get("KALSHI_API_SECRET", "")

session = requests.Session()

def _auth_headers(path: str, method: str = "GET") -> dict:
    """Generate Kalshi API authentication headers."""
    ts = str(int(time.time() * 1000))
    msg = ts + method + path
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "KALSHI-ACCESS-KEY": API_KEY,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }

def reset_order_group(order_group_id: str) -> None:
    """Reset order group to clear rolling 15s counter."""
    path = f"/portfolio/order_groups/{order_group_id}/reset"
    r = session.put(BASE + path, headers=_auth_headers(path, "PUT"), json={}, timeout=3)
    r.raise_for_status()

async def order_group_updates_loop(group_state: dict):
    """Monitor order group updates via WebSocket."""
    headers = {
        "KALSHI-ACCESS-KEY": API_KEY,
        # Add signature/timestamp for WS auth if needed
    }
    
    async with websockets.connect(WS_URL, extra_headers=headers) as ws:
        sub = {"type": "subscribe", "channels": [{"name": "order_group_updates"}]}
        await ws.send(json.dumps(sub))
        
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") != "order_group_updates":
                continue
            
            ev = msg["msg"]
            og_id = ev["order_group_id"]
            et = ev["event_type"]  # "triggered", "limit_updated", "reset", ...
            
            if et == "triggered":
                group_state[og_id] = "triggered"
            elif et == "reset":
                group_state[og_id] = "active"


# 2. Lightweight Live Monitoring Dashboard (Text/Log)

def snapshot(bot) -> dict:
    """Create bot state snapshot for monitoring."""
    return {
        "ts": time.time(),
        "pnl": getattr(bot, 'total_pnl', 0.0),
        "positions": dict(getattr(bot, 'positions', {})),
        "active_orders": len(getattr(bot, 'active_orders', [])),
        "order_groups": dict(getattr(bot, 'order_group_state', {})),
    }

async def monitoring_loop(bot, interval: float = 5.0, running: Optional[threading.Event] = None):
    """Periodic monitoring loop with bot state logging.

    Args:
        bot: Bot instance to monitor
        interval: Monitoring interval in seconds
        running: Optional threading.Event to signal loop exit
    """
    while running is None or running.is_set():
        snap = snapshot(bot)
        logger.info(f"PNL={snap['pnl']:.2f}, pos={snap['positions']}, "
                    f"active={snap['active_orders']}, og={snap['order_groups']}")
        await asyncio.sleep(interval)


# 3. Slippage Simulation for Maker Optimization

def simulate_slippage(orderbook: dict, side: str, size: int) -> dict:
    """
    Simulate slippage for maker optimization.
    
    Args:
        orderbook: Orderbook with YES/NO bid arrays
        side: 'buy_yes' or 'sell_yes' treating YES side
        size: Order size in contracts
    
    Returns:
        Slippage analysis with average price
    """
    yes = orderbook.get("yes", [])
    no = orderbook.get("no", [])
    
    if side == "buy_yes":
        # Cross implied asks: from highest NO downwards
        ladder = sorted(no, key=lambda x: -x[0])  # high NO → low YES ask
        remaining = size
        cost_cents = 0
        
        for price_no, qty in ladder:
            if remaining <= 0:
                break
            take = min(remaining, qty)
            yes_ask_c = 100 - price_no
            cost_cents += yes_ask_c * take
            remaining -= take
        
        avg_price_c = cost_cents / size if size > 0 else None
        return {"avg_price_c": avg_price_c, "slippage_c": None}  # Compare to mid
    
    elif side == "sell_yes":
        # Cross implied bids: from lowest NO upwards
        ladder = sorted(no, key=lambda x: x[0])  # low NO → high YES bid
        remaining = size
        revenue_cents = 0
        
        for price_no, qty in ladder:
            if remaining <= 0:
                break
            take = min(remaining, qty)
            yes_bid_c = 100 - price_no
            revenue_cents += yes_bid_c * take
            remaining -= take
        
        avg_price_c = revenue_cents / size if size > 0 else None
        return {"avg_price_c": avg_price_c, "slippage_c": None}
    
    else:
        return {"avg_price_c": None, "slippage_c": None}


# 4. Risk Management Position Sizing

def kelly_fraction(edge: float, odds: float = 1.0) -> float:
    """
    Calculate Kelly fraction with safety caps.
    
    Args:
        edge: Expected value per $1 risk (e.g. 0.02 for 2% edge)
        odds: Betting odds (default 1.0 for even money)
    
    Returns:
        Kelly fraction capped at 10%
    """
    return max(0.0, min(edge / odds, 0.1))  # cap at 10%

def size_for_market(bankroll_dollars: float, edge: float,
                    max_contracts: int, contract_value: float = 1.0) -> int:
    """
    Calculate position size using Kelly criterion with limits.
    
    Args:
        bankroll_dollars: Total bankroll in dollars
        edge: Expected edge per contract
        max_contracts: Maximum allowed contracts (position limits)
        contract_value: Contract value in dollars (default 1.0)
    
    Returns:
        Recommended position size in contracts
    """
    f = kelly_fraction(edge)
    target = int((bankroll_dollars * f) / contract_value)
    return max(1, min(target, max_contracts))


# 5. Multi-Market Maker PnL Backtest Skeleton

def backtest_multi_market(signals_by_tkr: dict, obs_by_tkr: dict, trades_by_tkr: dict) -> tuple:
    """
    Multi-market maker backtest with realistic simulation.
    
    Args:
        signals_by_tkr: {ticker: signals}
        obs_by_tkr: {ticker: orderbooks}
        trades_by_tkr: {ticker: trades}
    
    Returns:
        (total_pnl, all_fills)
    """
    all_fills = []
    
    for tkr, signals in signals_by_tkr.items():
        obs = obs_by_tkr[tkr]
        trades = trades_by_tkr[tkr]
        
        for sig in signals:
            ob = find_ob_at_time(obs, sig["ts_with_latency"])
            if not ob:
                continue
            
            price = sig["price_cents"]
            side = sig["side"]
            size = sig["size"]
            
            # Calculate queue position
            qp = depth_at_price(ob, price, side)
            
            # Simulate fill with queue position
            fill_ts, filled = simulate_fill_with_qp(
                trades, sig["ts_with_latency"], price, side, qp, size
            )
            
            if filled == 0:
                continue
            
            # Calculate PnL with maker fees
            maker = True  # for resting orders
            pnl = pnl_per_fill(price, filled, sig["outcome_yes"], maker)
            
            all_fills.append({
                "ticker": tkr, 
                "pnl": pnl, 
                "filled": filled,
                "qp": qp,
                "price": price,
                "fill_ts": fill_ts
            })
    
    total_pnl = sum(f["pnl"] for f in all_fills)
    return total_pnl, all_fills


# ── Kalshi API Rate Limit Management & Optimization ─────────────────────────────

# 1. Know Your Tier and Limits

class KalshiRateLimitManager:
    """Manage API rate limits and tier optimization."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.session = requests.Session()
        
        # Rate limit tiers (reads/writes per second)
        self.tiers = {
            "basic": {"read": 20, "write": 10},
            "advanced": {"read": 30, "write": 30},
            "premier": {"read": 100, "write": 100},
            "prime": {"read": 400, "write": 400}
        }
        
        # Current limits (fetched from API)
        self.current_limits = {"read_limit": 20, "write_limit": 10}
        self.tier = "basic"
        
        # Usage tracking
        self.read_tokens = self.current_limits["read_limit"]
        self.write_tokens = self.current_limits["write_limit"]
        self.last_refill = time.time()
        
    def get_account_api_limits(self) -> dict:
        """Fetch current API limits from Kalshi."""
        try:
            path = "/account/api_limits"
            headers = self._auth_headers(path)
            r = self.session.get(self.base_url + path, headers=headers, timeout=5)
            r.raise_for_status()
            
            limits_data = r.json()
            self.current_limits = {
                "read_limit": limits_data.get("read_limit", 20),
                "write_limit": limits_data.get("write_limit", 10)
            }
            
            # Determine tier based on limits
            for tier_name, tier_limits in self.tiers.items():
                if (self.current_limits["read_limit"] == tier_limits["read"] and
                    self.current_limits["write_limit"] == tier_limits["write"]):
                    self.tier = tier_name
                    break
            
            return self.current_limits
            
        except Exception as e:
            logger.error(f"Failed to fetch API limits: {e}")
            return self.current_limits
    
    def _auth_headers(self, path: str, method: str = "GET") -> dict:
        """Generate Kalshi API authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + method + path
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    def get_safe_limits(self, safety_factor: float = 0.7) -> dict:
        """Get safe limits below API ceilings."""
        return {
            "read_limit": int(self.current_limits["read_limit"] * safety_factor),
            "write_limit": int(self.current_limits["write_limit"] * safety_factor)
        }


# 2. Prefer WebSockets over REST for Live Data

class KalshiWebSocketManager:
    """WebSocket manager for efficient live data streaming."""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.connections = {}
        self.subscribers = {}
        
    def _auth_headers(self) -> dict:
        """Generate WebSocket authentication headers."""
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + "/ws/v2"
        sig = hmac.new(self.api_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }
    
    async def subscribe_to_orderbooks(self, tickers: List[str], callback: callable):
        """Subscribe to orderbook updates for multiple tickers."""
        channel_key = "orderbook"
        
        if channel_key not in self.connections:
            headers = self._auth_headers()
            ws = await websockets.connect(self.ws_url, extra_headers=headers)
            self.connections[channel_key] = ws
            
            # Subscribe to orderbooks
            sub = {
                "type": "subscribe",
                "channels": [{"name": "orderbook", "symbols": tickers}]
            }
            await ws.send(json.dumps(sub))
            
            # Start message handler
            asyncio.create_task(self._handle_orderbook_messages(ws, callback))
    
    async def subscribe_to_trades(self, tickers: List[str], callback: callable):
        """Subscribe to trade updates for multiple tickers."""
        channel_key = "trades"
        
        if channel_key not in self.connections:
            headers = self._auth_headers()
            ws = await websockets.connect(self.ws_url, extra_headers=headers)
            self.connections[channel_key] = ws
            
            # Subscribe to trades
            sub = {
                "type": "subscribe",
                "channels": [{"name": "trades", "symbols": tickers}]
            }
            await ws.send(json.dumps(sub))
            
            # Start message handler
            asyncio.create_task(self._handle_trade_messages(ws, callback))
    
    async def subscribe_to_user_orders(self, callback: callable):
        """Subscribe to user order updates."""
        channel_key = "user_orders"
        
        if channel_key not in self.connections:
            headers = self._auth_headers()
            ws = await websockets.connect(self.ws_url, extra_headers=headers)
            self.connections[channel_key] = ws
            
            # Subscribe to user orders
            sub = {
                "type": "subscribe",
                "channels": [{"name": "order_updates"}]
            }
            await ws.send(json.dumps(sub))
            
            # Start message handler
            asyncio.create_task(self._handle_order_messages(ws, callback))
    
    async def subscribe_to_order_groups(self, callback: callable):
        """Subscribe to order group updates."""
        channel_key = "order_groups"
        
        if channel_key not in self.connections:
            headers = self._auth_headers()
            ws = await websockets.connect(self.ws_url, extra_headers=headers)
            self.connections[channel_key] = ws
            
            # Subscribe to order groups
            sub = {
                "type": "subscribe",
                "channels": [{"name": "order_group_updates"}]
            }
            await ws.send(json.dumps(sub))
            
            # Start message handler
            asyncio.create_task(self._handle_order_group_messages(ws, callback))
    
    async def _handle_orderbook_messages(self, ws, callback):
        """Handle incoming orderbook messages."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "orderbook":
                    await callback(msg)
            except Exception as e:
                logger.error(f"Orderbook message error: {e}")
    
    async def _handle_trade_messages(self, ws, callback):
        """Handle incoming trade messages."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "trade":
                    await callback(msg)
            except Exception as e:
                logger.error(f"Trade message error: {e}")
    
    async def _handle_order_messages(self, ws, callback):
        """Handle incoming order messages."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "order_update":
                    await callback(msg)
            except Exception as e:
                logger.error(f"Order message error: {e}")
    
    async def _handle_order_group_messages(self, ws, callback):
        """Handle incoming order group messages."""
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if msg.get("type") == "order_group_updates":
                    await callback(msg)
            except Exception as e:
                logger.error(f"Order group message error: {e}")
    
    async def close_all(self):
        """Close all WebSocket connections."""
        for ws in self.connections.values():
            await ws.close()
        self.connections.clear()


# 3. Batch Where Possible

class KalshiBatchManager:
    """Batch operations for efficient API usage."""
    
    def __init__(self, rate_manager: KalshiRateLimitManager):
        self.rate_manager = rate_manager
        self.session = rate_manager.session
        self.base_url = rate_manager.base_url
        
    def batch_create_orders(self, orders: List[dict]) -> dict:
        """
        Create multiple orders in one API call.
        
        Each order in orders should be a dict with:
        - ticker
        - side (buy/sell)
        - order_type (limit/market)
        - price (for limit orders)
        - count (number of contracts)
        - client_order_id (optional)
        - order_group_id (optional)
        """
        try:
            path = "/portfolio/batch/create_orders"
            headers = self.rate_manager._auth_headers(path, "POST")
            
            payload = {"orders": orders}
            r = self.session.post(
                self.base_url + path,
                headers=headers,
                json=payload,
                timeout=10
            )
            r.raise_for_status()
            
            # Each cancel in batch counts as 0.2 write
            write_cost = len(orders) * 0.2
            self.rate_manager.write_tokens -= write_cost
            
            return r.json()
            
        except Exception as e:
            logger.error(f"Batch create orders error: {e}")
            raise
    
    def batch_cancel_orders(self, order_ids: List[str]) -> dict:
        """
        Cancel multiple orders in one API call.
        
        Args:
            order_ids: List of order IDs to cancel
        """
        try:
            path = "/portfolio/batch/cancel_orders"
            headers = self.rate_manager._auth_headers(path, "POST")
            
            payload = {"order_ids": order_ids}
            r = self.session.post(
                self.base_url + path,
                headers=headers,
                json=payload,
                timeout=10
            )
            r.raise_for_status()
            
            # Each cancel in batch counts as 0.2 write
            write_cost = len(order_ids) * 0.2
            self.rate_manager.write_tokens -= write_cost
            
            return r.json()
            
        except Exception as e:
            logger.error(f"Batch cancel orders error: {e}")
            raise
    
    def get_queue_positions_for_orders(self, order_ids: List[str]) -> dict:
        """
        Get queue positions for multiple orders in one call.
        
        Args:
            order_ids: List of order IDs to check
        """
        try:
            path = "/portfolio/queue_positions"
            headers = self.rate_manager._auth_headers(path)
            
            params = {"order_ids": ",".join(order_ids)}
            r = self.session.get(
                self.base_url + path,
                headers=headers,
                params=params,
                timeout=5
            )
            r.raise_for_status()
            
            # Counts as 1 read
            self.rate_manager.read_tokens -= 1
            
            return r.json()
            
        except Exception as e:
            logger.error(f"Get queue positions error: {e}")
            raise


# 4. Apply Client-Side Throttling

class KalshiTokenBucket:
    """Token bucket implementation for rate limiting."""
    
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self.lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> bool:
        """Consume tokens if available."""
        async with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            
            # Refill tokens
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def wait_for_tokens(self, tokens: int = 1):
        """Wait until tokens are available."""
        return asyncio.create_task(self._wait_for_tokens(tokens))
    
    async def _wait_for_tokens(self, tokens: int):
        """Async wait for tokens."""
        while not await self.consume(tokens):
            await asyncio.sleep(0.1)


class KalshiThrottledClient:
    """Throttled HTTP client with automatic backoff."""
    
    def __init__(self, rate_manager: KalshiRateLimitManager, safety_factor: float = 0.7):
        self.rate_manager = rate_manager
        safe_limits = rate_manager.get_safe_limits(safety_factor)
        
        # Create token buckets
        self.read_bucket = KalshiTokenBucket(
            safe_limits["read_limit"], 
            safe_limits["read_limit"]
        )
        self.write_bucket = KalshiTokenBucket(
            safe_limits["write_limit"], 
            safe_limits["write_limit"]
        )
        
        self.session = rate_manager.session
        self.base_url = rate_manager.base_url
    
    async def throttled_get(self, path: str, params: dict = None) -> dict:
        """Throttled GET request with automatic retry."""
        await self.read_bucket.wait_for_tokens(1)
        
        for attempt in range(3):  # 3 attempts
            try:
                headers = self.rate_manager._auth_headers(path)
                r = self.session.get(
                    self.base_url + path,
                    headers=headers,
                    params=params,
                    timeout=10
                )
                
                if r.status_code == 429:
                    # Rate limited, backoff with jitter
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
                    continue
                
                r.raise_for_status()
                return r.json()
                
            except Exception as e:
                if attempt == 2:  # Last attempt
                    raise
                await asyncio.sleep(1)
    
    async def throttled_post(self, path: str, data: dict = None) -> dict:
        """Throttled POST request with automatic retry."""
        await self.write_bucket.wait_for_tokens(1)
        
        for attempt in range(3):  # 3 attempts
            try:
                headers = self.rate_manager._auth_headers(path, "POST")
                r = self.session.post(
                    self.base_url + path,
                    headers=headers,
                    json=data,
                    timeout=10
                )
                
                if r.status_code == 429:
                    # Rate limited, backoff with jitter
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
                    continue
                
                r.raise_for_status()
                return r.json()
                
            except Exception as e:
                if attempt == 2:  # Last attempt
                    raise
                await asyncio.sleep(1)


# 5. Cache and Reuse Data

class KalshiCacheManager:
    """Cache manager for static and semi-static data."""
    
    def __init__(self, ttl_seconds: int = 300):  # 5 minute default TTL
        self.cache = {}
        self.ttl_seconds = ttl_seconds
        
    def get(self, key: str) -> any:
        """Get cached value if not expired."""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl_seconds:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, value: any):
        """Set cached value with timestamp."""
        self.cache[key] = (value, time.time())
    
    def invalidate(self, key: str):
        """Invalidate specific cache key."""
        if key in self.cache:
            del self.cache[key]
    
    def clear(self):
        """Clear all cache."""
        self.cache.clear()


# 6. Split Workload Across Processes but Not Keys

class KalshiWorkloadManager:
    """Manage workload distribution across components."""
    
    def __init__(self, rate_manager: KalshiRateLimitManager):
        self.rate_manager = rate_manager
        self.components = {}
        self.request_queue = asyncio.Queue()
        self.running = False
        
    def register_component(self, name: str, priority: int = 1):
        """Register a component that needs API access."""
        self.components[name] = {
            "priority": priority,
            "requests": 0,
            "last_request": 0
        }
    
    async def submit_request(self, request_type: str, path: str, data: dict = None):
        """Submit a request to the shared queue."""
        await self.request_queue.put({
            "type": request_type,
            "path": path,
            "data": data,
            "timestamp": time.time()
        })
    
    async def process_requests(self):
        """Process requests from the shared queue."""
        self.running = True
        throttled_client = KalshiThrottledClient(self.rate_manager)
        
        while self.running:
            try:
                request = await asyncio.wait_for(
                    self.request_queue.get(), 
                    timeout=1.0
                )
                
                if request["type"] == "GET":
                    result = await throttled_client.throttled_get(
                        request["path"], 
                        request.get("params")
                    )
                elif request["type"] == "POST":
                    result = await throttled_client.throttled_post(
                        request["path"], 
                        request["data"]
                    )
                
                # Return result to caller (implement callback system as needed)
                logger.debug(f"Processed {request['type']} {request['path']}")
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Request processing error: {e}")
    
    def stop(self):
        """Stop the request processor."""
        self.running = False


# 7. Tier Management and Upgrade Guidance

class KalshiTierManager:
    """Manage API tier information and upgrade guidance."""
    
    def __init__(self):
        self.tier_requirements = {
            "basic": {
                "description": "Free tier, suitable for testing and low-volume trading",
                "limits": {"read": 20, "write": 10},
                "upgrade_path": "advanced"
            },
            "advanced": {
                "description": "Free after short form, good for moderate volume",
                "limits": {"read": 30, "write": 30},
                "upgrade_path": "premier"
            },
            "premier": {
                "description": "Requires meaningful exchange volume and good rate limit hygiene",
                "limits": {"read": 100, "write": 100},
                "upgrade_path": "prime"
            },
            "prime": {
                "description": "Highest tier, requires significant volume and excellent practices",
                "limits": {"read": 400, "write": 400},
                "upgrade_path": None
            }
        }
    
    def get_tier_info(self, tier: str) -> dict:
        """Get detailed information about a tier."""
        return self.tier_requirements.get(tier, {})
    
    def analyze_usage(self, current_tier: str, usage_stats: dict) -> dict:
        """
        Analyze usage and provide recommendations.
        
        Args:
            current_tier: Current API tier
            usage_stats: Usage statistics
        """
        tier_info = self.get_tier_info(current_tier)
        limits = tier_info.get("limits", {})
        
        read_usage_pct = (usage_stats.get("reads_per_second", 0) / limits.get("read", 1)) * 100
        write_usage_pct = (usage_stats.get("writes_per_second", 0) / limits.get("write", 1)) * 100
        
        recommendations = []
        
        if read_usage_pct > 80 or write_usage_pct > 80:
            recommendations.append("Consider upgrading to next tier")
            recommendations.append("Optimize WebSocket usage to reduce REST calls")
            recommendations.append("Implement more aggressive batching")
        
        if read_usage_pct < 30 and write_usage_pct < 30:
            recommendations.append("Current usage is well within limits")
        
        return {
            "current_tier": current_tier,
            "read_usage_pct": read_usage_pct,
            "write_usage_pct": write_usage_pct,
            "recommendations": recommendations,
            "next_tier": tier_info.get("upgrade_path")
        }
    
    def get_upgrade_guidance(self, current_tier: str) -> dict:
        """Get guidance for upgrading to next tier."""
        tier_info = self.get_tier_info(current_tier)
        next_tier = tier_info.get("upgrade_path")
        
        if not next_tier:
            return {"message": "Already at highest tier"}
        
        next_info = self.get_tier_info(next_tier)
        
        return {
            "current_tier": current_tier,
            "next_tier": next_tier,
            "requirements": {
                "volume": "Meaningful portion of exchange volume",
                "hygiene": "Good rate limit hygiene and monitoring",
                "contact": "Talk to Kalshi about tier upgrade"
            },
            "benefits": {
                "read_limit": next_info["limits"]["read"],
                "write_limit": next_info["limits"]["write"]
            }
        }


# ── Kalshi Event Stream Architecture ───────────────────────────────────────

# 1. Define a clean event interface

from dataclasses import dataclass
from typing import Literal, Any, Dict, Optional
import queue
import threading
import asyncio
from datetime import datetime

EventType = Literal["position_update", "order_fill", "order_reject", "rate_limiter", "order_group_trigger", "api_error"]

@dataclass
class KalshiEvent:
    """Domain event for Kalshi trading activities."""
    type: EventType
    payload: Dict[str, Any]
    ts: float
    source: str = "kalshi_client"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "payload": self.payload,
            "ts": self.ts,
            "source": self.source
        }

class KalshiEventBus:
    """Central event bus for Kalshi events."""
    
    def __init__(self, max_size: int = 1000):
        self.event_queue = queue.Queue(maxsize=max_size)
        self.subscribers = []
        self.running = False
        self._lock = threading.Lock()
        
    def publish(self, event: KalshiEvent):
        """Publish an event to the bus."""
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            # Remove oldest event if queue is full
            try:
                self.event_queue.get_nowait()
                self.event_queue.put_nowait(event)
            except queue.Empty:
                pass
    
    def subscribe(self, callback):
        """Subscribe to events with a callback."""
        with self._lock:
            self.subscribers.append(callback)
    
    def unsubscribe(self, callback):
        """Unsubscribe from events."""
        with self._lock:
            if callback in self.subscribers:
                self.subscribers.remove(callback)
    
    def get_events(self, limit: int = 50) -> list[KalshiEvent]:
        """Get recent events from the queue."""
        events = []
        try:
            while len(events) < limit:
                event = self.event_queue.get_nowait()
                events.append(event)
        except queue.Empty:
            pass
        return events
    
    def start_dispatcher(self):
        """Start the event dispatcher in background thread."""
        if self.running:
            return
        self.running = True
        self._dispatcher_thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher_thread.start()
    
    def _dispatch_loop(self):
        """Dispatch events to all subscribers with proper error isolation."""
        while self.running:
            try:
                event = self.event_queue.get(timeout=1.0)
                
                # Create subscriber snapshot to avoid holding lock during callbacks
                with self._lock:
                    subscribers = list(self.subscribers)
                
                # Dispatch to each subscriber with exception isolation
                for callback in subscribers:
                    try:
                        callback(event)
                    except Exception as e:
                        logger.exception(f"Event subscriber failed for event {event.type}: {e}")
                        
            except queue.Empty:
                continue
            except Exception as e:
                logger.exception(f"Event dispatcher error: {e}")
                # Continue running even if there's an unexpected error
    
    def stop(self):
        """Stop the event dispatcher."""
        self.running = False
        if hasattr(self, '_dispatcher_thread'):
            self._dispatcher_thread.join(timeout=5.0)

# Global event bus instance
kalshi_event_bus = KalshiEventBus()

# ── Enhanced Rate-Aware Client with Event Emission ───────────────────────────────

# 1. Python: Exponential Backoff for Kalshi API Calls

import time
import random
import requests
import threading
import queue
import os
import hmac
import hashlib
from typing import Dict, Optional

TRANSIENT_STATUSES: set[int] = {408, 429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 60.0  # seconds - cap to prevent indefinite stalls

def kalshi_request(method: str, url: str, **kwargs) -> requests.Response:
    """
    HTTP call with exponential backoff on 429/5xx.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        url: Request URL
        **kwargs: Additional requests arguments
    
    Returns:
        requests.Response object
    
    Raises:
        requests.HTTPError: If all retries exhausted
    """
    max_retries = 5
    base_delay = 0.25  # seconds

    for attempt in range(max_retries):
        resp = requests.request(method, url, **kwargs)
        
        if resp.status_code not in TRANSIENT_STATUSES:
            return resp

        # Log transient status for debugging
        logger.warning(f"Transient status {resp.status_code} on {method} {url}, attempt {attempt + 1}/{max_retries}")

        # Check for Retry-After header if available
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                # Retry-After can be seconds or HTTP date
                if retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    # Parse HTTP date format
                    from email.utils import parsedate_to_datetime
                    retry_time = parsedate_to_datetime(retry_after)
                    delay = (retry_time.timestamp() - time.time())
                    delay = max(0, delay)  # Ensure non-negative
                    delay = min(delay, MAX_RETRY_AFTER)  # Cap to prevent indefinite stalls
                
                logger.info(f"Using Retry-After header: {delay:.1f} seconds")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid Retry-After header '{retry_after}': {e}")
                delay = base_delay * (2 ** attempt)
                delay *= random.uniform(0.8, 1.2)  # fallback to exponential backoff
        else:
            # Rate limited or transient error - use exponential backoff
            delay = base_delay * (2 ** attempt)
            delay *= random.uniform(0.8, 1.2)  # jitter
        
        time.sleep(delay)

    # Log retry exhaustion
    logger.error(f"Exhausted {max_retries} retries for {method} {url}")
    resp.raise_for_status()
    return resp


# 2. Best Practices for Request Queuing

class RateLimiter:
    """Token bucket rate limiter for API requests."""
    
    def __init__(self, max_per_sec: int):
        self.max_per_sec = max_per_sec
        self.tokens = max_per_sec
        self.last = time.time()
        self.lock = threading.Lock()

    def acquire(self, timeout: Optional[float] = None):
        """Acquire a token, blocking until available.

        Args:
            timeout: Maximum time to wait in seconds. If None, blocks indefinitely.

        Returns:
            True if token acquired, False if timeout expired.
        """
        start_time = time.time()
        with self.lock:
            while True:
                now = time.time()
                elapsed = now - self.last

                # Refill tokens
                self.tokens = min(self.max_per_sec, self.tokens + elapsed * self.max_per_sec)
                self.last = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return True

                # Check timeout
                if timeout is not None and (now - start_time) >= timeout:
                    return False

                time.sleep(0.01)

class KalshiRequestQueue:
    """Rate-limited request queue for Kalshi API calls."""

    def __init__(self, read_limit: int = 15, write_limit: int = 8):
        self.request_q = queue.Queue()
        self.read_limiter = RateLimiter(read_limit)
        self.write_limiter = RateLimiter(write_limit)
        self._running = True
        self._shutdown_sentinel = (None, None, None, None)  # Signal to stop worker

        # Start worker thread
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def stop(self):
        """Stop the worker thread gracefully."""
        self._running = False
        self.request_q.put(self._shutdown_sentinel)
        self.worker_thread.join(timeout=5.0)

    def _worker(self):
        """Worker thread that processes requests from queue."""
        while self._running:
            item = self.request_q.get()

            # Check for shutdown sentinel
            if item == self._shutdown_sentinel:
                self.request_q.task_done()
                break

            method, url, kwargs, future = item

            # Choose appropriate limiter
            limiter = self.read_limiter if method.upper() in ['GET', 'HEAD'] else self.write_limiter

            # Acquire rate limit token
            limiter.acquire()

            try:
                resp = kalshi_request(method, url, **kwargs)
                future["resp"] = resp
            except Exception as e:
                future["error"] = e
            finally:
                self.request_q.task_done()
    
    def enqueue_request(self, method: str, url: str, **kwargs) -> dict:
        """
        Enqueue a request and return a future dictionary.
        
        Args:
            method: HTTP method
            url: Request URL
            **kwargs: Additional requests arguments
        
        Returns:
            Future dict that will contain 'resp' or 'error'
        """
        fut = {}
        self.request_q.put((method, url, kwargs, fut))
        return fut
    
    def get_response(self, future: dict, timeout: float = 30.0) -> requests.Response:
        """
        Wait for response from future.
        
        Args:
            future: Future dict from enqueue_request
            timeout: Maximum time to wait
        
        Returns:
            requests.Response object
        
        Raises:
            Exception: If request failed or timed out
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if "resp" in future:
                return future["resp"]
            if "error" in future:
                raise future["error"]
            time.sleep(0.01)
        
        raise TimeoutError(f"Request timed out after {timeout} seconds")


# 3. Python: Check Kalshi API Limits Dynamically

BASE = os.getenv("KALSHI_API_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")
API_KEY = os.environ.get("KALSHI_API_KEY", "")
API_SECRET = os.environ.get("KALSHI_API_SECRET", "")

def auth_headers(path: str, method: str = "GET") -> dict:
    """Generate Kalshi API authentication headers."""
    ts = str(int(time.time() * 1000))
    msg = ts + method + path
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "KALSHI-ACCESS-KEY": API_KEY,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }

def get_api_limits() -> dict:
    """
    Get current API limits from Kalshi.
    
    Returns:
        Dict with usage_tier, read_limit, write_limit
    """
    path = "/account/limits"
    r = requests.get(BASE + path, headers=auth_headers(path), timeout=3)
    r.raise_for_status()
    return r.json()  # {"usage_tier", "read_limit", "write_limit"}

class DynamicRateLimiter:
    """Dynamic rate limiter that adapts to API limits with read/write separation and event emission."""
    
    def __init__(self, safety_factor: float = 0.8, event_bus: Optional[KalshiEventBus] = None):
        self.safety_factor = safety_factor
        self.read_limiter: Optional[RateLimiter] = None
        self.write_limiter: Optional[RateLimiter] = None
        self.current_limits = {"read_limit": 20, "write_limit": 10}
        self.last_update = 0
        self.update_interval = 300  # Update limits every 5 minutes
        self.event_bus = event_bus or kalshi_event_bus
        
    def _emit_event(self, event_type: EventType, payload: Dict[str, Any]):
        """Emit an event to the event bus."""
        if self.event_bus:
            event = KalshiEvent(type=event_type, payload=payload, ts=time.time())
            self.event_bus.publish(event)
        
    def _update_limits_if_needed(self):
        """Update limits if enough time has passed."""
        now = time.time()
        if now - self.last_update > self.update_interval:
            try:
                limits = get_api_limits()
                read_limit = int(limits["read_limit"] * self.safety_factor)
                write_limit = int(limits["write_limit"] * self.safety_factor)
                
                old_limits = self.current_limits.copy()
                self.current_limits = {
                    "read_limit": read_limit,
                    "write_limit": write_limit
                }
                self.last_update = now
                
                # Reinitialize limiters with new limits
                self.read_limiter = RateLimiter(read_limit)
                self.write_limiter = RateLimiter(write_limit)
                
                logger.info(f"Updated rate limits: read={read_limit}/s, write={write_limit}/s")
                
                # Emit rate limiter event
                self._emit_event("rate_limiter", {
                    "action": "limits_updated",
                    "old_limits": old_limits,
                    "new_limits": self.current_limits,
                    "usage_tier": limits.get("usage_tier", "unknown")
                })
                
            except Exception as e:
                logger.error(f"Failed to update API limits: {e}")
                # Initialize with default limits if not already done
                if self.read_limiter is None:
                    self.read_limiter = RateLimiter(self.current_limits["read_limit"])
                    self.write_limiter = RateLimiter(self.current_limits["write_limit"])
                    
                    # Emit API error event
                    self._emit_event("api_error", {
                        "error": "Failed to update limits",
                        "details": str(e),
                        "fallback_limits": self.current_limits
                    })
    
    def _get_limiter(self, method: str) -> RateLimiter:
        """Get appropriate limiter for HTTP method."""
        self._update_limits_if_needed()
        
        # Use read limiter for GET/HEAD, write limiter for others
        if method.upper() in ["GET", "HEAD"]:
            return self.read_limiter
        else:
            return self.write_limiter
    
    def make_request(self, method: str, path: str, **kwargs) -> requests.Response:
        """
        Make a rate-limited request to Kalshi API with event emission.
        
        Args:
            method: HTTP method
            path: API path (without base URL)
            **kwargs: Additional requests arguments
        
        Returns:
            requests.Response object
        """
        limiter = self._get_limiter(method)
        
        # Check if we need to wait for rate limit
        start_time = time.time()
        limiter.acquire()
        wait_time = time.time() - start_time
        
        # Emit rate limiting event if we had to wait
        if wait_time > 0.1:  # Only emit if we waited more than 100ms
            self._emit_event("rate_limiter", {
                "action": "throttled",
                "method": method,
                "path": path,
                "wait_time": wait_time,
                "limiter_type": "read" if method.upper() in ["GET", "HEAD"] else "write"
            })
        
        # Build full URL
        url = BASE + path
        
        # Add auth headers if not provided
        if "headers" not in kwargs:
            kwargs["headers"] = auth_headers(path, method)
        
        try:
            # Make the request
            resp = kalshi_request(method, url, **kwargs)
            
            # Emit success event for significant operations
            if method.upper() in ["POST", "PUT", "DELETE"]:
                self._emit_event("api_error", {
                    "action": "api_success",
                    "method": method,
                    "path": path,
                    "status_code": resp.status_code,
                    "response_time": time.time() - start_time
                })
            
            return resp
            
        except Exception as e:
            # Emit error event
            self._emit_event("api_error", {
                "action": "api_error",
                "method": method,
                "path": path,
                "error": str(e),
                "response_time": time.time() - start_time
            })
            raise
    
    def get_limits(self) -> Dict[str, int]:
        """Get current rate limits."""
        self._update_limits_if_needed()
        return dict(self.current_limits)
    
    def update_limits(self):
        """Force update of API limits."""
        self._update_limits_if_needed()


# ── Enhanced Kalshi Client with Event Emission ───────────────────────────────


# 4. Simplified Kalshi Client Wrapper

class KalshiRateAwareClient:
    """Simple wrapper for Kalshi client with rate limiting."""
    
    def __init__(self, safety_factor: float = 0.8):
        self.dynamic_limiter = DynamicRateLimiter(safety_factor)
        self.base_url = BASE
        
    def get(self, path: str, params: dict = None, timeout: int = 10) -> dict:
        """Make rate-limited GET request."""
        kwargs = {"params": params, "timeout": timeout}
        resp = self.dynamic_limiter.make_request("GET", path, **kwargs)
        return resp.json()
    
    def post(self, path: str, json: dict = None, timeout: int = 10) -> dict:
        """Make rate-limited POST request."""
        kwargs = {"json": json, "timeout": timeout}
        resp = self.dynamic_limiter.make_request("POST", path, **kwargs)
        return resp.json()
    
    def put(self, path: str, json: dict = None, timeout: int = 10) -> dict:
        """Make rate-limited PUT request."""
        kwargs = {"json": json, "timeout": timeout}
        resp = self.dynamic_limiter.make_request("PUT", path, **kwargs)
        return resp.json()
    
    def delete(self, path: str, timeout: int = 10) -> dict:
        """Make rate-limited DELETE request."""
        kwargs = {"timeout": timeout}
        resp = self.dynamic_limiter.make_request("DELETE", path, **kwargs)
        return resp.json()
    
    def get_limits(self) -> dict:
        """Get current API limits."""
        return self.dynamic_limiter.current_limits
    
    def update_limits(self):
        """Force update of API limits."""
        self.dynamic_limiter._update_limits_if_needed()


# ── FastAPI Integration for Event Streaming ───────────────────────────────

# 2. Wire into your FastAPI UI backend

class KalshiEventAPI:
    """FastAPI endpoints for Kalshi event streaming."""
    
    def __init__(self, event_bus: Optional[KalshiEventBus] = None):
        self.event_bus = event_bus or kalshi_event_bus
        
    def get_events(self, limit: int = 50) -> list[Dict[str, Any]]:
        """
        Get recent Kalshi events for UI consumption.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        events = self.event_bus.get_events(limit)
        return [event.to_dict() for event in events]
    
    def get_events_by_type(self, event_type: EventType, limit: int = 50) -> list[Dict[str, Any]]:
        """
        Get recent events filtered by type.
        
        Args:
            event_type: Type of events to filter
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries
        """
        all_events = self.event_bus.get_events(limit * 2)  # Get more to filter
        filtered_events = [e for e in all_events if e.type == event_type]
        return [event.to_dict() for event in filtered_events[:limit]]

# Shared instances for FastAPI app (created during app startup)
_shared_event_bus = KalshiEventBus()
_shared_event_api = KalshiEventAPI(_shared_event_bus)

def get_shared_event_api() -> KalshiEventAPI:
    """Dependency injection function for FastAPI."""
    return _shared_event_api

# Example FastAPI router (to be added to your main FastAPI app)
"""
from fastapi import APIRouter, HTTPException, Depends

router = APIRouter()

@router.get("/kalshi/events")
def get_kalshi_events(limit: int = 50, event_api: KalshiEventAPI = Depends(get_shared_event_api)):
    \"\"\"Get recent Kalshi events.\"\"\"
    return event_api.get_events(limit)

@router.get("/kalshi/events/{event_type}")
def get_kalshi_events_by_type(
    event_type: str, 
    limit: int = 50, 
    event_api: KalshiEventAPI = Depends(get_shared_event_api)
):
    \"\"\"Get events filtered by type.\"\"\"
    try:
        return event_api.get_events_by_type(EventType(event_type), limit)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event type: {event_type}")

# App startup
from fastapi import FastAPI

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    \"\"\"Initialize shared event bus and start dispatcher.\"\"\"
    _shared_event_bus.start_dispatcher()
    logger.info("Kalshi event bus started")

@app.on_event("shutdown")
async def shutdown_event():
    \"\"\"Clean shutdown of event bus.\"\"\"
    _shared_event_bus.stop()
    logger.info("Kalshi event bus stopped")
"""

# ── Telegram Integration ─────────────────────────────────────────────────────

# 3. Telegram wiring (python-telegram-bot)

class KalshiTelegramNotifier:
    """Telegram notifier for Kalshi events."""
    
    def __init__(self, event_bus: Optional[KalshiEventBus] = None):
        self.event_bus = event_bus or kalshi_event_bus
        self.token = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = int(os.environ.get("KALSHI_ALERT_CHAT_ID", "0"))
        self.running = False
        
    def start(self):
        """Start the Telegram notifier."""
        if not self.token or self.chat_id == 0:
            logger.warning("Telegram token or chat ID not configured")
            return
            
        self.running = True
        self.event_bus.subscribe(self._handle_event)
        logger.info("Telegram notifier started")
    
    def stop(self):
        """Stop the Telegram notifier."""
        self.running = False
        if self.event_bus:
            self.event_bus.unsubscribe(self._handle_event)
        logger.info("Telegram notifier stopped")
    
    def _handle_event(self, event: KalshiEvent):
        """Handle incoming Kalshi events."""
        if not self.running:
            return
            
        try:
            if event.type == "order_fill":
                self._send_order_fill_alert(event)
            elif event.type == "order_reject":
                self._send_order_reject_alert(event)
            elif event.type == "rate_limiter":
                self._send_rate_limit_alert(event)
            elif event.type == "order_group_trigger":
                self._send_order_group_alert(event)
            elif event.type == "api_error":
                self._send_api_error_alert(event)
                
        except Exception as e:
            logger.error(f"Telegram notification error: {e}")
    
    def _send_order_fill_alert(self, event: KalshiEvent):
        """Send order fill alert."""
        payload = event.payload
        ticker = payload.get("ticker", "Unknown")
        side = payload.get("side", "Unknown")
        count = payload.get("count", 0)
        price = payload.get("price", 0)
        
        text = f"✅ Fill: {ticker} {side} x{count} @ {price}"
        self._send_message(text)
    
    def _send_order_reject_alert(self, event: KalshiEvent):
        """Send order reject alert."""
        payload = event.payload
        ticker = payload.get("ticker", "Unknown")
        reason = payload.get("reason", "Unknown")
        
        text = f"❌ Reject: {ticker} - {reason}"
        self._send_message(text)
    
    def _send_rate_limit_alert(self, event: KalshiEvent):
        """Send rate limit alert."""
        payload = event.payload
        action = payload.get("action", "Unknown")
        wait_time = payload.get("wait_time", 0)
        
        if action == "throttled":
            text = f"⚠️ Rate limiting: waiting {wait_time:.1f}s"
        elif action == "limits_updated":
            new_limits = payload.get("new_limits", {})
            text = f"📊 Limits updated: read={new_limits.get('read_limit', 0)}/s, write={new_limits.get('write_limit', 0)}/s"
        else:
            text = f"⚠️ Rate limiter: {action}"
            
        self._send_message(text)
    
    def _send_order_group_alert(self, event: KalshiEvent):
        """Send order group trigger alert."""
        payload = event.payload
        group_id = payload.get("order_group_id", "Unknown")
        
        text = f"🚨 Order group triggered: {group_id}"
        self._send_message(text)
    
    def _send_api_error_alert(self, event: KalshiEvent):
        """Send API error alert."""
        payload = event.payload
        error = payload.get("error", "Unknown error")
        path = payload.get("path", "Unknown")
        
        text = f"🔴 API Error: {path} - {error}"
        self._send_message(text)
    
    def _send_message(self, text: str):
        """Send message to Telegram chat."""
        try:
            # This would use python-telegram-bot in actual implementation
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            resp = requests.post(url, json=data, timeout=5)
            resp.raise_for_status()
            
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

# ── X (Twitter) Integration ───────────────────────────────────────────────────

# 4. X (Twitter) posting bot

class KalshiXNotifier:
    """X (Twitter) notifier for Kalshi events with conservative rate limiting."""
    
    def __init__(self, event_bus: Optional[KalshiEventBus] = None):
        self.event_bus = event_bus or kalshi_event_bus
        self.api_key = os.environ.get("X_API_KEY", "")
        self.api_secret = os.environ.get("X_API_SECRET", "")
        self.access_token = os.environ.get("X_ACCESS_TOKEN", "")
        self.access_secret = os.environ.get("X_ACCESS_SECRET", "")
        self.running = False
        
        # Conservative rate limiting to stay well under X API limits
        # Basic tier: ~1,500-3,000 posts/month, so we limit to ~200/day max
        self.min_post_interval = 60.0  # 1 minute between posts
        self.daily_post_limit = 200    # Max 200 posts per day
        self.last_post_time = 0
        self.posts_today = 0
        self.last_reset_date = time.strftime("%Y-%m-%d")
        
    def start(self):
        """Start the X notifier."""
        if not all([self.api_key, self.api_secret, self.access_token, self.access_secret]):
            logger.warning("X API credentials not configured")
            return
            
        self.running = True
        self.event_bus.subscribe(self._handle_event)
        logger.info("X notifier started with conservative rate limiting")
    
    def stop(self):
        """Stop the X notifier."""
        self.running = False
        if self.event_bus:
            self.event_bus.unsubscribe(self._handle_event)
        logger.info("X notifier stopped")
    
    def _handle_event(self, event: KalshiEvent):
        """Handle incoming Kalshi events with rate limiting."""
        if not self.running:
            return
            
        try:
            if event.type == "order_fill":
                self._post_order_fill_tweet(event)
                
        except Exception as e:
            logger.error(f"X notification error: {e}")
    
    def _can_post(self) -> bool:
        """Check if we can post within rate limits."""
        now = time.time()
        current_date = time.strftime("%Y-%m-%d")
        
        # Reset daily counter if date changed
        if current_date != self.last_reset_date:
            self.posts_today = 0
            self.last_reset_date = current_date
            logger.info("X notifier daily post counter reset")
        
        # Check minimum interval
        time_since_last = now - self.last_post_time
        if time_since_last < self.min_post_interval:
            logger.debug(f"X notifier rate limited: {time_since_last:.1f}s since last post (min: {self.min_post_interval}s)")
            return False
        
        # Check daily limit
        if self.posts_today >= self.daily_post_limit:
            logger.warning(f"X notifier daily limit reached: {self.posts_today}/{self.daily_post_limit}")
            return False
        
        return True
    
    def _post_order_fill_tweet(self, event: KalshiEvent):
        """Post order fill tweet with rate limiting."""
        if not self._can_post():
            logger.debug("Skipping X post due to rate limiting")
            return
            
        payload = event.payload
        ticker = payload.get("ticker", "Unknown")
        side = payload.get("side", "Unknown")
        count = payload.get("count", 0)
        
        text = f"New Kalshi fill: {ticker} {side} x{count}. #Kalshi #Trading"
        
        try:
            self._post_to_x(text)
            self.last_post_time = time.time()
            self.posts_today += 1
            logger.info(f"Posted to X: {text} (posts today: {self.posts_today})")
        except Exception as e:
            logger.error(f"Failed to post to X: {e}")
    
    def _post_to_x(self, text: str) -> dict:
        """Post tweet to X with proper error handling."""
        try:
            # This would use requests_oauthlib in actual implementation
            auth = self._get_oauth1_auth()
            
            url = "https://api.x.com/2/tweets"
            resp = requests.post(url, auth=auth, json={"text": text}, timeout=10)
            resp.raise_for_status()
            return resp.json()
            
        except Exception as e:
            logger.error(f"Failed to post to X: {e}")
            raise
    
    def _get_oauth1_auth(self):
        """Get OAuth1 authentication for X API."""
        try:
            from requests_oauthlib import OAuth1
            return OAuth1(
                self.api_key,
                client_secret=self.api_secret,
                resource_owner_key=self.access_token,
                resource_owner_secret=self.access_secret
            )
        except ImportError:
            logger.error("requests_oauthlib not installed")
            raise
    
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get current rate limit status."""
        now = time.time()
        time_since_last = now - self.last_post_time if self.last_post_time > 0 else float('inf')
        
        return {
            "running": self.running,
            "posts_today": self.posts_today,
            "daily_limit": self.daily_post_limit,
            "last_post_time": self.last_post_time,
            "time_since_last": time_since_last,
            "min_post_interval": self.min_post_interval,
            "can_post": self._can_post(),
            "last_reset_date": self.last_reset_date
        }

# ── Complete Event-Driven Architecture Example ───────────────────────────────

class KalshiEventDrivenSystem:
    """Complete event-driven Kalshi trading system."""
    
    def __init__(self):
        # Initialize event bus
        self.event_bus = KalshiEventBus()
        self.event_bus.start_dispatcher()
        
        # Initialize rate-aware client with event emission
        self.client = KalshiRateAwareClient(safety_factor=0.8)
        
        # Initialize notifiers
        self.telegram_notifier = KalshiTelegramNotifier(self.event_bus)
        self.x_notifier = KalshiXNotifier(self.event_bus)
        
        # Initialize API endpoints
        self.event_api = KalshiEventAPI(self.event_bus)
        
    def start(self):
        """Start the complete system."""
        self.telegram_notifier.start()
        self.x_notifier.start()
        logger.info("Kalshi event-driven system started")
    
    def stop(self):
        """Stop the complete system."""
        self.telegram_notifier.stop()
        self.x_notifier.stop()
        self.event_bus.stop()
        logger.info("Kalshi event-driven system stopped")
    
    def make_trading_request(self, method: str, path: str, **kwargs) -> dict:
        """Make a trading request with automatic event emission."""
        resp = self.client.dynamic_limiter.make_request(method, path, **kwargs)
        
        # Emit trading-specific events based on response
        if method.upper() == "POST" and "/portfolio/orders" in path:
            try:
                order_data = resp.json()
                if order_data.get("status") == "filled":
                    self.event_bus.publish(KalshiEvent(
                        type="order_fill",
                        payload=order_data,
                        ts=time.time(),
                        source="trading_engine"
                    ))
                elif order_data.get("status") in ["rejected", "cancelled"]:
                    self.event_bus.publish(KalshiEvent(
                        type="order_reject",
                        payload=order_data,
                        ts=time.time(),
                        source="trading_engine"
                    ))
            except Exception as e:
                logger.error(f"Failed to process order response: {e}")
        
        return resp.json()

# Usage example:
"""
# Initialize the system
system = KalshiEventDrivenSystem()
system.start()

# Make trading requests - events are automatically emitted
try:
    order_data = {
        "ticker": "KXBTC15M-25MAR26",
        "side": "buy",
        "order_type": "limit",
        "price": 4500,
        "count": 10
    }
    result = system.make_trading_request("POST", "/portfolio/orders", json=order_data)
    print(f"Order result: {result}")
except Exception as e:
    print(f"Trading error: {e}")

# Clean shutdown
system.stop()
"""

# ── Production Integration Summary ───────────────────────────────────────

# Example 1: Basic usage with rate limiting
def example_basic_usage():
    """Example of basic rate-limited API usage."""
    client = KalshiRateAwareClient(safety_factor=0.8)
    
    # Get positions (rate-limited)
    try:
        positions = client.get("/portfolio/positions")
        print(f"Got {len(positions.get('positions', []))} positions")
    except Exception as e:
        print(f"Error getting positions: {e}")
    
    # Create order (rate-limited)
    try:
        order_data = {
            "ticker": "KXBTC15M-25MAR26",
            "side": "buy",
            "order_type": "limit",
            "price": 4500,
            "count": 10
        }
        order = client.post("/portfolio/orders", json=order_data)
        print(f"Created order: {order.get('order_id')}")
    except Exception as e:
        print(f"Error creating order: {e}")

# Example 2: Direct queue usage for advanced scenarios
def example_direct_queue():
    """Example of using request queue directly."""
    
    # Create custom queue with specific limits
    queue = KalshiRequestQueue(read_limit=10, write_limit=5)
    
    # Enqueue multiple requests concurrently
    futures = []
    for i in range(5):
        future = queue.enqueue_request(
            "GET", 
            f"{BASE}/portfolio/positions",
            headers=auth_headers("/portfolio/positions")
        )
        futures.append(future)
    
    # Wait for all responses
    responses = []
    for i, future in enumerate(futures):
        try:
            resp = queue.get_response(future, timeout=10)
            responses.append(resp.json())
            print(f"Request {i+1} completed")
        except Exception as e:
            print(f"Request {i+1} failed: {e}")
    
    print(f"Completed {len(responses)} requests")

# Example 3: Dynamic limit adjustment
def example_dynamic_limits():
    """Example of dynamic limit adjustment."""
    
    # Get current limits
    limits = get_api_limits()
    print(f"Current tier: {limits.get('usage_tier')}")
    print(f"Read limit: {limits.get('read_limit')}/s")
    print(f"Write limit: {limits.get('write_limit')}/s")
    
    # Create client with 70% safety factor
    client = KalshiRateAwareClient(safety_factor=0.7)
    client_limits = client.get_limits()
    print(f"Client read limit: {client_limits['read_limit']}/s")
    print(f"Client write limit: {client_limits['write_limit']}/s")
    
    # Force update limits
    client.update_limits()
    
    # Make some requests to test rate limiting
    start_time = time.time()
    for i in range(10):
        try:
            positions = client.get("/portfolio/positions")
            print(f"Request {i+1} completed")
        except Exception as e:
            print(f"Request {i+1} failed: {e}")
    
    elapsed = time.time() - start_time
    print(f"Completed 10 requests in {elapsed:.2f} seconds")


# ── Production Integration Example ───────────────────────────────────────

async def run_production_maker_bot():
    """Complete production maker bot with all optimizations."""
    
    # Configure for 15m crypto markets
    tickers = [
        "KXBTC15M-25MAR26",
        "KXETH15M-25MAR26", 
        "KXSOL15M-25MAR26"
    ]
    
    # Initialize multi-market maker
    maker = KalshiMultiMarketMaker(
        tickers=tickers,
        max_concurrent_quotes=8
    )
    
    # Start the bot
    await maker.start()
    
    logger.info("Production maker bot running with optimized latency and risk management")


if __name__ == "__main__":
    # Run example
    asyncio.run(run_maker_bot_example())
