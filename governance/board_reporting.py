"""
Board-Level MI Reporting and Accountability Framework

Provides:
- Management Information (MI) reports for board oversight
- Accountability mapping for governance decisions
- Risk exposure summaries
- Compliance status reporting
- Performance attribution
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import threading

logger = get_logger(__name__)


class ReportType(Enum):
    """Types of board reports."""
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_REVIEW = "weekly_review"
    MONTHLY_BOARD = "monthly_board"
    QUARTERLY_GOVERNANCE = "quarterly_governance"
    INCIDENT_REPORT = "incident_report"
    COMPLIANCE_AUDIT = "compliance_audit"
    RISK_ASSESSMENT = "risk_assessment"


class AccountabilityLevel(Enum):
    """Levels of accountability."""
    BOARD = "board"
    EXECUTIVE = "executive"
    MANAGEMENT = "management"
    OPERATIONAL = "operational"
    AUTOMATED = "automated"


class RiskCategory(Enum):
    """Risk categories for reporting."""
    MARKET = "market"
    CREDIT = "credit"
    LIQUIDITY = "liquidity"
    OPERATIONAL = "operational"
    REGULATORY = "regulatory"
    TECHNOLOGY = "technology"
    REPUTATIONAL = "reputational"


class ComplianceStatus(Enum):
    """Compliance status levels."""
    COMPLIANT = "compliant"
    MINOR_ISSUES = "minor_issues"
    MATERIAL_ISSUES = "material_issues"
    NON_COMPLIANT = "non_compliant"


@dataclass
class AccountabilityMapping:
    """Maps decisions to accountable parties."""
    mapping_id: str
    decision_type: str
    
    board_accountable: List[str] = field(default_factory=list)
    executive_accountable: List[str] = field(default_factory=list)
    management_accountable: List[str] = field(default_factory=list)
    
    escalation_path: List[str] = field(default_factory=list)
    approval_requirements: Dict[str, Any] = field(default_factory=dict)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RiskExposure:
    """Risk exposure summary."""
    category: RiskCategory
    
    current_exposure: float = 0.0
    limit: float = 0.0
    utilization_pct: float = 0.0
    
    var_1d: float = 0.0
    var_10d: float = 0.0
    stress_loss: float = 0.0
    
    trend: str = "stable"
    alerts: List[str] = field(default_factory=list)
    
    as_of: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ComplianceItem:
    """A compliance item for reporting."""
    item_id: str
    requirement: str
    
    status: ComplianceStatus
    
    last_review: datetime = field(default_factory=datetime.utcnow)
    next_review: Optional[datetime] = None
    
    findings: List[str] = field(default_factory=list)
    remediation_actions: List[str] = field(default_factory=list)
    
    owner: str = ""
    reviewer: str = ""


@dataclass
class PerformanceAttribution:
    """Performance attribution for reporting."""
    period: str
    
    total_return: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    
    by_strategy: Dict[str, float] = field(default_factory=dict)
    by_asset_class: Dict[str, float] = field(default_factory=dict)
    by_agent: Dict[str, float] = field(default_factory=dict)
    
    risk_adjusted_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    
    as_of: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BoardReport:
    """A board-level MI report."""
    report_id: str
    report_type: ReportType
    
    title: str
    period_start: datetime
    period_end: datetime
    
    executive_summary: str = ""
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    
    risk_exposures: List[RiskExposure] = field(default_factory=list)
    compliance_items: List[ComplianceItem] = field(default_factory=list)
    performance: Optional[PerformanceAttribution] = None
    
    incidents: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    action_items: List[Dict[str, Any]] = field(default_factory=list)
    
    prepared_by: str = ""
    reviewed_by: str = ""
    approved_by: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "draft"


@dataclass
class PublicGoodsFundingSummary:
    """QF / grants round snapshot for governance reporting."""
    round_id: str
    created_at: datetime
    matching_pool_usd: float
    total_direct_usd: float
    total_matched_usd: float
    total_allocated_usd: float
    funded_projects: int
    governance_notes: List[str] = field(default_factory=list)
    breakdown: List[Dict[str, Any]] = field(default_factory=list)


class BoardReportingFramework:
    """
    Board-Level MI Reporting Framework.
    
    Features:
    - Automated report generation
    - Accountability mapping
    - Risk exposure aggregation
    - Compliance status tracking
    - Performance attribution
    """
    
    def __init__(self):
        self._reports: Dict[str, BoardReport] = {}
        self._accountability_mappings: Dict[str, AccountabilityMapping] = {}
        self._risk_exposures: Dict[RiskCategory, RiskExposure] = {}
        self._compliance_items: Dict[str, ComplianceItem] = {}
        self._performance_history: List[PerformanceAttribution] = []
        self._public_goods_history: List[PublicGoodsFundingSummary] = []
        
        self._initialize_default_mappings()
        self._initialize_default_compliance()
    
    def _initialize_default_mappings(self) -> None:
        """Initialize default accountability mappings."""
        mappings = [
            AccountabilityMapping(
                mapping_id="strategy_approval",
                decision_type="New Strategy Deployment",
                board_accountable=["Risk Committee"],
                executive_accountable=["CIO", "CRO"],
                management_accountable=["Head of Quant", "Head of Risk"],
                escalation_path=["Management", "Executive", "Board"],
                approval_requirements={
                    "backtest_required": True,
                    "risk_review_required": True,
                    "capital_threshold_usd": 100000,
                },
            ),
            AccountabilityMapping(
                mapping_id="risk_limit_change",
                decision_type="Risk Limit Modification",
                board_accountable=["Risk Committee", "Audit Committee"],
                executive_accountable=["CRO"],
                management_accountable=["Head of Risk"],
                escalation_path=["Management", "CRO", "Risk Committee"],
                approval_requirements={
                    "dual_approval": True,
                    "documentation_required": True,
                },
            ),
            AccountabilityMapping(
                mapping_id="agent_deployment",
                decision_type="AI Agent Deployment",
                board_accountable=["Technology Committee"],
                executive_accountable=["CTO", "CIO"],
                management_accountable=["Head of AI", "Head of Engineering"],
                escalation_path=["Management", "Executive", "Technology Committee"],
                approval_requirements={
                    "testing_required": True,
                    "security_review_required": True,
                    "canary_deployment": True,
                },
            ),
            AccountabilityMapping(
                mapping_id="custody_change",
                decision_type="Custody Arrangement Change",
                board_accountable=["Board", "Audit Committee"],
                executive_accountable=["CEO", "CFO"],
                management_accountable=["Head of Operations", "Head of Compliance"],
                escalation_path=["Management", "Executive", "Board"],
                approval_requirements={
                    "legal_review_required": True,
                    "security_audit_required": True,
                    "board_approval_required": True,
                },
            ),
        ]
        
        for mapping in mappings:
            self._accountability_mappings[mapping.mapping_id] = mapping
        
        logger.info(f"Initialized {len(mappings)} accountability mappings")
    
    def _initialize_default_compliance(self) -> None:
        """Initialize default compliance items."""
        items = [
            ComplianceItem(
                item_id="aml_kyc",
                requirement="AML/KYC Compliance",
                status=ComplianceStatus.COMPLIANT,
                owner="Head of Compliance",
                next_review=datetime.utcnow() + timedelta(days=90),
            ),
            ComplianceItem(
                item_id="data_protection",
                requirement="Data Protection (GDPR/CCPA)",
                status=ComplianceStatus.COMPLIANT,
                owner="Data Protection Officer",
                next_review=datetime.utcnow() + timedelta(days=180),
            ),
            ComplianceItem(
                item_id="market_conduct",
                requirement="Market Conduct Rules",
                status=ComplianceStatus.COMPLIANT,
                owner="Head of Compliance",
                next_review=datetime.utcnow() + timedelta(days=30),
            ),
            ComplianceItem(
                item_id="custody_requirements",
                requirement="Custody and Safekeeping",
                status=ComplianceStatus.COMPLIANT,
                owner="Head of Operations",
                next_review=datetime.utcnow() + timedelta(days=90),
            ),
            ComplianceItem(
                item_id="disclosure_requirements",
                requirement="Disclosure and Transparency",
                status=ComplianceStatus.COMPLIANT,
                owner="Head of Legal",
                next_review=datetime.utcnow() + timedelta(days=30),
            ),
        ]
        
        for item in items:
            self._compliance_items[item.item_id] = item
        
        logger.info(f"Initialized {len(items)} compliance items")
    
    def update_risk_exposure(
        self,
        category: RiskCategory,
        current_exposure: float,
        limit: float,
        var_1d: float = 0.0,
        var_10d: float = 0.0,
        stress_loss: float = 0.0,
    ) -> RiskExposure:
        """Update risk exposure for a category."""
        utilization = (current_exposure / limit * 100) if limit > 0 else 0.0
        
        prev = self._risk_exposures.get(category)
        if prev:
            if current_exposure > prev.current_exposure * 1.1:
                trend = "increasing"
            elif current_exposure < prev.current_exposure * 0.9:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        alerts = []
        if utilization > 90:
            alerts.append(f"CRITICAL: {category.value} utilization at {utilization:.1f}%")
        elif utilization > 75:
            alerts.append(f"WARNING: {category.value} utilization at {utilization:.1f}%")
        
        exposure = RiskExposure(
            category=category,
            current_exposure=current_exposure,
            limit=limit,
            utilization_pct=utilization,
            var_1d=var_1d,
            var_10d=var_10d,
            stress_loss=stress_loss,
            trend=trend,
            alerts=alerts,
        )
        
        self._risk_exposures[category] = exposure
        return exposure
    
    def update_compliance_status(
        self,
        item_id: str,
        status: ComplianceStatus,
        findings: Optional[List[str]] = None,
        remediation_actions: Optional[List[str]] = None,
    ) -> Optional[ComplianceItem]:
        """Update compliance status for an item."""
        if item_id not in self._compliance_items:
            return None
        
        item = self._compliance_items[item_id]
        item.status = status
        item.last_review = datetime.utcnow()
        
        if findings:
            item.findings = findings
        if remediation_actions:
            item.remediation_actions = remediation_actions
        
        return item
    
    def record_performance(
        self,
        period: str,
        total_return: float,
        benchmark_return: float,
        by_strategy: Dict[str, float],
        by_asset_class: Dict[str, float],
        by_agent: Dict[str, float],
        sharpe_ratio: float,
        max_drawdown: float,
    ) -> PerformanceAttribution:
        """Record performance attribution."""
        attribution = PerformanceAttribution(
            period=period,
            total_return=total_return,
            benchmark_return=benchmark_return,
            alpha=total_return - benchmark_return,
            by_strategy=by_strategy,
            by_asset_class=by_asset_class,
            by_agent=by_agent,
            risk_adjusted_return=total_return / max(0.01, max_drawdown),
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
        )
        
        self._performance_history.append(attribution)
        return attribution
    
    def generate_report(
        self,
        report_type: ReportType,
        period_start: datetime,
        period_end: datetime,
        prepared_by: str,
    ) -> BoardReport:
        """Generate a board report."""
        report_id = f"report_{report_type.value}_{int(datetime.utcnow().timestamp())}"
        
        if report_type == ReportType.DAILY_SUMMARY:
            title = f"Daily Summary - {period_end.strftime('%Y-%m-%d')}"
        elif report_type == ReportType.WEEKLY_REVIEW:
            title = f"Weekly Review - Week {period_end.isocalendar()[1]}"
        elif report_type == ReportType.MONTHLY_BOARD:
            title = f"Monthly Board Report - {period_end.strftime('%B %Y')}"
        elif report_type == ReportType.QUARTERLY_GOVERNANCE:
            quarter = (period_end.month - 1) // 3 + 1
            title = f"Quarterly Governance Report - Q{quarter} {period_end.year}"
        else:
            title = f"{report_type.value.replace('_', ' ').title()} Report"
        
        risk_exposures = list(self._risk_exposures.values())
        compliance_items = list(self._compliance_items.values())
        
        recent_performance = (
            self._performance_history[-1] if self._performance_history else None
        )
        
        key_metrics = self._calculate_key_metrics(risk_exposures, compliance_items)
        executive_summary = self._generate_executive_summary(
            key_metrics, risk_exposures, compliance_items
        )
        recommendations = self._generate_recommendations(
            risk_exposures, compliance_items
        )
        
        report = BoardReport(
            report_id=report_id,
            report_type=report_type,
            title=title,
            period_start=period_start,
            period_end=period_end,
            executive_summary=executive_summary,
            key_metrics=key_metrics,
            risk_exposures=risk_exposures,
            compliance_items=compliance_items,
            performance=recent_performance,
            recommendations=recommendations,
            prepared_by=prepared_by,
        )
        
        self._reports[report_id] = report
        logger.info(f"Generated report '{report_id}': {title}")
        return report
    
    def _calculate_key_metrics(
        self,
        risk_exposures: List[RiskExposure],
        compliance_items: List[ComplianceItem],
    ) -> Dict[str, Any]:
        """Calculate key metrics for report."""
        total_var = sum(r.var_1d for r in risk_exposures)
        max_utilization = max((r.utilization_pct for r in risk_exposures), default=0)
        
        compliant_count = sum(
            1 for c in compliance_items if c.status == ComplianceStatus.COMPLIANT
        )
        compliance_rate = (
            compliant_count / len(compliance_items) * 100
            if compliance_items else 100
        )
        
        critical_alerts = sum(
            len([a for a in r.alerts if "CRITICAL" in a])
            for r in risk_exposures
        )
        
        return {
            "total_var_1d": total_var,
            "max_risk_utilization_pct": max_utilization,
            "compliance_rate_pct": compliance_rate,
            "critical_alerts": critical_alerts,
            "risk_categories_monitored": len(risk_exposures),
            "compliance_items_tracked": len(compliance_items),
        }
    
    def _generate_executive_summary(
        self,
        key_metrics: Dict[str, Any],
        risk_exposures: List[RiskExposure],
        compliance_items: List[ComplianceItem],
    ) -> str:
        """Generate executive summary."""
        lines = []
        
        lines.append("EXECUTIVE SUMMARY")
        lines.append("-" * 40)
        
        if key_metrics["critical_alerts"] > 0:
            lines.append(f"⚠️ {key_metrics['critical_alerts']} critical risk alerts require attention")
        else:
            lines.append("✓ No critical risk alerts")
        
        lines.append(f"Risk utilization: {key_metrics['max_risk_utilization_pct']:.1f}% (max)")
        lines.append(f"Compliance rate: {key_metrics['compliance_rate_pct']:.1f}%")
        lines.append(f"1-day VaR: ${key_metrics['total_var_1d']:,.0f}")
        
        non_compliant = [
            c for c in compliance_items
            if c.status in [ComplianceStatus.MATERIAL_ISSUES, ComplianceStatus.NON_COMPLIANT]
        ]
        if non_compliant:
            lines.append(f"\n⚠️ {len(non_compliant)} compliance items require remediation")
        
        return "\n".join(lines)
    
    def _generate_recommendations(
        self,
        risk_exposures: List[RiskExposure],
        compliance_items: List[ComplianceItem],
    ) -> List[str]:
        """Generate recommendations."""
        recommendations = []
        
        for exposure in risk_exposures:
            if exposure.utilization_pct > 80:
                recommendations.append(
                    f"Review {exposure.category.value} risk limits - "
                    f"utilization at {exposure.utilization_pct:.1f}%"
                )
        
        for item in compliance_items:
            if item.status == ComplianceStatus.MATERIAL_ISSUES:
                recommendations.append(
                    f"Prioritize remediation of {item.requirement}"
                )
            elif item.next_review and item.next_review < datetime.utcnow() + timedelta(days=7):
                recommendations.append(
                    f"Schedule review of {item.requirement} (due soon)"
                )
        
        return recommendations
    
    def get_accountability_for_decision(
        self,
        decision_type: str,
    ) -> Optional[AccountabilityMapping]:
        """Get accountability mapping for a decision type."""
        for mapping in self._accountability_mappings.values():
            if mapping.decision_type.lower() == decision_type.lower():
                return mapping
        return None
    
    def approve_report(
        self,
        report_id: str,
        reviewer: str,
        approver: str,
    ) -> bool:
        """Approve a report for distribution."""
        if report_id not in self._reports:
            return False
        
        report = self._reports[report_id]
        report.reviewed_by = reviewer
        report.approved_by = approver
        report.status = "approved"
        
        logger.info(f"Report '{report_id}' approved by {approver}")
        return True
    
    def get_report_summary(self) -> Dict[str, Any]:
        """Get summary of reporting status."""
        by_type = {}
        for report_type in ReportType:
            count = sum(
                1 for r in self._reports.values()
                if r.report_type == report_type
            )
            by_type[report_type.value] = count
        
        pending = sum(1 for r in self._reports.values() if r.status == "draft")
        approved = sum(1 for r in self._reports.values() if r.status == "approved")
        
        return {
            "total_reports": len(self._reports),
            "pending_approval": pending,
            "approved": approved,
            "by_type": by_type,
            "accountability_mappings": len(self._accountability_mappings),
            "compliance_items": len(self._compliance_items),
            "risk_categories": len(self._risk_exposures),
            "public_goods_rounds": len(self._public_goods_history),
        }

    # ------------------------------------------------------------------
    # Quadratic Funding integration
    # ------------------------------------------------------------------

    def record_public_goods_round(self, summary: Dict[str, Any]) -> PublicGoodsFundingSummary:
        """Record funding summary from quadratic funding program."""
        record = PublicGoodsFundingSummary(
            round_id=summary["round_id"],
            created_at=datetime.fromisoformat(summary["created_at"]),
            matching_pool_usd=summary["matching_pool_usd"],
            total_direct_usd=summary["total_direct_usd"],
            total_matched_usd=summary["total_matched_usd"],
            total_allocated_usd=summary["total_allocated_usd"],
            funded_projects=sum(1 for entry in summary["proposal_breakdown"] if entry.get("total_usd", 0) > 0),
            governance_notes=summary.get("governance_notes", []),
            breakdown=summary.get("proposal_breakdown", []),
        )
        self._public_goods_history.append(record)
        logger.info(
            "Recorded public goods funding round %s (allocated=$%.2f)",
            record.round_id,
            record.total_allocated_usd,
        )
        return record

    def recent_public_goods_rounds(self, limit: int = 5) -> List[PublicGoodsFundingSummary]:
        return self._public_goods_history[-limit:]


_framework: Optional[BoardReportingFramework] = None
_framework_lock = threading.Lock()


def get_board_reporting_framework() -> BoardReportingFramework:
    """Get global BoardReportingFramework instance."""
    global _framework
    if _framework is None:
        with _framework_lock:
            if _framework is None:
                _framework = BoardReportingFramework()
    return _framework


def reset_board_reporting_framework() -> BoardReportingFramework:
    """Reset the global BoardReportingFramework (primarily for tests)."""
    global _framework
    _framework = BoardReportingFramework()
    return _framework
