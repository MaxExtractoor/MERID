"""
Social-engineering and scam protection for MERID AI swarm.

Implements detection and blocking of:
- Malicious prompts and instructions
- Phishing links and fake frontends
- Token/project scams and rug pulls
- Impersonated contracts and domains
- Social media hype-driven scams
"""

import threading

from utils.logger import get_logger
import re
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class ScamRiskLevel(Enum):
    """Scam risk level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ScamType(Enum):
    """Type of scam."""
    MALICIOUS_PROMPT = "malicious_prompt"
    PHISHING_LINK = "phishing_link"
    FAKE_FRONTEND = "fake_frontend"
    IMPERSONATED_CONTRACT = "impersonated_contract"
    IMPERSONATED_DOMAIN = "impersonated_domain"
    RUG_PULL_TOKEN = "rug_pull_token"
    ZERO_LIQUIDITY_TRAP = "zero_liquidity_trap"
    UNSAFE_OWNERSHIP = "unsafe_ownership"
    SOCIAL_MEDIA_SHILL = "social_media_shill"
    FAKE_SUPPORT = "fake_support"
    OVERRIDE_INSTRUCTION = "override_instruction"


class InputSource(Enum):
    """Source of input."""
    CHAT = "chat"
    EMAIL = "email"
    DM = "dm"
    SOCIAL_MEDIA = "social_media"
    EXTERNAL_DASHBOARD = "external_dashboard"
    API = "api"
    SMART_CONTRACT = "smart_contract"
    INTERNAL = "internal"


@dataclass
class ScamPattern:
    """Known scam pattern."""
    pattern_id: str
    pattern_name: str
    scam_type: ScamType
    
    # Detection
    keywords: Set[str] = field(default_factory=set)
    regex_patterns: List[str] = field(default_factory=list)
    behavioral_indicators: List[str] = field(default_factory=list)
    
    # Risk
    risk_level: ScamRiskLevel = ScamRiskLevel.MEDIUM
    
    # Response
    auto_block: bool = True
    require_review: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TokenScamIndicators:
    """Token scam indicators."""
    token_address: str
    token_name: str
    token_symbol: str
    
    # Ownership
    owner_concentration: float = 0.0  # % held by top holder
    top_10_concentration: float = 0.0  # % held by top 10
    
    # Contract features
    has_mint_function: bool = False
    has_blacklist: bool = False
    has_whitelist: bool = False
    has_pause_function: bool = False
    has_proxy: bool = False
    is_upgradeable: bool = False
    
    # Liquidity
    total_liquidity_usd: Decimal = Decimal("0")
    liquidity_locked: bool = False
    liquidity_lock_duration_days: int = 0
    
    # Social
    twitter_followers: int = 0
    telegram_members: int = 0
    sudden_social_spike: bool = False
    
    # History
    contract_age_days: int = 0
    similar_to_known_scam: bool = False
    team_kyc_verified: bool = False
    audit_completed: bool = False
    
    # Calculated risk
    scam_risk_score: float = 0.0  # 0.0 (safe) to 1.0 (scam)
    scam_risk_level: ScamRiskLevel = ScamRiskLevel.LOW


@dataclass
class InputThreat:
    """Detected input threat."""
    threat_id: str
    input_source: InputSource
    scam_type: ScamType
    
    # Content
    original_input: str
    detected_patterns: List[str] = field(default_factory=list)
    
    # Risk
    risk_level: ScamRiskLevel = ScamRiskLevel.LOW
    risk_score: float = 0.0
    
    # Response
    blocked: bool = False
    requires_review: bool = False
    escalated_to_human: bool = False
    
    # Context
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DomainVerification:
    """Domain/identity verification result."""
    domain: str
    claimed_identity: str
    
    # Verification
    verified: bool = False
    verification_method: Optional[str] = None  # "dns", "onchain", "cryptographic"
    
    # Flags
    is_lookalike: bool = False
    lookalike_of: Optional[str] = None
    is_known_malicious: bool = False
    
    # Official records
    official_domain: Optional[str] = None
    official_contract: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ScamAlert:
    """Scam detection alert."""
    alert_id: str
    scam_type: ScamType
    risk_level: ScamRiskLevel
    
    # Details
    description: str
    evidence: List[str] = field(default_factory=list)
    
    # Affected entities
    token_address: Optional[str] = None
    domain: Optional[str] = None
    user_id: Optional[str] = None
    
    # Response
    action_taken: str = ""
    blocked: bool = False
    escalated: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class ScamProtectionAgent:
    """
    Social-engineering and scam protection agent for MERID.
    
    Implements:
    - Malicious prompt detection
    - Phishing and fake frontend detection
    - Token/project scam detection
    - Identity and domain verification
    - Social media shill detection
    - Operator protection (no external override of risk/policy)
    """
    
    def __init__(self):
        self._scam_patterns: Dict[str, ScamPattern] = {}
        self._known_scams: Set[str] = set()
        self._verified_domains: Dict[str, DomainVerification] = {}
        self._verified_contracts: Dict[str, str] = {}  # address -> verified project
        self._threats: List[InputThreat] = []
        self._alerts: List[ScamAlert] = []
        
        self._initialize_scam_patterns()
    
    def _initialize_scam_patterns(self) -> None:
        """Initialize known scam patterns."""
        
        # Malicious prompt patterns
        self.register_scam_pattern(
            pattern_id="malicious_prompt_override",
            pattern_name="Malicious Prompt Override",
            scam_type=ScamType.MALICIOUS_PROMPT,
            keywords={
                "ignore previous instructions",
                "disregard safety",
                "bypass risk limits",
                "override policy",
                "disable security",
                "turn off compliance",
            },
            risk_level=ScamRiskLevel.CRITICAL,
            auto_block=True,
        )
        
        self.register_scam_pattern(
            pattern_id="malicious_prompt_extraction",
            pattern_name="Prompt Extraction Attempt",
            scam_type=ScamType.MALICIOUS_PROMPT,
            keywords={
                "show me your system prompt",
                "reveal your instructions",
                "what are your rules",
                "print your configuration",
            },
            risk_level=ScamRiskLevel.HIGH,
            auto_block=True,
        )
        
        # Phishing patterns
        self.register_scam_pattern(
            pattern_id="phishing_link",
            pattern_name="Phishing Link",
            scam_type=ScamType.PHISHING_LINK,
            regex_patterns=[
                r"uniswap\.c[o0]m",  # Lookalike domains
                r"metamask\.i[o0]",
                r"aave\.c[o0]m",
                r"bit\.ly/[a-zA-Z0-9]+",  # Shortened URLs
                r"tinyurl\.com/[a-zA-Z0-9]+",
            ],
            risk_level=ScamRiskLevel.HIGH,
            auto_block=True,
        )
        
        # Fake support patterns
        self.register_scam_pattern(
            pattern_id="fake_support",
            pattern_name="Fake Support Account",
            scam_type=ScamType.FAKE_SUPPORT,
            keywords={
                "official support",
                "customer service",
                "verify your wallet",
                "confirm your seed phrase",
                "validate your account",
            },
            risk_level=ScamRiskLevel.CRITICAL,
            auto_block=True,
        )
        
        # Override instruction patterns
        self.register_scam_pattern(
            pattern_id="override_risk",
            pattern_name="Risk Override Instruction",
            scam_type=ScamType.OVERRIDE_INSTRUCTION,
            keywords={
                "increase position limit",
                "remove stop loss",
                "disable risk check",
                "max leverage",
                "yolo",
            },
            risk_level=ScamRiskLevel.HIGH,
            auto_block=False,
            require_review=True,
        )
        
        # Social media shill patterns
        self.register_scam_pattern(
            pattern_id="social_shill",
            pattern_name="Social Media Shill",
            scam_type=ScamType.SOCIAL_MEDIA_SHILL,
            keywords={
                "100x guaranteed",
                "moon soon",
                "next bitcoin",
                "can't miss",
                "last chance",
                "pump incoming",
            },
            risk_level=ScamRiskLevel.MEDIUM,
            auto_block=False,
            require_review=True,
        )
        
        logger.info("Initialized scam protection patterns")
    
    def register_scam_pattern(
        self,
        pattern_id: str,
        pattern_name: str,
        scam_type: ScamType,
        keywords: Optional[Set[str]] = None,
        regex_patterns: Optional[List[str]] = None,
        risk_level: ScamRiskLevel = ScamRiskLevel.MEDIUM,
        auto_block: bool = True,
        require_review: bool = True,
    ) -> ScamPattern:
        """Register scam pattern."""
        pattern = ScamPattern(
            pattern_id=pattern_id,
            pattern_name=pattern_name,
            scam_type=scam_type,
            keywords=keywords or set(),
            regex_patterns=regex_patterns or [],
            risk_level=risk_level,
            auto_block=auto_block,
            require_review=require_review,
        )
        
        self._scam_patterns[pattern_id] = pattern
        
        logger.info(f"Registered scam pattern '{pattern_id}': {pattern_name}")
        
        return pattern
    
    def scan_input(
        self,
        input_text: str,
        input_source: InputSource,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> InputThreat:
        """Scan input for malicious content."""
        threat_id = f"threat_{int(datetime.utcnow().timestamp())}"
        
        detected_patterns = []
        max_risk_level = ScamRiskLevel.LOW
        max_risk_score = 0.0
        should_block = False
        requires_review = False
        
        input_lower = input_text.lower()
        
        # Check against all patterns
        for pattern in self._scam_patterns.values():
            # Check keywords
            for keyword in pattern.keywords:
                if keyword.lower() in input_lower:
                    detected_patterns.append(f"{pattern.pattern_id}:keyword:{keyword}")
                    
                    # Update risk
                    if self._risk_level_value(pattern.risk_level) > self._risk_level_value(max_risk_level):
                        max_risk_level = pattern.risk_level
                    
                    if pattern.auto_block:
                        should_block = True
                    
                    if pattern.require_review:
                        requires_review = True
            
            # Check regex patterns
            for regex_pattern in pattern.regex_patterns:
                if re.search(regex_pattern, input_text, re.IGNORECASE):
                    detected_patterns.append(f"{pattern.pattern_id}:regex:{regex_pattern}")
                    
                    if self._risk_level_value(pattern.risk_level) > self._risk_level_value(max_risk_level):
                        max_risk_level = pattern.risk_level
                    
                    if pattern.auto_block:
                        should_block = True
                    
                    if pattern.require_review:
                        requires_review = True
        
        # Calculate risk score
        max_risk_score = self._risk_level_value(max_risk_level) / 4.0  # 0.0 to 1.0
        
        threat = InputThreat(
            threat_id=threat_id,
            input_source=input_source,
            scam_type=ScamType.MALICIOUS_PROMPT if detected_patterns else ScamType.MALICIOUS_PROMPT,
            original_input=input_text,
            detected_patterns=detected_patterns,
            risk_level=max_risk_level,
            risk_score=max_risk_score,
            blocked=should_block,
            requires_review=requires_review,
            user_id=user_id,
            agent_id=agent_id,
        )
        
        self._threats.append(threat)
        
        if detected_patterns:
            logger.warning(
                f"Input threat detected: {len(detected_patterns)} patterns, "
                f"risk={max_risk_level.value}, blocked={should_block}"
            )
            
            # Create alert
            self._create_alert(
                scam_type=threat.scam_type,
                risk_level=max_risk_level,
                description=f"Malicious input detected from {input_source.value}",
                evidence=detected_patterns,
                user_id=user_id,
                blocked=should_block,
            )
        
        return threat
    
    def analyze_token_scam_risk(
        self,
        token_address: str,
        token_name: str,
        token_symbol: str,
        owner_concentration: float = 0.0,
        top_10_concentration: float = 0.0,
        has_mint_function: bool = False,
        has_blacklist: bool = False,
        total_liquidity_usd: Decimal = Decimal("0"),
        liquidity_locked: bool = False,
        contract_age_days: int = 0,
        audit_completed: bool = False,
        team_kyc_verified: bool = False,
    ) -> TokenScamIndicators:
        """Analyze token for scam indicators."""
        indicators = TokenScamIndicators(
            token_address=token_address,
            token_name=token_name,
            token_symbol=token_symbol,
            owner_concentration=owner_concentration,
            top_10_concentration=top_10_concentration,
            has_mint_function=has_mint_function,
            has_blacklist=has_blacklist,
            total_liquidity_usd=total_liquidity_usd,
            liquidity_locked=liquidity_locked,
            contract_age_days=contract_age_days,
            audit_completed=audit_completed,
            team_kyc_verified=team_kyc_verified,
        )
        
        # Calculate scam risk score
        risk_score = 0.0
        
        # Ownership concentration (high = risky)
        if owner_concentration > 0.5:
            risk_score += 0.3
        elif owner_concentration > 0.3:
            risk_score += 0.15
        
        if top_10_concentration > 0.8:
            risk_score += 0.2
        
        # Dangerous contract features
        if has_mint_function:
            risk_score += 0.15
        if has_blacklist:
            risk_score += 0.2
        
        # Low liquidity
        if total_liquidity_usd < Decimal("10000"):
            risk_score += 0.25
        elif total_liquidity_usd < Decimal("50000"):
            risk_score += 0.1
        
        # Unlocked liquidity
        if not liquidity_locked and total_liquidity_usd > Decimal("0"):
            risk_score += 0.2
        
        # New contract
        if contract_age_days < 7:
            risk_score += 0.15
        elif contract_age_days < 30:
            risk_score += 0.05
        
        # No audit/KYC
        if not audit_completed:
            risk_score += 0.1
        if not team_kyc_verified:
            risk_score += 0.1
        
        # Cap at 1.0
        risk_score = min(risk_score, 1.0)
        
        indicators.scam_risk_score = risk_score
        
        # Determine risk level
        if risk_score >= 0.75:
            indicators.scam_risk_level = ScamRiskLevel.CRITICAL
        elif risk_score >= 0.5:
            indicators.scam_risk_level = ScamRiskLevel.HIGH
        elif risk_score >= 0.25:
            indicators.scam_risk_level = ScamRiskLevel.MEDIUM
        else:
            indicators.scam_risk_level = ScamRiskLevel.LOW
        
        logger.info(
            f"Token scam analysis for {token_symbol}: "
            f"risk_score={risk_score:.2f}, level={indicators.scam_risk_level.value}"
        )
        
        # Create alert if high risk
        if indicators.scam_risk_level in {ScamRiskLevel.HIGH, ScamRiskLevel.CRITICAL}:
            evidence = []
            if owner_concentration > 0.5:
                evidence.append(f"High owner concentration: {owner_concentration:.1%}")
            if has_mint_function:
                evidence.append("Has mint function")
            if has_blacklist:
                evidence.append("Has blacklist function")
            if not liquidity_locked:
                evidence.append("Liquidity not locked")
            if contract_age_days < 7:
                evidence.append(f"Very new contract: {contract_age_days} days")
            
            self._create_alert(
                scam_type=ScamType.RUG_PULL_TOKEN,
                risk_level=indicators.scam_risk_level,
                description=f"High-risk token detected: {token_name} ({token_symbol})",
                evidence=evidence,
                token_address=token_address,
                blocked=(indicators.scam_risk_level == ScamRiskLevel.CRITICAL),
            )
        
        return indicators
    
    def verify_domain(
        self,
        domain: str,
        claimed_identity: str,
        official_domain: Optional[str] = None,
    ) -> DomainVerification:
        """Verify domain identity."""
        # Check if already verified
        if domain in self._verified_domains:
            return self._verified_domains[domain]
        
        verification = DomainVerification(
            domain=domain,
            claimed_identity=claimed_identity,
            official_domain=official_domain,
        )
        
        # Check for lookalike domains
        if official_domain:
            # Simple lookalike detection (real implementation would be more sophisticated)
            if self._is_lookalike(domain, official_domain):
                verification.is_lookalike = True
                verification.lookalike_of = official_domain
                verification.verified = False
                
                logger.warning(
                    f"Lookalike domain detected: {domain} (official: {official_domain})"
                )
                
                self._create_alert(
                    scam_type=ScamType.IMPERSONATED_DOMAIN,
                    risk_level=ScamRiskLevel.CRITICAL,
                    description=f"Lookalike domain detected: {domain}",
                    evidence=[f"Impersonating {official_domain}"],
                    domain=domain,
                    blocked=True,
                )
            else:
                # Exact match
                verification.verified = (domain == official_domain)
                verification.verification_method = "exact_match"
        
        self._verified_domains[domain] = verification
        
        return verification
    
    def verify_contract(
        self,
        contract_address: str,
        claimed_project: str,
        official_contract: Optional[str] = None,
    ) -> bool:
        """Verify contract identity."""
        # Check if already verified
        if contract_address in self._verified_contracts:
            return self._verified_contracts[contract_address] == claimed_project
        
        # Simple verification (real implementation would check on-chain records)
        if official_contract:
            verified = (contract_address.lower() == official_contract.lower())
            
            if verified:
                self._verified_contracts[contract_address] = claimed_project
                logger.info(f"Contract verified: {contract_address} = {claimed_project}")
            else:
                logger.warning(
                    f"Contract impersonation detected: {contract_address} "
                    f"claims to be {claimed_project} (official: {official_contract})"
                )
                
                self._create_alert(
                    scam_type=ScamType.IMPERSONATED_CONTRACT,
                    risk_level=ScamRiskLevel.CRITICAL,
                    description=f"Impersonated contract: {contract_address}",
                    evidence=[f"Claims to be {claimed_project}", f"Official: {official_contract}"],
                    token_address=contract_address,
                    blocked=True,
                )
            
            return verified
        
        return False
    
    def check_operator_protection(
        self,
        input_text: str,
        requested_action: str,
    ) -> bool:
        """Check if input attempts to override operator controls."""
        # Patterns that attempt to override risk/policy
        override_patterns = [
            "increase.*limit",
            "remove.*limit",
            "disable.*check",
            "bypass.*policy",
            "override.*governance",
            "change.*parameter",
        ]
        
        input_lower = input_text.lower()
        
        for pattern in override_patterns:
            if re.search(pattern, input_lower):
                logger.warning(
                    f"Operator protection triggered: attempted override via '{pattern}'"
                )
                
                self._create_alert(
                    scam_type=ScamType.OVERRIDE_INSTRUCTION,
                    risk_level=ScamRiskLevel.HIGH,
                    description="Attempted override of operator controls",
                    evidence=[f"Pattern: {pattern}", f"Action: {requested_action}"],
                    blocked=True,
                    escalated=True,
                )
                
                return False  # Block action
        
        return True  # Allow action
    
    def _is_lookalike(self, domain1: str, domain2: str) -> bool:
        """Check if domain1 is a lookalike of domain2."""
        # Simple lookalike detection
        # Real implementation would use more sophisticated techniques
        
        # Character substitutions
        substitutions = {
            '0': 'o',
            '1': 'i',
            '1': 'l',
            'vv': 'w',
        }
        
        normalized1 = domain1.lower()
        normalized2 = domain2.lower()
        
        for old, new in substitutions.items():
            normalized1 = normalized1.replace(old, new)
        
        # Check if very similar
        if normalized1 == normalized2 and domain1 != domain2:
            return True
        
        # Check for extra characters
        if domain2 in domain1 and domain1 != domain2:
            return True
        
        return False
    
    def _risk_level_value(self, level: ScamRiskLevel) -> int:
        """Convert risk level to numeric value."""
        return {
            ScamRiskLevel.LOW: 1,
            ScamRiskLevel.MEDIUM: 2,
            ScamRiskLevel.HIGH: 3,
            ScamRiskLevel.CRITICAL: 4,
        }[level]
    
    def _create_alert(
        self,
        scam_type: ScamType,
        risk_level: ScamRiskLevel,
        description: str,
        evidence: List[str],
        token_address: Optional[str] = None,
        domain: Optional[str] = None,
        user_id: Optional[str] = None,
        blocked: bool = False,
        escalated: bool = False,
    ) -> ScamAlert:
        """Create scam alert."""
        alert_id = f"alert_{int(datetime.utcnow().timestamp())}"
        
        alert = ScamAlert(
            alert_id=alert_id,
            scam_type=scam_type,
            risk_level=risk_level,
            description=description,
            evidence=evidence,
            token_address=token_address,
            domain=domain,
            user_id=user_id,
            action_taken="blocked" if blocked else "flagged",
            blocked=blocked,
            escalated=escalated,
        )
        
        self._alerts.append(alert)
        
        logger.warning(
            f"Scam alert [{risk_level.value}]: {scam_type.value} - {description}"
        )
        
        return alert
    
    def get_threats(
        self,
        input_source: Optional[InputSource] = None,
        risk_level: Optional[ScamRiskLevel] = None,
        blocked_only: bool = False,
    ) -> List[InputThreat]:
        """Get detected threats."""
        threats = self._threats
        
        if input_source:
            threats = [t for t in threats if t.input_source == input_source]
        
        if risk_level:
            threats = [t for t in threats if t.risk_level == risk_level]
        
        if blocked_only:
            threats = [t for t in threats if t.blocked]
        
        return threats
    
    def get_active_alerts(
        self,
        scam_type: Optional[ScamType] = None,
        risk_level: Optional[ScamRiskLevel] = None,
    ) -> List[ScamAlert]:
        """Get active alerts."""
        alerts = [a for a in self._alerts if not a.resolved_at]
        
        if scam_type:
            alerts = [a for a in alerts if a.scam_type == scam_type]
        
        if risk_level:
            alerts = [a for a in alerts if a.risk_level == risk_level]
        
        return alerts


_scam_protection_agent: Optional[ScamProtectionAgent] = None
_scam_protection_agent_lock = threading.Lock()


def get_scam_protection_agent() -> ScamProtectionAgent:
    """Get global ScamProtectionAgent instance."""
    global _scam_protection_agent
    if _scam_protection_agent is None:
        with _scam_protection_agent_lock:
            if _scam_protection_agent is None:
                _scam_protection_agent = ScamProtectionAgent()
    return _scam_protection_agent
