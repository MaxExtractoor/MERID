"""
Local Venue Adapter - First-class local simulation venue for MERID

Implements a broker-like API that forwards to the internal matching engine
instead of external exchanges, maintaining sim/paper/live parity.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from execution.venue_adapter import VenueAdapter, VenueConfig, VenueType, VenueOrder, VenuePosition, VenueAccount, OrderStatus
from execution.simulator import get_execution_simulator, MarketData
from execution.persistent_book import get_persistent_book_manager, PersistentOrderBook
from data.market_data_schemas import DataType, Side, LiquidityFlag
from data.geo_aware_venue_system import VenueType as GeoVenueType, AssetClass
from utils.logger import get_logger

logger = get_logger("venues.local_sim")


class LocalSimOrderStatus(Enum):
    """Local simulation order status."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class LocalSimOrder:
    """Local simulation order."""
    order_id: str
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "GTC"
    status: LocalSimOrderStatus = LocalSimOrderStatus.PENDING
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    created_at: float = 0.0
    updated_at: float = 0.0
    fills: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.updated_at == 0.0:
            self.updated_at = time.time()
        if self.fills is None:
            self.fills = []


class LocalVenueAdapter(VenueAdapter):
    """
    Local venue adapter that connects MERID to the internal matching engine.
    
    Provides a broker-like API while forwarding orders to the local simulator
    and persistent order books, maintaining full parity with external venues.
    """
    
    def __init__(self, config: VenueConfig):
        super().__init__(config)
        self.venue_type = VenueType.SIMULATOR
        self.venue_name = "local_sim"
        
        # Internal components
        self.simulator = get_execution_simulator()
        self.book_manager = get_persistent_book_manager()
        
        # Order tracking
        self._orders: Dict[str, LocalSimOrder] = {}
        self._account_id = config.credentials.get("account_id", "local_sim_account")
        self._initial_cash = config.settings.get("initial_cash", 100000.0)
        
        # Market data subscription
        self._market_data_callbacks: List[callable] = []
        
        logger.info(f"LocalVenueAdapter initialized for account: {self._account_id}")
    
    async def connect(self) -> None:
        """Connect to the local venue."""
        try:
            # Start simulator
            await self.simulator.start()
            
            # Start persistent book manager
            self.book_manager.start_all()
            
            # Create account if needed
            account = self.simulator.get_account(self._account_id)
            if not account:
                initial_cash = self._initial_cash
                self.simulator.create_account(self._account_id, initial_cash)
                logger.info(f"Created local venue account with ${initial_cash:,.2f}")
            
            # Subscribe to market data
            self.simulator.subscribe_market_data(self._on_market_data)
            
            self._connected = True
            logger.info("Connected to local venue")
            
        except Exception as e:
            logger.error(f"Failed to connect to local venue: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from the local venue."""
        try:
            await self.simulator.stop()
            self.book_manager.stop_all()
            self._connected = False
            logger.info("Disconnected from local venue")
        except Exception as e:
            logger.error(f"Error disconnecting from local venue: {e}")
    
    async def submit_order(self, order: VenueOrder) -> VenueOrder:
        """Submit an order to the local venue."""
        if not self._connected:
            raise RuntimeError("Not connected to local venue")
        
        try:
            # Convert to local order
            local_order = LocalSimOrder(
                order_id=order.venue_order_id,
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                stop_price=order.stop_price,
                time_in_force=order.time_in_force
            )
            
            # Risk check
            if not self._check_order_risk(local_order):
                local_order.status = LocalSimOrderStatus.REJECTED
                order.status = OrderStatus.REJECTED
                order.venue_metadata["error"] = "Risk check failed"
                self._notify_order_update(order)
                return order
            
            # Submit to simulator
            result = self.simulator.submit_order(
                account_id=self._account_id,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                stop_price=order.stop_price
            )
            
            # Update order status
            local_order.status = LocalSimOrderStatus.ACCEPTED
            order.status = OrderStatus.NEW
            order.venue_order_id = result["order_id"]
            local_order.order_id = result["order_id"]
            
            # Store order
            self._orders[local_order.order_id] = local_order
            
            # Get updated order details
            sim_orders = self.simulator.get_orders(self._account_id)
            for sim_order in sim_orders:
                if sim_order["order_id"] == local_order.order_id:
                    local_order.filled_quantity = sim_order["filled_quantity"]
                    local_order.avg_fill_price = sim_order["avg_fill_price"]
                    
                    if sim_order["status"] == "filled":
                        local_order.status = LocalSimOrderStatus.FILLED
                        order.status = OrderStatus.FILLED
                    elif sim_order["status"] == "partially_filled":
                        local_order.status = LocalSimOrderStatus.PARTIALLY_FILLED
                        order.status = OrderStatus.PARTIALLY_FILLED
                    
                    break
            
            local_order.updated_at = time.time()
            
            # Update persistent order book
            book = self.book_manager.get_book(order.symbol)
            if order.order_type == "limit":
                book.add_order(
                    order_id=local_order.order_id,
                    side=order.side,
                    price=order.price or 0.0,
                    quantity=int(order.quantity)
                )
            
            self._notify_order_update(order)
            
            logger.info(f"Submitted local order {local_order.order_id}: {order.side} {order.quantity} {order.symbol}")
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to submit local order: {e}")
            order.status = OrderStatus.REJECTED
            order.venue_metadata["error"] = str(e)
            self._notify_order_update(order)
            raise
    
    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an order in the local venue."""
        if not self._connected:
            raise RuntimeError("Not connected to local venue")
        
        try:
            local_order = self._orders.get(venue_order_id)
            if not local_order:
                return False
            
            # Cancel in simulator
            result = self.simulator.cancel_order(self._account_id, venue_order_id)
            
            if result["status"] == "cancelled":
                # Update order status
                local_order.status = LocalSimOrderStatus.CANCELLED
                local_order.updated_at = time.time()
                
                # Update persistent order book
                book = self.book_manager.get_book(local_order.symbol)
                book.remove_order(venue_order_id)
                
                # Notify subscribers
                venue_order = self._convert_local_to_venue(local_order)
                self._notify_order_update(venue_order)
                
                logger.info(f"Cancelled local order {venue_order_id}")
                return True
            else:
                logger.warning(f"Failed to cancel local order {venue_order_id}: {result}")
                return False
        
        except Exception as e:
            logger.error(f"Error cancelling local order {venue_order_id}: {e}")
            return False
    
    async def get_orders(self, status: Optional[str] = None) -> List[VenueOrder]:
        """Get orders from the local venue."""
        if not self._connected:
            raise RuntimeError("Not connected to local venue")
        
        try:
            orders = []
            for local_order in self._orders.values():
                if status and local_order.status.value != status:
                    continue
                
                venue_order = self._convert_local_to_venue(local_order)
                orders.append(venue_order)
            
            return orders
        
        except Exception as e:
            logger.error(f"Failed to get local orders: {e}")
            return []
    
    async def get_positions(self) -> Dict[str, VenuePosition]:
        """Get positions from the local venue."""
        if not self._connected:
            raise RuntimeError("Not connected to local venue")
        
        try:
            positions = {}
            
            # Get positions from simulator
            sim_positions = self.simulator.get_positions(self._account_id)
            for sim_pos in sim_positions:
                venue_pos = VenuePosition(
                    symbol=sim_pos["symbol"],
                    quantity=sim_pos["quantity"],
                    avg_price=sim_pos["avg_price"],
                    unrealized_pnl=sim_pos["unrealized_pnl"],
                    realized_pnl=sim_pos["realized_pnl"]
                )
                positions[sim_pos["symbol"]] = venue_pos
            
            return positions
        
        except Exception as e:
            logger.error(f"Failed to get local positions: {e}")
            return {}
    
    async def get_account(self) -> VenueAccount:
        """Get account information from the local venue."""
        if not self._connected:
            raise RuntimeError("Not connected to local venue")
        
        try:
            summary = self.simulator.get_account_summary(self._account_id)
            
            # Get positions for PnL calculation
            positions = await self.get_positions()
            
            account = VenueAccount(
                account_id=self._account_id,
                cash=summary["cash"],
                buying_power=summary["buying_power"],
                margin_used=summary["margin_used"],
                total_unrealized_pnl=summary["total_unrealized_pnl"],
                total_realized_pnl=summary["total_realized_pnl"],
                positions=positions
            )
            
            return account
        
        except Exception as e:
            logger.error(f"Failed to get local account: {e}")
            raise
    
    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get symbol information."""
        # For local venue, we return basic info
        return {
            "symbol": symbol,
            "min_tick_size": 0.01,
            "min_order_size": 0.01,
            "round_lot_size": 1.0,
            "trading_hours": "24/7",
            "is_tradable": True,
            "venue_type": "local_sim"
        }
    
    def _check_order_risk(self, order: LocalSimOrder) -> bool:
        """Check if order passes risk rules."""
        # Basic risk checks
        if order.quantity <= 0:
            return False
        
        if order.order_type == "limit" and order.price is None:
            return False
        
        if order.order_type == "stop" and order.stop_price is None:
            return False
        
        # Add more sophisticated risk checks here
        # - Position limits
        # - Notional limits
        # - Buying power checks
        
        return True
    
    def _convert_local_to_venue(self, local_order: LocalSimOrder) -> VenueOrder:
        """Convert local order to venue order."""
        status_mapping = {
            LocalSimOrderStatus.PENDING: OrderStatus.NEW,
            LocalSimOrderStatus.ACCEPTED: OrderStatus.NEW,
            LocalSimOrderStatus.REJECTED: OrderStatus.REJECTED,
            LocalSimOrderStatus.FILLED: OrderStatus.FILLED,
            LocalSimOrderStatus.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
            LocalSimOrderStatus.CANCELLED: OrderStatus.CANCELLED,
            LocalSimOrderStatus.EXPIRED: OrderStatus.EXPIRED
        }
        
        return VenueOrder(
            venue_order_id=local_order.order_id,
            client_order_id=local_order.client_order_id,
            symbol=local_order.symbol,
            side=local_order.side,
            order_type=local_order.order_type,
            quantity=local_order.quantity,
            price=local_order.price,
            stop_price=local_order.stop_price,
            time_in_force=local_order.time_in_force,
            status=status_mapping.get(local_order.status, OrderStatus.NEW),
            filled_quantity=local_order.filled_quantity,
            avg_fill_price=local_order.avg_fill_price,
            created_at=local_order.created_at,
            updated_at=local_order.updated_at
        )
    
    def _on_market_data(self, market_data: MarketData) -> None:
        """Handle market data updates."""
        # Convert to local market data format
        local_data = {
            "symbol": market_data.symbol,
            "timestamp": market_data.timestamp,
            "data_type": DataType.LOCAL_SIM_TICK,
            "bid_price": market_data.bid_price,
            "ask_price": market_data.ask_price,
            "bid_size": market_data.bid_size,
            "ask_size": market_data.ask_size,
            "last_price": market_data.last_price,
            "last_size": market_data.last_size,
            "venue": "local_sim"
        }
        
        # Notify subscribers
        for callback in self._market_data_callbacks:
            try:
                callback(local_data)
            except Exception as e:
                logger.error(f"Error in market data callback: {e}")
    
    def subscribe_market_data(self, callback: callable) -> None:
        """Subscribe to market data updates."""
        self._market_data_callbacks.append(callback)
    
    def get_order_book(self, symbol: str) -> Dict[str, Any]:
        """Get current order book for symbol."""
        if not self._connected:
            return {}
        
        book = self.book_manager.get_book(symbol)
        snapshot = book.get_snapshot()
        
        return {
            "symbol": symbol,
            "timestamp": snapshot.timestamp,
            "bids": [{"price": level.price, "quantity": level.quantity} for level in snapshot.bids],
            "asks": [{"price": level.price, "quantity": level.quantity} for level in snapshot.asks],
            "best_bid": book.get_best_bid(),
            "best_ask": book.get_best_ask(),
            "spread": book.get_spread(),
            "sequence_number": snapshot.sequence_number
        }


def create_local_sim_adapter(account_id: str = "local_sim_account", initial_cash: float = 100000.0) -> LocalVenueAdapter:
    """Create a local simulation venue adapter."""
    config = VenueConfig(
        venue_type=VenueType.SIMULATOR,
        venue_name="local_sim",
        credentials={"account_id": account_id},
        settings={"initial_cash": initial_cash}
    )
    
    return LocalVenueAdapter(config)
