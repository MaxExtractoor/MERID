"""
Essential on-chain DEX components for MERID.

Defines all on-chain smart contract components required for a sovereign,
decentralized exchange including AMM, perps, vaults, oracles, governance,
and AI control contracts.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ContractType(Enum):
    """Smart contract type."""
    AMM_POOL = "amm_pool"
    ORDER_BOOK = "order_book"
    PERP_MARKET = "perp_market"
    VAULT = "vault"
    MARGIN_ACCOUNT = "margin_account"
    ORACLE = "oracle"
    GOVERNANCE = "governance"
    PARAMETER_REGISTRY = "parameter_registry"
    AI_REGISTRY = "ai_registry"
    AI_POLICY = "ai_policy"
    TREASURY = "treasury"
    REWARD_DISTRIBUTOR = "reward_distributor"
    IDENTITY = "identity"
    ROUTER = "router"
    BRIDGE = "bridge"


class ChainType(Enum):
    """Blockchain type."""
    ETHEREUM_L1 = "ethereum_l1"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    BASE = "base"
    POLYGON = "polygon"
    AVALANCHE = "avalanche"
    BSC = "bsc"


@dataclass
class ContractDefinition:
    """On-chain contract definition."""
    contract_id: str
    name: str
    contract_type: ContractType
    chain: ChainType
    
    # Deployment
    address: Optional[str] = None
    deployed: bool = False
    deployment_date: Optional[datetime] = None
    
    # Governance
    upgradeable: bool = False
    upgrade_controlled_by: str = "dao"  # dao, multisig, immutable
    timelock_hours: int = 48
    
    # Dependencies
    depends_on: List[str] = field(default_factory=list)
    
    # Sovereignty
    open_source: bool = True
    verified: bool = False
    audited: bool = False
    audit_reports: List[str] = field(default_factory=list)
    
    # Description
    description: str = ""
    critical_for_trading: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AIAgentPolicy:
    """AI agent policy stored on-chain."""
    policy_id: str
    agent_id: str
    
    # Capital limits
    max_capital_usd: Optional[int] = None
    max_leverage: Optional[int] = None
    max_position_size_usd: Optional[int] = None
    
    # Asset restrictions
    allowed_assets: Set[str] = field(default_factory=set)
    blocked_assets: Set[str] = field(default_factory=set)
    
    # Venue restrictions
    allowed_venues: Set[str] = field(default_factory=set)
    blocked_venues: Set[str] = field(default_factory=set)
    
    # Behavior restrictions
    allowed_strategies: Set[str] = field(default_factory=set)
    blocked_behaviors: Set[str] = field(default_factory=set)
    
    # Risk limits
    max_drawdown_percent: Optional[int] = None
    max_daily_loss_usd: Optional[int] = None
    
    # Governance
    approved_by_dao: bool = False
    approval_date: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class OnChainDEXComponents:
    """
    Essential on-chain DEX components for MERID.
    
    Manages all smart contract components required for sovereign,
    decentralized exchange operations including trading, liquidity,
    vaults, oracles, governance, and AI control.
    """
    
    def __init__(self):
        self._contracts: Dict[str, ContractDefinition] = {}
        self._ai_policies: Dict[str, AIAgentPolicy] = {}
        
        self._initialize_contracts()
    
    def _initialize_contracts(self) -> None:
        """Initialize contract definitions."""
        
        # === CORE TRADING & LIQUIDITY ===
        
        self.register_contract(
            contract_id="amm_spot_pool",
            name="AMM Spot Pool",
            contract_type=ContractType.AMM_POOL,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            description="Uniswap V3-style AMM for spot crypto, memecoins, xStocks",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="order_book_spot",
            name="Order Book Spot",
            contract_type=ContractType.ORDER_BOOK,
            chain=ChainType.ARBITRUM,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            description="On-chain order book for spot trading with RFQ support",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="perp_market",
            name="Perpetual Futures Market",
            contract_type=ContractType.PERP_MARKET,
            chain=ChainType.ARBITRUM,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["oracle_price_feed", "margin_account"],
            description="Perpetual futures with funding, margin, and liquidation",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="router_aggregator",
            name="Router & Aggregator",
            contract_type=ContractType.ROUTER,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=24,
            depends_on=["amm_spot_pool", "order_book_spot"],
            description="Best-execution router across pools and venues",
            critical_for_trading=True,
        )
        
        # === VAULTS, MARGIN, COLLATERAL ===
        
        self.register_contract(
            contract_id="user_vault",
            name="User Vault",
            contract_type=ContractType.VAULT,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=False,
            upgrade_controlled_by="immutable",
            description="Non-custodial user vault for deposits and withdrawals",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="strategy_vault",
            name="Strategy Vault",
            contract_type=ContractType.VAULT,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["user_vault", "ai_policy"],
            description="Vault for AI strategy capital with policy enforcement",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="margin_account",
            name="Margin Account",
            contract_type=ContractType.MARGIN_ACCOUNT,
            chain=ChainType.ARBITRUM,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["oracle_price_feed"],
            description="Margin/collateral accounts for leverage and perps",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="btc_vault_trustless",
            name="BTC Trustless Vault",
            contract_type=ContractType.VAULT,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=72,
            description="Trust-minimized BTC vault using threshold signatures",
            critical_for_trading=False,
        )
        
        # === ORACLES & DATA ===
        
        self.register_contract(
            contract_id="oracle_price_feed",
            name="Price Oracle Feed",
            contract_type=ContractType.ORACLE,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=24,
            description="Multi-source price oracle with fallback (Chainlink, Pyth, UMA)",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="oracle_prediction_market",
            name="Prediction Market Oracle",
            contract_type=ContractType.ORACLE,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            description="Prediction market resolution oracle",
            critical_for_trading=False,
        )
        
        self.register_contract(
            contract_id="oracle_cross_chain",
            name="Cross-Chain Oracle",
            contract_type=ContractType.ORACLE,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=24,
            depends_on=["bridge_canonical"],
            description="Cross-chain messaging and state verification",
            critical_for_trading=False,
        )
        
        # === GOVERNANCE & PARAMETERS ===
        
        self.register_contract(
            contract_id="dao_governance",
            name="DAO Governance",
            contract_type=ContractType.GOVERNANCE,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=72,
            description="DAO voting and proposal execution",
            critical_for_trading=False,
        )
        
        self.register_contract(
            contract_id="parameter_registry",
            name="Parameter Registry",
            contract_type=ContractType.PARAMETER_REGISTRY,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["dao_governance"],
            description="Registry for risk limits, fees, whitelists, AI policies",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="guardian_multisig",
            name="Guardian Multisig",
            contract_type=ContractType.GOVERNANCE,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=False,
            upgrade_controlled_by="immutable",
            description="Emergency pause multisig with time-locked powers",
            critical_for_trading=False,
        )
        
        # === AI REGISTRY & CONTROL ===
        
        self.register_contract(
            contract_id="ai_agent_registry",
            name="AI Agent Registry",
            contract_type=ContractType.AI_REGISTRY,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["dao_governance"],
            description="Registry of authorized AI agents, strategies, and tools",
            critical_for_trading=True,
        )
        
        self.register_contract(
            contract_id="ai_policy_contract",
            name="AI Policy Contract",
            contract_type=ContractType.AI_POLICY,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["ai_agent_registry", "parameter_registry"],
            description="AI swarm policy enforcement (capital limits, asset/venue permissions)",
            critical_for_trading=True,
        )
        
        # === TREASURY & REWARDS ===
        
        self.register_contract(
            contract_id="dao_treasury",
            name="DAO Treasury",
            contract_type=ContractType.TREASURY,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=72,
            depends_on=["dao_governance"],
            description="DAO treasury with multisig protection",
            critical_for_trading=False,
        )
        
        self.register_contract(
            contract_id="fee_collector",
            name="Fee Collector",
            contract_type=ContractType.TREASURY,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["dao_treasury"],
            description="Protocol fee collection and distribution",
            critical_for_trading=False,
        )
        
        self.register_contract(
            contract_id="reward_distributor",
            name="Reward Distributor",
            contract_type=ContractType.REWARD_DISTRIBUTOR,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            depends_on=["dao_governance"],
            description="Emissions, rewards, vesting, and lockups",
            critical_for_trading=False,
        )
        
        # === IDENTITY & ACCESS ===
        
        self.register_contract(
            contract_id="did_registry",
            name="DID Registry",
            contract_type=ContractType.IDENTITY,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=48,
            description="Decentralized identity (DID/SSI) for KYC attestations",
            critical_for_trading=False,
        )
        
        # === CROSS-CHAIN & BRIDGES ===
        
        self.register_contract(
            contract_id="bridge_canonical",
            name="Canonical Bridge",
            contract_type=ContractType.BRIDGE,
            chain=ChainType.ETHEREUM_L1,
            upgradeable=True,
            upgrade_controlled_by="dao",
            timelock_hours=72,
            description="Trust-minimized canonical bridge for cross-chain swaps",
            critical_for_trading=False,
        )
        
        logger.info(f"Initialized {len(self._contracts)} on-chain contracts")
    
    def register_contract(
        self,
        contract_id: str,
        name: str,
        contract_type: ContractType,
        chain: ChainType,
        upgradeable: bool = False,
        upgrade_controlled_by: str = "dao",
        timelock_hours: int = 48,
        depends_on: Optional[List[str]] = None,
        description: str = "",
        critical_for_trading: bool = False,
    ) -> ContractDefinition:
        """Register contract definition."""
        contract = ContractDefinition(
            contract_id=contract_id,
            name=name,
            contract_type=contract_type,
            chain=chain,
            upgradeable=upgradeable,
            upgrade_controlled_by=upgrade_controlled_by,
            timelock_hours=timelock_hours,
            depends_on=depends_on or [],
            description=description,
            critical_for_trading=critical_for_trading,
        )
        
        self._contracts[contract_id] = contract
        
        return contract
    
    def deploy_contract(
        self,
        contract_id: str,
        address: str,
        verified: bool = False,
        audited: bool = False,
    ) -> None:
        """Mark contract as deployed."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract '{contract_id}' not found")
        
        contract.address = address
        contract.deployed = True
        contract.deployment_date = datetime.utcnow()
        contract.verified = verified
        contract.audited = audited
        
        logger.info(f"Deployed contract '{contract_id}' at {address}")
    
    def register_ai_policy(
        self,
        policy_id: str,
        agent_id: str,
        max_capital_usd: Optional[int] = None,
        max_leverage: Optional[int] = None,
        allowed_assets: Optional[Set[str]] = None,
        allowed_venues: Optional[Set[str]] = None,
        approved_by_dao: bool = False,
    ) -> AIAgentPolicy:
        """Register AI agent policy."""
        policy = AIAgentPolicy(
            policy_id=policy_id,
            agent_id=agent_id,
            max_capital_usd=max_capital_usd,
            max_leverage=max_leverage,
            allowed_assets=allowed_assets or set(),
            allowed_venues=allowed_venues or set(),
            approved_by_dao=approved_by_dao,
        )
        
        self._ai_policies[policy_id] = policy
        
        logger.info(f"Registered AI policy '{policy_id}' for agent '{agent_id}'")
        
        return policy
    
    def get_critical_contracts(self) -> List[ContractDefinition]:
        """Get contracts critical for trading."""
        return [c for c in self._contracts.values() if c.critical_for_trading]
    
    def get_contracts_by_type(self, contract_type: ContractType) -> List[ContractDefinition]:
        """Get contracts by type."""
        return [c for c in self._contracts.values() if c.contract_type == contract_type]
    
    def get_contracts_by_chain(self, chain: ChainType) -> List[ContractDefinition]:
        """Get contracts by chain."""
        return [c for c in self._contracts.values() if c.chain == chain]
    
    def get_undeployed_contracts(self) -> List[ContractDefinition]:
        """Get contracts not yet deployed."""
        return [c for c in self._contracts.values() if not c.deployed]
    
    def get_unaudited_contracts(self) -> List[ContractDefinition]:
        """Get deployed but unaudited contracts."""
        return [c for c in self._contracts.values() if c.deployed and not c.audited]
    
    def get_dao_controlled_contracts(self) -> List[ContractDefinition]:
        """Get contracts controlled by DAO."""
        return [c for c in self._contracts.values() if c.upgrade_controlled_by == "dao"]
    
    def get_contract_dependencies(self, contract_id: str) -> List[ContractDefinition]:
        """Get contract dependencies."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract '{contract_id}' not found")
        
        return [self._contracts[dep_id] for dep_id in contract.depends_on if dep_id in self._contracts]
    
    def validate_deployment_readiness(self, contract_id: str) -> tuple[bool, List[str]]:
        """Validate if contract is ready for deployment."""
        contract = self._contracts.get(contract_id)
        if not contract:
            raise ValueError(f"Contract '{contract_id}' not found")
        
        issues = []
        
        # Check dependencies deployed
        for dep_id in contract.depends_on:
            dep = self._contracts.get(dep_id)
            if not dep or not dep.deployed:
                issues.append(f"Dependency '{dep_id}' not deployed")
        
        # Check open source
        if not contract.open_source:
            issues.append("Contract not open source")
        
        # Check critical contracts are audited
        if contract.critical_for_trading and not contract.audited:
            issues.append("Critical contract not audited")
        
        return len(issues) == 0, issues
    
    def get_deployment_summary(self) -> Dict[str, Any]:
        """Get deployment summary."""
        total = len(self._contracts)
        deployed = sum(1 for c in self._contracts.values() if c.deployed)
        verified = sum(1 for c in self._contracts.values() if c.verified)
        audited = sum(1 for c in self._contracts.values() if c.audited)
        critical = sum(1 for c in self._contracts.values() if c.critical_for_trading)
        critical_deployed = sum(1 for c in self._contracts.values() if c.critical_for_trading and c.deployed)
        
        return {
            "total_contracts": total,
            "deployed": deployed,
            "verified": verified,
            "audited": audited,
            "critical_contracts": critical,
            "critical_deployed": critical_deployed,
            "deployment_percentage": (deployed / total * 100) if total > 0 else 0,
            "critical_deployment_percentage": (critical_deployed / critical * 100) if critical > 0 else 0,
            "by_chain": self._get_deployment_by_chain(),
            "by_type": self._get_deployment_by_type(),
        }
    
    def _get_deployment_by_chain(self) -> Dict[str, Dict[str, int]]:
        """Get deployment stats by chain."""
        stats = {}
        for chain in ChainType:
            contracts = self.get_contracts_by_chain(chain)
            deployed = sum(1 for c in contracts if c.deployed)
            stats[chain.value] = {
                "total": len(contracts),
                "deployed": deployed,
            }
        return stats
    
    def _get_deployment_by_type(self) -> Dict[str, Dict[str, int]]:
        """Get deployment stats by type."""
        stats = {}
        for contract_type in ContractType:
            contracts = self.get_contracts_by_type(contract_type)
            deployed = sum(1 for c in contracts if c.deployed)
            stats[contract_type.value] = {
                "total": len(contracts),
                "deployed": deployed,
            }
        return stats
    
    def get_all_contracts(self) -> List[ContractDefinition]:
        """Get all contracts."""
        return list(self._contracts.values())
    
    def get_contract(self, contract_id: str) -> Optional[ContractDefinition]:
        """Get contract by ID."""
        return self._contracts.get(contract_id)
    
    def get_ai_policy(self, policy_id: str) -> Optional[AIAgentPolicy]:
        """Get AI policy by ID."""
        return self._ai_policies.get(policy_id)
    
    def get_all_ai_policies(self) -> List[AIAgentPolicy]:
        """Get all AI policies."""
        return list(self._ai_policies.values())


_onchain_dex_components: Optional[OnChainDEXComponents] = None


def get_onchain_dex_components() -> OnChainDEXComponents:
    """Get global OnChainDEXComponents instance."""
    global _onchain_dex_components
    if _onchain_dex_components is None:
        _onchain_dex_components = OnChainDEXComponents()
    return _onchain_dex_components
