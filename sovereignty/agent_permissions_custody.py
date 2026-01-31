"""
Agent permissions, key custody, and safeguards for MERID.

Treats agents as untrusted but powerful tools operating under strict
on-chain and off-chain policy. Implements read-only defaults, proposal-based
execution, secure key custody, deployment safeguards, and anti-rug protection.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class AgentPermissionLevel(Enum):
    """Agent permission level."""
    READ_ONLY = "read_only"
    PROPOSE = "propose"
    EXECUTE_BOUNDED = "execute_bounded"
    EXECUTE_GOVERNED = "execute_governed"
    ADMIN = "admin"


class WalletType(Enum):
    """Wallet type for agents."""
    SMART_CONTRACT = "smart_contract"
    POLICY_WALLET = "policy_wallet"
    INTENT_CONTRACT = "intent_contract"
    MPC_WALLET = "mpc_wallet"
    MULTISIG = "multisig"
    BOUNDED_EOA = "bounded_eoa"


class ActionType(Enum):
    """Agent action type."""
    READ_DATA = "read_data"
    PROPOSE_TRADE = "propose_trade"
    PROPOSE_STRATEGY = "propose_strategy"
    PROPOSE_TOKEN = "propose_token"
    PROPOSE_DEPLOYMENT = "propose_deployment"
    EXECUTE_TRADE = "execute_trade"
    DEPLOY_CONTRACT = "deploy_contract"
    MINT_TOKEN = "mint_token"
    WITHDRAW_LIQUIDITY = "withdraw_liquidity"
    CHANGE_PARAMETERS = "change_parameters"


class ApprovalStatus(Enum):
    """Approval status for agent actions."""
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    HUMAN_APPROVED = "human_approved"
    DAO_APPROVED = "dao_approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass
class AgentPermissions:
    """Agent permission definition."""
    agent_id: str
    permission_level: AgentPermissionLevel
    
    # Read permissions
    can_read_onchain_data: bool = True
    can_read_market_data: bool = True
    can_read_governance: bool = True
    
    # Proposal permissions
    can_propose_trades: bool = False
    can_propose_strategies: bool = False
    can_propose_tokens: bool = False
    can_propose_deployments: bool = False
    
    # Execution permissions (bounded)
    can_execute_trades: bool = False
    max_trade_size_usd: Optional[Decimal] = None
    max_daily_volume_usd: Optional[Decimal] = None
    
    can_deploy_contracts: bool = False
    allowed_factories: Set[str] = field(default_factory=set)
    
    # Wallet access
    wallet_type: Optional[WalletType] = None
    wallet_address: Optional[str] = None
    max_wallet_balance_usd: Optional[Decimal] = None
    
    # Restrictions
    allowed_assets: Set[str] = field(default_factory=set)
    allowed_venues: Set[str] = field(default_factory=set)
    blocked_actions: Set[ActionType] = field(default_factory=set)
    
    # Governance
    requires_human_approval: bool = True
    requires_dao_approval: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentWallet:
    """Agent wallet definition (no private keys stored)."""
    wallet_id: str
    agent_id: str
    wallet_type: WalletType
    address: str
    
    # Custody
    key_custody_service: str  # "mpc", "multisig", "policy_engine"
    signing_endpoint: str  # Isolated signing service
    
    # Limits
    max_balance_usd: Decimal
    max_transaction_usd: Decimal
    max_daily_volume_usd: Decimal
    
    # Current state
    current_balance_usd: Decimal = Decimal("0")
    daily_volume_usd: Decimal = Decimal("0")
    
    # Policy
    policy_contract_address: Optional[str] = None
    requires_policy_check: bool = True
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None


@dataclass
class AgentProposal:
    """Agent-generated proposal requiring approval."""
    proposal_id: str
    agent_id: str
    action_type: ActionType
    
    # Proposal details
    description: str
    parameters: Dict[str, Any]
    estimated_value_usd: Decimal
    estimated_risk_score: float
    
    # Transaction bundle
    transactions: List[Dict[str, Any]] = field(default_factory=list)
    
    # Approval
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    requires_human: bool = True
    requires_dao: bool = False
    
    # Review
    approved_by: Optional[str] = None
    approval_timestamp: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    
    # Execution
    executed: bool = False
    execution_timestamp: Optional[datetime] = None
    transaction_hashes: List[str] = field(default_factory=list)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentAuditLog:
    """Comprehensive audit log for agent actions."""
    log_id: str
    agent_id: str
    action_type: ActionType
    
    # Agent context
    agent_role: str
    agent_version: str
    agent_configuration: Dict[str, Any]
    
    # Action details
    wallet_address: Optional[str] = None
    contract_address: Optional[str] = None
    function_signature: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Value and gas
    estimated_value_usd: Optional[Decimal] = None
    actual_value_usd: Optional[Decimal] = None
    estimated_gas: Optional[int] = None
    actual_gas: Optional[int] = None
    
    # Environment
    environment: str = "live"  # sim/paper/live
    approval_path: str = "auto"  # auto/guarded/dao
    
    # On-chain correlation
    transaction_hash: Optional[str] = None
    block_number: Optional[int] = None
    
    # Rationale
    agent_rationale: Optional[str] = None
    
    # Timestamps
    timestamp: datetime = field(default_factory=datetime.utcnow)
    execution_timestamp: Optional[datetime] = None


@dataclass
class TokenDeploymentRequest:
    """Agent request to deploy a token."""
    request_id: str
    agent_id: str
    
    # Token parameters
    token_name: str
    token_symbol: str
    total_supply: Decimal
    decimals: int
    
    # Factory
    factory_address: str
    factory_type: str  # "erc20", "erc4626", "erc721"
    
    # Safeguards
    has_minting_cap: bool = True
    has_vesting: bool = False
    vesting_duration_days: Optional[int] = None
    has_admin_limits: bool = True
    
    # Liquidity
    initial_liquidity_usd: Optional[Decimal] = None
    liquidity_lock_days: Optional[int] = None
    
    # Approval
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    dao_approved: bool = False
    council_approved: bool = False
    
    # Risk assessment
    rug_risk_score: float = 0.0
    rug_risk_flags: List[str] = field(default_factory=list)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class AgentPermissionsCustody:
    """
    Agent permissions, key custody, and safeguards for MERID.
    
    Treats agents as untrusted but powerful tools operating under strict
    policy. Implements:
    - Default read-only permissions
    - Proposal-based execution
    - Secure key custody (no raw keys to agents)
    - Contract deployment safeguards
    - Comprehensive audit logging
    - Anti-rug protection for agent-launched tokens
    """
    
    def __init__(self):
        self._agent_permissions: Dict[str, AgentPermissions] = {}
        self._agent_wallets: Dict[str, AgentWallet] = {}
        self._proposals: Dict[str, AgentProposal] = {}
        self._audit_logs: List[AgentAuditLog] = []
        self._token_requests: Dict[str, TokenDeploymentRequest] = {}
        
        self._whitelisted_factories: Set[str] = set()
        self._initialize_default_policies()
    
    def _initialize_default_policies(self) -> None:
        """Initialize default policies."""
        
        # Whitelist audited factory contracts
        self._whitelisted_factories = {
            "erc20_factory_v1",
            "erc4626_vault_factory_v1",
            "erc721_nft_factory_v1",
            "strategy_vault_factory_v1",
        }
        
        logger.info("Initialized default agent policies")
    
    def register_agent_permissions(
        self,
        agent_id: str,
        permission_level: AgentPermissionLevel,
        can_propose_trades: bool = False,
        can_execute_trades: bool = False,
        max_trade_size_usd: Optional[Decimal] = None,
        allowed_assets: Optional[Set[str]] = None,
        allowed_venues: Optional[Set[str]] = None,
    ) -> AgentPermissions:
        """Register agent permissions."""
        
        # Default: read-only
        permissions = AgentPermissions(
            agent_id=agent_id,
            permission_level=permission_level,
            can_read_onchain_data=True,
            can_read_market_data=True,
            can_read_governance=True,
        )
        
        # Proposal permissions
        if permission_level in [AgentPermissionLevel.PROPOSE, AgentPermissionLevel.EXECUTE_BOUNDED, AgentPermissionLevel.EXECUTE_GOVERNED]:
            permissions.can_propose_trades = can_propose_trades
            permissions.can_propose_strategies = True
            permissions.can_propose_tokens = False  # Requires explicit approval
            permissions.can_propose_deployments = False  # Requires explicit approval
        
        # Execution permissions (bounded)
        if permission_level == AgentPermissionLevel.EXECUTE_BOUNDED:
            permissions.can_execute_trades = can_execute_trades
            permissions.max_trade_size_usd = max_trade_size_usd or Decimal("10000")
            permissions.max_daily_volume_usd = max_trade_size_usd * 10 if max_trade_size_usd else Decimal("100000")
            permissions.requires_human_approval = False  # Auto-approved within limits
        
        # Governed execution
        if permission_level == AgentPermissionLevel.EXECUTE_GOVERNED:
            permissions.can_execute_trades = can_execute_trades
            permissions.max_trade_size_usd = max_trade_size_usd or Decimal("100000")
            permissions.max_daily_volume_usd = max_trade_size_usd * 10 if max_trade_size_usd else Decimal("1000000")
            permissions.requires_human_approval = True
            permissions.requires_dao_approval = False
        
        # Restrictions
        permissions.allowed_assets = allowed_assets or set()
        permissions.allowed_venues = allowed_venues or set()
        
        self._agent_permissions[agent_id] = permissions
        
        logger.info(f"Registered permissions for agent '{agent_id}': {permission_level.value}")
        
        return permissions
    
    def create_agent_wallet(
        self,
        agent_id: str,
        wallet_type: WalletType,
        max_balance_usd: Decimal,
        max_transaction_usd: Decimal,
        key_custody_service: str = "mpc",
    ) -> AgentWallet:
        """
        Create agent wallet (NO PRIVATE KEYS STORED).
        
        Wallet signing happens in isolated service.
        """
        wallet_id = f"wallet_{agent_id}_{int(datetime.utcnow().timestamp())}"
        
        wallet = AgentWallet(
            wallet_id=wallet_id,
            agent_id=agent_id,
            wallet_type=wallet_type,
            address=f"0x{wallet_id[:40]}",  # Placeholder
            key_custody_service=key_custody_service,
            signing_endpoint=f"https://signing-service.merid.io/sign/{wallet_id}",
            max_balance_usd=max_balance_usd,
            max_transaction_usd=max_transaction_usd,
            max_daily_volume_usd=max_transaction_usd * Decimal("10"),
            requires_policy_check=True,
        )
        
        self._agent_wallets[wallet_id] = wallet
        
        logger.info(
            f"Created {wallet_type.value} wallet for agent '{agent_id}' "
            f"(max balance: ${max_balance_usd}, custody: {key_custody_service})"
        )
        
        return wallet
    
    def submit_proposal(
        self,
        agent_id: str,
        action_type: ActionType,
        description: str,
        parameters: Dict[str, Any],
        estimated_value_usd: Decimal,
        transactions: Optional[List[Dict[str, Any]]] = None,
    ) -> AgentProposal:
        """Submit agent proposal for approval."""
        
        # Check permissions
        permissions = self._agent_permissions.get(agent_id)
        if not permissions:
            raise ValueError(f"Agent '{agent_id}' not registered")
        
        # Validate action allowed
        if action_type in permissions.blocked_actions:
            raise ValueError(f"Action '{action_type.value}' blocked for agent '{agent_id}'")
        
        # Create proposal
        proposal_id = f"proposal_{agent_id}_{int(datetime.utcnow().timestamp())}"
        
        proposal = AgentProposal(
            proposal_id=proposal_id,
            agent_id=agent_id,
            action_type=action_type,
            description=description,
            parameters=parameters,
            estimated_value_usd=estimated_value_usd,
            estimated_risk_score=self._calculate_risk_score(action_type, estimated_value_usd),
            transactions=transactions or [],
            requires_human=permissions.requires_human_approval,
            requires_dao=permissions.requires_dao_approval,
        )
        
        # Auto-approve if within bounded limits
        if (permissions.permission_level == AgentPermissionLevel.EXECUTE_BOUNDED and
            action_type == ActionType.EXECUTE_TRADE and
            estimated_value_usd <= permissions.max_trade_size_usd):
            proposal.approval_status = ApprovalStatus.AUTO_APPROVED
            proposal.approved_by = "system"
            proposal.approval_timestamp = datetime.utcnow()
        
        self._proposals[proposal_id] = proposal
        
        logger.info(
            f"Agent '{agent_id}' submitted proposal '{proposal_id}': "
            f"{action_type.value} (${estimated_value_usd})"
        )
        
        return proposal
    
    def approve_proposal(
        self,
        proposal_id: str,
        approved_by: str,
        approval_type: str = "human",
    ) -> None:
        """Approve agent proposal."""
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal '{proposal_id}' not found")
        
        if approval_type == "human":
            proposal.approval_status = ApprovalStatus.HUMAN_APPROVED
        elif approval_type == "dao":
            proposal.approval_status = ApprovalStatus.DAO_APPROVED
        
        proposal.approved_by = approved_by
        proposal.approval_timestamp = datetime.utcnow()
        
        logger.info(f"Proposal '{proposal_id}' approved by {approved_by} ({approval_type})")
    
    def reject_proposal(
        self,
        proposal_id: str,
        reason: str,
    ) -> None:
        """Reject agent proposal."""
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal '{proposal_id}' not found")
        
        proposal.approval_status = ApprovalStatus.REJECTED
        proposal.rejection_reason = reason
        
        logger.warning(f"Proposal '{proposal_id}' rejected: {reason}")
    
    def log_agent_action(
        self,
        agent_id: str,
        action_type: ActionType,
        agent_role: str,
        agent_version: str,
        parameters: Dict[str, Any],
        wallet_address: Optional[str] = None,
        transaction_hash: Optional[str] = None,
        agent_rationale: Optional[str] = None,
    ) -> AgentAuditLog:
        """Log agent action for audit trail."""
        
        log_id = f"log_{agent_id}_{int(datetime.utcnow().timestamp())}"
        
        log = AgentAuditLog(
            log_id=log_id,
            agent_id=agent_id,
            action_type=action_type,
            agent_role=agent_role,
            agent_version=agent_version,
            agent_configuration=self._get_agent_config(agent_id),
            wallet_address=wallet_address,
            parameters=parameters,
            transaction_hash=transaction_hash,
            agent_rationale=agent_rationale,
        )
        
        self._audit_logs.append(log)
        
        logger.info(
            f"Logged action for agent '{agent_id}': {action_type.value} "
            f"(tx: {transaction_hash or 'N/A'})"
        )
        
        return log
    
    def request_token_deployment(
        self,
        agent_id: str,
        token_name: str,
        token_symbol: str,
        total_supply: Decimal,
        factory_address: str,
        initial_liquidity_usd: Optional[Decimal] = None,
    ) -> TokenDeploymentRequest:
        """Request token deployment (requires DAO approval)."""
        
        # Check permissions
        permissions = self._agent_permissions.get(agent_id)
        if not permissions or not permissions.can_propose_tokens:
            raise ValueError(f"Agent '{agent_id}' not authorized to propose tokens")
        
        # Check factory whitelisted
        if factory_address not in self._whitelisted_factories:
            raise ValueError(f"Factory '{factory_address}' not whitelisted")
        
        request_id = f"token_{agent_id}_{int(datetime.utcnow().timestamp())}"
        
        request = TokenDeploymentRequest(
            request_id=request_id,
            agent_id=agent_id,
            token_name=token_name,
            token_symbol=token_symbol,
            total_supply=total_supply,
            decimals=18,
            factory_address=factory_address,
            factory_type="erc20",
            has_minting_cap=True,
            has_vesting=True,
            vesting_duration_days=365,
            has_admin_limits=True,
            initial_liquidity_usd=initial_liquidity_usd,
            liquidity_lock_days=180,
        )
        
        # Assess rug risk
        request.rug_risk_score, request.rug_risk_flags = self._assess_rug_risk(request)
        
        self._token_requests[request_id] = request
        
        logger.info(
            f"Agent '{agent_id}' requested token deployment: {token_name} ({token_symbol}) "
            f"(rug risk: {request.rug_risk_score:.2f})"
        )
        
        return request
    
    def _assess_rug_risk(self, request: TokenDeploymentRequest) -> tuple[float, List[str]]:
        """Assess rug-pull risk for token deployment."""
        risk_score = 0.0
        flags = []
        
        # No minting cap
        if not request.has_minting_cap:
            risk_score += 0.3
            flags.append("no_minting_cap")
        
        # No vesting
        if not request.has_vesting:
            risk_score += 0.2
            flags.append("no_vesting")
        
        # No admin limits
        if not request.has_admin_limits:
            risk_score += 0.3
            flags.append("unlimited_admin_powers")
        
        # Large initial liquidity without lock
        if request.initial_liquidity_usd and request.initial_liquidity_usd > 100000:
            if not request.liquidity_lock_days or request.liquidity_lock_days < 90:
                risk_score += 0.2
                flags.append("large_liquidity_no_lock")
        
        return risk_score, flags
    
    def _calculate_risk_score(self, action_type: ActionType, value_usd: Decimal) -> float:
        """Calculate risk score for action."""
        base_risk = {
            ActionType.READ_DATA: 0.0,
            ActionType.PROPOSE_TRADE: 0.1,
            ActionType.EXECUTE_TRADE: 0.3,
            ActionType.DEPLOY_CONTRACT: 0.5,
            ActionType.MINT_TOKEN: 0.6,
            ActionType.WITHDRAW_LIQUIDITY: 0.7,
        }.get(action_type, 0.5)
        
        # Scale by value
        value_risk = min(float(value_usd) / 1000000, 0.3)
        
        return min(base_risk + value_risk, 1.0)
    
    def _get_agent_config(self, agent_id: str) -> Dict[str, Any]:
        """Get agent configuration for logging."""
        permissions = self._agent_permissions.get(agent_id)
        if not permissions:
            return {}
        
        return {
            "permission_level": permissions.permission_level.value,
            "max_trade_size_usd": str(permissions.max_trade_size_usd) if permissions.max_trade_size_usd else None,
            "allowed_assets": list(permissions.allowed_assets),
            "allowed_venues": list(permissions.allowed_venues),
        }
    
    def get_agent_permissions(self, agent_id: str) -> Optional[AgentPermissions]:
        """Get agent permissions."""
        return self._agent_permissions.get(agent_id)
    
    def get_pending_proposals(self, agent_id: Optional[str] = None) -> List[AgentProposal]:
        """Get pending proposals."""
        proposals = [p for p in self._proposals.values() if p.approval_status == ApprovalStatus.PENDING]
        
        if agent_id:
            proposals = [p for p in proposals if p.agent_id == agent_id]
        
        return proposals
    
    def get_audit_logs(
        self,
        agent_id: Optional[str] = None,
        action_type: Optional[ActionType] = None,
        start_time: Optional[datetime] = None,
    ) -> List[AgentAuditLog]:
        """Get audit logs with filters."""
        logs = self._audit_logs
        
        if agent_id:
            logs = [l for l in logs if l.agent_id == agent_id]
        
        if action_type:
            logs = [l for l in logs if l.action_type == action_type]
        
        if start_time:
            logs = [l for l in logs if l.timestamp >= start_time]
        
        return logs
    
    def get_token_requests(self, status: Optional[ApprovalStatus] = None) -> List[TokenDeploymentRequest]:
        """Get token deployment requests."""
        requests = list(self._token_requests.values())
        
        if status:
            requests = [r for r in requests if r.approval_status == status]
        
        return requests
    
    def whitelist_factory(self, factory_address: str) -> None:
        """Whitelist factory contract."""
        self._whitelisted_factories.add(factory_address)
        logger.info(f"Whitelisted factory: {factory_address}")
    
    def get_whitelisted_factories(self) -> Set[str]:
        """Get whitelisted factories."""
        return self._whitelisted_factories.copy()


_agent_permissions_custody: Optional[AgentPermissionsCustody] = None


def get_agent_permissions_custody() -> AgentPermissionsCustody:
    """Get global AgentPermissionsCustody instance."""
    global _agent_permissions_custody
    if _agent_permissions_custody is None:
        _agent_permissions_custody = AgentPermissionsCustody()
    return _agent_permissions_custody
