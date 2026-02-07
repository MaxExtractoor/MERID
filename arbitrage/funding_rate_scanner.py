"""
Funding Rate Capture Scanner.

Detects opportunities to capture funding rate payments on perpetual futures.
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
from utils.deps import get_ccxt_async
from utils.logger import get_logger

logger = get_logger("arbitrage.funding_rate")


@dataclass
class FundingRateData:
    """Funding rate data for a perpetual contract."""
    exchange: str
    symbol: str
    current_rate: float  # Current funding rate (per 8h)
    predicted_rate: float  # Predicted next funding rate
    next_funding_time: float  # Unix timestamp
    mark_price: float
    index_price: float
    open_interest: float
    timestamp: float
    
    @property
    def annualized_rate(self) -> float:
        """Annualized funding rate."""
        return self.current_rate * 3 * 365 * 100  # 3 periods/day, as percentage
    
    @property
    def time_to_funding_seconds(self) -> float:
        """Seconds until next funding."""
        return max(0, self.next_funding_time - time.time())
    
    @property
    def time_to_funding_minutes(self) -> float:
        """Minutes until next funding."""
        return self.time_to_funding_seconds / 60


class FundingRateScanner(ArbitrageScanner):
    """
    Scanner for funding rate capture opportunities.
    
    Strategies:
    1. Long funding: Go long when funding is very negative (longs receive)
    2. Short funding: Go short when funding is very positive (shorts receive)
    3. Cross-exchange funding: Hedge on exchange with opposite funding
    
    Key considerations:
    - Must hold position through funding timestamp
    - Entry/exit slippage can eat into profits
    - Funding rates can change before settlement
    """
    
    def __init__(self, config: Optional[ScannerConfig] = None):
        if config is None:
            config = ScannerConfig(
                scanner_id="funding_rate_scanner",
                scanner_type=ArbitrageType.FUNDING_RATE,
                enabled_venues=["binance", "bybit", "okx", "dydx"],
                enabled_symbols=["BTC/USDT", "ETH/USDT", "SOL/USDT", "ARB/USDT"],
                min_profit_usd=5.0,
                min_profit_margin_pct=0.05,
                scan_interval_seconds=60.0,  # Check every minute
            )
        super().__init__(config)
        
        # Fee rates
        self._fees: Dict[str, float] = {
            "binance": 0.0004,   # 0.04% taker
            "bybit": 0.00055,   # 0.055% taker
            "okx": 0.0005,      # 0.05% taker
            "dydx": 0.0005,     # 0.05% taker
        }
        
        # Minimum funding rate thresholds (per 8h)
        self._min_funding_rate: float = 0.0005  # 0.05% minimum
        self._high_funding_rate: float = 0.001   # 0.1% considered high
        
        # Time window for funding capture (minutes before funding)
        self._entry_window_minutes: float = 30.0
        self._min_time_to_funding_minutes: float = 5.0
    
    async def _initialize(self) -> None:
        """Initialize scanner."""
        logger.info("Initializing Funding Rate scanner...")
        logger.info(f"Venues: {self.config.enabled_venues}")
        logger.info(f"Symbols: {self.config.enabled_symbols}")
        logger.info(f"Min funding rate: {self._min_funding_rate * 100:.3f}%")
    
    async def _cleanup(self) -> None:
        """Cleanup scanner."""
        logger.info("Funding Rate scanner cleaned up")
    
    async def _scan(self) -> List[ArbitrageOpportunity]:
        """Scan for funding rate opportunities."""
        opportunities = []
        
        # Fetch all funding rates
        all_rates: Dict[str, List[FundingRateData]] = {}
        
        for symbol in self.config.enabled_symbols:
            rates = []
            for exchange in self.config.enabled_venues:
                rate = await self._fetch_funding_rate(exchange, symbol)
                if rate:
                    rates.append(rate)
            all_rates[symbol] = rates
        
        # Find single-exchange opportunities
        for symbol, rates in all_rates.items():
            for rate in rates:
                opp = self._evaluate_single_exchange(rate)
                if opp:
                    opportunities.append(opp)
        
        # Find cross-exchange opportunities
        for symbol, rates in all_rates.items():
            if len(rates) >= 2:
                cross_opps = self._evaluate_cross_exchange(rates)
                opportunities.extend(cross_opps)
        
        return opportunities
    
    async def _fetch_funding_rate(self, exchange: str, symbol: str) -> Optional[FundingRateData]:
        """Fetch real funding rate from exchange via CCXT."""
        ccxt_async = get_ccxt_async()
        if not ccxt_async:
            logger.warning("CCXT not available; skipping funding rate fetch")
            return None

        try:
            exchange_class = getattr(ccxt_async, exchange, None)
            if not exchange_class:
                logger.debug(f"Exchange {exchange} not supported")
                return None
            
            ex = exchange_class({'enableRateLimit': True})
            
            try:
                # Format symbol for perp market
                perp_symbol = symbol.replace("/", "") + ":USDT"
                
                # Fetch funding rate
                funding_info = await ex.fetch_funding_rate(perp_symbol)
                
                funding_rate = funding_info.get('fundingRate', 0.0) or 0.0
                next_funding_ts = funding_info.get('fundingTimestamp', 0) or 0
                if next_funding_ts > 1e12:  # milliseconds
                    next_funding_ts = next_funding_ts / 1000
                
                # Fetch ticker for prices
                ticker = await ex.fetch_ticker(perp_symbol)
                mark_price = ticker.get('last', 0) or ticker.get('close', 0)
                index_price = ticker.get('index', mark_price) or mark_price
                
                # Try to get open interest
                open_interest = 0.0
                try:
                    oi_data = await ex.fetch_open_interest(perp_symbol)
                    open_interest = oi_data.get('openInterestValue', 0) or 0
                except Exception:
                    open_interest = ticker.get('quoteVolume', 0) or 0
                
                # Predicted rate is typically similar to current
                predicted_rate = funding_info.get('fundingRatePredicted', funding_rate) or funding_rate
                
                return FundingRateData(
                    exchange=exchange,
                    symbol=symbol,
                    current_rate=funding_rate,
                    predicted_rate=predicted_rate,
                    next_funding_time=next_funding_ts if next_funding_ts > 0 else time.time() + 28800,
                    mark_price=mark_price,
                    index_price=index_price,
                    open_interest=open_interest,
                    timestamp=time.time(),
                )
            finally:
                await ex.close()
                
        except Exception as e:
            logger.debug(f"Funding rate fetch error for {exchange}/{symbol}: {e}")
            return None
    
    def _evaluate_single_exchange(self, rate: FundingRateData) -> Optional[ArbitrageOpportunity]:
        """Evaluate single-exchange funding capture opportunity."""
        
        # Check if funding rate is significant
        if abs(rate.current_rate) < self._min_funding_rate:
            return None
        
        # Check timing window
        time_to_funding = rate.time_to_funding_minutes
        if time_to_funding > self._entry_window_minutes:
            return None
        if time_to_funding < self._min_time_to_funding_minutes:
            return None
        
        # Determine direction
        if rate.current_rate > 0:
            # Positive funding: shorts receive
            side = "sell"
            direction = "short_funding"
        else:
            # Negative funding: longs receive
            side = "buy"
            direction = "long_funding"
        
        # Calculate position size
        qty = self.config.max_position_usd / rate.mark_price
        
        # Calculate expected funding payment
        funding_payment = abs(rate.current_rate) * rate.mark_price * qty
        
        # Calculate costs (entry + exit)
        fee_rate = self._fees.get(rate.exchange, 0.0005)
        entry_exit_fees = rate.mark_price * qty * fee_rate * 2
        
        # Estimate slippage (entry + exit)
        slippage = rate.mark_price * qty * 0.0002 * 2  # 0.02% each way
        
        total_cost = entry_exit_fees + slippage
        net_profit = funding_payment - total_cost
        
        # Check thresholds
        if net_profit < self.config.min_profit_usd:
            return None
        
        margin_pct = (net_profit / (rate.mark_price * qty)) * 100
        
        # Create opportunity
        opp = ArbitrageOpportunity(
            arb_type=ArbitrageType.FUNDING_RATE,
            status=ArbitrageStatus.DETECTED,
            source_scanner=self.config.scanner_id,
            confidence=min(0.85, abs(rate.current_rate) / 0.002),
            notes=f"{direction} | Rate: {rate.current_rate*100:.4f}% | Time: {time_to_funding:.1f}min",
        )
        
        # Add leg
        opp.legs.append(ArbitrageLeg(
            sequence=1,
            venue=rate.exchange,
            venue_type=VenueType.PERP,
            symbol=rate.symbol,
            side=side,
            quantity=qty,
            price=rate.mark_price,
            estimated_fee=entry_exit_fees,
            estimated_slippage=slippage,
        ))
        
        # Set metrics
        opp.gross_profit_usd = funding_payment
        opp.net_profit_usd = net_profit
        opp.profit_margin_pct = margin_pct
        opp.cost_model = CostModel(
            total_fees=entry_exit_fees,
            total_slippage=slippage,
        )
        
        # Risk metrics
        opp.execution_risk = 0.3  # Moderate risk
        opp.liquidity_score = min(1.0, rate.open_interest / 100000000)
        opp.time_sensitivity = time_to_funding * 60  # Seconds
        opp.expires_at = rate.next_funding_time
        
        return opp
    
    def _evaluate_cross_exchange(self, rates: List[FundingRateData]) -> List[ArbitrageOpportunity]:
        """Evaluate cross-exchange funding arbitrage opportunities."""
        opportunities = []
        
        # Find pairs with opposite or different funding rates
        for i, rate1 in enumerate(rates):
            for rate2 in rates[i+1:]:
                # Check if rates have meaningful difference
                rate_diff = rate1.current_rate - rate2.current_rate
                
                if abs(rate_diff) < self._min_funding_rate:
                    continue
                
                # Determine direction: long on lower rate, short on higher rate
                if rate1.current_rate > rate2.current_rate:
                    short_rate = rate1
                    long_rate = rate2
                else:
                    short_rate = rate2
                    long_rate = rate1
                
                # Calculate position size (use smaller of the two)
                qty = self.config.max_position_usd / short_rate.mark_price
                
                # Calculate net funding received
                # Short position receives positive funding
                # Long position pays positive funding (or receives if negative)
                short_funding = short_rate.current_rate * short_rate.mark_price * qty
                long_funding = -long_rate.current_rate * long_rate.mark_price * qty
                total_funding = short_funding + long_funding
                
                if total_funding <= 0:
                    continue
                
                # Calculate costs
                fee1 = short_rate.mark_price * qty * self._fees.get(short_rate.exchange, 0.0005) * 2
                fee2 = long_rate.mark_price * qty * self._fees.get(long_rate.exchange, 0.0005) * 2
                total_fees = fee1 + fee2
                
                slippage = (short_rate.mark_price + long_rate.mark_price) * qty * 0.0002
                
                net_profit = total_funding - total_fees - slippage
                
                if net_profit < self.config.min_profit_usd:
                    continue
                
                margin_pct = (net_profit / (short_rate.mark_price * qty * 2)) * 100
                
                # Create opportunity
                opp = ArbitrageOpportunity(
                    arb_type=ArbitrageType.FUNDING_RATE,
                    status=ArbitrageStatus.DETECTED,
                    source_scanner=self.config.scanner_id,
                    confidence=min(0.9, abs(rate_diff) / 0.002),
                    notes=f"cross_exchange | {short_rate.exchange} short ({short_rate.current_rate*100:.4f}%) vs {long_rate.exchange} long ({long_rate.current_rate*100:.4f}%)",
                )
                
                # Add short leg
                opp.legs.append(ArbitrageLeg(
                    sequence=1,
                    venue=short_rate.exchange,
                    venue_type=VenueType.PERP,
                    symbol=short_rate.symbol,
                    side="sell",
                    quantity=qty,
                    price=short_rate.mark_price,
                    estimated_fee=fee1,
                ))
                
                # Add long leg
                opp.legs.append(ArbitrageLeg(
                    sequence=2,
                    venue=long_rate.exchange,
                    venue_type=VenueType.PERP,
                    symbol=long_rate.symbol,
                    side="buy",
                    quantity=qty,
                    price=long_rate.mark_price,
                    estimated_fee=fee2,
                ))
                
                # Set metrics
                opp.gross_profit_usd = total_funding
                opp.net_profit_usd = net_profit
                opp.profit_margin_pct = margin_pct
                opp.cost_model = CostModel(
                    total_fees=total_fees,
                    total_slippage=slippage,
                )
                
                # Risk metrics - cross-exchange is lower risk (hedged)
                opp.execution_risk = 0.15
                opp.liquidity_score = min(
                    1.0,
                    min(short_rate.open_interest, long_rate.open_interest) / 100000000
                )
                opp.time_sensitivity = min(
                    short_rate.time_to_funding_seconds,
                    long_rate.time_to_funding_seconds
                )
                
                opportunities.append(opp)
        
        return opportunities


# Singleton
_funding_rate_scanner: Optional[FundingRateScanner] = None


def get_funding_rate_scanner() -> FundingRateScanner:
    """Get or create the Funding Rate scanner singleton."""
    global _funding_rate_scanner
    if _funding_rate_scanner is None:
        _funding_rate_scanner = FundingRateScanner()
    return _funding_rate_scanner
