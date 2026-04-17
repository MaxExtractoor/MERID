"""MERID Universal Router - US-Compliant Multi-Venue Trading.

Unified trading interface across US-compliant venues with geo-blocking.
Routes trades to appropriate venues based on asset class and compliance.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum
import structlog

from core.us_compliance_config import (
    US_COMPLIANT_VENUES,
    BLOCKED_VENUES,
    OPTIONAL_VENUES,
    is_venue_allowed,
    is_venue_blocked,
    is_venue_optional,
    get_venues_for_asset_class
)
from core.venue_adapter import VenueAdapter, OrderSide, OrderType, Order, MarketData
from core.rate_limiter import rate_limiter
from core.venues.kalshi_adapter import kalshi_adapter

# LEGACY: Non-Kalshi venue adapters - safe import with fallback to None
def _safe_import_adapter(module_name: str, attr_name: str):
    """Safely import an adapter, returning None if not available."""
    try:
        module = __import__(module_name, fromlist=[attr_name])
        return getattr(module, attr_name, None)
    except Exception:
        return None

alpaca_adapter = _safe_import_adapter("core.venues.alpaca_adapter", "alpaca_adapter")
ibkr_adapter = _safe_import_adapter("core.venues.ibkr_adapter", "ibkr_adapter")
binanceus_adapter = _safe_import_adapter("core.venues.binanceus_adapter", "binanceus_adapter")
coinbase_advanced_adapter = _safe_import_adapter("core.venues.coinbase_advanced_adapter", "coinbase_advanced_adapter")
kraken_adapter = _safe_import_adapter("core.venues.kraken_adapter", "kraken_adapter")
gemini_adapter = _safe_import_adapter("core.venues.gemini_adapter", "gemini_adapter")
merid_sim_adapter = _safe_import_adapter("core.venues.sim_adapter", "merid_sim_adapter")
bitget_adapter = _safe_import_adapter("core.venues.bitget_adapter", "bitget_adapter")
kucoin_adapter = _safe_import_adapter("core.venues.kucoin_adapter", "kucoin_adapter")
gateio_adapter = _safe_import_adapter("core.venues.gateio_adapter", "gateio_adapter")
mexc_adapter = _safe_import_adapter("core.venues.mexc_adapter", "mexc_adapter")
htx_adapter = _safe_import_adapter("core.venues.htx_adapter", "htx_adapter")
okx_adapter = _safe_import_adapter("core.venues.okx_adapter", "okx_adapter")

logger = structlog.get_logger(__name__)


class AssetClass(str, Enum):
    EQUITIES = "equities"
    ETFS = "etfs"
    OPTIONS = "options"
    FUTURES = "futures"
    FX = "fx"
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_PERP = "crypto_perp"
    PREDICTION = "prediction"


@dataclass
class UniversalTrade:
    """Universal trade request."""
    symbol: str
    side: OrderSide
    order_type: OrderType
    amount: Decimal
    price: Optional[Decimal]
    venue: str
    asset_class: AssetClass
    paper: bool = True


class UniversalRouter:
    """US-compliant universal trading router."""
    
    def __init__(self):
        self.logger = logger.bind(router="UniversalRouter")
        self.rate_limiter = rate_limiter
        # Build adapters dict, filtering out None values for missing adapters
        _all_adapters = {
            # US-Compliant venues
            "alpaca": alpaca_adapter,
            "ibkr": ibkr_adapter,
            "binanceus": binanceus_adapter,
            "coinbase_advanced": coinbase_advanced_adapter,
            "kraken": kraken_adapter,
            "gemini": gemini_adapter,
            "kalshi": kalshi_adapter,
            "merid_sim": merid_sim_adapter,
            # Optional/Data-only venues (US residents: data/sim only)
            "bitget": bitget_adapter,
            "kucoin": kucoin_adapter,
            "gateio": gateio_adapter,
            "mexc": mexc_adapter,
            "htx": htx_adapter,
            "okx": okx_adapter,
        }
        self.adapters: Dict[str, VenueAdapter] = {
            k: v for k, v in _all_adapters.items() if v is not None
        }
        self.venue_health: Dict[str, bool] = {}
        
    def validate_venue(self, venue: str) -> bool:
        """Validate venue is US-compliant."""
        if is_venue_blocked(venue):
            self.logger.error("blocked_venue_attempted", venue=venue)
            raise ValueError(f"Venue '{venue}' is blocked for US compliance")
        
        if not is_venue_allowed(venue):
            self.logger.error("non_compliant_venue", venue=venue)
            raise ValueError(f"Venue '{venue}' is not US-compliant")
        
        return True
    
    def get_adapter(self, venue: str) -> VenueAdapter:
        """Get venue adapter with validation."""
        self.validate_venue(venue)
        
        if venue not in self.adapters:
            raise ValueError(f"No adapter for venue: {venue}")
        
        return self.adapters[venue]
    
    def route_by_asset_class(
        self,
        asset_class: AssetClass,
        paper: bool = True
    ) -> str:
        """Auto-route to appropriate venue by asset class."""
        venues = get_venues_for_asset_class(asset_class.value)
        
        if not venues:
            raise ValueError(f"No US-compliant venues for {asset_class}")
        
        # Prefer paper/simulator
        if paper and "merid_sim" in venues:
            return "merid_sim"
        
        # Return first available
        return list(venues)[0]
    
    async def execute(self, trade: UniversalTrade) -> Dict[str, Any]:
        """Execute trade through appropriate venue with rate limiting."""
        # Validate venue
        self.validate_venue(trade.venue)
        
        # Get adapter
        adapter = self.get_adapter(trade.venue)
        
        # Connect if needed
        if not adapter.is_connected():
            await adapter.connect()
        
        # Wait for rate limit
        can_proceed = await self.rate_limiter.wait(trade.venue)
        if not can_proceed:
            return {
                "status": "rate_limited",
                "venue": trade.venue,
                "reason": "Rate limit quota exhausted for this venue"
            }
        
        self.logger.info(
            "executing_trade",
            venue=trade.venue,
            symbol=trade.symbol,
            side=trade.side.value,
            asset_class=trade.asset_class.value
        )
        
        # Route to simulator if paper mode
        if trade.paper and trade.venue != "merid_sim":
            self.logger.info("routing_to_simulator", original_venue=trade.venue)
            adapter = self.adapters["merid_sim"]
            await self.rate_limiter.wait("merid_sim")  # Also rate limit sim
        
        # Execute with retry on rate limit
        for attempt in range(3):
            try:
                result = await adapter.place_order(
                    symbol=trade.symbol,
                    side=trade.side,
                    order_type=trade.order_type,
                    amount=trade.amount,
                    price=trade.price
                )
                break
            except Exception as e:
                if "rate limit" in str(e).lower() and attempt < 2:
                    self.logger.warning("rate_limit_hit_retrying", venue=trade.venue, attempt=attempt + 1)
                    await self.rate_limiter.wait_with_backoff(trade.venue, attempt + 1)
                else:
                    raise
        
        result["routed_through"] = trade.venue
        result["paper"] = trade.paper
        
        return result
    
    async def execute_auto(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        amount: Decimal,
        asset_class: AssetClass,
        price: Optional[Decimal] = None,
        paper: bool = True
    ) -> Dict[str, Any]:
        """Auto-route and execute trade."""
        venue = self.route_by_asset_class(asset_class, paper)
        
        trade = UniversalTrade(
            symbol=symbol,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            venue=venue,
            asset_class=asset_class,
            paper=paper
        )
        
        return await self.execute(trade)
    
    async def get_market_data(
        self,
        symbol: str,
        venue: str
    ) -> Optional[MarketData]:
        """Get market data from venue with rate limiting."""
        adapter = self.get_adapter(venue)
        
        if not adapter.is_connected():
            await adapter.connect()
        
        # Wait for rate limit
        can_proceed = await self.rate_limiter.wait(venue)
        if not can_proceed:
            self.logger.warning("rate_limit_skip_market_data", venue=venue, symbol=symbol)
            return None
        
        return await adapter.get_market_data(symbol)
    
    async def get_best_price(
        self,
        symbol: str,
        asset_class: AssetClass,
        side: OrderSide
    ) -> Dict[str, Any]:
        """Get best price across venues for asset class."""
        venues = get_venues_for_asset_class(asset_class.value)
        prices = []
        
        for venue in venues:
            try:
                data = await self.get_market_data(symbol, venue)
                if data:
                    price = data.ask if side == OrderSide.BUY else data.bid
                    prices.append({"venue": venue, "price": price})
            except Exception as e:
                self.logger.error("price_fetch_error", venue=venue, error=str(e))
        
        if not prices:
            return {"error": "No prices available"}
        
        # Best price for buy = lowest ask, for sell = highest bid
        if side == OrderSide.BUY:
            best = min(prices, key=lambda x: x["price"])
        else:
            best = max(prices, key=lambda x: x["price"])
        
        return {
            "symbol": symbol,
            "side": side.value,
            "best_venue": best["venue"],
            "best_price": str(best["price"]),
            "all_prices": prices
        }
    
    async def get_all_balances(self) -> Dict[str, Dict[str, Decimal]]:
        """Get balances from all venues with rate limiting."""
        balances = {}
        
        for venue, adapter in self.adapters.items():
            try:
                # Wait for rate limit
                can_proceed = await self.rate_limiter.wait(venue)
                if not can_proceed:
                    self.logger.warning("rate_limit_skip_balance", venue=venue)
                    continue
                
                if not adapter.is_connected():
                    await adapter.connect()
                balances[venue] = await adapter.get_balance()
            except Exception as e:
                self.logger.error("balance_fetch_error", venue=venue, error=str(e))
        
        return balances
    
    async def get_all_positions(self) -> Dict[str, List[Any]]:
        """Get positions from all venues with rate limiting."""
        positions = {}
        
        for venue, adapter in self.adapters.items():
            try:
                # Wait for rate limit
                can_proceed = await self.rate_limiter.wait(venue)
                if not can_proceed:
                    self.logger.warning("rate_limit_skip_positions", venue=venue)
                    continue
                
                if not adapter.is_connected():
                    await adapter.connect()
                positions[venue] = await adapter.get_positions()
            except Exception as e:
                self.logger.error("position_fetch_error", venue=venue, error=str(e))
        
        return positions
    
    def list_allowed_venues(self) -> List[str]:
        """List all US-compliant venues."""
        return sorted(list(US_COMPLIANT_VENUES))
    
    def list_blocked_venues(self) -> List[str]:
        """List blocked venues."""
        return sorted(list(BLOCKED_VENUES))


# Singleton
universal_router = UniversalRouter()
