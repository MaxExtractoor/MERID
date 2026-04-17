"""MERID Simulator Adapter - Paper Trading & Backtesting.

Internal MERID paper trading engine for simulation and backtesting.
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import structlog

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)


class MERIDSimulatorAdapter(VenueAdapter):
    """MERID internal paper trading simulator."""
    
    def __init__(self, initial_balance: Decimal = Decimal("100000")):
        super().__init__("merid_sim", paper=True)
        self.initial_balance = initial_balance
        self.balance = {"USD": initial_balance}
        self.orders: List[Order] = []
        self.positions: List[Position] = []
        self.logger = logger.bind(adapter="MERID_SIM")
    
    async def connect(self) -> bool:
        """Connect to MERID simulator."""
        self.connected = True
        self.logger.info("merid_sim_connected", balance=str(self.initial_balance))
        return True
    
    async def disconnect(self) -> bool:
        """Disconnect from simulator."""
        self.connected = False
        self.logger.info("merid_sim_disconnected")
        return True
    
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get simulated market data."""
        return MarketData(
            symbol=symbol,
            bid=Decimal("100.00"),
            ask=Decimal("100.05"),
            last=Decimal("100.02"),
            volume_24h=Decimal("1000000"),
            high_24h=Decimal("105.00"),
            low_24h=Decimal("95.00"),
            timestamp=datetime.now(),
            venue="merid_sim"
        )
    
    async def _place_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Place simulated order."""
        order_id = f"sim_{datetime.now().timestamp()}"
        
        order = Order(
            id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            filled=amount,
            remaining=Decimal("0"),
            status="filled",
            venue="merid_sim",
            timestamp=datetime.now()
        )
        
        self.orders.append(order)
        
        # Update balance
        fill_price = price or Decimal("100")
        cost = amount * fill_price
        
        if side == OrderSide.BUY:
            self.balance["USD"] -= cost
        else:
            self.balance["USD"] += cost
        
        self.logger.info(
            "simulated_order",
            symbol=symbol,
            side=side.value,
            amount=str(amount),
            price=str(fill_price)
        )
        
        return {
            "status": "filled",
            "order_id": order_id,
            "symbol": symbol,
            "side": side.value,
            "filled_amount": str(amount),
            "filled_price": str(fill_price),
            "venue": "merid_sim"
        }
    
    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel simulated order."""
        return {"status": "cancelled", "order_id": order_id}
    
    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status."""
        for order in self.orders:
            if order.id == order_id:
                return order
        return None
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders."""
        return [o for o in self.orders if o.status == "open"]
    
    async def get_positions(self) -> List[Position]:
        """Get simulated positions."""
        return self.positions
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get simulated balance."""
        return self.balance


# Singleton
merid_sim_adapter = MERIDSimulatorAdapter()
