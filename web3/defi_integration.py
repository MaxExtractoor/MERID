"""
DeFi Protocol Integration Layer

Provides unified access to major DeFi protocols with US-compliant
configuration and comprehensive protocol abstraction.

Features:
- Multi-protocol support (Uniswap, Curve, Aave, Compound)
- Unified protocol interface
- Liquidity and yield tracking
- Risk assessment and monitoring
- US regulatory compliance
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import json

from web3.blockchain_connector import BlockchainConnector, ContractCall
from utils.logger import get_logger

logger = get_logger("web3.defi_integration")

@dataclass
class ProtocolConfig:
    """DeFi protocol configuration."""
    name: str
    chain: str
    contract_address: str
    protocol_type: str  # dex, lending, yield, bridge
    version: str
    is_us_compliant: bool
    risk_level: str  # low, medium, high
    tvl_usd: float

@dataclass
class LiquidityPool:
    """Liquidity pool data structure."""
    pool_address: str
    protocol: str
    chain: str
    token0: str
    token1: str
    reserve0: float
    reserve1: float
    fee_rate: float
    tvl_usd: float
    apr: float
    volume_24h: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LendingPosition:
    """Lending position data structure."""
    protocol: str
    chain: str
    user_address: str
    token: str
    supplied_amount: float
    borrowed_amount: float
    supply_rate: float
    borrow_rate: float
    collateral_factor: float
    health_factor: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class YieldOpportunity:
    """Yield farming opportunity data structure."""
    protocol: str
    chain: str
    pool_address: str
    token: str
    apr: float
    tvl_usd: float
    risk_level: str
    lock_period: int
    min_amount: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class DeFiIntegration:
    """
    Unified DeFi protocol integration layer.
    
    Provides standardized access to major DeFi protocols with
    US-compliant configuration and comprehensive risk assessment.
    """
    
    def __init__(self, blockchain_connector: BlockchainConnector, config: Dict[str, Any]):
        self.blockchain_connector = blockchain_connector
        self.config = config
        
        # Protocol configurations (US-compliant mainnets)
        self.protocols = {
            # DEX protocols
            "uniswap_v2": ProtocolConfig(
                name="Uniswap V2",
                chain="ethereum",
                contract_address="0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
                protocol_type="dex",
                version="2.0",
                is_us_compliant=True,
                risk_level="medium",
                tvl_usd=3000000000
            ),
            "uniswap_v3": ProtocolConfig(
                name="Uniswap V3",
                chain="ethereum",
                contract_address="0xE592427A0AEce92De3Edee1F18E0157C05861564",
                protocol_type="dex",
                version="3.0",
                is_us_compliant=True,
                risk_level="medium",
                tvl_usd=5000000000
            ),
            "curve": ProtocolConfig(
                name="Curve Finance",
                chain="ethereum",
                contract_address="0x8eB8f3e564ed34C704D0A1C4F19aC4F5Ff863965",
                protocol_type="dex",
                version="1.0",
                is_us_compliant=True,
                risk_level="low",
                tvl_usd=2000000000
            ),
            "sushiswap": ProtocolConfig(
                name="SushiSwap",
                chain="ethereum",
                contract_address="0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F",
                protocol_type="dex",
                version="1.0",
                is_us_compliant=True,
                risk_level="medium",
                tvl_usd=500000000
            ),
            
            # Lending protocols
            "aave": ProtocolConfig(
                name="Aave",
                chain="ethereum",
                contract_address="0x7d2768dE32b0b80b7a3454C06BdAc94A69DDc7A9",
                protocol_type="lending",
                version="2.0",
                is_us_compliant=True,
                risk_level="medium",
                tvl_usd=8000000000
            ),
            "compound": ProtocolConfig(
                name="Compound",
                chain="ethereum",
                contract_address="0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
                protocol_type="lending",
                version="2.0",
                is_us_compliant=True,
                risk_level="medium",
                tvl_usd=2000000000
            ),
            
            # Yield protocols
            "yearn_finance": ProtocolConfig(
                name="Yearn Finance",
                chain="ethereum",
                contract_address="0x01856552841e79769F5E0820C64553234d902329",
                protocol_type="yield",
                version="2.0",
                is_us_compliant=True,
                risk_level="medium",
                tvl_usd=1000000000
            )
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "only_us_compliant": True,
            "max_risk_level": "medium",
            "min_tvl_usd": 1000000,  # $1M minimum TVL
            "require_audit": True
        })
        
        # Data storage
        self.liquidity_pools: Dict[str, LiquidityPool] = {}
        self.lending_positions: Dict[str, List[LendingPosition]] = {}
        self.yield_opportunities: List[YieldOpportunity] = []
        
        # Performance metrics
        self.api_calls: Dict[str, int] = {}
        self.last_update: float = 0
        
        logger.info(f"DeFiIntegration initialized with {len(self.protocols)} protocols")
    
    async def initialize_protocols(self) -> Dict[str, bool]:
        """Initialize all supported DeFi protocols."""
        results = {}
        
        for protocol_id, protocol_config in self.protocols.items():
            try:
                # US compliance check
                if self.us_compliance["only_us_compliant"] and not protocol_config.is_us_compliant:
                    logger.info(f"Skipping non-US compliant protocol: {protocol_id}")
                    results[protocol_id] = False
                    continue
                
                if self.us_compliance["max_risk_level"] and protocol_config.risk_level == "high":
                    logger.info(f"Skipping high-risk protocol: {protocol_id}")
                    results[protocol_id] = False
                    continue
                
                # Check minimum TVL
                if protocol_config.tvl_usd < self.us_compliance["min_tvl_usd"]:
                    logger.info(f"Skipping low-TVL protocol: {protocol_id}")
                    results[protocol_id] = False
                    continue
                
                # Simulate protocol initialization
                await asyncio.sleep(0.1)
                
                # Initialize protocol-specific data
                if protocol_config.protocol_type == "dex":
                    await self._initialize_dex_protocol(protocol_id, protocol_config)
                elif protocol_config.protocol_type == "lending":
                    await self._initialize_lending_protocol(protocol_id, protocol_config)
                elif protocol_config.protocol_type == "yield":
                    await self._initialize_yield_protocol(protocol_id, protocol_config)
                
                results[protocol_id] = True
                logger.info(f"Initialized protocol: {protocol_id}")
                
            except Exception as e:
                logger.error(f"Failed to initialize protocol {protocol_id}: {e}")
                results[protocol_id] = False
        
        self.last_update = time.time()
        return results
    
    async def get_liquidity_pools(self, protocol_id: Optional[str] = None) -> List[LiquidityPool]:
        """Get liquidity pools from protocols."""
        pools = []
        
        protocols_to_check = [protocol_id] if protocol_id else list(self.protocols.keys())
        
        for pid in protocols_to_check:
            if pid not in self.protocols:
                continue
            
            protocol = self.protocols[pid]
            
            if protocol.protocol_type != "dex":
                continue
            
            try:
                # Get pools for this protocol
                protocol_pools = await self._get_dex_pools(pid, protocol)
                pools.extend(protocol_pools)
                
                self.api_calls[pid] = self.api_calls.get(pid, 0) + 1
                
            except Exception as e:
                logger.error(f"Failed to get pools for {pid}: {e}")
        
        return pools
    
    async def get_lending_positions(self, user_address: str, protocol_id: Optional[str] = None) -> List[LendingPosition]:
        """Get lending positions for a user."""
        positions = []
        
        protocols_to_check = [protocol_id] if protocol_id else list(self.protocols.keys())
        
        for pid in protocols_to_check:
            if pid not in self.protocols:
                continue
            
            protocol = self.protocols[pid]
            
            if protocol.protocol_type != "lending":
                continue
            
            try:
                # Get positions for this user
                user_positions = await self._get_lending_positions(pid, protocol, user_address)
                positions.extend(user_positions)
                
                self.api_calls[pid] = self.api_calls.get(pid, 0) + 1
                
            except Exception as e:
                logger.error(f"Failed to get positions for {pid}: {e}")
        
        return positions
    
    async def get_yield_opportunities(self, min_apr: float = 0.01) -> List[YieldOpportunity]:
        """Get yield farming opportunities."""
        opportunities = []
        
        for protocol_id, protocol in self.protocols.items():
            if protocol.protocol_type != "yield":
                continue
            
            try:
                # Get opportunities for this protocol
                protocol_opportunities = await self._get_yield_opportunities(protocol_id, protocol, min_apr)
                opportunities.extend(protocol_opportunities)
                
                self.api_calls[protocol_id] = self.api_calls.get(protocol_id, 0) + 1
                
            except Exception as e:
                logger.error(f"Failed to get opportunities for {protocol_id}: {e}")
        
        # Sort by APR (highest first)
        opportunities.sort(key=lambda x: x.apr, reverse=True)
        
        return opportunities
    
    async def execute_swap(self, protocol_id: str, token_in: str, token_out: str, 
                          amount_in: float, user_address: str) -> Optional[Dict[str, Any]]:
        """Execute a token swap on a DEX protocol."""
        if protocol_id not in self.protocols:
            return None
        
        protocol = self.protocols[protocol_id]
        
        if protocol.protocol_type != "dex":
            logger.error(f"Protocol {protocol_id} is not a DEX")
            return None
        
        try:
            # US compliance check
            if not self._check_swap_compliance(token_in, token_out, amount_in):
                logger.warning(f"Swap failed compliance check")
                return None
            
            # Simulate swap execution
            await asyncio.sleep(0.2)
            
            # Mock swap result
            amount_out = amount_in * 0.98  # 2% slippage
            gas_used = 150000 + hash(token_in + token_out) % 50000
            tx_hash = f"0x{hash(str(amount_in) + token_in + token_out) % (16**64):064x}"
            
            result = {
                "protocol_id": protocol_id,
                "token_in": token_in,
                "token_out": token_out,
                "amount_in": amount_in,
                "amount_out": amount_out,
                "user_address": user_address,
                "tx_hash": tx_hash,
                "gas_used": gas_used,
                "timestamp": time.time(),
                "success": True
            }
            
            logger.info(f"Executed swap on {protocol_id}: {amount_in} {token_in} -> {amount_out} {token_out}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute swap on {protocol_id}: {e}")
            return None
    
    async def supply_to_lending(self, protocol_id: str, token: str, amount: float, 
                               user_address: str) -> Optional[Dict[str, Any]]:
        """Supply tokens to a lending protocol."""
        if protocol_id not in self.protocols:
            return None
        
        protocol = self.protocols[protocol_id]
        
        if protocol.protocol_type != "lending":
            logger.error(f"Protocol {protocol_id} is not a lending protocol")
            return None
        
        try:
            # US compliance check
            if not self._check_lending_compliance(token, amount):
                logger.warning(f"Lending supply failed compliance check")
                return None
            
            # Simulate supply execution
            await asyncio.sleep(0.3)
            
            # Mock supply result
            supply_rate = 0.05 + hash(token) % 1000 / 10000  # 5-15% APY
            tx_hash = f"0x{hash(str(amount) + token + user_address) % (16**64):064x}"
            
            result = {
                "protocol_id": protocol_id,
                "token": token,
                "amount": amount,
                "user_address": user_address,
                "supply_rate": supply_rate,
                "tx_hash": tx_hash,
                "timestamp": time.time(),
                "success": True
            }
            
            logger.info(f"Supplied {amount} {token} to {protocol_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to supply to {protocol_id}: {e}")
            return None
    
    async def _initialize_dex_protocol(self, protocol_id: str, protocol: ProtocolConfig):
        """Initialize a DEX protocol."""
        # Mock pool initialization
        mock_pools = [
            ("ETH", "USDC", 1000000, 2000000000),
            ("ETH", "USDT", 800000, 1600000000),
            ("WBTC", "USDC", 50000, 2500000000),
            ("ETH", "WBTC", 30000, 900000000)
        ]
        
        for token0, token1, reserve0, reserve1 in mock_pools:
            pool_id = f"{protocol_id}_{token0}_{token1}"
            
            pool = LiquidityPool(
                pool_address=f"0x{hash(pool_id) % (16**40):040x}",
                protocol=protocol_id,
                chain=protocol.chain,
                token0=token0,
                token1=token1,
                reserve0=reserve0,
                reserve1=reserve1,
                fee_rate=0.003 if "uniswap" in protocol_id else 0.004,
                tvl_usd=(reserve0 * 3000 + reserve1) if token0 == "ETH" else (reserve0 * 45000 + reserve1),
                apr=0.05 + hash(pool_id) % 1000 / 10000,  # 5-15% APR
                volume_24h=reserve0 * 0.1,  # 10% of reserves
                metadata={
                    "protocol_name": protocol.name,
                    "version": protocol.version
                }
            )
            
            self.liquidity_pools[pool_id] = pool
    
    async def _initialize_lending_protocol(self, protocol_id: str, protocol: ProtocolConfig):
        """Initialize a lending protocol."""
        # Mock initialization - no specific data needed for now
        pass
    
    async def _initialize_yield_protocol(self, protocol_id: str, protocol: ProtocolConfig):
        """Initialize a yield protocol."""
        # Mock yield opportunities
        mock_opportunities = [
            ("USDC", 0.08, 50000000),
            ("USDT", 0.075, 30000000),
            ("ETH", 0.06, 20000000),
            ("WBTC", 0.055, 15000000)
        ]
        
        for token, apr, tvl in mock_opportunities:
            opportunity = YieldOpportunity(
                protocol=protocol_id,
                chain=protocol.chain,
                pool_address=f"0x{hash(protocol_id + token) % (16**40):040x}",
                token=token,
                apr=apr,
                tvl_usd=tvl,
                risk_level=protocol.risk_level,
                lock_period=0,  # No lock period
                min_amount=1000,  # $1000 minimum
                metadata={
                    "protocol_name": protocol.name,
                    "version": protocol.version
                }
            )
            
            self.yield_opportunities.append(opportunity)
    
    async def _get_dex_pools(self, protocol_id: str, protocol: ProtocolConfig) -> List[LiquidityPool]:
        """Get pools for a DEX protocol."""
        return [pool for pool_id, pool in self.liquidity_pools.items() if pool.protocol == protocol_id]
    
    async def _get_lending_positions(self, protocol_id: str, protocol: ProtocolConfig, 
                                    user_address: str) -> List[LendingPosition]:
        """Get lending positions for a user."""
        # Mock positions
        if hash(user_address) % 3 == 0:  # 33% of users have positions
            return [
                LendingPosition(
                    protocol=protocol_id,
                    chain=protocol.chain,
                    user_address=user_address,
                    token="USDC",
                    supplied_amount=hash(user_address) % 100000,
                    borrowed_amount=0,
                    supply_rate=0.08,
                    borrow_rate=0.10,
                    collateral_factor=0.8,
                    health_factor=2.5,
                    metadata={
                        "protocol_name": protocol.name
                    }
                )
            ]
        
        return []
    
    async def _get_yield_opportunities(self, protocol_id: str, protocol: ProtocolConfig, 
                                     min_apr: float) -> List[YieldOpportunity]:
        """Get yield opportunities for a protocol."""
        return [opp for opp in self.yield_opportunities 
                if opp.protocol == protocol_id and opp.apr >= min_apr]
    
    def _check_swap_compliance(self, token_in: str, token_out: str, amount: float) -> bool:
        """Check if swap complies with US regulations."""
        # Simple compliance checks
        if amount > 1000000:  # $1M max
            return False
        
        # Check against blacklisted tokens (mock)
        blacklisted_tokens = ["TORN", "BAD_TOKEN"]
        if token_in in blacklisted_tokens or token_out in blacklisted_tokens:
            return False
        
        return True
    
    def _check_lending_compliance(self, token: str, amount: float) -> bool:
        """Check if lending complies with US regulations."""
        # Simple compliance checks
        if amount > 500000:  # $500K max
            return False
        
        # Check against blacklisted tokens
        blacklisted_tokens = ["TORN", "BAD_TOKEN"]
        if token in blacklisted_tokens:
            return False
        
        return True
    
    def get_protocol_summary(self) -> Dict[str, Any]:
        """Get summary of all DeFi protocols."""
        connected_protocols = [pid for pid, config in self.protocols.items() 
                              if config.is_us_compliant and 
                              config.risk_level != "high" and 
                              config.tvl_usd >= self.us_compliance["min_tvl_usd"]]
        
        total_tvl = sum(config.tvl_usd for pid, config in self.protocols.items() if pid in connected_protocols)
        
        return {
            "total_protocols": len(self.protocols),
            "connected_protocols": len(connected_protocols),
            "protocol_types": {
                "dex": len([p for p in self.protocols.values() if p.protocol_type == "dex"]),
                "lending": len([p for p in self.protocols.values() if p.protocol_type == "lending"]),
                "yield": len([p for p in self.protocols.values() if p.protocol_type == "yield"])
            },
            "total_tvl_usd": total_tvl,
            "liquidity_pools": len(self.liquidity_pools),
            "yield_opportunities": len(self.yield_opportunities),
            "api_calls": self.api_calls,
            "last_update": self.last_update,
            "us_compliance": self.us_compliance
        }
    
    def get_supported_protocols(self) -> List[Dict[str, Any]]:
        """Get list of supported DeFi protocols."""
        return [
            {
                "protocol_id": pid,
                "name": config.name,
                "chain": config.chain,
                "type": config.protocol_type,
                "version": config.version,
                "tvl_usd": config.tvl_usd,
                "risk_level": config.risk_level,
                "is_us_compliant": config.is_us_compliant
            }
            for pid, config in self.protocols.items()
        ]
