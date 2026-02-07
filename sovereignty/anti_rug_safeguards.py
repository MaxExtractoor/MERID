"""
Anti-rug safeguards for agent-launched tokens and projects.

Implements detection, prevention, and monitoring of rug-pull patterns
in agent-deployed tokens, liquidity pools, and smart contracts.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class RugPullPattern(Enum):
    """Known rug-pull pattern."""
    IMMEDIATE_LIQUIDITY_DRAIN = "immediate_liquidity_drain"
    LARGE_LIQUIDITY_WITHDRAWAL = "large_liquidity_withdrawal"
    SUDDEN_FEE_INCREASE = "sudden_fee_increase"
    BLACKLIST_TRAP = "blacklist_trap"
    MINT_FLOOD = "mint_flood"
    OWNERSHIP_TRANSFER = "ownership_transfer"
    PROXY_UPGRADE_MALICIOUS = "proxy_upgrade_malicious"
    HONEYPOT_SELL_RESTRICTION = "honeypot_sell_restriction"
    HIDDEN_BACKDOOR = "hidden_backdoor"


class TokenSafetyLevel(Enum):
    """Token safety level."""
    SAFE = "safe"
    LOW_RISK = "low_risk"
    MEDIUM_RISK = "medium_risk"
    HIGH_RISK = "high_risk"
    CRITICAL_RISK = "critical_risk"
    BLOCKED = "blocked"


class LiquidityLockStatus(Enum):
    """Liquidity lock status."""
    LOCKED = "locked"
    PARTIALLY_LOCKED = "partially_locked"
    UNLOCKED = "unlocked"
    EXPIRED = "expired"


@dataclass
class TokenSafetyAnalysis:
    """Token safety analysis result."""
    token_address: str
    token_name: str
    token_symbol: str
    
    # Safety assessment
    safety_level: TokenSafetyLevel
    risk_score: float  # 0.0 (safe) to 1.0 (critical)
    
    # Detected patterns
    detected_patterns: List[RugPullPattern] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    
    # Contract analysis
    has_minting_cap: bool = False
    has_burn_function: bool = False
    has_pause_function: bool = False
    has_blacklist: bool = False
    has_whitelist: bool = False
    is_upgradeable: bool = False
    has_timelock: bool = False
    
    # Ownership
    owner_address: Optional[str] = None
    owner_can_mint: bool = False
    owner_can_burn: bool = False
    owner_can_pause: bool = False
    owner_can_blacklist: bool = False
    
    # Liquidity
    total_liquidity_usd: Decimal = Decimal("0")
    liquidity_lock_status: LiquidityLockStatus = LiquidityLockStatus.UNLOCKED
    liquidity_lock_duration_days: Optional[int] = None
    liquidity_lock_expiry: Optional[datetime] = None
    
    # Distribution
    top_holder_percentage: float = 0.0
    top_10_holders_percentage: float = 0.0
    deployer_balance_percentage: float = 0.0
    
    # Trading
    buy_tax_percentage: float = 0.0
    sell_tax_percentage: float = 0.0
    max_transaction_percentage: Optional[float] = None
    max_wallet_percentage: Optional[float] = None
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    should_block: bool = False
    
    analyzed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LiquidityMonitor:
    """Liquidity monitoring for rug detection."""
    pool_address: str
    token_address: str
    
    # Initial state
    initial_liquidity_usd: Decimal
    initial_timestamp: datetime
    
    # Current state
    current_liquidity_usd: Decimal
    last_update: datetime
    
    # Thresholds
    alert_threshold_percentage: float = 20.0  # Alert if >20% withdrawn
    critical_threshold_percentage: float = 50.0  # Block if >50% withdrawn
    
    # History
    liquidity_history: List[Dict[str, Any]] = field(default_factory=list)
    withdrawals: List[Dict[str, Any]] = field(default_factory=list)
    
    # Alerts
    alerts_triggered: List[str] = field(default_factory=list)
    blocked: bool = False


@dataclass
class FactoryContract:
    """Audited factory contract for safe deployments."""
    factory_id: str
    factory_address: str
    factory_type: str  # "erc20", "erc4626", "erc721"
    
    # Audit
    audited: bool = True
    audit_reports: List[str] = field(default_factory=list)
    audit_date: Optional[datetime] = None
    
    # Safety features
    enforces_minting_cap: bool = True
    enforces_vesting: bool = True
    enforces_timelock: bool = True
    enforces_liquidity_lock: bool = True
    
    # Limits
    max_deployments_per_agent: int = 10
    max_total_supply: Optional[Decimal] = None
    min_liquidity_lock_days: int = 90
    
    # Governance
    requires_dao_approval: bool = True
    requires_council_review: bool = True
    
    # Usage
    deployments_count: int = 0
    last_deployment: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RugPullAlert:
    """Rug-pull alert."""
    alert_id: str
    token_address: str
    pattern: RugPullPattern
    severity: str  # "low", "medium", "high", "critical"
    
    description: str
    evidence: Dict[str, Any]
    
    # Response
    action_taken: Optional[str] = None
    blocked: bool = False
    
    detected_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class AntiRugSafeguards:
    """
    Anti-rug safeguards for agent-launched tokens and projects.
    
    Implements:
    - Token safety analysis (contract scanning)
    - Rug-pull pattern detection
    - Liquidity monitoring
    - Factory contract whitelisting
    - Automated blocking and alerts
    """
    
    def __init__(self):
        self._token_analyses: Dict[str, TokenSafetyAnalysis] = {}
        self._liquidity_monitors: Dict[str, LiquidityMonitor] = {}
        self._factory_contracts: Dict[str, FactoryContract] = {}
        self._alerts: List[RugPullAlert] = []
        
        self._initialize_factories()
    
    def _initialize_factories(self) -> None:
        """Initialize audited factory contracts."""
        
        # ERC-20 factory with safety features
        self.register_factory(
            factory_id="erc20_safe_factory_v1",
            factory_address="0x1234567890123456789012345678901234567890",
            factory_type="erc20",
            enforces_minting_cap=True,
            enforces_vesting=True,
            enforces_timelock=True,
            enforces_liquidity_lock=True,
            min_liquidity_lock_days=180,
            requires_dao_approval=True,
        )
        
        # ERC-4626 vault factory
        self.register_factory(
            factory_id="erc4626_vault_factory_v1",
            factory_address="0x2345678901234567890123456789012345678901",
            factory_type="erc4626",
            enforces_minting_cap=True,
            enforces_vesting=False,
            enforces_timelock=True,
            enforces_liquidity_lock=False,
            requires_dao_approval=True,
        )
        
        logger.info(f"Initialized {len(self._factory_contracts)} factory contracts")
    
    def register_factory(
        self,
        factory_id: str,
        factory_address: str,
        factory_type: str,
        enforces_minting_cap: bool = True,
        enforces_vesting: bool = True,
        enforces_timelock: bool = True,
        enforces_liquidity_lock: bool = True,
        min_liquidity_lock_days: int = 90,
        requires_dao_approval: bool = True,
    ) -> FactoryContract:
        """Register audited factory contract."""
        factory = FactoryContract(
            factory_id=factory_id,
            factory_address=factory_address,
            factory_type=factory_type,
            enforces_minting_cap=enforces_minting_cap,
            enforces_vesting=enforces_vesting,
            enforces_timelock=enforces_timelock,
            enforces_liquidity_lock=enforces_liquidity_lock,
            min_liquidity_lock_days=min_liquidity_lock_days,
            requires_dao_approval=requires_dao_approval,
        )
        
        self._factory_contracts[factory_id] = factory
        
        logger.info(f"Registered factory '{factory_id}': {factory_type}")
        
        return factory
    
    def analyze_token_safety(
        self,
        token_address: str,
        token_name: str,
        token_symbol: str,
        contract_code: Optional[str] = None,
    ) -> TokenSafetyAnalysis:
        """
        Analyze token for rug-pull risks.
        
        In production, this would:
        - Scan contract bytecode
        - Check for known malicious patterns
        - Analyze ownership and permissions
        - Verify liquidity locks
        - Check holder distribution
        """
        analysis = TokenSafetyAnalysis(
            token_address=token_address,
            token_name=token_name,
            token_symbol=token_symbol,
            safety_level=TokenSafetyLevel.SAFE,
            risk_score=0.0,
        )
        
        # Simulate contract analysis
        # In production: use static analysis tools, bytecode scanning
        
        # Check for dangerous features
        if self._has_unlimited_minting(contract_code):
            analysis.owner_can_mint = True
            analysis.has_minting_cap = False
            analysis.risk_score += 0.3
            analysis.risk_flags.append("unlimited_minting")
            analysis.detected_patterns.append(RugPullPattern.MINT_FLOOD)
        
        if self._has_blacklist_function(contract_code):
            analysis.has_blacklist = True
            analysis.owner_can_blacklist = True
            analysis.risk_score += 0.2
            analysis.risk_flags.append("blacklist_function")
            analysis.detected_patterns.append(RugPullPattern.BLACKLIST_TRAP)
        
        if self._is_upgradeable_without_timelock(contract_code):
            analysis.is_upgradeable = True
            analysis.has_timelock = False
            analysis.risk_score += 0.3
            analysis.risk_flags.append("upgradeable_no_timelock")
            analysis.detected_patterns.append(RugPullPattern.PROXY_UPGRADE_MALICIOUS)
        
        if self._has_hidden_backdoor(contract_code):
            analysis.risk_score += 0.5
            analysis.risk_flags.append("hidden_backdoor")
            analysis.detected_patterns.append(RugPullPattern.HIDDEN_BACKDOOR)
        
        # Check holder distribution
        if analysis.top_holder_percentage > 50:
            analysis.risk_score += 0.2
            analysis.risk_flags.append("concentrated_ownership")
        
        if analysis.deployer_balance_percentage > 30:
            analysis.risk_score += 0.15
            analysis.risk_flags.append("deployer_large_balance")
        
        # Check taxes
        if analysis.sell_tax_percentage > 10:
            analysis.risk_score += 0.1
            analysis.risk_flags.append("high_sell_tax")
        
        if analysis.sell_tax_percentage > analysis.buy_tax_percentage + 5:
            analysis.risk_score += 0.15
            analysis.risk_flags.append("asymmetric_tax")
        
        # Determine safety level
        if analysis.risk_score >= 0.8:
            analysis.safety_level = TokenSafetyLevel.CRITICAL_RISK
            analysis.should_block = True
        elif analysis.risk_score >= 0.6:
            analysis.safety_level = TokenSafetyLevel.HIGH_RISK
        elif analysis.risk_score >= 0.4:
            analysis.safety_level = TokenSafetyLevel.MEDIUM_RISK
        elif analysis.risk_score >= 0.2:
            analysis.safety_level = TokenSafetyLevel.LOW_RISK
        else:
            analysis.safety_level = TokenSafetyLevel.SAFE
        
        # Generate recommendations
        self._generate_recommendations(analysis)
        
        self._token_analyses[token_address] = analysis
        
        logger.info(
            f"Analyzed token {token_symbol}: {analysis.safety_level.value} "
            f"(risk: {analysis.risk_score:.2f})"
        )
        
        return analysis
    
    def _has_unlimited_minting(self, contract_code: Optional[str]) -> bool:
        """Check if contract has unlimited minting."""
        if not contract_code:
            return False
        # Simplified check - in production: use static analysis
        return "mint(" in contract_code and "maxSupply" not in contract_code
    
    def _has_blacklist_function(self, contract_code: Optional[str]) -> bool:
        """Check if contract has blacklist function."""
        if not contract_code:
            return False
        return "blacklist" in contract_code.lower() or "blocked" in contract_code.lower()
    
    def _is_upgradeable_without_timelock(self, contract_code: Optional[str]) -> bool:
        """Check if contract is upgradeable without timelock."""
        if not contract_code:
            return False
        return "upgradeTo" in contract_code and "timelock" not in contract_code.lower()
    
    def _has_hidden_backdoor(self, contract_code: Optional[str]) -> bool:
        """Check for hidden backdoor functions."""
        if not contract_code:
            return False
        # Simplified - in production: use advanced static analysis
        suspicious_patterns = ["selfdestruct", "delegatecall", "callcode"]
        return any(pattern in contract_code for pattern in suspicious_patterns)
    
    def _generate_recommendations(self, analysis: TokenSafetyAnalysis) -> None:
        """Generate safety recommendations."""
        if not analysis.has_minting_cap:
            analysis.recommendations.append("Add minting cap to prevent inflation attacks")
        
        if analysis.has_blacklist and analysis.owner_can_blacklist:
            analysis.recommendations.append("Remove blacklist function or add governance control")
        
        if analysis.is_upgradeable and not analysis.has_timelock:
            analysis.recommendations.append("Add timelock to proxy upgrades")
        
        if analysis.liquidity_lock_status == LiquidityLockStatus.UNLOCKED:
            analysis.recommendations.append("Lock liquidity for minimum 90 days")
        
        if analysis.top_holder_percentage > 50:
            analysis.recommendations.append("Distribute tokens more evenly to prevent manipulation")
        
        if analysis.sell_tax_percentage > 10:
            analysis.recommendations.append("Reduce sell tax to reasonable levels (<5%)")
    
    def monitor_liquidity(
        self,
        pool_address: str,
        token_address: str,
        initial_liquidity_usd: Decimal,
    ) -> LiquidityMonitor:
        """Start monitoring liquidity for rug detection."""
        monitor = LiquidityMonitor(
            pool_address=pool_address,
            token_address=token_address,
            initial_liquidity_usd=initial_liquidity_usd,
            initial_timestamp=datetime.utcnow(),
            current_liquidity_usd=initial_liquidity_usd,
            last_update=datetime.utcnow(),
        )
        
        self._liquidity_monitors[pool_address] = monitor
        
        logger.info(
            f"Monitoring liquidity for pool {pool_address}: ${initial_liquidity_usd}"
        )
        
        return monitor
    
    def update_liquidity(
        self,
        pool_address: str,
        current_liquidity_usd: Decimal,
    ) -> Optional[RugPullAlert]:
        """Update liquidity and check for rug-pull."""
        monitor = self._liquidity_monitors.get(pool_address)
        if not monitor:
            logger.warning(f"No monitor found for pool {pool_address}")
            return None
        
        # Calculate change
        change_percentage = float(
            (monitor.initial_liquidity_usd - current_liquidity_usd) /
            monitor.initial_liquidity_usd * 100
        )
        
        # Update monitor
        monitor.current_liquidity_usd = current_liquidity_usd
        monitor.last_update = datetime.utcnow()
        monitor.liquidity_history.append({
            "timestamp": datetime.utcnow(),
            "liquidity_usd": current_liquidity_usd,
            "change_percentage": change_percentage,
        })
        
        # Check thresholds
        alert = None
        
        if change_percentage >= monitor.critical_threshold_percentage:
            # Critical: block immediately
            alert = self._create_alert(
                token_address=monitor.token_address,
                pattern=RugPullPattern.LARGE_LIQUIDITY_WITHDRAWAL,
                severity="critical",
                description=f"Critical liquidity drain: {change_percentage:.1f}% withdrawn",
                evidence={
                    "pool_address": pool_address,
                    "initial_liquidity": str(monitor.initial_liquidity_usd),
                    "current_liquidity": str(current_liquidity_usd),
                    "change_percentage": change_percentage,
                },
            )
            alert.blocked = True
            alert.action_taken = "pool_blocked"
            monitor.blocked = True
            monitor.alerts_triggered.append("critical_liquidity_drain")
            
        elif change_percentage >= monitor.alert_threshold_percentage:
            # Warning: alert but don't block
            alert = self._create_alert(
                token_address=monitor.token_address,
                pattern=RugPullPattern.LARGE_LIQUIDITY_WITHDRAWAL,
                severity="high",
                description=f"Significant liquidity withdrawal: {change_percentage:.1f}%",
                evidence={
                    "pool_address": pool_address,
                    "initial_liquidity": str(monitor.initial_liquidity_usd),
                    "current_liquidity": str(current_liquidity_usd),
                    "change_percentage": change_percentage,
                },
            )
            monitor.alerts_triggered.append("liquidity_withdrawal_warning")
        
        return alert
    
    def _create_alert(
        self,
        token_address: str,
        pattern: RugPullPattern,
        severity: str,
        description: str,
        evidence: Dict[str, Any],
    ) -> RugPullAlert:
        """Create rug-pull alert."""
        alert_id = f"alert_{token_address}_{int(datetime.utcnow().timestamp())}"
        
        alert = RugPullAlert(
            alert_id=alert_id,
            token_address=token_address,
            pattern=pattern,
            severity=severity,
            description=description,
            evidence=evidence,
        )
        
        self._alerts.append(alert)
        
        logger.warning(
            f"RUG ALERT [{severity}]: {description} (token: {token_address})"
        )
        
        return alert
    
    def get_token_analysis(self, token_address: str) -> Optional[TokenSafetyAnalysis]:
        """Get token safety analysis."""
        return self._token_analyses.get(token_address)
    
    def get_high_risk_tokens(self) -> List[TokenSafetyAnalysis]:
        """Get high-risk tokens."""
        return [
            a for a in self._token_analyses.values()
            if a.safety_level in [TokenSafetyLevel.HIGH_RISK, TokenSafetyLevel.CRITICAL_RISK]
        ]
    
    def get_blocked_tokens(self) -> List[TokenSafetyAnalysis]:
        """Get blocked tokens."""
        return [a for a in self._token_analyses.values() if a.should_block]
    
    def get_liquidity_monitor(self, pool_address: str) -> Optional[LiquidityMonitor]:
        """Get liquidity monitor."""
        return self._liquidity_monitors.get(pool_address)
    
    def get_active_alerts(self, severity: Optional[str] = None) -> List[RugPullAlert]:
        """Get active alerts."""
        alerts = [a for a in self._alerts if a.resolved_at is None]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        return alerts
    
    def get_factory_contracts(self) -> List[FactoryContract]:
        """Get all factory contracts."""
        return list(self._factory_contracts.values())
    
    def is_factory_whitelisted(self, factory_address: str) -> bool:
        """Check if factory is whitelisted."""
        return any(
            f.factory_address == factory_address
            for f in self._factory_contracts.values()
        )


_anti_rug_safeguards: Optional[AntiRugSafeguards] = None


def get_anti_rug_safeguards() -> AntiRugSafeguards:
    """Get global AntiRugSafeguards instance."""
    global _anti_rug_safeguards
    if _anti_rug_safeguards is None:
        _anti_rug_safeguards = AntiRugSafeguards()
    return _anti_rug_safeguards
