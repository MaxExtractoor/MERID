"""MERID Spot & Perp Trading Module using CCXT.

Unified trading interface for 100+ CEX/DEX exchanges supporting spot and
perpetual futures trading. Integrates with MERID swarm for risk management.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum
import structlog
import os

logger = structlog.get_logger(__name__)


class MarketType(str, Enum):
    """Market types."""
    SPOT = "spot"
    PERP = "perp"
    FUTURES = "futures"
    MARGIN = "margin"


class OrderSide(str, Enum):
    """Order sides."""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TAKE_PROFIT = "take_profit"


@dataclass
class Order:
    """Trading order."""
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    amount: Decimal
    price: Optional[Decimal]
    filled: Decimal
    remaining: Decimal
    status: str
    timestamp: datetime
    fee: Decimal
    market_type: MarketType


@dataclass
class Position:
    """Perp/futures position."""
    symbol: str
    side: str  # long/short
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    liquidation_price: Optional[Decimal]
    margin: Decimal
    leverage: Decimal
    unrealized_pnl: Decimal
    funding_rate: Decimal
    timestamp: datetime


@dataclass
class Ticker:
    """Market ticker."""
    symbol: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    volume_24h: Decimal
    high_24h: Decimal
    low_24h: Decimal
    change_24h: Decimal
    change_pct_24h: Decimal
    timestamp: datetime


class CCXTTrader:
    """Unified trading interface via CCXT."""
    
    def __init__(
        self,
        exchange_id: str = "binance",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        sandbox: bool = True
    ):
        self.exchange_id = exchange_id
        self.api_key = api_key or os.getenv(f"{exchange_id.upper()}_API_KEY")
        self.api_secret = api_secret or os.getenv(f"{exchange_id.upper()}_API_SECRET")
        self.sandbox = sandbox
        self.exchange = None
        self.logger = logger.bind(trader=exchange_id)
        
        self._init_exchange()
    
    def _init_exchange(self):
        """Initialize CCXT exchange."""
        try:
            # Mock CCXT initialization
            self.exchange = {
                "id": self.exchange_id,
                "sandbox": self.sandbox,
                "has": {
                    "spot": True,
                    "future": True,
                    "leverage": True
                }
            }
            self.logger.info("exchange_initialized", sandbox=self.sandbox)
        except Exception as e:
            self.logger.error("exchange_init_error", error=str(e))
    
    async def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """Get market ticker."""
        try:
            # Mock ticker
            return Ticker(
                symbol=symbol,
                bid=Decimal("50000"),
                ask=Decimal("50100"),
                last=Decimal("50050"),
                volume_24h=Decimal("100000000"),
                high_24h=Decimal("51000"),
                low_24h=Decimal("49000"),
                change_24h=Decimal("500"),
                change_pct_24h=Decimal("0.01"),
                timestamp=datetime.now()
            )
        except Exception as e:
            self.logger.error("ticker_error", error=str(e))
            return None
    
    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        price: Optional[Decimal] = None,
        market_type: MarketType = MarketType.SPOT,
        leverage: Optional[int] = None
    ) -> Dict[str, Any]:
        """Place order on exchange."""
        try:
            self.logger.info(
                "placing_order",
                symbol=symbol,
                side=side.value,
                type=order_type.value,
                amount=str(amount),
                market=market_type.value
            )
            
            # Set leverage for perp
            if market_type == MarketType.PERP and leverage:
                await self.set_leverage(symbol, leverage)
            
            # Mock order execution
            order_id = f"{self.exchange_id}_{datetime.now().timestamp()}"
            
            return {
                "status": "filled",
                "order_id": order_id,
                "symbol": symbol,
                "side": side.value,
                "type": order_type.value,
                "amount": str(amount),
                "price": str(price) if price else str(Decimal("50000")),
                "filled": str(amount),
                "fee": str(amount * Decimal("0.001")),
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            self.logger.error("order_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel open order."""
        try:
            self.logger.info("cancelling_order", order_id=order_id)
            return {"status": "cancelled", "order_id": order_id}
        except Exception as e:
            self.logger.error("cancel_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Get open orders."""
        # Mock open orders
        return [
            Order(
                id=f"order_{i}",
                symbol=symbol or "BTC/USDT",
                side=OrderSide.BUY,
                type=OrderType.LIMIT,
                amount=Decimal("0.1"),
                price=Decimal("49000"),
                filled=Decimal("0"),
                remaining=Decimal("0.1"),
                status="open",
                timestamp=datetime.now(),
                fee=Decimal("0"),
                market_type=MarketType.SPOT
            )
            for i in range(2)
        ]
    
    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Get perp/futures positions."""
        # Mock positions
        return [
            Position(
                symbol=symbol or "BTC/USDT:USDT",
                side="long",
                size=Decimal("1.0"),
                entry_price=Decimal("50000"),
                mark_price=Decimal("51000"),
                liquidation_price=Decimal("45000"),
                margin=Decimal("1000"),
                leverage=Decimal("10"),
                unrealized_pnl=Decimal("1000"),
                funding_rate=Decimal("0.0001"),
                timestamp=datetime.now()
            )
        ]
    
    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """Set leverage for perp trading."""
        try:
            self.logger.info("setting_leverage", symbol=symbol, leverage=leverage)
            return {
                "status": "success",
                "symbol": symbol,
                "leverage": leverage
            }
        except Exception as e:
            self.logger.error("leverage_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def close_position(
        self,
        symbol: str,
        position_side: Optional[str] = None
    ) -> Dict[str, Any]:
        """Close perp/futures position."""
        try:
            self.logger.info("closing_position", symbol=symbol)
            
            # Mock close
            return {
                "status": "closed",
                "symbol": symbol,
                "realized_pnl": "500",
                "closing_price": "51000"
            }
        except Exception as e:
            self.logger.error("close_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def get_balance(self) -> Dict[str, Decimal]:
        """Get account balance."""
        return {
            "USDT": Decimal("10000"),
            "BTC": Decimal("0.5"),
            "ETH": Decimal("5.0")
        }


class MultiExchangeTrader:
    """Manage multiple exchange connections."""
    
    def __init__(self):
        self.exchanges: Dict[str, CCXTTrader] = {}
        self.logger = logger.bind(component="MultiExchangeTrader")
    
    def add_exchange(
        self,
        exchange_id: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None
    ):
        """Add exchange connection."""
        trader = CCXTTrader(
            exchange_id=exchange_id,
            api_key=api_key,
            api_secret=api_secret
        )
        self.exchanges[exchange_id] = trader
        self.logger.info("exchange_added", exchange=exchange_id)
    
    async def get_best_price(self, symbol: str, side: OrderSide) -> Tuple[str, Decimal]:
        """Get best price across all exchanges."""
        prices = []
        
        for exchange_id, trader in self.exchanges.items():
            ticker = await trader.get_ticker(symbol)
            if ticker:
                price = ticker.ask if side == OrderSide.BUY else ticker.bid
                prices.append((exchange_id, price))
        
        if not prices:
            return ("", Decimal("0"))
        
        # Best price for buy = lowest ask, for sell = highest bid
        if side == OrderSide.BUY:
            return min(prices, key=lambda x: x[1])
        else:
            return max(prices, key=lambda x: x[1])
    
    async def arbitrage_scan(
        self,
        symbol: str,
        min_spread_pct: Decimal = Decimal("0.005")
    ) -> List[Dict[str, Any]]:
        """Scan for arbitrage opportunities across exchanges."""
        opportunities = []
        
        prices = []
        for exchange_id, trader in self.exchanges.items():
            ticker = await trader.get_ticker(symbol)
            if ticker:
                prices.append({
                    "exchange": exchange_id,
                    "bid": ticker.bid,
                    "ask": ticker.ask
                })
        
        # Find spreads
        for i, p1 in enumerate(prices):
            for p2 in prices[i+1:]:
                spread = (p1["bid"] - p2["ask"]) / p2["ask"]
                if spread > min_spread_pct:
                    opportunities.append({
                        "buy_exchange": p2["exchange"],
                        "sell_exchange": p1["exchange"],
                        "spread_pct": float(spread * 100),
                        "buy_price": str(p2["ask"]),
                        "sell_price": str(p1["bid"])
                    })
        
        return opportunities


class PerpStrategy:
    """Perpetual futures trading strategies."""
    
    def __init__(self, trader: CCXTTrader):
        self.trader = trader
        self.logger = logger.bind(strategy="Perp")
    
    async def funding_rate_arbitrage(
        self,
        symbol: str,
        threshold: Decimal = Decimal("0.001")
    ) -> Dict[str, Any]:
        """Trade based on funding rate differential."""
        # Mock funding rate
        funding_rate = Decimal("0.0005")
        
        if funding_rate > threshold:
            # Negative funding = go long
            return await self.trader.place_order(
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                amount=Decimal("1.0"),
                market_type=MarketType.PERP,
                leverage=5
            )
        elif funding_rate < -threshold:
            # Positive funding = go short
            return await self.trader.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                amount=Decimal("1.0"),
                market_type=MarketType.PERP,
                leverage=5
            )
        
        return {"status": "no_action", "reason": "funding_within_threshold"}
    
    async def delta_neutral_hedge(
        self,
        spot_symbol: str,
        perp_symbol: str,
        amount: Decimal
    ) -> Dict[str, Any]:
        """Create delta-neutral position."""
        # Buy spot
        spot_order = await self.trader.place_order(
            symbol=spot_symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            amount=amount,
            market_type=MarketType.SPOT
        )
        
        # Short perp
        perp_order = await self.trader.place_order(
            symbol=perp_symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            amount=amount,
            market_type=MarketType.PERP,
            leverage=1
        )
        
        return {
            "status": "hedged",
            "spot_order": spot_order,
            "perp_order": perp_order
        }


# Singleton instances
binance_trader = CCXTTrader(exchange_id="binance")
bybit_trader = CCXTTrader(exchange_id="bybit")
multi_exchange = MultiExchangeTrader()
perp_strategy = PerpStrategy(binance_trader)
