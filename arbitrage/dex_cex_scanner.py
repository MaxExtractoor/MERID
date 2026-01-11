"""
DEX vs CEX Arbitrage Scanner.

Detects price differences between decentralized and centralized exchanges.
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

logger = get_logger("arbitrage.dex_cex")


@dataclass
class DEXPrice:
    """Price data from a DEX."""
    dex: str
    chain: str
    symbol: str
    price: float
    liquidity_usd: float
    pool_address: str
    timestamp: float


@dataclass
class CEXPrice:
    """Price data from a CEX."""
    exchange: str
    symbol: str
    bid: float
    ask: float
    timestamp: float


class DEXCEXScanner(ArbitrageScanner):
    """
    Scanner for DEX vs CEX arbitrage opportunities.
    
    Monitors price differences between DEXs (Uniswap, etc.)
    and CEXs (Binance, etc.) for arbitrage opportunities.
    
    Note: DEX execution requires on-chain transactions with gas costs.
    """
    
    def __init__(self, config: Optional[ScannerConfig] = None):
        if config is None:
            config = ScannerConfig(
                scanner_id="dex_cex_scanner",
                scanner_type=ArbitrageType.DEX_CEX,
                enabled_venues=["uniswap_v3", "sushiswap", "binance", "coinbase"],
                enabled_symbols=["ETH/USDT", "WBTC/USDT"],
                min_profit_usd=20.0,  # Higher threshold due to gas
                min_profit_margin_pct=0.2,
            )
        super().__init__(config)
        
        # DEX configurations
        self._dex_configs: Dict[str, Dict[str, Any]] = {
            "uniswap_v3": {"chain": "ethereum", "fee_tier": 0.003},
            "sushiswap": {"chain": "ethereum", "fee_tier": 0.003},
            "pancakeswap": {"chain": "bsc", "fee_tier": 0.0025},
        }
        
        # CEX fee rates
        self._cex_fees: Dict[str, float] = {
            "binance": 0.001,
            "coinbase": 0.006,
            "kraken": 0.0026,
        }
        
        # Gas price estimates (in USD)
        self._gas_estimates: Dict[str, float] = {
            "ethereum": 15.0,  # Typical swap gas cost
            "bsc": 0.50,
            "arbitrum": 1.0,
            "polygon": 0.10,
        }
    
    async def _initialize(self) -> None:
        """Initialize DEX and CEX connections."""
        logger.info("Initializing DEX-CEX scanner...")
        logger.info(f"DEXs: {list(self._dex_configs.keys())}")
        logger.info(f"CEXs: {[v for v in self.config.enabled_venues if v in self._cex_fees]}")
    
    async def _cleanup(self) -> None:
        """Cleanup connections."""
        logger.info("DEX-CEX scanner cleaned up")
    
    async def _scan(self) -> List[ArbitrageOpportunity]:
        """Scan for DEX vs CEX arbitrage opportunities."""
        opportunities = []
        
        for symbol in self.config.enabled_symbols:
            # Fetch DEX prices
            dex_prices = await self._fetch_dex_prices(symbol)
            
            # Fetch CEX prices
            cex_prices = await self._fetch_cex_prices(symbol)
            
            if not dex_prices or not cex_prices:
                continue
            
            # Find opportunities
            opps = self._find_opportunities(symbol, dex_prices, cex_prices)
            opportunities.extend(opps)
        
        return opportunities
    
    async def _fetch_dex_prices(self, symbol: str) -> List[DEXPrice]:
        """Fetch prices from DEXs."""
        prices = []
        
        # In production, query DEX subgraphs or on-chain
        # For now, simulate with realistic data
        try:
            from data.live_price_feed import get_live_price_feed
            
            feed = get_live_price_feed()
            price_data = feed.get_current_price(symbol)
            
            if not price_data:
                return prices
            
            base_price = price_data.price
            
            import random
            
            for dex, config in self._dex_configs.items():
                # DEX prices often have slight premium/discount
                variance = random.uniform(-0.003, 0.003)
                dex_price = base_price * (1 + variance)
                
                prices.append(DEXPrice(
                    dex=dex,
                    chain=config["chain"],
                    symbol=symbol,
                    price=dex_price,
                    liquidity_usd=random.uniform(100000, 5000000),
                    pool_address=f"0x{random.randbytes(20).hex()}",
                    timestamp=time.time(),
                ))
        except Exception as e:
            logger.debug(f"DEX price fetch error: {e}")
        
        return prices
    
    async def _fetch_cex_prices(self, symbol: str) -> List[CEXPrice]:
        """Fetch prices from CEXs."""
        prices = []
        
        try:
            from data.live_price_feed import get_live_price_feed
            
            feed = get_live_price_feed()
            price_data = feed.get_current_price(symbol)
            
            if not price_data:
                return prices
            
            base_price = price_data.price
            
            import random
            
            for cex in self._cex_fees.keys():
                spread = random.uniform(0.0001, 0.0003)
                mid = base_price * (1 + random.uniform(-0.001, 0.001))
                
                prices.append(CEXPrice(
                    exchange=cex,
                    symbol=symbol,
                    bid=mid * (1 - spread),
                    ask=mid * (1 + spread),
                    timestamp=time.time(),
                ))
        except Exception as e:
            logger.debug(f"CEX price fetch error: {e}")
        
        return prices
    
    def _find_opportunities(
        self,
        symbol: str,
        dex_prices: List[DEXPrice],
        cex_prices: List[CEXPrice]
    ) -> List[ArbitrageOpportunity]:
        """Find DEX-CEX arbitrage opportunities."""
        opportunities = []
        
        for dex_price in dex_prices:
            for cex_price in cex_prices:
                # Direction 1: Buy on DEX, sell on CEX
                opp1 = self._evaluate_opportunity(
                    symbol=symbol,
                    buy_venue=dex_price.dex,
                    buy_price=dex_price.price,
                    buy_is_dex=True,
                    buy_chain=dex_price.chain,
                    buy_liquidity=dex_price.liquidity_usd,
                    sell_venue=cex_price.exchange,
                    sell_price=cex_price.bid,
                    sell_is_dex=False,
                )
                if opp1:
                    opportunities.append(opp1)
                
                # Direction 2: Buy on CEX, sell on DEX
                opp2 = self._evaluate_opportunity(
                    symbol=symbol,
                    buy_venue=cex_price.exchange,
                    buy_price=cex_price.ask,
                    buy_is_dex=False,
                    buy_chain=None,
                    buy_liquidity=1000000,  # CEX assumed liquid
                    sell_venue=dex_price.dex,
                    sell_price=dex_price.price,
                    sell_is_dex=True,
                    sell_chain=dex_price.chain,
                )
                if opp2:
                    opportunities.append(opp2)
        
        return opportunities
    
    def _evaluate_opportunity(
        self,
        symbol: str,
        buy_venue: str,
        buy_price: float,
        buy_is_dex: bool,
        buy_chain: Optional[str],
        buy_liquidity: float,
        sell_venue: str,
        sell_price: float,
        sell_is_dex: bool,
        sell_chain: Optional[str] = None,
    ) -> Optional[ArbitrageOpportunity]:
        """Evaluate a potential DEX-CEX arbitrage opportunity."""
        
        # Check if profitable before fees
        if sell_price <= buy_price:
            return None
        
        # Calculate quantity
        qty = min(
            self.config.max_position_usd / buy_price,
            buy_liquidity / buy_price * 0.1,  # Max 10% of liquidity
        )
        
        if qty <= 0:
            return None
        
        gross_profit = (sell_price - buy_price) * qty
        
        # Calculate fees
        buy_fee = 0.0
        sell_fee = 0.0
        gas_cost = 0.0
        
        if buy_is_dex:
            dex_config = self._dex_configs.get(buy_venue, {"fee_tier": 0.003})
            buy_fee = buy_price * qty * dex_config["fee_tier"]
            gas_cost += self._gas_estimates.get(buy_chain, 15.0)
        else:
            buy_fee = buy_price * qty * self._cex_fees.get(buy_venue, 0.001)
        
        if sell_is_dex:
            dex_config = self._dex_configs.get(sell_venue, {"fee_tier": 0.003})
            sell_fee = sell_price * qty * dex_config["fee_tier"]
            gas_cost += self._gas_estimates.get(sell_chain, 15.0)
        else:
            sell_fee = sell_price * qty * self._cex_fees.get(sell_venue, 0.001)
        
        total_fees = buy_fee + sell_fee
        total_cost = total_fees + gas_cost
        
        net_profit = gross_profit - total_cost
        
        # Check thresholds
        total_value = buy_price * qty
        margin_pct = (net_profit / total_value) * 100 if total_value > 0 else 0
        
        if net_profit < self.config.min_profit_usd:
            return None
        if margin_pct < self.config.min_profit_margin_pct:
            return None
        
        # Create opportunity
        opp = ArbitrageOpportunity(
            arb_type=ArbitrageType.DEX_CEX,
            status=ArbitrageStatus.DETECTED,
            source_scanner=self.config.scanner_id,
            confidence=min(0.85, margin_pct / 1.5),
        )
        
        # Add buy leg
        opp.legs.append(ArbitrageLeg(
            sequence=1,
            venue=buy_venue,
            venue_type=VenueType.DEX if buy_is_dex else VenueType.CEX,
            symbol=symbol,
            side="buy",
            quantity=qty,
            price=buy_price,
            estimated_fee=buy_fee,
            estimated_gas=self._gas_estimates.get(buy_chain, 0) if buy_is_dex else 0,
        ))
        
        # Add sell leg
        opp.legs.append(ArbitrageLeg(
            sequence=2,
            venue=sell_venue,
            venue_type=VenueType.DEX if sell_is_dex else VenueType.CEX,
            symbol=symbol,
            side="sell",
            quantity=qty,
            price=sell_price,
            estimated_fee=sell_fee,
            estimated_gas=self._gas_estimates.get(sell_chain, 0) if sell_is_dex else 0,
        ))
        
        # Set metrics
        opp.gross_profit_usd = gross_profit
        opp.net_profit_usd = net_profit
        opp.profit_margin_pct = margin_pct
        opp.cost_model = CostModel(
            total_fees=total_fees,
            total_gas=gas_cost,
        )
        
        # Risk metrics - DEX arb is higher risk due to gas/MEV
        opp.execution_risk = 0.5
        opp.liquidity_score = min(1.0, buy_liquidity / 500000)
        opp.expires_at = time.time() + 15  # Short validity due to volatility
        opp.time_sensitivity = 15
        
        return opp


# Singleton
_dex_cex_scanner: Optional[DEXCEXScanner] = None


def get_dex_cex_scanner() -> DEXCEXScanner:
    """Get or create the DEX-CEX scanner singleton."""
    global _dex_cex_scanner
    if _dex_cex_scanner is None:
        _dex_cex_scanner = DEXCEXScanner()
    return _dex_cex_scanner
