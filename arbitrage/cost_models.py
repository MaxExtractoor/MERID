"""
MERID Cost, Slippage & Latency Models - Phase 16

Makes arbitrage REAL, not theoretical.
All profit calculations must account for actual execution costs.
"""

from __future__ import annotations

import threading
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("arbitrage.cost_models")


class ChainType(Enum):
    """Blockchain types for gas estimation."""
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    SOLANA = "solana"
    BSC = "bsc"
    AVALANCHE = "avalanche"


class VenueType(Enum):
    """Trading venue types."""
    CEX = "cex"
    DEX_AMM = "dex_amm"
    DEX_ORDERBOOK = "dex_orderbook"
    PERP = "perp"
    PREDICTION = "prediction"


@dataclass
class GasEstimate:
    """Gas cost estimation for on-chain transactions."""
    chain: ChainType
    gas_units: int
    gas_price_gwei: float
    base_fee_gwei: float
    priority_fee_gwei: float
    native_token_price_usd: float
    total_cost_usd: float
    confidence: float = 0.8
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain": self.chain.value,
            "gas_units": self.gas_units,
            "gas_price_gwei": self.gas_price_gwei,
            "base_fee_gwei": self.base_fee_gwei,
            "priority_fee_gwei": self.priority_fee_gwei,
            "native_token_price_usd": self.native_token_price_usd,
            "total_cost_usd": self.total_cost_usd,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass
class SlippageEstimate:
    """Slippage estimation for trade execution."""
    venue: str
    venue_type: VenueType
    symbol: str
    side: str
    size_usd: float
    expected_slippage_bps: float
    worst_case_slippage_bps: float
    price_impact_pct: float
    liquidity_depth_usd: float
    confidence: float = 0.7
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "venue_type": self.venue_type.value,
            "symbol": self.symbol,
            "side": self.side,
            "size_usd": self.size_usd,
            "expected_slippage_bps": self.expected_slippage_bps,
            "worst_case_slippage_bps": self.worst_case_slippage_bps,
            "price_impact_pct": self.price_impact_pct,
            "liquidity_depth_usd": self.liquidity_depth_usd,
            "confidence": self.confidence,
        }


@dataclass
class LatencyEstimate:
    """Latency estimation for trade execution."""
    venue: str
    expected_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    network_latency_ms: float
    exchange_latency_ms: float
    settlement_time_ms: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "expected_latency_ms": self.expected_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "network_latency_ms": self.network_latency_ms,
            "exchange_latency_ms": self.exchange_latency_ms,
            "settlement_time_ms": self.settlement_time_ms,
        }


@dataclass
class MEVRisk:
    """MEV (Maximal Extractable Value) risk assessment."""
    probability: float
    expected_loss_bps: float
    worst_case_loss_bps: float
    sandwich_risk: float
    frontrun_risk: float
    backrun_risk: float
    recommended_protection: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "probability": self.probability,
            "expected_loss_bps": self.expected_loss_bps,
            "worst_case_loss_bps": self.worst_case_loss_bps,
            "sandwich_risk": self.sandwich_risk,
            "frontrun_risk": self.frontrun_risk,
            "backrun_risk": self.backrun_risk,
            "recommended_protection": self.recommended_protection,
        }


@dataclass
class NetProfitAnalysis:
    """Complete profit analysis after all costs."""
    gross_profit_usd: float
    total_fees_usd: float
    total_slippage_usd: float
    total_gas_usd: float
    mev_cost_usd: float
    latency_penalty_usd: float
    net_profit_usd: float
    net_profit_bps: float
    roi_pct: float
    profitable: bool
    profit_threshold_met: bool
    confidence: float
    breakdown: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "gross_profit_usd": self.gross_profit_usd,
            "total_fees_usd": self.total_fees_usd,
            "total_slippage_usd": self.total_slippage_usd,
            "total_gas_usd": self.total_gas_usd,
            "mev_cost_usd": self.mev_cost_usd,
            "latency_penalty_usd": self.latency_penalty_usd,
            "net_profit_usd": self.net_profit_usd,
            "net_profit_bps": self.net_profit_bps,
            "roi_pct": self.roi_pct,
            "profitable": self.profitable,
            "profit_threshold_met": self.profit_threshold_met,
            "confidence": self.confidence,
            "breakdown": self.breakdown,
        }


class GasEstimator:
    """
    Gas cost estimator for EVM and Solana chains.
    
    Estimates transaction costs based on:
    - Current gas prices
    - Transaction complexity
    - Network congestion
    """
    
    # Default gas units for common operations
    GAS_UNITS = {
        "erc20_transfer": 65000,
        "erc20_approve": 46000,
        "uniswap_v2_swap": 150000,
        "uniswap_v3_swap": 185000,
        "curve_swap": 300000,
        "1inch_swap": 250000,
        "perp_open": 200000,
        "perp_close": 180000,
        "bridge_deposit": 100000,
        "bridge_withdraw": 150000,
    }
    
    # Default gas prices by chain (gwei)
    DEFAULT_GAS_PRICES = {
        ChainType.ETHEREUM: 30.0,
        ChainType.POLYGON: 100.0,
        ChainType.ARBITRUM: 0.1,
        ChainType.OPTIMISM: 0.001,
        ChainType.BASE: 0.001,
        ChainType.BSC: 5.0,
        ChainType.AVALANCHE: 25.0,
    }
    
    # Native token prices (updated externally)
    NATIVE_PRICES_USD = {
        ChainType.ETHEREUM: 3100.0,
        ChainType.POLYGON: 0.50,
        ChainType.ARBITRUM: 3100.0,
        ChainType.OPTIMISM: 3100.0,
        ChainType.BASE: 3100.0,
        ChainType.BSC: 600.0,
        ChainType.AVALANCHE: 35.0,
        ChainType.SOLANA: 140.0,
    }
    
    def __init__(self):
        self._gas_price_cache: Dict[ChainType, Tuple[float, float]] = {}
        self._native_price_cache: Dict[ChainType, Tuple[float, float]] = {}
    
    def update_gas_price(self, chain: ChainType, gas_price_gwei: float) -> None:
        """Update cached gas price for a chain."""
        self._gas_price_cache[chain] = (gas_price_gwei, time.time())
    
    def update_native_price(self, chain: ChainType, price_usd: float) -> None:
        """Update cached native token price."""
        self._native_price_cache[chain] = (price_usd, time.time())
    
    def get_gas_price(self, chain: ChainType) -> float:
        """Get current gas price for a chain."""
        if chain in self._gas_price_cache:
            price, ts = self._gas_price_cache[chain]
            if time.time() - ts < 60:  # Cache valid for 60s
                return price
        return self.DEFAULT_GAS_PRICES.get(chain, 30.0)
    
    def get_native_price(self, chain: ChainType) -> float:
        """Get native token price in USD."""
        if chain in self._native_price_cache:
            price, ts = self._native_price_cache[chain]
            if time.time() - ts < 60:
                return price
        return self.NATIVE_PRICES_USD.get(chain, 3000.0)
    
    def estimate_gas(
        self,
        chain: ChainType,
        operation: str,
        gas_units: Optional[int] = None,
        priority_multiplier: float = 1.0,
    ) -> GasEstimate:
        """
        Estimate gas cost for an operation.
        
        Args:
            chain: Target blockchain
            operation: Operation type (e.g., "uniswap_v3_swap")
            gas_units: Override gas units (uses default if None)
            priority_multiplier: Multiplier for priority fee (1.0 = normal)
        """
        if gas_units is None:
            gas_units = self.GAS_UNITS.get(operation, 150000)
        
        gas_price = self.get_gas_price(chain)
        native_price = self.get_native_price(chain)
        
        # EIP-1559 style estimation
        base_fee = gas_price * 0.7
        priority_fee = gas_price * 0.3 * priority_multiplier
        total_gas_price = base_fee + priority_fee
        
        # Calculate cost in native token then USD
        gas_cost_native = (gas_units * total_gas_price) / 1e9
        gas_cost_usd = gas_cost_native * native_price
        
        # Confidence based on cache freshness
        confidence = 0.9 if chain in self._gas_price_cache else 0.6
        
        return GasEstimate(
            chain=chain,
            gas_units=gas_units,
            gas_price_gwei=total_gas_price,
            base_fee_gwei=base_fee,
            priority_fee_gwei=priority_fee,
            native_token_price_usd=native_price,
            total_cost_usd=gas_cost_usd,
            confidence=confidence,
        )
    
    def estimate_solana(self, compute_units: int = 200000) -> GasEstimate:
        """Estimate Solana transaction cost."""
        # Solana uses fixed priority fees + compute units
        base_fee_lamports = 5000  # 0.000005 SOL
        priority_fee_lamports = compute_units * 1  # 1 microlamport per CU
        total_lamports = base_fee_lamports + priority_fee_lamports
        
        sol_price = self.get_native_price(ChainType.SOLANA)
        cost_usd = (total_lamports / 1e9) * sol_price
        
        return GasEstimate(
            chain=ChainType.SOLANA,
            gas_units=compute_units,
            gas_price_gwei=0,
            base_fee_gwei=0,
            priority_fee_gwei=0,
            native_token_price_usd=sol_price,
            total_cost_usd=cost_usd,
            confidence=0.85,
        )


class SlippageModel:
    """
    Slippage curve fitting for AMMs and orderbooks.
    
    Models price impact based on:
    - Order size relative to liquidity
    - AMM curve parameters
    - Orderbook depth
    """
    
    def __init__(self):
        # Liquidity depth estimates by venue (USD)
        self._liquidity_cache: Dict[str, Dict[str, float]] = {}
    
    def update_liquidity(self, venue: str, symbol: str, depth_usd: float) -> None:
        """Update liquidity depth for a venue/symbol."""
        if venue not in self._liquidity_cache:
            self._liquidity_cache[venue] = {}
        self._liquidity_cache[venue][symbol] = depth_usd
    
    def get_liquidity(self, venue: str, symbol: str) -> float:
        """Get liquidity depth estimate."""
        return self._liquidity_cache.get(venue, {}).get(symbol, 100000.0)
    
    def estimate_amm_slippage(
        self,
        venue: str,
        symbol: str,
        side: str,
        size_usd: float,
        pool_tvl_usd: Optional[float] = None,
    ) -> SlippageEstimate:
        """
        Estimate slippage for AMM (constant product) swap.
        
        Uses the formula: slippage ≈ size / (2 * liquidity)
        """
        liquidity = pool_tvl_usd or self.get_liquidity(venue, symbol)
        
        # Constant product AMM slippage approximation
        # For x*y=k, price impact ≈ Δx / (x + Δx)
        size_ratio = size_usd / liquidity if liquidity > 0 else 1.0
        
        # Expected slippage in basis points
        expected_slippage_bps = size_ratio * 5000  # 0.5% per 1% of liquidity
        
        # Worst case adds 50% buffer
        worst_case_bps = expected_slippage_bps * 1.5
        
        # Price impact percentage
        price_impact_pct = expected_slippage_bps / 100
        
        # Confidence decreases with size
        confidence = max(0.3, 0.9 - size_ratio)
        
        return SlippageEstimate(
            venue=venue,
            venue_type=VenueType.DEX_AMM,
            symbol=symbol,
            side=side,
            size_usd=size_usd,
            expected_slippage_bps=min(expected_slippage_bps, 500),  # Cap at 5%
            worst_case_slippage_bps=min(worst_case_bps, 750),
            price_impact_pct=min(price_impact_pct, 5.0),
            liquidity_depth_usd=liquidity,
            confidence=confidence,
        )
    
    def estimate_orderbook_slippage(
        self,
        venue: str,
        symbol: str,
        side: str,
        size_usd: float,
        bid_depth_usd: Optional[float] = None,
        ask_depth_usd: Optional[float] = None,
    ) -> SlippageEstimate:
        """
        Estimate slippage for orderbook execution.
        
        Based on walking the book to fill the order.
        """
        depth = bid_depth_usd if side == "sell" else ask_depth_usd
        if depth is None:
            depth = self.get_liquidity(venue, symbol)
        
        # Orderbook slippage is typically lower than AMM
        size_ratio = size_usd / depth if depth > 0 else 1.0
        
        # Estimate based on typical orderbook shape
        expected_slippage_bps = size_ratio * 2000  # 0.2% per 1% of depth
        worst_case_bps = expected_slippage_bps * 2.0
        
        return SlippageEstimate(
            venue=venue,
            venue_type=VenueType.DEX_ORDERBOOK,
            symbol=symbol,
            side=side,
            size_usd=size_usd,
            expected_slippage_bps=min(expected_slippage_bps, 300),
            worst_case_slippage_bps=min(worst_case_bps, 500),
            price_impact_pct=expected_slippage_bps / 100,
            liquidity_depth_usd=depth,
            confidence=0.75,
        )
    
    def estimate_cex_slippage(
        self,
        venue: str,
        symbol: str,
        side: str,
        size_usd: float,
    ) -> SlippageEstimate:
        """Estimate slippage for CEX execution."""
        # CEX typically has better liquidity
        liquidity = self.get_liquidity(venue, symbol) * 5  # CEX multiplier
        size_ratio = size_usd / liquidity if liquidity > 0 else 1.0
        
        expected_slippage_bps = size_ratio * 1000  # 0.1% per 1% of depth
        
        return SlippageEstimate(
            venue=venue,
            venue_type=VenueType.CEX,
            symbol=symbol,
            side=side,
            size_usd=size_usd,
            expected_slippage_bps=min(expected_slippage_bps, 100),
            worst_case_slippage_bps=min(expected_slippage_bps * 1.5, 150),
            price_impact_pct=expected_slippage_bps / 100,
            liquidity_depth_usd=liquidity,
            confidence=0.85,
        )


class LatencyModel:
    """
    Latency penalty model for arbitrage execution.
    
    Accounts for:
    - Network latency to exchanges
    - Exchange processing time
    - Settlement/confirmation time
    """
    
    # Default latencies by venue type (ms)
    DEFAULT_LATENCIES = {
        VenueType.CEX: {"network": 50, "exchange": 20, "settlement": 0},
        VenueType.DEX_AMM: {"network": 100, "exchange": 0, "settlement": 12000},
        VenueType.DEX_ORDERBOOK: {"network": 100, "exchange": 50, "settlement": 12000},
        VenueType.PERP: {"network": 50, "exchange": 30, "settlement": 0},
        VenueType.PREDICTION: {"network": 100, "exchange": 100, "settlement": 0},
    }
    
    def __init__(self):
        self._latency_history: Dict[str, List[float]] = {}
    
    def record_latency(self, venue: str, latency_ms: float) -> None:
        """Record observed latency for a venue."""
        if venue not in self._latency_history:
            self._latency_history[venue] = []
        self._latency_history[venue].append(latency_ms)
        # Keep last 100 observations
        if len(self._latency_history[venue]) > 100:
            self._latency_history[venue] = self._latency_history[venue][-100:]
    
    def estimate_latency(
        self,
        venue: str,
        venue_type: VenueType,
    ) -> LatencyEstimate:
        """Estimate execution latency for a venue."""
        defaults = self.DEFAULT_LATENCIES.get(venue_type, self.DEFAULT_LATENCIES[VenueType.CEX])
        
        # Use historical data if available
        if venue in self._latency_history and len(self._latency_history[venue]) >= 10:
            history = sorted(self._latency_history[venue])
            expected = sum(history) / len(history)
            p95 = history[int(len(history) * 0.95)]
            p99 = history[int(len(history) * 0.99)]
        else:
            network = defaults["network"]
            exchange = defaults["exchange"]
            expected = network + exchange
            p95 = expected * 1.5
            p99 = expected * 2.0
        
        return LatencyEstimate(
            venue=venue,
            expected_latency_ms=expected,
            p95_latency_ms=p95,
            p99_latency_ms=p99,
            network_latency_ms=defaults["network"],
            exchange_latency_ms=defaults["exchange"],
            settlement_time_ms=defaults["settlement"],
        )
    
    def calculate_latency_penalty(
        self,
        latency_ms: float,
        spread_bps: float,
        volatility_bps_per_second: float = 1.0,
    ) -> float:
        """
        Calculate expected profit loss due to latency.
        
        Returns penalty in basis points.
        """
        # Spread can close during latency
        latency_seconds = latency_ms / 1000
        expected_spread_decay = volatility_bps_per_second * latency_seconds
        
        # Probability spread closes before execution
        close_probability = min(1.0, expected_spread_decay / spread_bps) if spread_bps > 0 else 1.0
        
        # Expected penalty
        penalty_bps = spread_bps * close_probability * 0.5
        
        return penalty_bps


class MEVEstimator:
    """
    MEV (Maximal Extractable Value) probability estimator.
    
    Assesses risk of:
    - Sandwich attacks
    - Frontrunning
    - Backrunning
    """
    
    def estimate_mev_risk(
        self,
        chain: ChainType,
        size_usd: float,
        expected_profit_bps: float,
        is_public_mempool: bool = True,
    ) -> MEVRisk:
        """Estimate MEV extraction risk."""
        # MEV risk varies by chain
        chain_mev_factor = {
            ChainType.ETHEREUM: 1.0,
            ChainType.POLYGON: 0.3,
            ChainType.ARBITRUM: 0.5,
            ChainType.OPTIMISM: 0.4,
            ChainType.BASE: 0.4,
            ChainType.BSC: 0.6,
            ChainType.SOLANA: 0.7,
        }.get(chain, 0.5)
        
        # Larger trades attract more MEV
        size_factor = min(1.0, size_usd / 100000)
        
        # More profitable trades attract more MEV
        profit_factor = min(1.0, expected_profit_bps / 100)
        
        # Public mempool increases risk
        mempool_factor = 1.0 if is_public_mempool else 0.2
        
        # Combined probability
        base_probability = chain_mev_factor * size_factor * profit_factor * mempool_factor
        
        # Specific attack probabilities
        sandwich_risk = base_probability * 0.6
        frontrun_risk = base_probability * 0.3
        backrun_risk = base_probability * 0.1
        
        # Expected loss
        expected_loss_bps = base_probability * expected_profit_bps * 0.3
        worst_case_loss_bps = expected_profit_bps * 0.8
        
        # Recommended protection
        if base_probability > 0.5:
            protection = "flashbots_protect"
        elif base_probability > 0.2:
            protection = "private_mempool"
        else:
            protection = "none"
        
        return MEVRisk(
            probability=base_probability,
            expected_loss_bps=expected_loss_bps,
            worst_case_loss_bps=worst_case_loss_bps,
            sandwich_risk=sandwich_risk,
            frontrun_risk=frontrun_risk,
            backrun_risk=backrun_risk,
            recommended_protection=protection,
        )


class NetProfitCalculator:
    """
    Calculates net profit after ALL costs.
    
    This is the final arbiter of whether an opportunity is real.
    """
    
    def __init__(
        self,
        gas_estimator: Optional[GasEstimator] = None,
        slippage_model: Optional[SlippageModel] = None,
        latency_model: Optional[LatencyModel] = None,
        mev_estimator: Optional[MEVEstimator] = None,
    ):
        self.gas_estimator = gas_estimator or GasEstimator()
        self.slippage_model = slippage_model or SlippageModel()
        self.latency_model = latency_model or LatencyModel()
        self.mev_estimator = mev_estimator or MEVEstimator()
        
        # Minimum profit threshold (basis points)
        self.min_profit_threshold_bps = 10.0
    
    def calculate_net_profit(
        self,
        gross_profit_usd: float,
        size_usd: float,
        legs: List[Dict[str, Any]],
        chain: Optional[ChainType] = None,
    ) -> NetProfitAnalysis:
        """
        Calculate net profit after all costs.
        
        Args:
            gross_profit_usd: Theoretical profit before costs
            size_usd: Total position size
            legs: List of trade legs with venue info
            chain: Blockchain for on-chain legs
        """
        gross_profit_bps = (gross_profit_usd / size_usd * 10000) if size_usd > 0 else 0
        
        # Calculate fees
        total_fees_usd = 0.0
        for leg in legs:
            fee_rate = leg.get("fee_rate_bps", 10) / 10000
            leg_size = leg.get("size_usd", size_usd / len(legs))
            total_fees_usd += leg_size * fee_rate
        
        # Calculate slippage
        total_slippage_usd = 0.0
        for leg in legs:
            venue = leg.get("venue", "unknown")
            venue_type = VenueType(leg.get("venue_type", "cex"))
            symbol = leg.get("symbol", "BTC/USD")
            side = leg.get("side", "buy")
            leg_size = leg.get("size_usd", size_usd / len(legs))
            
            if venue_type == VenueType.DEX_AMM:
                slip = self.slippage_model.estimate_amm_slippage(venue, symbol, side, leg_size)
            elif venue_type == VenueType.CEX:
                slip = self.slippage_model.estimate_cex_slippage(venue, symbol, side, leg_size)
            else:
                slip = self.slippage_model.estimate_orderbook_slippage(venue, symbol, side, leg_size)
            
            total_slippage_usd += leg_size * (slip.expected_slippage_bps / 10000)
        
        # Calculate gas costs
        total_gas_usd = 0.0
        if chain:
            # Estimate gas for each on-chain leg
            on_chain_legs = [l for l in legs if l.get("on_chain", False)]
            for leg in on_chain_legs:
                operation = leg.get("operation", "uniswap_v3_swap")
                gas = self.gas_estimator.estimate_gas(chain, operation)
                total_gas_usd += gas.total_cost_usd
        
        # Calculate MEV cost
        mev_cost_usd = 0.0
        if chain:
            mev = self.mev_estimator.estimate_mev_risk(chain, size_usd, gross_profit_bps)
            mev_cost_usd = size_usd * (mev.expected_loss_bps / 10000)
        
        # Calculate latency penalty
        latency_penalty_usd = 0.0
        for leg in legs:
            venue = leg.get("venue", "unknown")
            venue_type = VenueType(leg.get("venue_type", "cex"))
            latency = self.latency_model.estimate_latency(venue, venue_type)
            penalty_bps = self.latency_model.calculate_latency_penalty(
                latency.expected_latency_ms,
                gross_profit_bps,
            )
            leg_size = leg.get("size_usd", size_usd / len(legs))
            latency_penalty_usd += leg_size * (penalty_bps / 10000)
        
        # Calculate net profit
        total_costs = total_fees_usd + total_slippage_usd + total_gas_usd + mev_cost_usd + latency_penalty_usd
        net_profit_usd = gross_profit_usd - total_costs
        net_profit_bps = (net_profit_usd / size_usd * 10000) if size_usd > 0 else 0
        roi_pct = (net_profit_usd / size_usd * 100) if size_usd > 0 else 0
        
        # Determine if profitable
        profitable = net_profit_usd > 0
        profit_threshold_met = net_profit_bps >= self.min_profit_threshold_bps
        
        # Confidence based on model uncertainties
        confidence = 0.7  # Base confidence
        if total_gas_usd > gross_profit_usd * 0.5:
            confidence *= 0.8  # High gas uncertainty
        if total_slippage_usd > gross_profit_usd * 0.3:
            confidence *= 0.85  # High slippage uncertainty
        
        return NetProfitAnalysis(
            gross_profit_usd=gross_profit_usd,
            total_fees_usd=total_fees_usd,
            total_slippage_usd=total_slippage_usd,
            total_gas_usd=total_gas_usd,
            mev_cost_usd=mev_cost_usd,
            latency_penalty_usd=latency_penalty_usd,
            net_profit_usd=net_profit_usd,
            net_profit_bps=net_profit_bps,
            roi_pct=roi_pct,
            profitable=profitable,
            profit_threshold_met=profit_threshold_met,
            confidence=confidence,
            breakdown={
                "fees_pct": (total_fees_usd / gross_profit_usd * 100) if gross_profit_usd > 0 else 0,
                "slippage_pct": (total_slippage_usd / gross_profit_usd * 100) if gross_profit_usd > 0 else 0,
                "gas_pct": (total_gas_usd / gross_profit_usd * 100) if gross_profit_usd > 0 else 0,
                "mev_pct": (mev_cost_usd / gross_profit_usd * 100) if gross_profit_usd > 0 else 0,
                "latency_pct": (latency_penalty_usd / gross_profit_usd * 100) if gross_profit_usd > 0 else 0,
            },
        )


# Singleton instances
_gas_estimator: Optional[GasEstimator] = None
_gas_estimator_lock = threading.Lock()
_slippage_model: Optional[SlippageModel] = None
_slippage_model_lock = threading.Lock()
_latency_model: Optional[LatencyModel] = None
_latency_model_lock = threading.Lock()
_mev_estimator: Optional[MEVEstimator] = None
_mev_estimator_lock = threading.Lock()
_net_profit_calculator: Optional[NetProfitCalculator] = None
_net_profit_calculator_lock = threading.Lock()


def get_gas_estimator() -> GasEstimator:
    global _gas_estimator
    if _gas_estimator is None:
        with _gas_estimator_lock:
            if _gas_estimator is None:
                _gas_estimator = GasEstimator()
    return _gas_estimator


def get_slippage_model() -> SlippageModel:
    global _slippage_model
    if _slippage_model is None:
        with _slippage_model_lock:
            if _slippage_model is None:
                _slippage_model = SlippageModel()
    return _slippage_model


def get_latency_model() -> LatencyModel:
    global _latency_model
    if _latency_model is None:
        with _latency_model_lock:
            if _latency_model is None:
                _latency_model = LatencyModel()
    return _latency_model


def get_mev_estimator() -> MEVEstimator:
    global _mev_estimator
    if _mev_estimator is None:
        with _mev_estimator_lock:
            if _mev_estimator is None:
                _mev_estimator = MEVEstimator()
    return _mev_estimator


def get_net_profit_calculator() -> NetProfitCalculator:
    global _net_profit_calculator
    if _net_profit_calculator is None:
        with _net_profit_calculator_lock:
            if _net_profit_calculator is None:
                _net_profit_calculator = NetProfitCalculator()
    return _net_profit_calculator
