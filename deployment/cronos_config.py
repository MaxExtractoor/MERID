"""
Cronos deployment configuration for MERID.

Supports:
- Cronos EVM (L1-style, CRO gas)
- Cronos zkEVM (L2, zkCRO gas)
- Multi-chain deployment management
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class CronosChain(Enum):
    """Cronos chain types."""
    CRONOS_EVM_TESTNET = "cronos_evm_testnet"
    CRONOS_EVM_MAINNET = "cronos_evm_mainnet"
    CRONOS_ZKEVM_TESTNET = "cronos_zkevm_testnet"
    CRONOS_ZKEVM_MAINNET = "cronos_zkevm_mainnet"


class DeploymentStatus(Enum):
    """Deployment status."""
    PENDING = "pending"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    VERIFIED = "verified"
    FAILED = "failed"


@dataclass
class ChainConfig:
    """Chain configuration."""
    chain: CronosChain
    
    # Network details
    chain_id: int
    rpc_url: str
    explorer_url: str
    
    # Gas configuration
    gas_token: str
    avg_gas_price_gwei: Decimal
    avg_gas_cost_usd: Decimal
    
    # Limits
    min_trade_size_usd: Decimal
    max_gas_per_tx_usd: Decimal
    
    # Features
    supports_erc4626: bool = True
    supports_multicall: bool = True
    block_time_seconds: float = 2.0
    
    # Metadata
    description: str = ""


@dataclass
class ContractDeployment:
    """Contract deployment record."""
    deployment_id: str
    
    # Contract details
    contract_name: str
    contract_address: str
    chain: CronosChain
    
    # Deployment
    deployer_address: str
    deployment_tx: str
    deployment_block: int
    
    # Verification
    verified: bool = False
    verification_url: str = ""
    
    # Gas
    gas_used: int = 0
    gas_cost_usd: Decimal = Decimal("0.0")
    
    # Status
    status: DeploymentStatus = DeploymentStatus.DEPLOYED
    
    deployed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BridgeConfig:
    """Cross-chain bridge configuration."""
    bridge_id: str
    
    # Chains
    source_chain: CronosChain
    target_chain: CronosChain
    
    # Contracts
    source_contract: str
    target_contract: str
    
    # Security
    multisig_address: str
    required_signatures: int
    total_signers: int
    
    # Limits
    min_bridge_amount: Decimal
    max_bridge_amount: Decimal
    daily_limit: Decimal
    
    # Fees
    bridge_fee_percentage: Decimal
    
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


class CronosDeploymentManager:
    """
    Cronos deployment manager for MERID.
    
    Features:
    - Multi-chain configuration
    - Contract deployment tracking
    - Bridge management
    - Gas cost monitoring
    """
    
    def __init__(self):
        self._chain_configs: Dict[CronosChain, ChainConfig] = {}
        self._deployments: List[ContractDeployment] = []
        self._bridges: Dict[str, BridgeConfig] = {}
        
        self._initialize_chains()
    
    def _initialize_chains(self) -> None:
        """Initialize chain configurations."""
        
        # Cronos EVM Testnet
        self.register_chain(
            chain=CronosChain.CRONOS_EVM_TESTNET,
            chain_id=338,
            rpc_url="https://evm-t3.cronos.org",
            explorer_url="https://cronos.org/explorer/testnet3",
            gas_token="TCRO",
            avg_gas_price_gwei=Decimal("5000"),  # 5000 gwei
            avg_gas_cost_usd=Decimal("0.15"),
            min_trade_size_usd=Decimal("10.0"),
            max_gas_per_tx_usd=Decimal("0.20"),
            description="Cronos EVM testnet for development",
        )
        
        # Cronos EVM Mainnet
        self.register_chain(
            chain=CronosChain.CRONOS_EVM_MAINNET,
            chain_id=25,
            rpc_url="https://evm.cronos.org",
            explorer_url="https://cronos.org/explorer",
            gas_token="CRO",
            avg_gas_price_gwei=Decimal("5000"),
            avg_gas_cost_usd=Decimal("0.15"),
            min_trade_size_usd=Decimal("20.0"),
            max_gas_per_tx_usd=Decimal("0.20"),
            description="Cronos EVM mainnet - primary liquidity hub",
        )
        
        # Cronos zkEVM Testnet
        self.register_chain(
            chain=CronosChain.CRONOS_ZKEVM_TESTNET,
            chain_id=282,
            rpc_url="https://testnet.zkevm.cronos.org",
            explorer_url="https://explorer-testnet.zkevm.cronos.org",
            gas_token="zkTCRO",
            avg_gas_price_gwei=Decimal("1000"),  # 1000 gwei
            avg_gas_cost_usd=Decimal("0.05"),
            min_trade_size_usd=Decimal("5.0"),
            max_gas_per_tx_usd=Decimal("0.10"),
            description="Cronos zkEVM testnet for AI-heavy development",
        )
        
        # Cronos zkEVM Mainnet
        self.register_chain(
            chain=CronosChain.CRONOS_ZKEVM_MAINNET,
            chain_id=388,
            rpc_url="https://mainnet.zkevm.cronos.org",
            explorer_url="https://explorer.zkevm.cronos.org",
            gas_token="zkCRO",
            avg_gas_price_gwei=Decimal("1000"),
            avg_gas_cost_usd=Decimal("0.05"),
            min_trade_size_usd=Decimal("5.0"),
            max_gas_per_tx_usd=Decimal("0.10"),
            description="Cronos zkEVM mainnet - micro-capital and AI agents",
        )
        
        logger.info(f"Initialized {len(self._chain_configs)} Cronos chain configs")
    
    def register_chain(
        self,
        chain: CronosChain,
        chain_id: int,
        rpc_url: str,
        explorer_url: str,
        gas_token: str,
        avg_gas_price_gwei: Decimal,
        avg_gas_cost_usd: Decimal,
        min_trade_size_usd: Decimal,
        max_gas_per_tx_usd: Decimal,
        description: str,
    ) -> ChainConfig:
        """Register chain configuration."""
        config = ChainConfig(
            chain=chain,
            chain_id=chain_id,
            rpc_url=rpc_url,
            explorer_url=explorer_url,
            gas_token=gas_token,
            avg_gas_price_gwei=avg_gas_price_gwei,
            avg_gas_cost_usd=avg_gas_cost_usd,
            min_trade_size_usd=min_trade_size_usd,
            max_gas_per_tx_usd=max_gas_per_tx_usd,
            description=description,
        )
        
        self._chain_configs[chain] = config
        
        logger.info(f"Registered chain '{chain.value}': chain_id={chain_id}")
        
        return config
    
    def get_chain_config(self, chain: CronosChain) -> Optional[ChainConfig]:
        """Get chain configuration."""
        return self._chain_configs.get(chain)
    
    def record_deployment(
        self,
        contract_name: str,
        contract_address: str,
        chain: CronosChain,
        deployer_address: str,
        deployment_tx: str,
        deployment_block: int,
        gas_used: int,
    ) -> ContractDeployment:
        """Record contract deployment."""
        deployment_id = f"deploy_{chain.value}_{contract_name}_{int(datetime.utcnow().timestamp())}"
        
        # Calculate gas cost
        chain_config = self.get_chain_config(chain)
        gas_cost_usd = chain_config.avg_gas_cost_usd if chain_config else Decimal("0.0")
        
        deployment = ContractDeployment(
            deployment_id=deployment_id,
            contract_name=contract_name,
            contract_address=contract_address,
            chain=chain,
            deployer_address=deployer_address,
            deployment_tx=deployment_tx,
            deployment_block=deployment_block,
            gas_used=gas_used,
            gas_cost_usd=gas_cost_usd,
            status=DeploymentStatus.DEPLOYED,
        )
        
        self._deployments.append(deployment)
        
        logger.info(
            f"Recorded deployment '{contract_name}' on {chain.value}: "
            f"{contract_address} (gas: ${gas_cost_usd:.2f})"
        )
        
        return deployment
    
    def mark_verified(
        self,
        deployment_id: str,
        verification_url: str,
    ) -> None:
        """Mark deployment as verified."""
        deployment = self._get_deployment(deployment_id)
        
        if not deployment:
            logger.warning(f"Deployment '{deployment_id}' not found")
            return
        
        deployment.verified = True
        deployment.verification_url = verification_url
        deployment.status = DeploymentStatus.VERIFIED
        
        logger.info(f"Marked deployment '{deployment_id}' as verified")
    
    def _get_deployment(self, deployment_id: str) -> Optional[ContractDeployment]:
        """Get deployment by ID."""
        for deployment in self._deployments:
            if deployment.deployment_id == deployment_id:
                return deployment
        return None
    
    def register_bridge(
        self,
        source_chain: CronosChain,
        target_chain: CronosChain,
        source_contract: str,
        target_contract: str,
        multisig_address: str,
        required_signatures: int,
        total_signers: int,
        min_bridge_amount: Decimal,
        max_bridge_amount: Decimal,
        daily_limit: Decimal,
        bridge_fee_percentage: Decimal,
    ) -> BridgeConfig:
        """Register cross-chain bridge."""
        bridge_id = f"bridge_{source_chain.value}_{target_chain.value}"
        
        bridge = BridgeConfig(
            bridge_id=bridge_id,
            source_chain=source_chain,
            target_chain=target_chain,
            source_contract=source_contract,
            target_contract=target_contract,
            multisig_address=multisig_address,
            required_signatures=required_signatures,
            total_signers=total_signers,
            min_bridge_amount=min_bridge_amount,
            max_bridge_amount=max_bridge_amount,
            daily_limit=daily_limit,
            bridge_fee_percentage=bridge_fee_percentage,
        )
        
        self._bridges[bridge_id] = bridge
        
        logger.info(
            f"Registered bridge '{bridge_id}': "
            f"{required_signatures}-of-{total_signers} multisig"
        )
        
        return bridge
    
    def get_hardhat_config(self) -> Dict[str, Any]:
        """Generate Hardhat configuration."""
        networks = {}
        
        for chain, config in self._chain_configs.items():
            network_name = chain.value.replace("_", "")
            
            networks[network_name] = {
                "url": config.rpc_url,
                "chainId": config.chain_id,
                "accounts": "${process.env.DEPLOYER_PK}",
                "gasPrice": int(config.avg_gas_price_gwei),
            }
        
        hardhat_config = {
            "solidity": {
                "version": "0.8.24",
                "settings": {
                    "optimizer": {
                        "enabled": True,
                        "runs": 200,
                    },
                },
            },
            "networks": networks,
        }
        
        return hardhat_config
    
    def get_deployment_stats(self) -> Dict[str, Any]:
        """Get deployment statistics."""
        
        # Deployments by chain
        deployments_by_chain = {}
        for chain in CronosChain:
            count = sum(1 for d in self._deployments if d.chain == chain)
            deployments_by_chain[chain.value] = count
        
        # Verification rate
        verified_count = sum(1 for d in self._deployments if d.verified)
        verification_rate = (
            verified_count / len(self._deployments)
            if self._deployments else 0.0
        )
        
        # Total gas cost
        total_gas_cost = sum(d.gas_cost_usd for d in self._deployments)
        
        # Bridge stats
        active_bridges = sum(1 for b in self._bridges.values() if b.enabled)
        
        return {
            "chains": {
                "total": len(self._chain_configs),
                "configs": [c.value for c in self._chain_configs.keys()],
            },
            "deployments": {
                "total": len(self._deployments),
                "by_chain": deployments_by_chain,
                "verified": verified_count,
                "verification_rate": verification_rate,
                "total_gas_cost_usd": float(total_gas_cost),
            },
            "bridges": {
                "total": len(self._bridges),
                "active": active_bridges,
            },
        }


_cronos_deployment_manager: Optional[CronosDeploymentManager] = None


def get_cronos_deployment_manager() -> CronosDeploymentManager:
    """Get global CronosDeploymentManager instance."""
    global _cronos_deployment_manager
    if _cronos_deployment_manager is None:
        _cronos_deployment_manager = CronosDeploymentManager()
    return _cronos_deployment_manager
