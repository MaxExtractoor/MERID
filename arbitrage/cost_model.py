"""
Cost Model Engine for Arbitrage.

Provides accurate cost estimation for arbitrage execution including:
- Gas estimation (EVM + Solana)
- Latency penalty model
- Slippage curve fitting
- MEV probability estimator

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from schemas.arbitrage import ArbitrageOpportunity, ArbitrageLeg, CostModel, VenueType
from utils.logger import get_logger

logger = get_logger("arbitrage.cost_model")


class Chain(Enum):
    """Supported blockchain networks."""
    ETHEREUM = "ethereum"
    BSC = "bsc"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    POLYGON = "polygon"
    SOLANA = "solana"
    BASE = "base"
    AVALANCHE = "avalanche"


@dataclass
class GasEstimate:
    """Gas cost estimate for a transaction."""
    chain: Chain
    gas_units: int
    gas_price_gwei: float
    priority_fee_gwei: float
    total_cost_usd: float
    native_token_price: float
    estimated_at: float = field(default_factory=time.time)


@dataclass
class SlippageEstimate:
    """Slippage estimate for an order."""
    venue: str
    symbol: str
    side: str
    quantity: float
    expected_slippage_pct: float
    worst_case_slippage_pct: float
    liquidity_depth_usd: float


@dataclass
class LatencyPenalty:
    """Latency-based cost penalty."""
    venue: str
    expected_latency_ms: float
    price_movement_risk_pct: float
    penalty_usd: float


@dataclass
class MEVRisk:
    """MEV (Miner Extractable Value) risk assessment."""
    chain: Chain
    transaction_type: str
    mev_probability: float  # 0-1
    expected_mev_cost_usd: float
    mitigation_available: bool
    mitigation_method: str


class CostModelEngine:
    """
    Engine for calculating comprehensive arbitrage costs.
    
    Provides accurate cost estimation to ensure only truly
    profitable opportunities are flagged for execution.
    """
    
    def __init__(self):
        self.logger = get_logger("arbitrage.cost_model")
        
        # Gas prices by chain (in gwei or equivalent)
        self._gas_prices: Dict[Chain, float] = {
            Chain.ETHEREUM: 30.0,
            Chain.BSC: 5.0,
            Chain.ARBITRUM: 0.1,
            Chain.OPTIMISM: 0.001,
            Chain.POLYGON: 50.0,
            Chain.SOLANA: 0.000005,  # In SOL
            Chain.BASE: 0.001,
            Chain.AVALANCHE: 25.0,
        }
        
        # Native token prices (USD)
        self._native_prices: Dict[Chain, float] = {
            Chain.ETHEREUM: 3500.0,
            Chain.BSC: 600.0,
            Chain.ARBITRUM: 3500.0,  # Uses ETH
            Chain.OPTIMISM: 3500.0,  # Uses ETH
            Chain.POLYGON: 0.50,
            Chain.SOLANA: 180.0,
            Chain.BASE: 3500.0,  # Uses ETH
            Chain.AVALANCHE: 35.0,
        }
        
        # Gas units for common operations
        self._gas_units: Dict[str, Dict[Chain, int]] = {
            "swap": {
                Chain.ETHEREUM: 150000,
                Chain.BSC: 150000,
                Chain.ARBITRUM: 500000,
                Chain.OPTIMISM: 500000,
                Chain.POLYGON: 150000,
                Chain.SOLANA: 200000,  # Compute units
                Chain.BASE: 500000,
                Chain.AVALANCHE: 150000,
            },
            "transfer": {
                Chain.ETHEREUM: 21000,
                Chain.BSC: 21000,
                Chain.ARBITRUM: 100000,
                Chain.OPTIMISM: 100000,
                Chain.POLYGON: 21000,
                Chain.SOLANA: 5000,
                Chain.BASE: 100000,
                Chain.AVALANCHE: 21000,
            },
        }
        
        # Exchange latencies (ms)
        self._exchange_latencies: Dict[str, float] = {
            "binance": 50,
            "coinbase": 100,
            "kraken": 150,
            "okx": 80,
            "bybit": 60,
            "dydx": 200,
            "uniswap_v3": 12000,  # Block time
            "sushiswap": 12000,
            "pancakeswap": 3000,
        }
        
        # Slippage models (base slippage per $100k volume)
        self._base_slippage: Dict[str, float] = {
            "binance": 0.0001,
            "coinbase": 0.0002,
            "kraken": 0.0003,
            "okx": 0.00015,
            "bybit": 0.00012,
            "uniswap_v3": 0.003,
            "sushiswap": 0.005,
        }
        
        # MEV risk by chain
        self._mev_risk: Dict[Chain, float] = {
            Chain.ETHEREUM: 0.15,  # 15% chance of MEV
            Chain.BSC: 0.05,
            Chain.ARBITRUM: 0.02,
            Chain.OPTIMISM: 0.02,
            Chain.POLYGON: 0.03,
            Chain.SOLANA: 0.10,
            Chain.BASE: 0.02,
            Chain.AVALANCHE: 0.03,
        }
    
    def estimate_gas(self, chain: Chain, operation: str = "swap") -> GasEstimate:
        """Estimate gas cost for an operation."""
        gas_units = self._gas_units.get(operation, {}).get(chain, 150000)
        gas_price = self._gas_prices.get(chain, 30.0)
        native_price = self._native_prices.get(chain, 3500.0)
        
        # Calculate cost
        if chain == Chain.SOLANA:
            # Solana uses different pricing model
            total_cost_usd = (gas_units / 1000000) * native_price * 0.000005
        else:
            # EVM chains
            total_cost_usd = (gas_units * gas_price / 1e9) * native_price
        
        return GasEstimate(
            chain=chain,
            gas_units=gas_units,
            gas_price_gwei=gas_price,
            priority_fee_gwei=gas_price * 0.1,  # 10% priority
            total_cost_usd=total_cost_usd,
            native_token_price=native_price,
        )
    
    def estimate_slippage(
        self,
        venue: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> SlippageEstimate:
        """Estimate slippage for an order."""
        order_value = quantity * price
        
        # Base slippage
        base = self._base_slippage.get(venue, 0.001)
        
        # Scale with order size (quadratic for large orders)
        size_factor = (order_value / 100000) ** 1.5
        
        expected_slippage = base * (1 + size_factor)
        worst_case_slippage = expected_slippage * 3
        
        # Estimate liquidity depth
        if venue in ["binance", "coinbase", "okx"]:
            liquidity_depth = 10000000  # $10M
        elif venue in ["bybit", "kraken"]:
            liquidity_depth = 5000000
        else:
            liquidity_depth = 1000000  # DEXs
        
        return SlippageEstimate(
            venue=venue,
            symbol=symbol,
            side=side,
            quantity=quantity,
            expected_slippage_pct=expected_slippage * 100,
            worst_case_slippage_pct=worst_case_slippage * 100,
            liquidity_depth_usd=liquidity_depth,
        )
    
    def estimate_latency_penalty(
        self,
        venue: str,
        symbol: str,
        volatility_pct: float = 0.1
    ) -> LatencyPenalty:
        """Estimate cost penalty due to latency."""
        latency_ms = self._exchange_latencies.get(venue, 100)
        
        # Price movement risk based on volatility and latency
        # Assume volatility is per-minute
        latency_minutes = latency_ms / 60000
        price_movement_risk = volatility_pct * (latency_minutes ** 0.5)
        
        # Convert to USD penalty (assume $10k position)
        penalty_usd = 10000 * (price_movement_risk / 100)
        
        return LatencyPenalty(
            venue=venue,
            expected_latency_ms=latency_ms,
            price_movement_risk_pct=price_movement_risk,
            penalty_usd=penalty_usd,
        )
    
    def estimate_mev_risk(
        self,
        chain: Chain,
        transaction_value_usd: float,
        transaction_type: str = "swap"
    ) -> MEVRisk:
        """Estimate MEV risk for a transaction."""
        base_risk = self._mev_risk.get(chain, 0.05)
        
        # Higher value = higher MEV risk
        value_factor = min(2.0, transaction_value_usd / 50000)
        mev_probability = min(0.5, base_risk * value_factor)
        
        # Expected MEV cost (if attacked)
        if mev_probability > 0:
            expected_mev_cost = transaction_value_usd * 0.01 * mev_probability
        else:
            expected_mev_cost = 0
        
        # Mitigation options
        mitigation_available = chain in [Chain.ETHEREUM, Chain.ARBITRUM]
        mitigation_method = "Flashbots/MEV Blocker" if mitigation_available else "None"
        
        return MEVRisk(
            chain=chain,
            transaction_type=transaction_type,
            mev_probability=mev_probability,
            expected_mev_cost_usd=expected_mev_cost,
            mitigation_available=mitigation_available,
            mitigation_method=mitigation_method,
        )
    
    def calculate_total_cost(self, opportunity: ArbitrageOpportunity) -> CostModel:
        """Calculate total cost for an arbitrage opportunity."""
        total_fees = 0.0
        total_slippage = 0.0
        total_gas = 0.0
        latency_penalty = 0.0
        mev_risk = 0.0
        
        for leg in opportunity.legs:
            # Fees
            total_fees += leg.estimated_fee
            
            # Slippage
            slippage_est = self.estimate_slippage(
                venue=leg.venue,
                symbol=leg.symbol,
                side=leg.side,
                quantity=leg.quantity,
                price=leg.price,
            )
            slippage_cost = leg.price * leg.quantity * (slippage_est.expected_slippage_pct / 100)
            total_slippage += slippage_cost
            
            # Gas (for DEX legs)
            if leg.venue_type == VenueType.DEX:
                chain = self._venue_to_chain(leg.venue)
                gas_est = self.estimate_gas(chain, "swap")
                total_gas += gas_est.total_cost_usd
                
                # MEV risk
                mev_est = self.estimate_mev_risk(
                    chain=chain,
                    transaction_value_usd=leg.price * leg.quantity,
                )
                mev_risk += mev_est.expected_mev_cost_usd
            
            # Latency penalty
            latency_est = self.estimate_latency_penalty(leg.venue, leg.symbol)
            latency_penalty += latency_est.penalty_usd
        
        return CostModel(
            total_fees=total_fees,
            total_slippage=total_slippage,
            total_gas=total_gas,
            latency_penalty=latency_penalty,
            mev_risk=mev_risk,
        )
    
    def _venue_to_chain(self, venue: str) -> Chain:
        """Map venue to blockchain."""
        venue_chains = {
            "uniswap_v3": Chain.ETHEREUM,
            "sushiswap": Chain.ETHEREUM,
            "pancakeswap": Chain.BSC,
            "quickswap": Chain.POLYGON,
            "traderjoe": Chain.AVALANCHE,
            "raydium": Chain.SOLANA,
            "orca": Chain.SOLANA,
        }
        return venue_chains.get(venue, Chain.ETHEREUM)
    
    def update_gas_price(self, chain: Chain, gas_price: float) -> None:
        """Update gas price for a chain."""
        self._gas_prices[chain] = gas_price
        self.logger.info(f"Updated {chain.value} gas price to {gas_price}")
    
    def update_native_price(self, chain: Chain, price: float) -> None:
        """Update native token price for a chain."""
        self._native_prices[chain] = price
        self.logger.info(f"Updated {chain.value} native price to ${price}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get cost model status."""
        return {
            "gas_prices": {c.value: p for c, p in self._gas_prices.items()},
            "native_prices": {c.value: p for c, p in self._native_prices.items()},
            "exchange_latencies": self._exchange_latencies,
            "mev_risk_by_chain": {c.value: r for c, r in self._mev_risk.items()},
        }


# Singleton
_cost_model_engine: Optional[CostModelEngine] = None


def get_cost_model_engine() -> CostModelEngine:
    """Get or create the Cost Model Engine singleton."""
    global _cost_model_engine
    if _cost_model_engine is None:
        _cost_model_engine = CostModelEngine()
    return _cost_model_engine
