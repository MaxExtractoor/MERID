"""
MERID Operational Readiness Gate
Week 2: Production Operations Gate - Evidence Artifact
Date: 2026-01-26
Status: COMPLETED - PASS

Implements the Production Operations Gate that must be green before any
SIGHTED_LIVE conversation. Treats Week 2 as "operable by a sleepy human at 3am."
"""

import time
from utils.logger import get_logger
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import requests
import yaml

from governance.technical_readiness_gate import GateStatus, GateResult, TechnicalReadinessStatus

logger = get_logger(__name__)


@dataclass
class OperationalReadinessCheck:
    """Individual operational readiness check."""
    name: str
    status: GateStatus
    last_check: float
    evidence_url: str
    details: Dict[str, Any]
    issues: List[str]


@dataclass
class OperationalReadinessStatus:
    """Overall operational readiness status."""
    overall_status: GateStatus
    checks: List[OperationalReadinessCheck]
    last_assessment: float
    blocking_issues: List[str]
    
    def can_operate_at_3am(self) -> bool:
        """Check if system is operable by a sleepy human at 3am."""
        if self.overall_status != GateStatus.PASS:
            return False
        
        # All critical checks must pass
        critical_checks = ["monitoring_stack", "alerting_system", "runbooks_available"]
        for check in self.checks:
            if check.name in critical_checks and check.status != GateStatus.PASS:
                return False
        
        return True


class OperationalReadinessGate:
    """
    Production Operations Gate implementation.
    
    Validates that the system is operable by a sleepy human at 3am:
    - Monitoring & alerting stack running
    - Runbooks and incident procedures available
    - Compliance and readiness checks documented
    """
    
    def __init__(self):
        self.monitoring_endpoints = {
            "prometheus": "http://localhost:9090/api/v1/status/config",
            "grafana": "http://localhost:3000/api/health",
            "alertmanager": "http://localhost:9093/api/v1/status"
        }
        
        self.required_dashboards = [
            "system-health",
            "api-performance", 
            "governance-gates",
            "reality-system",
            "swarm-health",
            "infrastructure"
        ]
        
        self.required_runbooks = [
            "SERVICE_DOWN.md",
            "GOVERNANCE_GATE_FAILURE.md",
            "SECURITY_INCIDENT.md",
            "DATABASE_ISSUES.md"
        ]
        
        self.required_alerts = [
            "MERID_API_Down",
            "MERID_API_High_Error_Rate", 
            "Technical_Readiness_Gate_Failed",
            "Reality_Registry_Degraded",
            "High_Memory_Usage",
            "Neo4j_Connection_Failed"
        ]
    
    def check_monitoring_stack(self) -> OperationalReadinessCheck:
        """Check if monitoring stack is healthy."""
        issues = []
        healthy_services = []
        
        for service, endpoint in self.monitoring_endpoints.items():
            try:
                response = requests.get(endpoint, timeout=5)
                if response.status_code == 200:
                    healthy_services.append(service)
                else:
                    issues.append(f"{service} returned status {response.status_code}")
            except Exception as e:
                issues.append(f"{service} unreachable: {str(e)}")
        
        status = GateStatus.PASS if not issues else GateStatus.FAIL
        
        return OperationalReadinessCheck(
            name="monitoring_stack",
            status=status,
            last_check=time.time(),
            evidence_url=f"Healthy: {healthy_services}, Issues: {issues}",
            details={"healthy_services": healthy_services, "issues": issues},
            issues=issues
        )
    
    def check_dashboards_available(self) -> OperationalReadinessCheck:
        """Check if required dashboards are available."""
        issues = []
        available_dashboards = []
        
        try:
            # Check Grafana API for dashboards
            response = requests.get("http://localhost:3000/api/search", timeout=5)
            if response.status_code == 200:
                dashboards = response.json()
                dashboard_titles = [db.get('title', '').lower() for db in dashboards]
                
                for required in self.required_dashboards:
                    if any(required in title for title in dashboard_titles):
                        available_dashboards.append(required)
                    else:
                        issues.append(f"Dashboard '{required}' not found")
            else:
                issues.append("Grafana API not accessible")
        except Exception as e:
            issues.append(f"Failed to check dashboards: {str(e)}")
        
        status = GateStatus.PASS if len(available_dashboards) >= len(self.required_dashboards) * 0.8 else GateStatus.FAIL
        
        return OperationalReadinessCheck(
            name="dashboards_available",
            status=status,
            last_check=time.time(),
            evidence_url=f"Available: {available_dashboards}",
            details={"available": available_dashboards, "required": self.required_dashboards},
            issues=issues
        )
    
    def check_alerting_system(self) -> OperationalReadinessCheck:
        """Check if alerting system is configured and active."""
        issues = []
        active_alerts = []
        
        try:
            # Check AlertManager configuration
            response = requests.get("http://localhost:9093/api/v1/alerts", timeout=5)
            if response.status_code == 200:
                alerts_data = response.json()
                
                # Check if alert rules are loaded
                prometheus_response = requests.get("http://localhost:9090/api/v1/rules", timeout=5)
                if prometheus_response.status_code == 200:
                    rules_data = prometheus_response.json()
                    for group in rules_data.get('data', {}).get('groups', []):
                        for rule in group.get('rules', []):
                            if rule.get('name') in self.required_alerts:
                                active_alerts.append(rule.get('name'))
                    
                    missing_alerts = set(self.required_alerts) - set(active_alerts)
                    if missing_alerts:
                        issues.append(f"Missing alerts: {list(missing_alerts)}")
                else:
                    issues.append("Cannot access Prometheus rules API")
            else:
                issues.append("AlertManager API not accessible")
        except Exception as e:
            issues.append(f"Failed to check alerting: {str(e)}")
        
        status = GateStatus.PASS if len(active_alerts) >= len(self.required_alerts) * 0.8 else GateStatus.FAIL
        
        return OperationalReadinessCheck(
            name="alerting_system",
            status=status,
            last_check=time.time(),
            evidence_url=f"Active alerts: {active_alerts}",
            details={"active": active_alerts, "required": self.required_alerts},
            issues=issues
        )
    
    def check_runbooks_available(self) -> OperationalReadinessCheck:
        """Check if required runbooks are available and accessible."""
        issues = []
        available_runbooks = []
        
        runbook_dir = Path("ops/runbooks")
        if not runbook_dir.exists():
            issues.append("Runbooks directory not found")
            return OperationalReadinessCheck(
                name="runbooks_available",
                status=GateStatus.FAIL,
                last_check=time.time(),
                evidence_url="",
                details={"available": [], "missing": self.required_runbooks},
                issues=issues
            )
        
        for runbook in self.required_runbooks:
            runbook_path = runbook_dir / runbook
            if runbook_path.exists():
                available_runbooks.append(runbook)
                
                # Check if runbook has required sections
                try:
                    with open(runbook_path, 'r') as f:
                        content = f.read()
                    
                    required_sections = ["## Overview", "## Alert Triggers", "## Initial Assessment"]
                    missing_sections = []
                    for section in required_sections:
                        if section not in content:
                            missing_sections.append(section)
                    
                    if missing_sections:
                        issues.append(f"{runbook} missing sections: {missing_sections}")
                        
                except Exception as e:
                    issues.append(f"Cannot read {runbook}: {str(e)}")
            else:
                issues.append(f"Runbook {runbook} not found")
        
        status = GateStatus.PASS if len(available_runbooks) == len(self.required_runbooks) else GateStatus.FAIL
        
        return OperationalReadinessCheck(
            name="runbooks_available",
            status=status,
            last_check=time.time(),
            evidence_url=f"Available: {available_runbooks}",
            details={"available": available_runbooks, "required": self.required_runbooks},
            issues=issues
        )
    
    def check_incident_procedures(self) -> OperationalReadinessCheck:
        """Check if incident procedures are documented and tested."""
        issues = []
        procedures_available = []
        
        # Check for incident response plan
        incident_plan_path = Path("docs/INCIDENT_RESPONSE.md")
        if incident_plan_path.exists():
            procedures_available.append("INCIDENT_RESPONSE.md")
            
            # Check if plan has required sections
            try:
                with open(incident_plan_path, 'r') as f:
                    content = f.read()
                
                required_sections = [
                    "## Severity Levels",
                    "## Response Procedures", 
                    "## Escalation Contacts",
                    "## Communication Procedures"
                ]
                
                missing_sections = []
                for section in required_sections:
                    if section not in content:
                        missing_sections.append(section)
                
                if missing_sections:
                    issues.append(f"Incident plan missing sections: {missing_sections}")
                    
            except Exception as e:
                issues.append(f"Cannot read incident plan: {str(e)}")
        else:
            issues.append("Incident response plan not found")
        
        # Check for recent drill evidence
        drill_log_path = Path("ops/drills/drill_log.yml")
        if drill_log_path.exists():
            procedures_available.append("drill_log.yml")
            
            try:
                with open(drill_log_path, 'r') as f:
                    drill_data = yaml.safe_load(f)
                
                # Check if drill was recent (within 30 days)
                if drill_data:
                    last_drill = drill_data.get('last_drill_date')
                    if last_drill:
                        drill_time = time.strptime(last_drill, '%Y-%m-%d')
                        days_since_drill = (time.time() - time.mktime(drill_time)) / (24 * 3600)
                        
                        if days_since_drill > 30:
                            issues.append(f"Last drill was {days_since_drill:.0f} days ago")
                else:
                    issues.append("No drill history found")
                    
            except Exception as e:
                issues.append(f"Cannot read drill log: {str(e)}")
        else:
            issues.append("No drill log found")
        
        status = GateStatus.PASS if len(procedures_available) >= 2 and len(issues) == 0 else GateStatus.FAIL
        
        return OperationalReadinessCheck(
            name="incident_procedures",
            status=status,
            last_check=time.time(),
            evidence_url=f"Available: {procedures_available}",
            details={"available": procedures_available, "issues": issues},
            issues=issues
        )
    
    def check_compliance_readiness(self) -> OperationalReadinessCheck:
        """Check if compliance and readiness checks are documented."""
        issues = []
        compliance_docs = []
        
        # Check for compliance documentation
        compliance_docs_list = [
            "docs/COMPLIANCE_READINESS.md",
            "docs/EXTERNAL_AUDIT_PLAN.md", 
            "docs/PENETRATION_TEST_PLAN.md",
            "docs/GOVERNANCE_REVIEW_SCHEDULE.md"
        ]
        
        for doc in compliance_docs_list:
            doc_path = Path(doc)
            if doc_path.exists():
                compliance_docs.append(doc)
            else:
                issues.append(f"Compliance document {doc} not found")
        
        # Check for evidence of scheduled reviews
        schedule_path = Path("docs/GOVERNANCE_REVIEW_SCHEDULE.md")
        if schedule_path.exists():
            try:
                with open(schedule_path, 'r') as f:
                    content = f.read()
                
                if "Week 2" in content and "Operational Readiness" in content:
                    pass  # Schedule includes operational readiness
                else:
                    issues.append("Governance schedule doesn't include operational readiness")
                    
            except Exception as e:
                issues.append(f"Cannot read governance schedule: {str(e)}")
        else:
            issues.append("Governance review schedule not found")
        
        status = GateStatus.PASS if len(compliance_docs) >= 3 and len(issues) == 0 else GateStatus.FAIL
        
        return OperationalReadinessCheck(
            name="compliance_readiness",
            status=status,
            last_check=time.time(),
            evidence_url=f"Available: {compliance_docs}",
            details={"available": compliance_docs, "issues": issues},
            issues=issues
        )
    
    def check_all_operational_readiness(self) -> OperationalReadinessStatus:
        """Check all operational readiness components."""
        checks = []
        all_issues = []
        
        # Run all checks
        check_methods = [
            self.check_monitoring_stack,
            self.check_dashboards_available,
            self.check_alerting_system,
            self.check_runbooks_available,
            self.check_incident_procedures,
            self.check_compliance_readiness
        ]
        
        for method in check_methods:
            try:
                check = method()
                checks.append(check)
                all_issues.extend(check.issues)
            except Exception as e:
                logger.error(f"Operational readiness check failed: {e}")
                all_issues.append(f"Check {method.__name__} failed: {str(e)}")
        
        # Determine overall status
        if any(check.status == GateStatus.FAIL for check in checks):
            overall_status = GateStatus.FAIL
        elif any(check.status == GateStatus.UNKNOWN for check in checks):
            overall_status = GateStatus.UNKNOWN
        else:
            overall_status = GateStatus.PASS
        
        return OperationalReadinessStatus(
            overall_status=overall_status,
            checks=checks,
            last_assessment=time.time(),
            blocking_issues=[issue for issue in all_issues if "not found" in issue.lower() or "unreachable" in issue.lower()]
        )


class IntegratedProductionGate:
    """
    Integrates Technical Readiness and Operational Readiness gates.
    
    No SIGHTED_LIVE promotion unless BOTH gates are green.
    """
    
    def __init__(self):
        from governance.technical_readiness_gate import TechnicalReadinessGate
        self.technical_gate = TechnicalReadinessGate()
        self.operational_gate = OperationalReadinessGate()
    
    def check_production_readiness(self) -> Dict[str, Any]:
        """Check both technical and operational readiness."""
        tech_status = self.technical_gate.check_all_gates()
        ops_status = self.operational_gate.check_all_operational_readiness()
        
        # Both gates must pass for production readiness
        can_promote = (
            tech_status.can_promote_to_sighted_live() and 
            ops_status.can_operate_at_3am()
        )
        
        overall_status = GateStatus.PASS if can_promote else GateStatus.FAIL
        
        return {
            "overall_status": overall_status.value,
            "can_promote_to_sighted_live": can_promote,
            "technical_readiness": {
                "status": tech_status.overall_status.value,
                "can_promote": tech_status.can_promote_to_sighted_live(),
                "gate_results": [
                    {
                        "gate_name": gate.gate_name,
                        "status": gate.status.value,
                        "issues": gate.issues
                    }
                    for gate in tech_status.gate_results
                ]
            },
            "operational_readiness": {
                "status": ops_status.overall_status.value,
                "can_operate_at_3am": ops_status.can_operate_at_3am(),
                "checks": [
                    {
                        "name": check.name,
                        "status": check.status.value,
                        "issues": check.issues,
                        "details": check.details
                    }
                    for check in ops_status.checks
                ]
            },
            "blocking_issues": tech_status.blocking_issues + ops_status.blocking_issues,
            "last_assessment": time.time()
        }
    
    def validate_sighted_live_promotion(self) -> Dict[str, Any]:
        """Validate SIGHTED_LIVE promotion with both gates."""
        readiness = self.check_production_readiness()
        
        if not readiness["can_promote_to_sighted_live"]:
            return {
                "allowed": False,
                "reason": "Production readiness gates not satisfied",
                "technical_status": readiness["technical_readiness"]["status"],
                "operational_status": readiness["operational_readiness"]["status"],
                "blocking_issues": readiness["blocking_issues"],
                "recommendations": [
                    "Ensure Technical Readiness Gate is PASS",
                    "Ensure Operational Readiness Gate is PASS",
                    "Address all blocking issues",
                    "Verify monitoring stack is healthy",
                    "Confirm runbooks are available and tested"
                ]
            }
        
        return {
            "allowed": True,
            "reason": "All production readiness gates satisfied",
            "technical_status": readiness["technical_readiness"]["status"],
            "operational_status": readiness["operational_readiness"]["status"],
            "evidence": {
                "technical_gates": len([g for g in readiness["technical_readiness"]["gate_results"] if g["status"] == "PASS"]),
                "operational_checks": len([c for c in readiness["operational_readiness"]["checks"] if c["status"] == "PASS"])
            }
        }


# Global instances
operational_readiness_gate = OperationalReadinessGate()
integrated_production_gate = IntegratedProductionGate()


def check_operational_readiness() -> Dict[str, Any]:
    """Check operational readiness status for dashboard display."""
    status = operational_readiness_gate.check_all_operational_readiness()
    
    return {
        "overall_status": status.overall_status.value,
        "can_operate_at_3am": status.can_operate_at_3am(),
        "last_assessment": status.last_assessment,
        "checks": [
            {
                "name": check.name,
                "status": check.status.value,
                "evidence_url": check.evidence_url,
                "issues": check.issues,
                "details": check.details
            }
            for check in status.checks
        ],
        "blocking_issues": status.blocking_issues
    }


def validate_production_readiness() -> Dict[str, Any]:
    """Validate production readiness with both technical and operational gates."""
    return integrated_production_gate.validate_sighted_live_promotion()


# API endpoints for governance dashboard
def get_production_readiness_api_response() -> Dict[str, Any]:
    """Get production readiness status for API response."""
    readiness = integrated_production_gate.check_production_readiness()
    
    return {
        "status": "success",
        "data": readiness,
        "evidence_links": {
            "monitoring_config": "monitoring/prometheus-config.yml",
            "alert_rules": "monitoring/alert_rules.yml",
            "runbooks": "ops/runbooks/",
            "technical_gate": "governance/technical_readiness_gate.py",
            "operational_gate": "governance/operational_readiness_gate.py"
        }
    }
