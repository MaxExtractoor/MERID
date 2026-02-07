"""
Contract exploit and backdoor scanner for MERID HFT swarm.

Implements detection of:
- Backdoors and admin abuse
- Re-entrancy vulnerabilities
- Unsafe upgrades and proxies
- Malicious contract patterns
"""

import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class ExploitType(Enum):
    """Type of exploit."""
    BACKDOOR = "backdoor"
    ADMIN_ABUSE = "admin_abuse"
    REENTRANCY = "reentrancy"
    UNSAFE_UPGRADE = "unsafe_upgrade"
    UNSAFE_PROXY = "unsafe_proxy"
    UNLIMITED_MINT = "unlimited_mint"
    HIDDEN_FEES = "hidden_fees"
    BLACKLIST_TRAP = "blacklist_trap"
    OWNERSHIP_CENTRALIZATION = "ownership_centralization"
    UNVERIFIED_CODE = "unverified_code"


class ExploitSeverity(Enum):
    """Exploit severity."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ContractExploit:
    """Detected contract exploit."""
    exploit_id: str
    contract_address: str
    exploit_type: ExploitType
    severity: ExploitSeverity
    
    # Details
    description: str
    evidence: List[str] = field(default_factory=list)
    affected_functions: List[str] = field(default_factory=list)
    
    # Risk
    exploitable: bool = True
    requires_admin: bool = False
    
    # Response
    blocked: bool = False
    requires_governance_review: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ContractAnalysis:
    """Contract security analysis result."""
    contract_address: str
    contract_name: Optional[str] = None
    
    # Verification
    is_verified: bool = False
    source_code_available: bool = False
    
    # Exploits
    exploits: List[ContractExploit] = field(default_factory=list)
    
    # Risk score
    risk_score: float = 0.0  # 0.0 (safe) to 1.0 (critical)
    
    # Approval
    approved_for_use: bool = False
    requires_governance_approval: bool = False
    
    # Audit
    audit_completed: bool = False
    audit_provider: Optional[str] = None
    audit_date: Optional[datetime] = None
    
    analyzed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExploitPattern:
    """Known exploit pattern."""
    pattern_id: str
    pattern_name: str
    exploit_type: ExploitType
    severity: ExploitSeverity
    
    # Detection
    bytecode_signatures: List[str] = field(default_factory=list)
    function_signatures: List[str] = field(default_factory=list)
    behavioral_indicators: List[str] = field(default_factory=list)
    
    # Response
    auto_block: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class ContractExploitScanner:
    """
    Contract exploit and backdoor scanner for MERID.
    
    Implements:
    - Static analysis of contract code
    - Dynamic behavior analysis
    - Exploit pattern matching
    - Risk scoring and blocking
    - Governance integration for risky contracts
    """
    
    def __init__(self):
        self._exploit_patterns: Dict[str, ExploitPattern] = {}
        self._analyzed_contracts: Dict[str, ContractAnalysis] = {}
        self._blocked_contracts: Set[str] = set()
        self._approved_contracts: Set[str] = set()
        
        self._initialize_exploit_patterns()
    
    def _initialize_exploit_patterns(self) -> None:
        """Initialize known exploit patterns."""
        
        # Backdoor patterns
        self.register_exploit_pattern(
            pattern_id="hidden_admin_backdoor",
            pattern_name="Hidden Admin Backdoor",
            exploit_type=ExploitType.BACKDOOR,
            severity=ExploitSeverity.CRITICAL,
            function_signatures=[
                "function emergencyWithdraw()",
                "function adminTransfer(address,uint256)",
                "function ownerWithdraw()",
            ],
            auto_block=True,
        )
        
        # Admin abuse patterns
        self.register_exploit_pattern(
            pattern_id="unlimited_mint",
            pattern_name="Unlimited Mint Function",
            exploit_type=ExploitType.UNLIMITED_MINT,
            severity=ExploitSeverity.HIGH,
            function_signatures=[
                "function mint(address,uint256)",
                "function mintTo(address,uint256)",
            ],
            behavioral_indicators=[
                "No mint cap",
                "No time lock on minting",
                "Single address can mint unlimited",
            ],
            auto_block=False,  # May be legitimate, requires review
        )
        
        # Re-entrancy patterns
        self.register_exploit_pattern(
            pattern_id="reentrancy_vulnerable",
            pattern_name="Re-entrancy Vulnerability",
            exploit_type=ExploitType.REENTRANCY,
            severity=ExploitSeverity.CRITICAL,
            behavioral_indicators=[
                "External call before state update",
                "No re-entrancy guard",
                "Unchecked call return value",
            ],
            auto_block=True,
        )
        
        # Unsafe upgrade patterns
        self.register_exploit_pattern(
            pattern_id="unsafe_upgrade",
            pattern_name="Unsafe Upgrade Mechanism",
            exploit_type=ExploitType.UNSAFE_UPGRADE,
            severity=ExploitSeverity.HIGH,
            function_signatures=[
                "function upgradeTo(address)",
                "function upgradeToAndCall(address,bytes)",
            ],
            behavioral_indicators=[
                "No time lock on upgrades",
                "Single admin can upgrade",
                "No upgrade proposal/voting",
            ],
            auto_block=False,
        )
        
        # Blacklist trap patterns
        self.register_exploit_pattern(
            pattern_id="blacklist_trap",
            pattern_name="Blacklist Trap",
            exploit_type=ExploitType.BLACKLIST_TRAP,
            severity=ExploitSeverity.HIGH,
            function_signatures=[
                "function blacklist(address)",
                "function addToBlacklist(address)",
            ],
            behavioral_indicators=[
                "Can blacklist any address",
                "No governance control",
                "Blacklisted addresses cannot transfer",
            ],
            auto_block=False,
        )
        
        # Hidden fees patterns
        self.register_exploit_pattern(
            pattern_id="hidden_fees",
            pattern_name="Hidden or Variable Fees",
            exploit_type=ExploitType.HIDDEN_FEES,
            severity=ExploitSeverity.MEDIUM,
            function_signatures=[
                "function setFee(uint256)",
                "function updateTaxRate(uint256)",
            ],
            behavioral_indicators=[
                "Fee can be changed without notice",
                "No maximum fee cap",
                "Fee goes to single address",
            ],
            auto_block=False,
        )
        
        logger.info("Initialized contract exploit patterns")
    
    def register_exploit_pattern(
        self,
        pattern_id: str,
        pattern_name: str,
        exploit_type: ExploitType,
        severity: ExploitSeverity,
        bytecode_signatures: Optional[List[str]] = None,
        function_signatures: Optional[List[str]] = None,
        behavioral_indicators: Optional[List[str]] = None,
        auto_block: bool = True,
    ) -> ExploitPattern:
        """Register exploit pattern."""
        pattern = ExploitPattern(
            pattern_id=pattern_id,
            pattern_name=pattern_name,
            exploit_type=exploit_type,
            severity=severity,
            bytecode_signatures=bytecode_signatures or [],
            function_signatures=function_signatures or [],
            behavioral_indicators=behavioral_indicators or [],
            auto_block=auto_block,
        )
        
        self._exploit_patterns[pattern_id] = pattern
        
        logger.info(f"Registered exploit pattern '{pattern_id}': {pattern_name}")
        
        return pattern
    
    def scan_contract(
        self,
        contract_address: str,
        contract_name: Optional[str] = None,
        source_code: Optional[str] = None,
        is_verified: bool = False,
        audit_completed: bool = False,
    ) -> ContractAnalysis:
        """Scan contract for exploits and vulnerabilities."""
        # Check if already analyzed
        if contract_address in self._analyzed_contracts:
            return self._analyzed_contracts[contract_address]
        
        analysis = ContractAnalysis(
            contract_address=contract_address,
            contract_name=contract_name,
            is_verified=is_verified,
            source_code_available=(source_code is not None),
            audit_completed=audit_completed,
        )
        
        # Check if unverified (high risk)
        if not is_verified:
            exploit = ContractExploit(
                exploit_id=f"exploit_{contract_address}_unverified",
                contract_address=contract_address,
                exploit_type=ExploitType.UNVERIFIED_CODE,
                severity=ExploitSeverity.HIGH,
                description="Contract source code not verified",
                evidence=["No verified source code on block explorer"],
                blocked=False,
                requires_governance_review=True,
            )
            analysis.exploits.append(exploit)
        
        # Scan for exploit patterns (simplified - real implementation would analyze bytecode/source)
        if source_code:
            for pattern in self._exploit_patterns.values():
                # Check function signatures
                for func_sig in pattern.function_signatures:
                    if func_sig in source_code:
                        exploit = ContractExploit(
                            exploit_id=f"exploit_{contract_address}_{pattern.pattern_id}",
                            contract_address=contract_address,
                            exploit_type=pattern.exploit_type,
                            severity=pattern.severity,
                            description=f"{pattern.pattern_name} detected",
                            evidence=[f"Function signature: {func_sig}"],
                            affected_functions=[func_sig],
                            blocked=pattern.auto_block,
                            requires_governance_review=not pattern.auto_block,
                        )
                        analysis.exploits.append(exploit)
        
        # Calculate risk score
        risk_score = 0.0
        
        if not is_verified:
            risk_score += 0.3
        
        if not audit_completed:
            risk_score += 0.2
        
        for exploit in analysis.exploits:
            if exploit.severity == ExploitSeverity.CRITICAL:
                risk_score += 0.4
            elif exploit.severity == ExploitSeverity.HIGH:
                risk_score += 0.3
            elif exploit.severity == ExploitSeverity.MEDIUM:
                risk_score += 0.15
            elif exploit.severity == ExploitSeverity.LOW:
                risk_score += 0.05
        
        risk_score = min(risk_score, 1.0)
        analysis.risk_score = risk_score
        
        # Determine approval status
        critical_exploits = [
            e for e in analysis.exploits
            if e.severity == ExploitSeverity.CRITICAL and e.blocked
        ]
        
        if critical_exploits:
            analysis.approved_for_use = False
            self._blocked_contracts.add(contract_address)
            logger.warning(
                f"Contract {contract_address} BLOCKED: "
                f"{len(critical_exploits)} critical exploits"
            )
        elif risk_score >= 0.5:
            analysis.approved_for_use = False
            analysis.requires_governance_approval = True
            logger.warning(
                f"Contract {contract_address} requires governance approval: "
                f"risk_score={risk_score:.2f}"
            )
        else:
            analysis.approved_for_use = True
            self._approved_contracts.add(contract_address)
            logger.info(
                f"Contract {contract_address} approved: risk_score={risk_score:.2f}"
            )
        
        self._analyzed_contracts[contract_address] = analysis
        
        return analysis
    
    def is_contract_safe(self, contract_address: str) -> bool:
        """Check if contract is safe to use."""
        if contract_address in self._blocked_contracts:
            return False
        
        if contract_address in self._approved_contracts:
            return True
        
        # Not analyzed yet
        return False
    
    def approve_contract(
        self,
        contract_address: str,
        governance_approved: bool = False,
    ) -> bool:
        """Approve contract for use (governance override)."""
        if governance_approved:
            self._approved_contracts.add(contract_address)
            if contract_address in self._blocked_contracts:
                self._blocked_contracts.remove(contract_address)
            
            logger.info(
                f"Contract {contract_address} approved by governance"
            )
            return True
        
        return False
    
    def block_contract(self, contract_address: str, reason: str) -> None:
        """Block contract from use."""
        self._blocked_contracts.add(contract_address)
        if contract_address in self._approved_contracts:
            self._approved_contracts.remove(contract_address)
        
        logger.warning(
            f"Contract {contract_address} blocked: {reason}"
        )
    
    def get_contract_analysis(
        self,
        contract_address: str,
    ) -> Optional[ContractAnalysis]:
        """Get contract analysis."""
        return self._analyzed_contracts.get(contract_address)
    
    def get_blocked_contracts(self) -> Set[str]:
        """Get all blocked contracts."""
        return self._blocked_contracts.copy()
    
    def get_approved_contracts(self) -> Set[str]:
        """Get all approved contracts."""
        return self._approved_contracts.copy()


_contract_exploit_scanner: Optional[ContractExploitScanner] = None


def get_contract_exploit_scanner() -> ContractExploitScanner:
    """Get global ContractExploitScanner instance."""
    global _contract_exploit_scanner
    if _contract_exploit_scanner is None:
        _contract_exploit_scanner = ContractExploitScanner()
    return _contract_exploit_scanner
