"""MERID HTX (Huobi) Adapter - Optional/Data Venue.

Treat as data/sim only for US residents unless explicitly cleared for live trading.
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import structlog
import os

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)


class HTXAdapter(VenueAdapter):
    _is_stub = True
    """HTX (Huobi) adapter - optional/data venue for US users."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None
    ):
        super().__init__("htx", paper=True)  # Default to paper for safety
        self.api_key = api_key or os.getenv("HTX_KEY")
        self.api_secret = api_secret or os.getenv("HTX_SECRET")
        self.client = None
        self.endpoint = "https://api.huobi.pro"
        self.logger = logger.bind(adapter="HTX")
        self.us_compliance_warning = True  # Flag for US users
    
    async def connect(self) -> bool:
        """Connect to HTX API."""
        try:
            if self.us_compliance_warning:
                self.logger.warning(
                    "htx_us_compliance_warning",
                    message="HTX (Huobi) is not available to US residents. Use for data/sim only unless legally cleared."
                )
            
            self.client = {
                "connected": True,
                "endpoint": self.endpoint,
                "api_key": self.api_key[:8] if self.api_key else None
            }
            self.connected = True
            self.logger.info("htx_connected")
            return True
        except Exception as e:
            self.logger.error("htx_connect_error", error=str(e))
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from HTX."""
        self.connected = False
        self.client = None
        self.logger.info("htx_disconnected")
        return True
    
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data (safe for US data usage)."""
        try:
            # HTX uses symbols like "btcusdt"
            htx_symbol = symbol.replace("/", "").replace("-", "").lower()
            
            return MarketData(
                symbol=symbol,
                bid=Decimal("50012.00"),
                ask=Decimal("50022.00"),
                last=Decimal("50017.00"),
                volume_24h=Decimal("125000"),
                high_24h=Decimal("50600.00"),
                low_24h=Decimal("49400.00"),
                timestamp=datetime.now(),
                venue="htx"
            )
        except Exception as e:
            self.logger.error("market_data_error", error=str(e))
            return None
    
    async def get_candlestick(self, symbol: str, interval: str = "MIN1", size: int = 10) -> List[Dict]:
        """Get candlestick data."""
        try:
            self.logger.info("fetching_candlesticks", symbol=symbol, interval=interval, size=size)
            # Mock candlestick data
            return [
                {
                    "timestamp": int(datetime.now().timestamp()) - i * 60,
                    "open": "50000.00",
                    "high": "50100.00",
                    "low": "49900.00",
                    "close": "50050.00",
                    "volume": "100.5"
                }
                for i in range(size)
            ]
        except Exception as e:
            self.logger.error("candlestick_error", error=str(e))
            return []
    
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
            self.logger.error("htx_live_trading_blocked_us")
            return {
                "status": "blocked",
                "reason": "HTX live trading blocked for US residents. Use paper mode or MERID_SIM."
            }
        
        try:
            htx_symbol = symbol.replace("/", "").replace("-", "").lower()
            htx_side = "buy-market" if side == OrderSide.BUY else "sell-market"
            
            self.logger.info(
                "placing_order",
                symbol=htx_symbol,
                side=htx_side,
                amount=str(amount)
            )
            
            order_id = f"htx_{datetime.now().timestamp()}"
            
            return {
                "status": "filled" if self.paper else "rejected",
                "order_id": order_id,
                "symbol": htx_symbol,
                "venue": "htx",
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
            venue="htx",
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
        return {"USD": Decimal("0"), "BTC": Decimal("0"), "USDT": Decimal("0")}


# Singleton
htx_adapter = HTXAdapter()
