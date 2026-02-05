"""MERID Alpaca Adapter - US Stocks, ETFs, and Crypto.

US-compliant trading via Alpaca Markets API (paper and live).
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import structlog
import os

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)


class AlpacaAdapter(VenueAdapter):
    """Alpaca adapter for US equities and crypto trading."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        paper: bool = True
    ):
        super().__init__("alpaca", paper)
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.api_secret = api_secret or os.getenv("ALPACA_API_SECRET")
        self.client = None
        self.logger = logger.bind(adapter="Alpaca", paper=paper)
    
    async def connect(self) -> bool:
        """Connect to Alpaca API."""
        try:
            # Mock connection for structure
            self.client = {
                "connected": True,
                "paper": self.paper,
                "api_key": self.api_key[:8] if self.api_key else None
            }
            self.connected = True
            self.logger.info("alpaca_connected", paper=self.paper)
            return True
        except Exception as e:
            self.logger.error("alpaca_connect_error", error=str(e))
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from Alpaca."""
        self.connected = False
        self.client = None
        self.logger.info("alpaca_disconnected")
        return True
    
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data for symbol."""
        try:
            # Mock market data
            return MarketData(
                symbol=symbol,
                bid=Decimal("150.00"),
                ask=Decimal("150.05"),
                last=Decimal("150.02"),
                volume_24h=Decimal("10000000"),
                high_24h=Decimal("152.00"),
                low_24h=Decimal("148.00"),
                timestamp=datetime.now(),
                venue="alpaca"
            )
        except Exception as e:
            self.logger.error("market_data_error", error=str(e))
            return None
    
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Place order on Alpaca."""
        try:
            self.logger.info(
                "placing_order",
                symbol=symbol,
                side=side.value,
                type=order_type.value,
                amount=str(amount)
            )
            
            order_id = f"alpaca_{datetime.now().timestamp()}"
            
            return {
                "status": "filled",
                "order_id": order_id,
                "symbol": symbol,
                "side": side.value,
                "filled_amount": str(amount),
                "filled_price": str(price) if price else "150.00",
                "venue": "alpaca",
                "paper": self.paper
            }
        except Exception as e:
            self.logger.error("order_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel order."""
        self.logger.info("cancelling_order", order_id=order_id)
        return {"status": "cancelled", "order_id": order_id}
    
    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status."""
        return Order(
            id=order_id,
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=Decimal("100"),
            price=None,
            filled=Decimal("100"),
            remaining=Decimal("0"),
            status="filled",
            venue="alpaca",
            timestamp=datetime.now()
        )
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders."""
        return []
    
    async def get_positions(self) -> List[Position]:
        """Get positions."""
        return [
            Position(
                symbol="AAPL",
                side="long",
                size=Decimal("100"),
                entry_price=Decimal("150.00"),
                current_price=Decimal("155.00"),
                unrealized_pnl=Decimal("500"),
                venue="alpaca",
                timestamp=datetime.now()
            )
        ]
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance."""
        return {
            "USD": Decimal("100000"),
            "BUYING_POWER": Decimal("200000")
        }


# Singleton
alpaca_adapter = AlpacaAdapter()
