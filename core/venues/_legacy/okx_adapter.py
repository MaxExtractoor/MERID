"""MERID OKX Adapter - Optional/Data Venue with Rate Limiting.

Treat as data/sim only for US residents unless explicitly cleared for live trading.
Includes rate limit checking to avoid 50061 errors.
"""

from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import datetime
import structlog
import os

from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, Position, MarketData

logger = structlog.get_logger(__name__)


class OKXAdapter(VenueAdapter):
    _is_stub = True
    """OKX adapter - optional/data venue for US users with rate limit awareness."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None
    ):
        super().__init__("okx", paper=True)  # Default to paper for safety
        self.api_key = api_key or os.getenv("OKX_KEY")
        self.api_secret = api_secret or os.getenv("OKX_SECRET")
        self.passphrase = passphrase or os.getenv("OKX_PASSPHRASE")
        self.client = None
        self.endpoint = "https://www.okx.com"
        self.logger = logger.bind(adapter="OKX")
        self.us_compliance_warning = True  # Flag for US users
        self.rate_limit_quota = {
            "remaining": 1500,  # OKX default: 1000-1500 per 2s
            "total": 1500,
            "reset_in": 2
        }
    
    async def connect(self) -> bool:
        """Connect to OKX API with rate limit awareness."""
        try:
            if self.us_compliance_warning:
                self.logger.warning(
                    "okx_us_compliance_warning",
                    message="OKX may be restricted for US residents. Use for data/sim only unless legally cleared."
                )
            
            self.client = {
                "connected": True,
                "endpoint": self.endpoint,
                "api_key": self.api_key[:8] if self.api_key else None,
                "rate_limit": self.rate_limit_quota
            }
            self.connected = True
            self.logger.info("okx_connected", rate_limit=self.rate_limit_quota)
            return True
        except Exception as e:
            self.logger.error("okx_connect_error", error=str(e))
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from OKX."""
        self.connected = False
        self.client = None
        self.logger.info("okx_disconnected")
        return True
    
    async def check_rate_limit(self) -> Dict[str, Any]:
        """Check current rate limit status (OKX: 50061 error prevention)."""
        try:
            # Mock rate limit check - in production, query OKX endpoint
            self.logger.info("checking_rate_limit", quota=self.rate_limit_quota)
            return {
                "remaining": self.rate_limit_quota["remaining"],
                "total": self.rate_limit_quota["total"],
                "reset_in": self.rate_limit_quota["reset_in"],
                "status": "ok" if self.rate_limit_quota["remaining"] > 100 else "warning"
            }
        except Exception as e:
            self.logger.error("rate_limit_check_error", error=str(e))
            return {"status": "error", "remaining": 0}
    
    async def consume_rate_limit(self, weight: int = 1):
        """Consume rate limit quota."""
        self.rate_limit_quota["remaining"] = max(0, self.rate_limit_quota["remaining"] - weight)
        if self.rate_limit_quota["remaining"] < 100:
            self.logger.warning("okx_rate_limit_low", remaining=self.rate_limit_quota["remaining"])
    
    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get market data with rate limit check."""
        try:
            await self.consume_rate_limit(weight=1)
            
            # OKX uses symbols like "BTC-USDT"
            okx_symbol = symbol.replace("/", "-").upper()
            
            return MarketData(
                symbol=symbol,
                bid=Decimal("50018.00"),
                ask=Decimal("50028.00"),
                last=Decimal("50023.00"),
                volume_24h=Decimal("135000"),
                high_24h=Decimal("50700.00"),
                low_24h=Decimal("49300.00"),
                timestamp=datetime.now(),
                venue="okx"
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
        """Place order with rate limit check and US compliance."""
        # Check rate limit first (OKX: 1000-1500 orders per 2s)
        if self.rate_limit_quota["remaining"] < 10:
            self.logger.error("okx_rate_limit_exceeded", error_code=50061)
            return {
                "status": "rate_limited",
                "error_code": 50061,
                "reason": "Rate limit exceeded. Back off and retry."
            }
        
        if self.us_compliance_warning and not self.paper:
            self.logger.error("okx_live_trading_blocked_us")
            return {
                "status": "blocked",
                "reason": "OKX live trading blocked for US residents. Use paper mode or MERID_SIM."
            }
        
        try:
            await self.consume_rate_limit(weight=2)  # Orders consume more weight
            
            okx_symbol = symbol.replace("/", "-").upper()
            td_mode = "cross"  # cross-margin mode
            ord_type = "market" if order_type == OrderType.MARKET else "limit"
            
            self.logger.info(
                "placing_order",
                symbol=okx_symbol,
                side=side.value,
                td_mode=td_mode,
                ord_type=ord_type,
                amount=str(amount)
            )
            
            order_id = f"okx_{datetime.now().timestamp()}"
            
            return {
                "status": "filled" if self.paper else "rejected",
                "order_id": order_id,
                "symbol": okx_symbol,
                "venue": "okx",
                "paper": self.paper,
                "rate_limit_remaining": self.rate_limit_quota["remaining"]
            }
        except Exception as e:
            self.logger.error("order_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel order with rate limit."""
        await self.consume_rate_limit(weight=1)
        return {"status": "cancelled", "order_id": order_id}
    
    async def get_order_status(self, order_id: str, symbol: str) -> Optional[Order]:
        """Get order status with rate limit."""
        await self.consume_rate_limit(weight=1)
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
            venue="okx",
            timestamp=datetime.now()
        )
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders with rate limit."""
        await self.consume_rate_limit(weight=1)
        return []
    
    async def get_positions(self) -> List[Position]:
        """Get positions with rate limit."""
        await self.consume_rate_limit(weight=1)
        return []
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get balance with rate limit."""
        await self.consume_rate_limit(weight=1)
        return {"USD": Decimal("0"), "BTC": Decimal("0"), "USDT": Decimal("0")}


# Singleton
okx_adapter = OKXAdapter()
