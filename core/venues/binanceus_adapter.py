"""MERID Binance.US Adapter - US Crypto Spot Trading.

US-compliant crypto spot trading via Binance.US (not global Binance).
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import structlog
import os

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)


class BinanceUSAdapter(VenueAdapter):
    """Binance.US adapter for US crypto spot trading."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None
    ):
        super().__init__("binanceus", paper=True)
        self.api_key = api_key or os.getenv("BINANCE_US_API_KEY")
        self.api_secret = api_secret or os.getenv("BINANCE_US_API_SECRET")
        self.client = None
        self.endpoint = "https://api.binance.us"  # US-only endpoint
        self.logger = logger.bind(adapter="BinanceUS")
    
    async def connect(self) -> bool:
        """Connect to Binance.US API."""
        try:
            # Mock connection
            self.client = {
                "connected": True,
                "endpoint": self.endpoint,
                "api_key": self.api_key[:8] if self.api_key else None
            }
            self.connected = True
            self.logger.info("binanceus_connected", endpoint=self.endpoint)
            return True
        except Exception as e:
            self.logger.error("binanceus_connect_error", error=str(e))
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from Binance.US."""
        self.connected = False
        self.client = None
        self.logger.info("binanceus_disconnected")
        return True
    
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get crypto market data."""
        try:
            return MarketData(
                symbol=symbol,
                bid=Decimal("50000.00"),
                ask=Decimal("50010.00"),
                last=Decimal("50005.00"),
                volume_24h=Decimal("100000"),
                high_24h=Decimal("51000.00"),
                low_24h=Decimal("49000.00"),
                timestamp=datetime.now(),
                venue="binanceus"
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
        """Place crypto spot order."""
        try:
            self.logger.info(
                "placing_order",
                symbol=symbol,
                side=side.value,
                type=order_type.value,
                amount=str(amount)
            )
            
            order_id = f"binanceus_{datetime.now().timestamp()}"
            
            return {
                "status": "filled",
                "order_id": order_id,
                "symbol": symbol,
                "side": side.value,
                "filled_amount": str(amount),
                "venue": "binanceus"
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
            amount=Decimal("0.1"),
            price=None,
            filled=Decimal("0.1"),
            remaining=Decimal("0"),
            status="filled",
            venue="binanceus",
            timestamp=datetime.now()
        )
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders."""
        return []
    
    async def get_positions(self) -> List[Position]:
        """Get crypto positions."""
        return [
            Position(
                symbol="BTC",
                side="long",
                size=Decimal("0.5"),
                entry_price=Decimal("48000"),
                current_price=Decimal("50000"),
                unrealized_pnl=Decimal("1000"),
                venue="binanceus",
                timestamp=datetime.now()
            )
        ]
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get crypto balances."""
        return {
            "USD": Decimal("10000"),
            "BTC": Decimal("0.5"),
            "ETH": Decimal("5.0")
        }


# Singleton
binanceus_adapter = BinanceUSAdapter()
