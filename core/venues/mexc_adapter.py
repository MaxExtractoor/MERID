"""MERID MEXC Adapter - Optional/Data Venue.

Treat as data/sim only for US residents unless explicitly cleared for live trading.
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import structlog
import os

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)


class MEXCAdapter(VenueAdapter):
    _is_stub = True
    """MEXC adapter - optional/data venue for US users."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None
    ):
        super().__init__("mexc", paper=True)  # Default to paper for safety
        self.api_key = api_key or os.getenv("MEXC_KEY")
        self.api_secret = api_secret or os.getenv("MEXC_SECRET")
        self.client = None
        self.endpoint = "https://api.mexc.com"
        self.logger = logger.bind(adapter="MEXC")
        self.us_compliance_warning = True  # Flag for US users
    
    async def connect(self) -> bool:
        """Connect to MEXC API."""
        try:
            if self.us_compliance_warning:
                self.logger.warning(
                    "mexc_us_compliance_warning",
                    message="MEXC may not be available to US residents. Use for data/sim only unless legally cleared."
                )
            
            self.client = {
                "connected": True,
                "endpoint": self.endpoint,
                "api_key": self.api_key[:8] if self.api_key else None
            }
            self.connected = True
            self.logger.info("mexc_connected")
            return True
        except Exception as e:
            self.logger.error("mexc_connect_error", error=str(e))
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from MEXC."""
        self.connected = False
        self.client = None
        self.logger.info("mexc_disconnected")
        return True
    
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data (safe for US data usage)."""
        try:
            return MarketData(
                symbol=symbol,
                bid=Decimal("50005.00"),
                ask=Decimal("50015.00"),
                last=Decimal("50010.00"),
                volume_24h=Decimal("140000"),
                high_24h=Decimal("50800.00"),
                low_24h=Decimal("49200.00"),
                timestamp=datetime.now(),
                venue="mexc"
            )
        except Exception as e:
            self.logger.error("market_data_error", error=str(e))
            return None
    
    async def _place_order_impl(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Place order - requires explicit US compliance clearance."""
        if self.us_compliance_warning and not self.paper:
            self.logger.error("mexc_live_trading_blocked_us")
            return {
                "status": "blocked",
                "reason": "MEXC live trading blocked for US residents. Use paper mode or MERID_SIM."
            }
        
        try:
            self.logger.info(
                "placing_order",
                symbol=symbol,
                side=side.value,
                amount=str(amount)
            )
            
            order_id = f"mexc_{datetime.now().timestamp()}"
            
            return {
                "status": "filled" if self.paper else "rejected",
                "order_id": order_id,
                "symbol": symbol,
                "venue": "mexc",
                "paper": self.paper
            }
        except Exception as e:
            self.logger.error("order_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel order."""
        return {"status": "cancelled", "order_id": order_id}
    
    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status."""
        return Order(
            id=order_id,
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("0.1"),
            price=None,
            filled=Decimal("0.1"),
            remaining=Decimal("0"),
            status="filled",
            venue="mexc",
            timestamp=datetime.now()
        )
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders."""
        return []
    
    async def get_positions(self) -> List[Position]:
        """Get positions."""
        return []
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get balance."""
        return {"USD": Decimal("0"), "BTC": Decimal("0")}


# Singleton
mexc_adapter = MEXCAdapter()
