"""
IP protection and legal compliance system for MERID.

Implements:
- Copyright and trademark management
- AI output attribution and disclaimers
- Patent and proprietary rights tracking
- Legal guardrails for agents
- Compliance monitoring
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class IPType(Enum):
    """Intellectual property type."""
    COPYRIGHT = "copyright"
    TRADEMARK = "trademark"
    PATENT = "patent"
    TRADE_SECRET = "trade_secret"


class LicenseType(Enum):
    """License type."""
    PROPRIETARY = "proprietary"
    APACHE_2 = "apache_2"
    MIT = "mit"
    GPL_3 = "gpl_3"
    AGPL_3 = "agpl_3"
    CUSTOM = "custom"


class DisclaimerType(Enum):
    """Disclaimer type."""
    AI_GENERATED = "ai_generated"
    NO_FINANCIAL_ADVICE = "no_financial_advice"
    NO_GUARANTEE = "no_guarantee"
    RISK_WARNING = "risk_warning"
    BETA_SOFTWARE = "beta_software"


@dataclass
class CopyrightNotice:
    """Copyright notice."""
    notice_id: str
    
    # Content
    year: int
    owner: str
    notice_text: str
    
    # Placement
    locations: List[str] = field(default_factory=list)  # UI footer, code headers, docs
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TrademarkRegistration:
    """Trademark registration."""
    trademark_id: str
    
    # Mark
    mark_text: str
    mark_type: str  # word, logo, combined
    
    # Registration
    jurisdiction: str  # US, EU, etc.
    registration_number: Optional[str] = None
    filing_date: Optional[datetime] = None
    registration_date: Optional[datetime] = None
    
    # Classes
    nice_classes: List[int] = field(default_factory=list)
    
    # Status
    status: str = "pending"  # pending, registered, opposed, cancelled
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PatentFiling:
    """Patent filing."""
    patent_id: str
    
    # Invention
    title: str
    description: str
    inventors: List[str] = field(default_factory=list)
    
    # Filing
    jurisdiction: str
    application_number: Optional[str] = None
    filing_date: Optional[datetime] = None
    
    # Status
    status: str = "pending"  # pending, granted, rejected
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AIOutputAttribution:
    """AI output attribution."""
    attribution_id: str
    
    # Output
    output_type: str  # code, text, strategy, design
    output_id: str
    
    # Attribution
    generated_by: str  # agent_id or model name
    attribution_text: str
    
    # Disclaimer
    disclaimer_types: List[DisclaimerType] = field(default_factory=list)
    
    # Metadata
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LegalGuardrail:
    """Legal guardrail for agents."""
    guardrail_id: str
    
    # Rule
    rule_type: str  # no_raw_keys, no_financial_advice, no_ip_infringement
    rule_description: str
    
    # Enforcement
    enforcement_level: str = "block"  # warn, block
    
    # Violations
    violation_count: int = 0
    
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ComplianceCheck:
    """Compliance check."""
    check_id: str
    
    # Scope
    component: str
    check_type: str
    
    # Result
    compliant: bool = False
    findings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    executed_at: datetime = field(default_factory=datetime.utcnow)


class IPProtectionSystem:
    """
    IP protection and legal compliance system.
    
    Features:
    - Copyright and trademark management
    - AI output attribution
    - Legal guardrails for agents
    - Compliance monitoring
    """
    
    def __init__(self, owner_entity: str = "MERID Technologies Inc."):
        self._owner_entity = owner_entity
        
        self._copyright_notices: Dict[str, CopyrightNotice] = {}
        self._trademarks: Dict[str, TrademarkRegistration] = {}
        self._patents: Dict[str, PatentFiling] = {}
        self._attributions: List[AIOutputAttribution] = []
        self._guardrails: Dict[str, LegalGuardrail] = {}
        self._compliance_checks: List[ComplianceCheck] = []
        
        self._initialize_copyright_notices()
        self._initialize_legal_guardrails()
    
    def _initialize_copyright_notices(self) -> None:
        """Initialize copyright notices."""
        current_year = datetime.utcnow().year
        
        # Main platform notice
        self.add_copyright_notice(
            year=current_year,
            owner=self._owner_entity,
            notice_text=f"© {current_year} {self._owner_entity}. All rights reserved. "
                       f"MERID™ is a trademark of {self._owner_entity}.",
            locations=["ui_footer", "docs", "api_responses"],
        )
        
        # Code header notice
        self.add_copyright_notice(
            year=current_year,
            owner=self._owner_entity,
            notice_text=f"Copyright {current_year} {self._owner_entity}\n"
                       f"All rights reserved.\n"
                       f"This source code is proprietary and confidential.",
            locations=["code_headers"],
        )
        
        logger.info("Initialized copyright notices")
    
    def _initialize_legal_guardrails(self) -> None:
        """Initialize legal guardrails."""
        
        # No raw private keys to agents
        self.add_legal_guardrail(
            rule_type="no_raw_keys",
            rule_description="Agents must never receive or handle raw private keys. "
                           "All signing via HSM/MPC with intent-based requests.",
            enforcement_level="block",
        )
        
        # No financial advice
        self.add_legal_guardrail(
            rule_type="no_financial_advice",
            rule_description="AI outputs must not be presented as financial, legal, or tax advice. "
                           "Always include appropriate disclaimers.",
            enforcement_level="warn",
        )
        
        # No IP infringement
        self.add_legal_guardrail(
            rule_type="no_ip_infringement",
            rule_description="Agents must not reproduce copyrighted material beyond fair use, "
                           "reveal trade secrets, or generate content that violates IP laws.",
            enforcement_level="block",
        )
        
        # No guaranteed profits
        self.add_legal_guardrail(
            rule_type="no_guaranteed_profits",
            rule_description="Agents must not present outputs as guaranteed profits or returns. "
                           "Always surface risks and uncertainty.",
            enforcement_level="warn",
        )
        
        # Attribute external sources
        self.add_legal_guardrail(
            rule_type="attribute_sources",
            rule_description="Agents must appropriately attribute external sources and data.",
            enforcement_level="warn",
        )
        
        logger.info(f"Initialized {len(self._guardrails)} legal guardrails")
    
    def add_copyright_notice(
        self,
        year: int,
        owner: str,
        notice_text: str,
        locations: List[str],
    ) -> CopyrightNotice:
        """Add copyright notice."""
        notice_id = f"copyright_{len(self._copyright_notices)}"
        
        notice = CopyrightNotice(
            notice_id=notice_id,
            year=year,
            owner=owner,
            notice_text=notice_text,
            locations=locations,
        )
        
        self._copyright_notices[notice_id] = notice
        
        logger.info(f"Added copyright notice '{notice_id}' for {owner}")
        
        return notice
    
    def register_trademark(
        self,
        mark_text: str,
        mark_type: str,
        jurisdiction: str,
        nice_classes: List[int],
    ) -> TrademarkRegistration:
        """Register trademark."""
        trademark_id = f"tm_{len(self._trademarks)}"
        
        trademark = TrademarkRegistration(
            trademark_id=trademark_id,
            mark_text=mark_text,
            mark_type=mark_type,
            jurisdiction=jurisdiction,
            nice_classes=nice_classes,
        )
        
        self._trademarks[trademark_id] = trademark
        
        logger.info(
            f"Registered trademark '{trademark_id}': {mark_text} "
            f"in {jurisdiction} (classes: {nice_classes})"
        )
        
        return trademark
    
    def file_patent(
        self,
        title: str,
        description: str,
        inventors: List[str],
        jurisdiction: str,
    ) -> PatentFiling:
        """File patent."""
        patent_id = f"patent_{len(self._patents)}"
        
        patent = PatentFiling(
            patent_id=patent_id,
            title=title,
            description=description,
            inventors=inventors,
            jurisdiction=jurisdiction,
        )
        
        self._patents[patent_id] = patent
        
        logger.info(f"Filed patent '{patent_id}': {title} in {jurisdiction}")
        
        return patent
    
    def add_ai_output_attribution(
        self,
        output_type: str,
        output_id: str,
        generated_by: str,
        disclaimer_types: Optional[List[DisclaimerType]] = None,
    ) -> AIOutputAttribution:
        """Add AI output attribution."""
        attribution_id = f"attr_{int(datetime.utcnow().timestamp())}"
        
        # Generate attribution text
        attribution_text = (
            f"Generated by MERID AI Agents © {datetime.utcnow().year} {self._owner_entity}. "
            f"No assurance of accuracy. Not financial, legal, or tax advice."
        )
        
        attribution = AIOutputAttribution(
            attribution_id=attribution_id,
            output_type=output_type,
            output_id=output_id,
            generated_by=generated_by,
            attribution_text=attribution_text,
            disclaimer_types=disclaimer_types or [
                DisclaimerType.AI_GENERATED,
                DisclaimerType.NO_FINANCIAL_ADVICE,
                DisclaimerType.NO_GUARANTEE,
            ],
        )
        
        self._attributions.append(attribution)
        
        logger.debug(
            f"Added attribution '{attribution_id}' for {output_type} '{output_id}'"
        )
        
        return attribution
    
    def add_legal_guardrail(
        self,
        rule_type: str,
        rule_description: str,
        enforcement_level: str = "block",
    ) -> LegalGuardrail:
        """Add legal guardrail."""
        guardrail_id = f"guardrail_{rule_type}"
        
        guardrail = LegalGuardrail(
            guardrail_id=guardrail_id,
            rule_type=rule_type,
            rule_description=rule_description,
            enforcement_level=enforcement_level,
        )
        
        self._guardrails[guardrail_id] = guardrail
        
        logger.info(f"Added legal guardrail '{guardrail_id}': {rule_type}")
        
        return guardrail
    
    def check_guardrail_compliance(
        self,
        agent_id: str,
        action: str,
        action_data: Dict[str, Any],
    ) -> List[str]:
        """Check action against legal guardrails."""
        violations = []
        
        for guardrail in self._guardrails.values():
            if not guardrail.enabled:
                continue
            
            violated = False
            
            # Check specific guardrails
            if guardrail.rule_type == "no_raw_keys":
                if action_data.get("contains_private_key", False):
                    violated = True
            
            elif guardrail.rule_type == "no_financial_advice":
                if action == "generate_advice" and not action_data.get("has_disclaimer", False):
                    violated = True
            
            elif guardrail.rule_type == "no_ip_infringement":
                if action_data.get("reproduces_copyrighted_content", False):
                    violated = True
            
            elif guardrail.rule_type == "no_guaranteed_profits":
                if action_data.get("guarantees_profit", False):
                    violated = True
            
            if violated:
                guardrail.violation_count += 1
                violations.append(guardrail.rule_type)
                
                logger.warning(
                    f"Guardrail violation by {agent_id}: {guardrail.rule_type} "
                    f"(enforcement: {guardrail.enforcement_level})"
                )
        
        return violations
    
    def run_compliance_check(
        self,
        component: str,
        check_type: str,
    ) -> ComplianceCheck:
        """Run compliance check."""
        check_id = f"check_{int(datetime.utcnow().timestamp())}"
        
        findings = []
        recommendations = []
        compliant = True
        
        if check_type == "copyright_notices":
            # Check if copyright notices are present
            if not self._copyright_notices:
                findings.append("No copyright notices found")
                recommendations.append("Add copyright notices to UI, docs, and code")
                compliant = False
        
        elif check_type == "ai_attributions":
            # Check if AI outputs have attributions
            recent_attributions = [
                a for a in self._attributions
                if a.timestamp >= datetime.utcnow() - timedelta(hours=24)
            ]
            
            if len(recent_attributions) < 10:
                findings.append("Low AI output attribution rate")
                recommendations.append("Ensure all AI outputs include attribution")
        
        elif check_type == "guardrail_violations":
            # Check guardrail violations
            total_violations = sum(
                g.violation_count for g in self._guardrails.values()
            )
            
            if total_violations > 100:
                findings.append(f"High guardrail violation count: {total_violations}")
                recommendations.append("Review agent behavior and strengthen guardrails")
                compliant = False
        
        check = ComplianceCheck(
            check_id=check_id,
            component=component,
            check_type=check_type,
            compliant=compliant,
            findings=findings,
            recommendations=recommendations,
        )
        
        self._compliance_checks.append(check)
        
        logger.info(
            f"Compliance check '{check_id}': {component}/{check_type} - "
            f"{'PASS' if compliant else 'FAIL'}"
        )
        
        return check
    
    def get_disclaimer_text(
        self,
        disclaimer_types: List[DisclaimerType],
    ) -> str:
        """Get disclaimer text."""
        disclaimers = []
        
        for dtype in disclaimer_types:
            if dtype == DisclaimerType.AI_GENERATED:
                disclaimers.append(
                    "This content was generated by AI and may contain errors."
                )
            
            elif dtype == DisclaimerType.NO_FINANCIAL_ADVICE:
                disclaimers.append(
                    "This is not financial, legal, or tax advice. "
                    "Consult with qualified professionals before making decisions."
                )
            
            elif dtype == DisclaimerType.NO_GUARANTEE:
                disclaimers.append(
                    "No guarantee of accuracy, completeness, or results. "
                    "Past performance does not indicate future results."
                )
            
            elif dtype == DisclaimerType.RISK_WARNING:
                disclaimers.append(
                    "Trading and DeFi involve substantial risk of loss. "
                    "Only invest what you can afford to lose."
                )
            
            elif dtype == DisclaimerType.BETA_SOFTWARE:
                disclaimers.append(
                    "This is beta software. Use at your own risk."
                )
        
        return " ".join(disclaimers)
    
    def get_ip_protection_dashboard(self) -> Dict[str, Any]:
        """Get IP protection dashboard."""
        return {
            "copyright": {
                "notices": len(self._copyright_notices),
                "owner": self._owner_entity,
            },
            "trademarks": {
                "total": len(self._trademarks),
                "registered": sum(
                    1 for tm in self._trademarks.values()
                    if tm.status == "registered"
                ),
                "pending": sum(
                    1 for tm in self._trademarks.values()
                    if tm.status == "pending"
                ),
            },
            "patents": {
                "total": len(self._patents),
                "granted": sum(
                    1 for p in self._patents.values()
                    if p.status == "granted"
                ),
                "pending": sum(
                    1 for p in self._patents.values()
                    if p.status == "pending"
                ),
            },
            "ai_attributions": {
                "total": len(self._attributions),
                "last_24h": len([
                    a for a in self._attributions
                    if a.timestamp >= datetime.utcnow() - timedelta(hours=24)
                ]),
            },
            "guardrails": {
                "total": len(self._guardrails),
                "enabled": sum(1 for g in self._guardrails.values() if g.enabled),
                "total_violations": sum(
                    g.violation_count for g in self._guardrails.values()
                ),
            },
            "compliance": {
                "total_checks": len(self._compliance_checks),
                "compliant": sum(
                    1 for c in self._compliance_checks
                    if c.compliant
                ),
                "non_compliant": sum(
                    1 for c in self._compliance_checks
                    if not c.compliant
                ),
            },
        }


_ip_protection_system: Optional[IPProtectionSystem] = None


def get_ip_protection_system() -> IPProtectionSystem:
    """Get global IPProtectionSystem instance."""
    global _ip_protection_system
    if _ip_protection_system is None:
        _ip_protection_system = IPProtectionSystem()
    return _ip_protection_system
