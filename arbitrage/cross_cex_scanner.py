"""
Cross-CEX Arbitrage Scanner.

Detects price differences between centralized exchanges.
READ-ONLY - does not execute trades.

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from arbitrage.scanner_base import ArbitrageScanner, ScannerConfig
from schemas.arbitrage import (
    ArbitrageOpportunity, ArbitrageType, ArbitrageStatus,
    ArbitrageLeg, VenueType, CostModel
)
from utils.logger import get_logger

logger = get_logger("arbitrage.cross_cex")


@dataclass
class ExchangePrice:
    """Price data from an exchange."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    timestamp: float
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2
    
    @property
    def spread_pct(self) -> float:
        return ((self.ask - self.bid) / self.mid) * 100 if self.mid > 0 else 0


class CrossCEXScanner(ArbitrageScanner):
    """
    Scanner for cross-exchange arbitrage opportunities.
    
    Monitors price differences between CEXs and identifies
    profitable buy-low-sell-high opportunities.
    """
    
    def __init__(self, config: Optional[ScannerConfig] = None):
        if config is None:
            config = ScannerConfig(
                scanner_id="cross_cex_scanner",
                scanner_type=ArbitrageType.CROSS_CEX,
                enabled_venues=["binance", "coinbase", "kraken", "okx", "bybit"],
                enabled_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
                min_profit_usd=5.0,
                min_profit_margin_pct=0.05,
            )
        super().__init__(config)
        
        # Exchange connections (simulated for now)
        self._exchanges: Dict[str, Any] = {}
        self._price_cache: Dict[str, Dict[str, ExchangePrice]] = {}
        
        # Fee structure per exchange (maker/taker)
        self._fee_rates: Dict[str, float] = {
            "binance": 0.001,    # 0.1%
            "coinbase": 0.006,   # 0.6%
            "kraken": 0.0026,    # 0.26%
            "okx": 0.001,        # 0.1%
            "bybit": 0.001,      # 0.1%
        }
    
    async def _initialize(self) -> None:
        """Initialize exchange connections."""
        logger.info("Initializing Cross-CEX scanner...")
        
        # In production, initialize CCXT exchange instances here
        for venue in self.config.enabled_venues:
            self._exchanges[venue] = {"connected": True}
            self._price_cache[venue] = {}
        
        logger.info(f"Connected to {len(self._exchanges)} exchanges")
    
    async def _cleanup(self) -> None:
        """Cleanup exchange connections."""
        self._exchanges.clear()
        self._price_cache.clear()
        logger.info("Cross-CEX scanner cleaned up")
    
    async def _scan(self) -> List[ArbitrageOpportunity]:
        """Scan for cross-exchange arbitrage opportunities."""
        opportunities = []
        
        for symbol in self.config.enabled_symbols:
            # Fetch prices from all exchanges
            prices = await self._fetch_prices(symbol)
            
            if len(prices) < 2:
                continue
            
            # Find arbitrage opportunities
            opps = self._find_opportunities(symbol, prices)
            opportunities.extend(opps)
        
        return opportunities
    
    async def _fetch_prices(self, symbol: str) -> List[ExchangePrice]:
        """Fetch prices from all exchanges for a symbol."""
        prices = []
        
        for exchange in self.config.enabled_venues:
            try:
                price = await self._fetch_exchange_price(exchange, symbol)
                if price:
                    prices.append(price)
                    self._price_cache[exchange][symbol] = price
            except Exception as e:
                logger.debug(f"Failed to fetch {symbol} from {exchange}: {e}")
        
        return prices
    
    async def _fetch_exchange_price(self, exchange: str, symbol: str) -> Optional[ExchangePrice]:
        """Fetch price from a single exchange."""
        # In production, use CCXT to fetch real prices
        # For now, simulate with realistic spreads
        
        try:
            from data.live_price_feed import get_live_price_feed
            
            feed = get_live_price_feed()
            price_data = feed.get_current_price(symbol)
            
            if not price_data:
                return None
            
            # Fetch real orderbook from CCXT for accurate bid/ask
            import ccxt.async_support as ccxt_async
            
            exchange_class = getattr(ccxt_async, exchange, None)
            if not exchange_class:
                # Fallback to price feed data
                return ExchangePrice(
                    exchange=exchange,
                    symbol=symbol,
                    bid=price_data.bid if hasattr(price_data, 'bid') else price_data.price * 0.9999,
                    ask=price_data.ask if hasattr(price_data, 'ask') else price_data.price * 1.0001,
                    bid_size=0,
                    ask_size=0,
                    timestamp=time.time(),
                )
            
            ex = exchange_class({'enableRateLimit': True})
            try:
                orderbook = await ex.fetch_order_book(symbol, limit=5)
                
                bid = orderbook['bids'][0][0] if orderbook['bids'] else price_data.price * 0.9999
                ask = orderbook['asks'][0][0] if orderbook['asks'] else price_data.price * 1.0001
                bid_size = orderbook['bids'][0][1] if orderbook['bids'] else 0
                ask_size = orderbook['asks'][0][1] if orderbook['asks'] else 0
                
                return ExchangePrice(
                    exchange=exchange,
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    timestamp=time.time(),
                )
            finally:
                await ex.close()
                
        except Exception as e:
            logger.debug(f"Price fetch error for {exchange}/{symbol}: {e}")
            return None
    
    def _find_opportunities(self, symbol: str, prices: List[ExchangePrice]) -> List[ArbitrageOpportunity]:
        """Find arbitrage opportunities from price list."""
        opportunities = []
        
        # Compare all pairs of exchanges
        for i, buy_price in enumerate(prices):
            for j, sell_price in enumerate(prices):
                if i == j:
                    continue
                
                # Buy at ask, sell at bid
                buy_at = buy_price.ask
                sell_at = sell_price.bid
                
                # Skip if no profit potential
                if sell_at <= buy_at:
                    continue
                
                # Calculate profit
                gross_profit_per_unit = sell_at - buy_at
                
                # Estimate quantity based on available liquidity
                max_qty = min(buy_price.ask_size, sell_price.bid_size)
                qty = min(max_qty, self.config.max_position_usd / buy_at)
                
                if qty <= 0:
                    continue
                
                gross_profit = gross_profit_per_unit * qty
                
                # Calculate fees
                buy_fee = buy_at * qty * self._fee_rates.get(buy_price.exchange, 0.001)
                sell_fee = sell_at * qty * self._fee_rates.get(sell_price.exchange, 0.001)
                total_fees = buy_fee + sell_fee
                
                # Net profit
                net_profit = gross_profit - total_fees
                
                # Profit margin
                total_value = buy_at * qty
                margin_pct = (net_profit / total_value) * 100 if total_value > 0 else 0
                
                # Check thresholds
                if net_profit < self.config.min_profit_usd:
                    continue
                if margin_pct < self.config.min_profit_margin_pct:
                    continue
                
                # Create opportunity
                opp = ArbitrageOpportunity(
                    arb_type=ArbitrageType.CROSS_CEX,
                    status=ArbitrageStatus.DETECTED,
                    source_scanner=self.config.scanner_id,
                    confidence=min(0.9, margin_pct / 1.0),  # Higher margin = higher confidence
                )
                
                # Add buy leg
                opp.legs.append(ArbitrageLeg(
                    sequence=1,
                    venue=buy_price.exchange,
                    venue_type=VenueType.CEX,
                    symbol=symbol,
                    side="buy",
                    quantity=qty,
                    price=buy_at,
                    estimated_fee=buy_fee,
                    estimated_slippage=buy_at * qty * 0.0005,  # 0.05% slippage estimate
                ))
                
                # Add sell leg
                opp.legs.append(ArbitrageLeg(
                    sequence=2,
                    venue=sell_price.exchange,
                    venue_type=VenueType.CEX,
                    symbol=symbol,
                    side="sell",
                    quantity=qty,
                    price=sell_at,
                    estimated_fee=sell_fee,
                    estimated_slippage=sell_at * qty * 0.0005,
                ))
                
                # Set profit metrics
                opp.gross_profit_usd = gross_profit
                opp.net_profit_usd = net_profit
                opp.profit_margin_pct = margin_pct
                opp.cost_model = CostModel(
                    total_fees=total_fees,
                    total_slippage=buy_at * qty * 0.001,
                )
                
                # Set timing
                opp.expires_at = time.time() + 30  # 30 second validity
                opp.time_sensitivity = 30
                
                # Risk metrics
                opp.execution_risk = 0.3  # Moderate risk for CEX arb
                opp.liquidity_score = min(1.0, (buy_price.ask_size + sell_price.bid_size) / 20)
                
                opportunities.append(opp)
        
        return opportunities


# Singleton instance
_cross_cex_scanner: Optional[CrossCEXScanner] = None


def get_cross_cex_scanner() -> CrossCEXScanner:
    """Get or create the Cross-CEX scanner singleton."""
    global _cross_cex_scanner
    if _cross_cex_scanner is None:
        _cross_cex_scanner = CrossCEXScanner()
    return _cross_cex_scanner
