"""MERID Gemini Adapter - US Crypto Trading.

US-compliant crypto trading via Gemini API (REST/WebSocket).
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import structlog
import os

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)


class GeminiAdapter(VenueAdapter):
    _is_stub = True
    """Gemini adapter for US crypto spot trading."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        sandbox: bool = True
    ):
        super().__init__("gemini", paper=sandbox)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.api_secret = api_secret or os.getenv("GEMINI_API_SECRET")
        self.sandbox = sandbox
        self.client = None
        self.endpoint = "https://api.sandbox.gemini.com" if sandbox else "https://api.gemini.com"
        self.logger = logger.bind(adapter="Gemini", sandbox=sandbox)
    
    async def connect(self) -> bool:
        """Connect to Gemini API."""
        try:
            self.client = {
                "connected": True,
                "endpoint": self.endpoint,
                "api_key": self.api_key[:8] if self.api_key else None,
                "sandbox": self.sandbox
            }
            self.connected = True
            self.logger.info("gemini_connected", endpoint=self.endpoint)
            return True
        except Exception as e:
            self.logger.error("gemini_connect_error", error=str(e))
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from Gemini."""
        self.connected = False
        self.client = None
        self.logger.info("gemini_disconnected")
        return True
    
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get crypto market data from Gemini."""
        try:
            # Gemini uses symbols like "btcusd"
            gemini_symbol = symbol.replace("/", "").replace("-", "").lower()
            
            return MarketData(
                symbol=symbol,
                bid=Decimal("50020.00"),
                ask=Decimal("50030.00"),
                last=Decimal("50025.00"),
                volume_24h=Decimal("60000"),
                high_24h=Decimal("50500.00"),
                low_24h=Decimal("49500.00"),
                timestamp=datetime.now(),
                venue="gemini"
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
        """Place crypto order on Gemini."""
        try:
            gemini_symbol = symbol.replace("/", "").replace("-", "").lower()
            
            self.logger.info(
                "placing_order",
                symbol=gemini_symbol,
                side=side.value,
                type=order_type.value,
                amount=str(amount)
            )
            
            order_id = f"gemini_{datetime.now().timestamp()}"
            
            return {
                "status": "filled",
                "order_id": order_id,
                "symbol": gemini_symbol,
                "side": side.value,
                "filled_amount": str(amount),
                "filled_price": str(price) if price else "50025.00",
                "venue": "gemini",
                "sandbox": self.sandbox
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
            venue="gemini",
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
                size=Decimal("0.2"),
                entry_price=Decimal("48500"),
                current_price=Decimal("50000"),
                unrealized_pnl=Decimal("300"),
                venue="gemini",
                timestamp=datetime.now()
            )
        ]
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance."""
        return {
            "USD": Decimal("12000"),
            "BTC": Decimal("0.2"),
            "ETH": Decimal("3.5")
        }


# Singleton
gemini_adapter = GeminiAdapter()
