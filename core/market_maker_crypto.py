"""MERID Crypto DEX Market Maker for Uniswap, Cronos, and AMMs.

Automated market making on DEXs with LP management, impermanent loss tracking,
and dynamic spread adjustment. Integrates with MERID swarm for risk management.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta
from enum import Enum
import structlog
import os

logger = structlog.get_logger(__name__)


class DEXType(str, Enum):
    """Types of DEXs supported."""
    UNISWAP_V2 = "uniswap_v2"
    UNISWAP_V3 = "uniswap_v3"
    PANCAKESWAP = "pancakeswap"
    VVS_FINANCE = "vvs_finance"
    TRADER_JOE = "trader_joe"


class MMStrategy(str, Enum):
    """Market making strategies."""
    PURE_MM = "pure_market_making"
    AVELLANEDA = "avellaneda_market_making"
    CROSS_EXCHANGE = "cross_exchange_market_making"
    LIQUIDITY_MINING = "liquidity_mining"


@dataclass
class LiquidityPosition:
    """LP position in an AMM."""
    pair: str
    token0: str
    token1: str
    token0_amount: Decimal
    token1_amount: Decimal
    lp_tokens: Decimal
    entry_price: Decimal
    impermanent_loss: Decimal
    fees_earned: Decimal
    apr: Decimal


@dataclass
class DEXQuote:
    """Quote from DEX market maker."""
    pair: str
    side: str  # buy/sell
    price: Decimal
    size: Decimal
    gas_cost: Decimal
    slippage: Decimal
    timestamp: datetime


class UniswapMarketMaker:
    """Market maker for Uniswap V2/V3."""
    
    def __init__(
        self,
        rpc_url: Optional[str] = None,
        private_key: Optional[str] = None
    ):
        self.rpc_url = rpc_url or os.getenv("ETH_RPC_URL")
        self.private_key = private_key
        self.web3 = None
        self.logger = logger.bind(market_maker="Uniswap")
        self.positions: Dict[str, LiquidityPosition] = {}
        
        self._init_web3()
    
    def _init_web3(self):
        """Initialize Web3 connection."""
        try:
            from web3 import Web3
            
            if self.rpc_url:
                self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                self.logger.info("web3_initialized", connected=self.web3.is_connected())
            else:
                self.web3 = None
                self.logger.warning("web3_no_rpc")
                
        except ImportError:
            self.logger.error("web3_not_installed")
            self.web3 = None
    
    def calculate_lp_value(
        self,
        token0_reserve: Decimal,
        token1_reserve: Decimal,
        lp_supply: Decimal,
        lp_tokens: Decimal,
        price_token1_in_token0: Decimal
    ) -> Decimal:
        """Calculate value of LP position."""
        share = lp_tokens / lp_supply
        
        token0_value = token0_reserve * share
        token1_value = token1_reserve * share * price_token1_in_token0
        
        return token0_value + token1_value
    
    def calculate_impermanent_loss(
        self,
        entry_price: Decimal,
        current_price: Decimal
    ) -> Decimal:
        """Calculate impermanent loss percentage."""
        price_ratio = current_price / entry_price
        
        # IL formula: 2 * sqrt(price_ratio) / (1 + price_ratio) - 1
        import math
        il = (2 * math.sqrt(float(price_ratio)) / (1 + float(price_ratio))) - 1
        
        return Decimal(str(abs(il)))
    
    def calculate_optimal_lp_range(
        self,
        volatility: Decimal,
        price: Decimal,
        confidence: Decimal = Decimal("0.95")
    ) -> Tuple[Decimal, Decimal]:
        """Calculate optimal price range for Uniswap V3 LP."""
        # Based on volatility, calculate range
        # Higher volatility = wider range
        range_width = volatility * Decimal("2")
        
        lower = price * (Decimal("1") - range_width)
        upper = price * (Decimal("1") + range_width)
        
        return lower, upper
    
    async def add_liquidity(
        self,
        pair: str,
        token0_amount: Decimal,
        token1_amount: Decimal,
        slippage: Decimal = Decimal("0.005")
    ) -> Dict[str, Any]:
        """Add liquidity to DEX pool."""
        try:
            self.logger.info(
                "adding_liquidity",
                pair=pair,
                token0=str(token0_amount),
                token1=str(token1_amount)
            )
            
            # Mock implementation
            lp_tokens = (token0_amount * token1_amount).sqrt()
            
            position = LiquidityPosition(
                pair=pair,
                token0=pair.split("-")[0],
                token1=pair.split("-")[1],
                token0_amount=token0_amount,
                token1_amount=token1_amount,
                lp_tokens=lp_tokens,
                entry_price=token1_amount / token0_amount,
                impermanent_loss=Decimal("0"),
                fees_earned=Decimal("0"),
                apr=Decimal("0.25")  # 25% estimated
            )
            
            self.positions[pair] = position
            
            return {
                "status": "success",
                "lp_tokens": lp_tokens,
                "position": position
            }
            
        except Exception as e:
            self.logger.error("add_liquidity_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def remove_liquidity(
        self,
        pair: str,
        lp_tokens: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        """Remove liquidity from DEX pool."""
        if pair not in self.positions:
            return {"status": "error", "message": "No position found"}
        
        position = self.positions[pair]
        
        # Calculate current impermanent loss
        current_price = position.token1_amount / position.token0_amount
        il = self.calculate_impermanent_loss(position.entry_price, current_price)
        
        self.logger.info(
            "removing_liquidity",
            pair=pair,
            impermanent_loss=str(il)
        )
        
        # Return tokens
        return {
            "status": "success",
            "token0_returned": position.token0_amount,
            "token1_returned": position.token1_amount,
            "fees_earned": position.fees_earned,
            "impermanent_loss": il
        }
    
    async def rebalance_position(
        self,
        pair: str,
        target_ratio: Decimal
    ) -> Dict[str, Any]:
        """Rebalance LP position to target ratio."""
        if pair not in self.positions:
            return {"status": "error", "message": "No position"}
        
        position = self.positions[pair]
        current_ratio = position.token1_amount / position.token0_amount
        
        if abs(current_ratio - target_ratio) / target_ratio < Decimal("0.05"):
            return {"status": "no_action", "reason": "within_tolerance"}
        
        self.logger.info(
            "rebalancing_position",
            pair=pair,
            current=str(current_ratio),
            target=str(target_ratio)
        )
        
        # In practice, would swap excess tokens
        return {"status": "rebalanced"}


class CronosMarketMaker:
    """Market maker for Cronos chain (VVS Finance, MM Finance)."""
    
    def __init__(
        self,
        rpc_url: str = "https://evm.cronos.org",
        private_key: Optional[str] = None
    ):
        self.rpc_url = rpc_url
        self.private_key = private_key or os.getenv("CRONOS_PK")
        self.web3 = None
        self.logger = logger.bind(market_maker="Cronos")
        
        self._init_web3()
    
    def _init_web3(self):
        """Initialize Web3 for Cronos."""
        try:
            from web3 import Web3
            
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            self.logger.info("cronos_web3_initialized")
            
        except Exception as e:
            self.logger.error("cronos_init_error", error=str(e))
    
    async def get_vvs_pools(self) -> List[Dict[str, Any]]:
        """Get VVS Finance liquidity pools."""
        # Mock VVS pools
        return [
            {
                "pair": "CRO-USDC",
                "tvl": 5000000,
                "apy": 0.35,
                "volume_24h": 2000000
            },
            {
                "pair": "VVS-CRO",
                "tvl": 2000000,
                "apy": 0.55,
                "volume_24h": 800000
            }
        ]
    
    async def quote_vvs_swap(
        self,
        pair: str,
        amount_in: Decimal,
        token_in: str
    ) -> Dict[str, Any]:
        """Quote a swap on VVS Finance."""
        # Mock quote
        amount_out = amount_in * Decimal("0.98")  # 2% slippage
        
        return {
            "amount_out": amount_out,
            "slippage": Decimal("0.02"),
            "price_impact": Decimal("0.005"),
            "fee": amount_in * Decimal("0.003")
        }


class HummingbotStrategyAdapter:
    """Adapter for Hummingbot market making strategies."""
    
    def __init__(self):
        self.logger = logger.bind(component="HummingbotAdapter")
        self.strategies = {}
    
    def configure_pure_mm(
        self,
        pair: str,
        bid_spread: Decimal,
        ask_spread: Decimal,
        order_amount: Decimal,
        order_refresh_time: int = 10
    ) -> Dict[str, Any]:
        """Configure pure market making strategy."""
        config = {
            "strategy": "pure_market_making",
            "pair": pair,
            "bid_spread": float(bid_spread),
            "ask_spread": float(ask_spread),
            "order_amount": float(order_amount),
            "order_refresh_time": order_refresh_time,
            "filled_order_delay": 60,
            "hanging_orders_enabled": True
        }
        
        self.strategies[pair] = config
        self.logger.info("pure_mm_configured", pair=pair)
        
        return config
    
    def configure_avellaneda_mm(
        self,
        pair: str,
        risk_factor: Decimal,
        order_amount: Decimal,
        volatility_buffer: Decimal = Decimal("0.1")
    ) -> Dict[str, Any]:
        """Configure Avellaneda-Stoikov market making."""
        config = {
            "strategy": "avellaneda_market_making",
            "pair": pair,
            "risk_factor": float(risk_factor),
            "order_amount": float(order_amount),
            "volatility_buffer": float(volatility_buffer),
            "order_levels": 3
        }
        
        self.strategies[pair] = config
        self.logger.info("avellaneda_mm_configured", pair=pair)
        
        return config
    
    def generate_hummingbot_config_yml(self, pair: str) -> str:
        """Generate Hummingbot config YAML."""
        if pair not in self.strategies:
            return ""
        
        config = self.strategies[pair]
        
        yml = f"""# Hummingbot configuration for {pair}
strategy: {config['strategy']}
market: {pair}

# Order settings
bid_spread: {config.get('bid_spread', 0.01)}
ask_spread: {config.get('ask_spread', 0.01)}
order_amount: {config.get('order_amount', 1.0)}
order_refresh_time: {config.get('order_refresh_time', 10)}

# Risk settings
risk_factor: {config.get('risk_factor', 0.5)}
volatility_buffer: {config.get('volatility_buffer', 0.1)}

# Advanced
hanging_orders_enabled: true
filled_order_delay: 60
order_levels: {config.get('order_levels', 1)}
"""
        
        return yml


class SwarmIntegratedDEXMaker:
    """DEX market maker integrated with MERID swarm."""
    
    def __init__(
        self,
        uniswap_mm: Optional[UniswapMarketMaker] = None,
        cronos_mm: Optional[CronosMarketMaker] = None,
        swarm_orchestrator=None
    ):
        self.uniswap = uniswap_mm or UniswapMarketMaker()
        self.cronos = cronos_mm or CronosMarketMaker()
        self.swarm = swarm_orchestrator
        self.hummingbot = HummingbotStrategyAdapter()
        
        self.logger = logger.bind(component="SwarmIntegratedDEXMaker")
    
    async def get_swarm_lp_recommendation(
        self,
        pair: str,
        expected_apr: Decimal
    ) -> Dict[str, Any]:
        """Get LP recommendation from swarm."""
        if not self.swarm:
            return {"approved": True, "size": Decimal("1000")}
        
        try:
            # Query swarm for risk assessment
            risk_check = await self.swarm.run_risk_check({
                "symbol": pair,
                "exposure": expected_apr * Decimal("1000"),
                "strategy": "lp_yield"
            })
            
            if not risk_check.get("approved"):
                return {"approved": False, "reason": "risk_check_failed"}
            
            return {
                "approved": True,
                "size": Decimal("1000"),
                "max_il_tolerance": Decimal("0.05")
            }
            
        except Exception as e:
            self.logger.error("swarm_lp_error", error=str(e))
            return {"approved": False, "error": str(e)}
    
    async def optimize_lp_positions(self):
        """Optimize LP positions based on swarm recommendations."""
        # Check all positions for impermanent loss
        for pair, position in self.uniswap.positions.items():
            current_price = position.token1_amount / position.token0_amount
            il = self.uniswap.calculate_impermanent_loss(
                position.entry_price,
                current_price
            )
            
            # If IL exceeds threshold, consider rebalancing
            if il > Decimal("0.1"):  # 10% IL
                self.logger.warning(
                    "high_impermanent_loss",
                    pair=pair,
                    il=str(il)
                )
                
                # Get swarm recommendation
                rec = await self.get_swarm_lp_recommendation(pair, position.apr)
                
                if not rec.get("approved"):
                    # Remove liquidity
                    await self.uniswap.remove_liquidity(pair)
    
    def generate_mm_config(
        self,
        pair: str,
        dex: DEXType,
        strategy: MMStrategy
    ) -> str:
        """Generate market maker configuration."""
        if strategy == MMStrategy.PURE_MM:
            config = self.hummingbot.configure_pure_mm(
                pair=pair,
                bid_spread=Decimal("0.005"),
                ask_spread=Decimal("0.005"),
                order_amount=Decimal("1.0")
            )
            return self.hummingbot.generate_hummingbot_config_yml(pair)
        
        elif strategy == MMStrategy.AVELLANEDA:
            config = self.hummingbot.configure_avellaneda_mm(
                pair=pair,
                risk_factor=Decimal("0.5"),
                order_amount=Decimal("1.0")
            )
            return self.hummingbot.generate_hummingbot_config_yml(pair)
        
        return ""


# Singleton instances
uniswap_market_maker = UniswapMarketMaker()
cronos_market_maker = CronosMarketMaker()
hummingbot_adapter = HummingbotStrategyAdapter()
