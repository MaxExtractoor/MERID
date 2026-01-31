"""
Simulator Venue Adapter - Connects MERID to the self-hosted execution simulator

Implements the VenueAdapter interface for the ExecutionSimulator,
providing a seamless transition between paper trading and live trading.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Any
import time

from execution.venue_adapter import VenueAdapter, VenueConfig, VenueType, VenueOrder, VenuePosition, VenueAccount, OrderStatus
from execution.simulator import get_execution_simulator, ExecutionSimulator, Order, OrderSide, OrderType, OrderStatus as SimOrderStatus
from utils.logger import get_logger

logger = get_logger("execution.simulator_adapter")


class SimulatorVenueAdapter(VenueAdapter):
    """Venue adapter for the self-hosted execution simulator."""
    
    def __init__(self, config: VenueConfig):
        super().__init__(config)
        self.simulator: Optional[ExecutionSimulator] = None
        self.account_id: str = config.credentials.get("account_id", "sim_account")
        
        logger.info(f"SimulatorVenueAdapter initialized for account: {self.account_id}")
    
    async def connect(self) -> None:
        """Connect to the simulator."""
        try:
            self.simulator = get_execution_simulator()
            await self.simulator.start()
            
            # Create account if it doesn't exist
            account = self.simulator.get_account(self.account_id)
            if not account:
                initial_cash = self.config.settings.get("initial_cash", 100000.0)
                self.simulator.create_account(self.account_id, initial_cash)
                logger.info(f"Created simulator account with ${initial_cash:,.2f}")
            
            # Subscribe to market data updates
            self.simulator.subscribe_market_data(self._on_market_data_update)
            
            self._connected = True
            logger.info(f"Connected to simulator for account: {self.account_id}")
            
        except Exception as e:
            logger.error(f"Failed to connect to simulator: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Disconnect from the simulator."""
        try:
            if self.simulator:
                await self.simulator.stop()
            self._connected = False
            logger.info("Disconnected from simulator")
        except Exception as e:
            logger.error(f"Error disconnecting from simulator: {e}")
    
    async def submit_order(self, order: VenueOrder) -> VenueOrder:
        """Submit an order to the simulator."""
        if not self.simulator or not self._connected:
            raise RuntimeError("Not connected to simulator")
        
        try:
            # Convert VenueOrder to simulator order
            sim_order_result = self.simulator.submit_order(
                account_id=self.account_id,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                price=order.price,
                stop_price=order.stop_price
            )
            
            # Update order with venue-specific data
            order.venue_order_id = sim_order_result["order_id"]
            order.status = self._convert_status(sim_order_result["status"])
            order.updated_at = time.time()
            
            # Get full order details
            sim_orders = self.simulator.get_orders(self.account_id)
            for sim_order in sim_orders:
                if sim_order["order_id"] == order.venue_order_id:
                    order.filled_quantity = sim_order["filled_quantity"]
                    order.avg_fill_price = sim_order["avg_fill_price"]
                    break
            
            logger.info(f"Submitted order {order.venue_order_id}: {order.side} {order.quantity} {order.symbol}")
            
            # Notify subscribers
            self._notify_order_update(order)
            
            return order
            
        except Exception as e:
            logger.error(f"Failed to submit order: {e}")
            order.status = OrderStatus.REJECTED
            order.venue_metadata["error"] = str(e)
            self._notify_order_update(order)
            raise
    
    async def cancel_order(self, venue_order_id: str) -> bool:
        """Cancel an order in the simulator."""
        if not self.simulator or not self._connected:
            raise RuntimeError("Not connected to simulator")
        
        try:
            result = self.simulator.cancel_order(self.account_id, venue_order_id)
            
            if result["status"] == "cancelled":
                # Get the cancelled order to notify subscribers
                orders = self.simulator.get_orders(self.account_id)
                for sim_order in orders:
                    if sim_order["order_id"] == venue_order_id:
                        venue_order = self._convert_sim_order_to_venue(sim_order)
                        self._notify_order_update(venue_order)
                        break
                
                logger.info(f"Cancelled order {venue_order_id}")
                return True
            else:
                logger.warning(f"Failed to cancel order {venue_order_id}: {result}")
                return False
                
        except Exception as e:
            logger.error(f"Error cancelling order {venue_order_id}: {e}")
            return False
    
    async def get_orders(self, status: Optional[str] = None) -> List[VenueOrder]:
        """Get orders from the simulator."""
        if not self.simulator or not self._connected:
            raise RuntimeError("Not connected to simulator")
        
        try:
            sim_orders = self.simulator.get_orders(self.account_id, status)
            venue_orders = []
            
            for sim_order in sim_orders:
                venue_order = self._convert_sim_order_to_venue(sim_order)
                venue_orders.append(venue_order)
            
            return venue_orders
            
        except Exception as e:
            logger.error(f"Failed to get orders: {e}")
            return []
    
    async def get_positions(self) -> Dict[str, VenuePosition]:
        """Get positions from the simulator."""
        if not self.simulator or not self._connected:
            raise RuntimeError("Not connected to simulator")
        
        try:
            sim_positions = self.simulator.get_positions(self.account_id)
            venue_positions = {}
            
            for sim_pos in sim_positions:
                venue_pos = VenuePosition(
                    symbol=sim_pos["symbol"],
                    quantity=sim_pos["quantity"],
                    avg_price=sim_pos["avg_price"],
                    unrealized_pnl=sim_pos["unrealized_pnl"],
                    realized_pnl=sim_pos["realized_pnl"]
                )
                venue_positions[sim_pos["symbol"]] = venue_pos
            
            return venue_positions
            
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return {}
    
    async def get_account(self) -> VenueAccount:
        """Get account information from the simulator."""
        if not self.simulator or not self._connected:
            raise RuntimeError("Not connected to simulator")
        
        try:
            sim_summary = self.simulator.get_account_summary(self.account_id)
            positions = await self.get_positions()
            
            account = VenueAccount(
                account_id=self.account_id,
                cash=sim_summary["cash"],
                buying_power=sim_summary["buying_power"],
                margin_used=sim_summary["margin_used"],
                total_unrealized_pnl=sim_summary["total_unrealized_pnl"],
                total_realized_pnl=sim_summary["total_realized_pnl"],
                positions=positions
            )
            
            return account
            
        except Exception as e:
            logger.error(f"Failed to get account: {e}")
            raise
    
    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get symbol information."""
        # For the simulator, we return basic symbol info
        # In a real implementation, this would come from market data
        return {
            "symbol": symbol,
            "min_tick_size": 0.01,
            "min_order_size": 0.01,
            "round_lot_size": 1.0,
            "trading_hours": "24/7",  # Simulator is always available
            "is_tradable": True
        }
    
    def _convert_status(self, sim_status: str) -> OrderStatus:
        """Convert simulator status to venue status."""
        status_mapping = {
            "new": OrderStatus.NEW,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED
        }
        return status_mapping.get(sim_status, OrderStatus.NEW)
    
    def _convert_sim_order_to_venue(self, sim_order: Dict[str, Any]) -> VenueOrder:
        """Convert simulator order to venue order."""
        return VenueOrder(
            venue_order_id=sim_order["order_id"],
            client_order_id=sim_order["order_id"],  # Simulator uses same ID
            symbol=sim_order["symbol"],
            side=sim_order["side"],
            order_type=sim_order["type"],
            quantity=sim_order["quantity"],
            filled_quantity=sim_order["filled_quantity"],
            avg_fill_price=sim_order["avg_fill_price"],
            status=self._convert_status(sim_order["status"]),
            created_at=sim_order.get("created_at", time.time()),
            updated_at=sim_order.get("updated_at", time.time())
        )
    
    def _on_market_data_update(self, market_data) -> None:
        """Handle market data updates from simulator."""
        # This could be used to trigger position updates or other events
        # For now, we'll just log that we received data
        pass


def create_simulator_adapter(account_id: str = "sim_account", initial_cash: float = 100000.0) -> SimulatorVenueAdapter:
    """Create a simulator venue adapter with default configuration."""
    config = VenueConfig(
        venue_type=VenueType.SIMULATOR,
        venue_name="execution_simulator",
        credentials={"account_id": account_id},
        settings={"initial_cash": initial_cash}
    )
    
    return SimulatorVenueAdapter(config)
