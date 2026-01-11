"""
Perpetual vs Spot Basis Scanner.

Detects basis (price difference) between perpetual futures and spot markets.
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

logger = get_logger("arbitrage.perp_spot")


@dataclass
class PerpPrice:
    """Perpetual futures price data."""
    exchange: str
    symbol: str
    mark_price: float
    index_price: float
    funding_rate: float  # Current funding rate (8h)
    next_funding_time: float
    open_interest: float
    timestamp: float
    
    @property
    def basis_pct(self) -> float:
        """Basis as percentage (mark vs index)."""
        if self.index_price <= 0:
            return 0.0
        return ((self.mark_price - self.index_price) / self.index_price) * 100
    
    @property
    def annualized_basis_pct(self) -> float:
        """Annualized basis rate."""
        return self.basis_pct * 365 * 3  # 3 funding periods per day


@dataclass
class SpotPrice:
    """Spot market price data."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    timestamp: float
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class PerpSpotScanner(ArbitrageScanner):
    """
    Scanner for perpetual vs spot basis arbitrage.
    
    Strategies:
    1. Cash-and-carry: Buy spot, short perp when basis is positive
    2. Reverse cash-and-carry: Sell spot, long perp when basis is negative
    
    This captures the basis convergence + funding payments.
    """
    
    def __init__(self, config: Optional[ScannerConfig] = None):
        if config is None:
            config = ScannerConfig(
                scanner_id="perp_spot_scanner",
                scanner_type=ArbitrageType.PERP_SPOT,
                enabled_venues=["binance", "bybit", "okx"],
                enabled_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT"],
                min_profit_usd=10.0,
                min_profit_margin_pct=0.1,
                scan_interval_seconds=10.0,
            )
        super().__init__(config)
        
        # Fee rates (maker fees for perps)
        self._perp_fees: Dict[str, float] = {
            "binance": 0.0002,   # 0.02% maker
            "bybit": 0.0001,    # 0.01% maker
            "okx": 0.0002,      # 0.02% maker
        }
        
        self._spot_fees: Dict[str, float] = {
            "binance": 0.001,   # 0.1%
            "bybit": 0.001,
            "okx": 0.001,
        }
        
        # Minimum basis thresholds (annualized %)
        self._min_basis_annualized: float = 5.0  # 5% annualized minimum
        
        # Position holding period assumptions
        self._assumed_holding_days: int = 7
    
    async def _initialize(self) -> None:
        """Initialize scanner."""
        logger.info("Initializing Perp-Spot basis scanner...")
        logger.info(f"Venues: {self.config.enabled_venues}")
        logger.info(f"Symbols: {self.config.enabled_symbols}")
        logger.info(f"Min annualized basis: {self._min_basis_annualized}%")
    
    async def _cleanup(self) -> None:
        """Cleanup scanner."""
        logger.info("Perp-Spot scanner cleaned up")
    
    async def _scan(self) -> List[ArbitrageOpportunity]:
        """Scan for perp-spot basis opportunities."""
        opportunities = []
        
        for symbol in self.config.enabled_symbols:
            for exchange in self.config.enabled_venues:
                # Fetch perp and spot prices
                perp_price = await self._fetch_perp_price(exchange, symbol)
                spot_price = await self._fetch_spot_price(exchange, symbol)
                
                if not perp_price or not spot_price:
                    continue
                
                # Evaluate opportunity
                opp = self._evaluate_basis_trade(perp_price, spot_price)
                if opp:
                    opportunities.append(opp)
        
        return opportunities
    
    async def _fetch_perp_price(self, exchange: str, symbol: str) -> Optional[PerpPrice]:
        """Fetch perpetual futures price from CCXT."""
        try:
            import ccxt.async_support as ccxt_async
            
            # Get exchange instance
            exchange_class = getattr(ccxt_async, exchange, None)
            if not exchange_class:
                logger.debug(f"Exchange {exchange} not supported")
                return None
            
            ex = exchange_class({'enableRateLimit': True})
            
            try:
                # Fetch ticker for perp market
                perp_symbol = symbol.replace("/", "") + ":USDT"  # e.g., BTCUSDT:USDT
                
                # Try to fetch funding rate
                funding_rate = 0.0
                next_funding_time = time.time() + 28800  # Default 8h
                open_interest = 0.0
                
                try:
                    funding_info = await ex.fetch_funding_rate(perp_symbol)
                    funding_rate = funding_info.get('fundingRate', 0.0) or 0.0
                    next_funding_time = funding_info.get('fundingTimestamp', time.time() + 28800) / 1000
                except Exception:
                    pass
                
                # Fetch ticker
                ticker = await ex.fetch_ticker(perp_symbol)
                
                mark_price = ticker.get('last', 0) or ticker.get('close', 0)
                index_price = ticker.get('index', mark_price) or mark_price
                
                # Try to get open interest
                try:
                    oi_data = await ex.fetch_open_interest(perp_symbol)
                    open_interest = oi_data.get('openInterestValue', 0) or 0
                except Exception:
                    open_interest = ticker.get('quoteVolume', 0) or 0
                
                return PerpPrice(
                    exchange=exchange,
                    symbol=symbol,
                    mark_price=mark_price,
                    index_price=index_price,
                    funding_rate=funding_rate,
                    next_funding_time=next_funding_time,
                    open_interest=open_interest,
                    timestamp=time.time(),
                )
            finally:
                await ex.close()
                
        except Exception as e:
            logger.debug(f"Perp price fetch error for {exchange}/{symbol}: {e}")
            return None
    
    async def _fetch_spot_price(self, exchange: str, symbol: str) -> Optional[SpotPrice]:
        """Fetch spot price from CCXT with real bid/ask."""
        try:
            import ccxt.async_support as ccxt_async
            
            # Get exchange instance
            exchange_class = getattr(ccxt_async, exchange, None)
            if not exchange_class:
                logger.debug(f"Exchange {exchange} not supported")
                return None
            
            ex = exchange_class({'enableRateLimit': True})
            
            try:
                # Fetch order book for real bid/ask
                orderbook = await ex.fetch_order_book(symbol, limit=5)
                
                bid = orderbook['bids'][0][0] if orderbook['bids'] else 0
                ask = orderbook['asks'][0][0] if orderbook['asks'] else 0
                
                if bid <= 0 or ask <= 0:
                    # Fallback to ticker
                    ticker = await ex.fetch_ticker(symbol)
                    bid = ticker.get('bid', 0) or ticker.get('last', 0)
                    ask = ticker.get('ask', 0) or ticker.get('last', 0)
                
                return SpotPrice(
                    exchange=exchange,
                    symbol=symbol,
                    bid=bid,
                    ask=ask,
                    timestamp=time.time(),
                )
            finally:
                await ex.close()
                
        except Exception as e:
            logger.debug(f"Spot price fetch error for {exchange}/{symbol}: {e}")
            return None
    
    def _evaluate_basis_trade(
        self,
        perp: PerpPrice,
        spot: SpotPrice
    ) -> Optional[ArbitrageOpportunity]:
        """Evaluate a basis trade opportunity."""
        
        # Calculate basis
        basis_pct = perp.basis_pct
        annualized_basis = perp.annualized_basis_pct
        
        # Check minimum threshold
        if abs(annualized_basis) < self._min_basis_annualized:
            return None
        
        # Determine direction
        if basis_pct > 0:
            # Positive basis: Cash-and-carry
            # Buy spot, short perp
            direction = "cash_and_carry"
            spot_side = "buy"
            perp_side = "sell"
            spot_price = spot.ask
            perp_price = perp.mark_price
        else:
            # Negative basis: Reverse cash-and-carry
            # Sell spot, long perp
            direction = "reverse_cash_and_carry"
            spot_side = "sell"
            perp_side = "buy"
            spot_price = spot.bid
            perp_price = perp.mark_price
        
        # Calculate position size
        qty = self.config.max_position_usd / spot_price
        
        # Calculate expected profit over holding period
        # Profit = Basis convergence + Funding payments
        
        # Basis profit (assuming full convergence)
        basis_profit = abs(basis_pct / 100) * spot_price * qty
        
        # Funding profit (if we're on the receiving side)
        funding_periods = self._assumed_holding_days * 3  # 3 per day
        funding_per_period = abs(perp.funding_rate) * perp_price * qty
        
        # If positive funding and we're short, we receive funding
        if perp.funding_rate > 0 and perp_side == "sell":
            funding_profit = funding_per_period * funding_periods
        elif perp.funding_rate < 0 and perp_side == "buy":
            funding_profit = funding_per_period * funding_periods
        else:
            funding_profit = -funding_per_period * funding_periods  # We pay
        
        gross_profit = basis_profit + funding_profit
        
        # Calculate costs
        spot_fee = spot_price * qty * self._spot_fees.get(spot.exchange, 0.001)
        perp_fee = perp_price * qty * self._perp_fees.get(perp.exchange, 0.0002)
        
        # Entry + exit fees (both sides)
        total_fees = (spot_fee + perp_fee) * 2
        
        net_profit = gross_profit - total_fees
        
        # Check thresholds
        total_value = spot_price * qty
        margin_pct = (net_profit / total_value) * 100 if total_value > 0 else 0
        
        if net_profit < self.config.min_profit_usd:
            return None
        
        # Create opportunity
        opp = ArbitrageOpportunity(
            arb_type=ArbitrageType.PERP_SPOT,
            status=ArbitrageStatus.DETECTED,
            source_scanner=self.config.scanner_id,
            confidence=min(0.8, abs(annualized_basis) / 20),  # Higher basis = higher confidence
            notes=f"{direction} | Basis: {basis_pct:.3f}% | Funding: {perp.funding_rate*100:.4f}%",
        )
        
        # Add spot leg
        opp.legs.append(ArbitrageLeg(
            sequence=1,
            venue=spot.exchange,
            venue_type=VenueType.CEX,
            symbol=spot.symbol,
            side=spot_side,
            quantity=qty,
            price=spot_price,
            estimated_fee=spot_fee,
        ))
        
        # Add perp leg
        opp.legs.append(ArbitrageLeg(
            sequence=2,
            venue=perp.exchange,
            venue_type=VenueType.PERP,
            symbol=perp.symbol,
            side=perp_side,
            quantity=qty,
            price=perp_price,
            estimated_fee=perp_fee,
        ))
        
        # Set metrics
        opp.gross_profit_usd = gross_profit
        opp.net_profit_usd = net_profit
        opp.profit_margin_pct = margin_pct
        opp.cost_model = CostModel(
            total_fees=total_fees,
        )
        
        # Risk metrics
        opp.execution_risk = 0.2  # Lower risk for basis trades
        opp.liquidity_score = min(1.0, perp.open_interest / 200000000)
        opp.time_sensitivity = self._assumed_holding_days * 86400  # Days in seconds
        
        return opp


# Singleton
_perp_spot_scanner: Optional[PerpSpotScanner] = None


def get_perp_spot_scanner() -> PerpSpotScanner:
    """Get or create the Perp-Spot scanner singleton."""
    global _perp_spot_scanner
    if _perp_spot_scanner is None:
        _perp_spot_scanner = PerpSpotScanner()
    return _perp_spot_scanner
