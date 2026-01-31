#!/usr/bin/env python3
"""
Weekly Release Dossier Summary Generator for MERID Season 1.

Creates canonical weekly narratives that tie together all changes, tests,
and behaviors for regulatory and stakeholder communication.
"""

import json
import argparse
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List
import hashlib

class WeeklyDossierSummary:
    """Generates weekly release dossier summaries for Season 1."""
    
    def __init__(self, week_number: int, year: int):
        self.week_number = week_number
        self.year = year
        self.week_start = datetime.strptime(f"{year}-W{week_number-1}-1", "%Y-W%U-%w")
        self.week_end = self.week_start + timedelta(days=6)
        self.summary_data = {
            "week_metadata": {
                "week_number": week_number,
                "year": year,
                "week_start": self.week_start.isoformat(),
                "week_end": self.week_end.isoformat(),
                "summary_id": hashlib.sha256(f"{year}-W{week_number}".encode()).hexdigest()[:16]
            },
            # Section A: Change Summary
            "change_summary": {
                "total_releases": 0,
                "features_deployed": [],
                "risk_control_changes": [],
                "security_enhancements": [],
                "bug_fixes": [],
                "infrastructure_changes": []
            },
            # Section B: Testing & Risk Lane Evidence
            "testing_evidence": {
                "unit_tests": {"total": 0, "passed": 0, "failed": 0, "coverage": 0.0},
                "integration_tests": {"total": 0, "passed": 0, "failed": 0},
                "chaos_experiments": {"total": 0, "passed": 0, "failed": 0},
                "security_scans": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "compliance_validations": {"total": 0, "passed": 0, "failed": 0}
            },
            # Section C: Security & Compliance
            "security_compliance": {
                "vulnerability_scan_results": {},
                "compliance_attestations": {},
                "audit_findings": [],
                "policy_violations": [],
                "remediation_actions": []
            },
            # Section D: Operational Metrics
            "operational_metrics": {
                "incidents": {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0},
                "rollbacks": {"total": 0, "reasons": []},
                "slo_performance": {"uptime": 0.0, "latency_p95": 0.0, "error_rate": 0.0},
                "mode_transitions": {"total": 0, "types": []},
                "priority_violations": {"total": 0, "domains": {}}
            },
            # Section E: Regulatory Notes
            "regulatory_notes": {
                "sec_references": [],
                "finra_compliance": {},
                "sox_controls": {},
                "data_retention": {},
                "audit_trail": {},
                "risk_management": {}
            },
            # Mode Promotion Readiness (NEW)
            "mode_promotion_readiness": {
                "target_mode": "SIGHTED_LIVE",
                "readiness_score": 0.0,
                "assertion_density": {"current": 0, "target": 0, "status": "insufficient"},
                "shadow_trading_pnl": {"current": 0.0, "target": 0.0, "drawdown": 0.0, "status": "insufficient"},
                "incident_rate": {"current": 0.0, "target": 0.0, "status": "insufficient"},
                "risk_conditions": {"passed": 0, "failed": 0, "blocking_issues": []},
                "evidence_accumulated": {
                    "weeks_stable": 0,
                    "assertion_consistency": 0.0,
                    "performance_benchmarks": {},
                    "security_posture": "unknown"
                },
                "missing_evidence": [],
                "recommendations": [],
                "estimated_readiness_date": None
            },
            # War Game Drill Results (NEW)
            "war_game_drills": {
                "drills_conducted": [],
                "overall_performance": {"score": 0.0, "grade": "F"},
                "response_time_metrics": {"avg_response_time": 0.0, "target_response_time": 300.0},
                "runbook_adherence": {"score": 0.0, "gaps_identified": []},
                "lessons_learned": [],
                "improvement_actions": []
            },
            # Legacy sections for backward compatibility
            "executive_summary": {},
            "technical_summary": {},
            "risk_summary": {},
            "compliance_summary": {},
            "operations_summary": {},
            "releases_deployed": [],
            "security_findings": {},
            "performance_metrics": {},
            "incidents_resolved": [],
            "improvements_made": [],
            "next_week_priorities": [],
            "stakeholder_communications": {},
            # Human annotations for qualitative context
            "human_annotations": {
                "drill_annotations": [],
                "change_annotations": [],
                "learning_annotations": [],
                "milestone_annotations": []
            }
        }
    
    def add_release_dossier(self, dossier_data: Dict[str, Any]):
        """Add a release dossier to the weekly summary."""
        release_info = {
            "version": dossier_data.get("release_metadata", {}).get("version", "unknown"),
            "timestamp": dossier_data.get("release_metadata", {}).get("timestamp", "unknown"),
            "pipeline_url": dossier_data.get("release_metadata", {}).get("pipeline_url", "unknown"),
            "compliance_score": dossier_data.get("compliance_score", 0),
            "overall_status": dossier_data.get("overall_status", "unknown"),
            "security_status": dossier_data.get("security_scan_results", {}).get("overall_security_status", "unknown"),
            "risk_control_status": dossier_data.get("risk_control_validation", {}).get("overall_risk_status", "unknown"),
            "compliance_status": dossier_data.get("compliance_attestation", {}).get("overall_compliance_status", "unknown")
        }
        
        # Update change summary
        self.summary_data["change_summary"]["total_releases"] += 1
        
        # Update testing evidence
        test_results = dossier_data.get("risk_control_validation", {})
        for test_type in ["runtime_primitive_tests", "domain_priority_tests", "sighted_degraded_activation"]:
            if test_type in test_results and test_results[test_type].get("passed"):
                self.summary_data["testing_evidence"]["compliance_validations"]["total"] += 1
                self.summary_data["testing_evidence"]["compliance_validations"]["passed"] += 1
        
        # Update security scan results
        security_results = dossier_data.get("security_scan_results", {})
        self.summary_data["testing_evidence"]["security_scans"]["critical"] += security_results.get("critical_vulnerabilities", 0)
        self.summary_data["testing_evidence"]["security_scans"]["high"] += security_results.get("high_vulnerabilities", 0)
        
        # Update operational metrics
        self.summary_data["operational_metrics"]["priority_violations"]["total"] += dossier_data.get("risk_control_validation", {}).get("priority_violations", 0)
        
        # Legacy compatibility
        self.summary_data["releases_deployed"].append(release_info)
    
    def add_security_findings(self, security_data: Dict[str, Any]):
        """Add security findings to the weekly summary."""
        self.summary_data["security_findings"] = {
            "critical_vulnerabilities": security_data.get("critical_vulnerabilities", 0),
            "high_vulnerabilities": security_data.get("high_vulnerabilities", 0),
            "medium_vulnerabilities": security_data.get("medium_vulnerabilities", 0),
            "secrets_found": security_data.get("secrets_found", 0),
            "security_scan_coverage": security_data.get("security_scan_coverage", 0),
            "remediation_actions": security_data.get("remediation_actions", []),
            "security_trends": security_data.get("security_trends", {})
        }
    
    def add_performance_metrics(self, performance_data: Dict[str, Any]):
        """Add performance metrics to the weekly summary."""
        self.summary_data["performance_metrics"] = {
            "avg_response_time_ms": performance_data.get("avg_response_time_ms", 0),
            "p95_response_time_ms": performance_data.get("p95_response_time_ms", 0),
            "error_rate": performance_data.get("error_rate", 0),
            "throughput": performance_data.get("throughput", 0),
            "resource_utilization": performance_data.get("resource_utilization", {}),
            "availability": performance_data.get("availability", 0),
            "performance_trends": performance_data.get("performance_trends", {})
        }
    
    def add_incidents_resolved(self, incidents: List[Dict[str, Any]]):
        """Add resolved incidents to the weekly summary."""
        self.summary_data["incidents_resolved"] = incidents
    
    def add_improvements_made(self, improvements: List[Dict[str, Any]]):
        """Add improvements made during the week."""
        self.summary_data["improvements_made"] = improvements
    
    def add_mode_promotion_assessment(self, assessment_data: Dict[str, Any]):
        """Add mode promotion readiness assessment."""
        self.summary_data["mode_promotion_readiness"].update(assessment_data)
    
    def add_war_game_drill_results(self, drill_results: Dict[str, Any]):
        """Add war game drill results."""
        self.summary_data["war_game_drills"]["drills_conducted"].append(drill_results)
        
        # Update overall performance metrics
        if "score" in drill_results:
            scores = [d.get("score", 0) for d in self.summary_data["war_game_drills"]["drills_conducted"]]
            avg_score = sum(scores) / len(scores) if scores else 0
            self.summary_data["war_game_drills"]["overall_performance"]["score"] = avg_score
            
            # Convert score to grade
            if avg_score >= 90:
                grade = "A"
            elif avg_score >= 80:
                grade = "B"
            elif avg_score >= 70:
                grade = "C"
            elif avg_score >= 60:
                grade = "D"
            else:
                grade = "F"
            self.summary_data["war_game_drills"]["overall_performance"]["grade"] = grade
    
    def calculate_mode_promotion_readiness(self) -> Dict[str, Any]:
        """Calculate overall mode promotion readiness score."""
        readiness = self.summary_data["mode_promotion_readiness"]
        
        # Calculate individual component scores
        scores = []
        
        # Assertion density score (30% weight)
        assertion_score = 0.0
        if readiness["assertion_density"]["current"] >= readiness["assertion_density"]["target"]:
            assertion_score = 100.0
            readiness["assertion_density"]["status"] = "met"
        else:
            ratio = readiness["assertion_density"]["current"] / readiness["assertion_density"]["target"]
            assertion_score = ratio * 100.0
            readiness["assertion_density"]["status"] = "insufficient"
        scores.append(("assertion_density", assertion_score, 0.3))
        
        # Shadow trading PnL score (25% weight)
        pnl_score = 0.0
        if (readiness["shadow_trading_pnl"]["current"] >= readiness["shadow_trading_pnl"]["target"] and 
            readiness["shadow_trading_pnl"]["drawdown"] <= 0.05):  # 5% max drawdown
            pnl_score = 100.0
            readiness["shadow_trading_pnl"]["status"] = "met"
        else:
            pnl_score = 50.0  # Partial credit
            readiness["shadow_trading_pnl"]["status"] = "insufficient"
        scores.append(("shadow_trading_pnl", pnl_score, 0.25))
        
        # Incident rate score (20% weight)
        incident_score = 0.0
        if readiness["incident_rate"]["current"] <= readiness["incident_rate"]["target"]:
            incident_score = 100.0
            readiness["incident_rate"]["status"] = "met"
        else:
            ratio = readiness["incident_rate"]["target"] / readiness["incident_rate"]["current"]
            incident_score = ratio * 100.0
            readiness["incident_rate"]["status"] = "insufficient"
        scores.append(("incident_rate", incident_score, 0.2))
        
        # Risk conditions score (15% weight)
        total_conditions = readiness["risk_conditions"]["passed"] + readiness["risk_conditions"]["failed"]
        if total_conditions > 0:
            risk_score = (readiness["risk_conditions"]["passed"] / total_conditions) * 100.0
        else:
            risk_score = 0.0
        scores.append(("risk_conditions", risk_score, 0.15))
        
        # Evidence accumulated score (10% weight)
        evidence_score = min(100.0, readiness["evidence_accumulated"]["weeks_stable"] * 12.5)  # 8 weeks = 100%
        scores.append(("evidence_accumulated", evidence_score, 0.1))
        
        # Calculate weighted average
        total_score = sum(score * weight for name, score, weight in scores)
        readiness["readiness_score"] = total_score
        
        # Generate recommendations
        readiness["recommendations"] = []
        if total_score < 100.0:
            for name, score, weight in scores:
                if score < 100.0:
                    readiness["recommendations"].append(f"Improve {name.replace('_', ' ').title()}: {score:.1f}%/100%")
        
        return readiness
    
    def generate_executive_summary(self) -> str:
        """Generate executive summary for stakeholders."""
        releases = self.summary_data["releases_deployed"]
        security = self.summary_data["security_findings"]
        
        summary = f"""
## Week {self.week_number} Executive Summary

### Key Metrics
- **Releases Deployed**: {len(releases)}
- **Security Posture**: {"HEALTHY" if security["critical_vulnerabilities"] == 0 else "ATTENTION"}
- **Critical Vulnerabilities**: {security["critical_vulnerabilities"]}
- **High Vulnerabilities**: {security["high_vulnerabilities"]}
- **Overall Availability**: {self.summary_data["performance_metrics"].get("availability", 0):.1f}%

### Releases This Week
"""
        
        for release in releases:
            summary += f"""
- **Version {release["version"]}**: {release["overall_status"]} (Compliance: {release["compliance_score"]:.1f}%)
"""
        
        summary += f"""
### Security Highlights
"""
        
        if security["critical_vulnerabilities"] > 0:
            summary += f"- WARNING: **{security['critical_vulnerabilities']} critical vulnerabilities** require immediate attention\n"
        
        if security["high_vulnerabilities"] > 0:
            summary += f"- HIGH: **{security['high_vulnerabilities']} high vulnerabilities** scheduled for remediation\n"
        
        if security["secrets_found"] > 0:
            summary += f"- SECURITY: **{security['secrets_found']} secrets** detected and remediated\n"
        
        summary += f"""
### Operational Status
- **System Mode**: {"SIGHTED_DEGRADED" if self._get_current_mode() == "SIGHTED_DEGRADED" else "BLIND"}
- **Risk Score**: {self._calculate_weekly_risk_score():.1f}%
- **Incidents Resolved**: {len(self.summary_data["incidents_resolved"])}
- **Improvements Made**: {len(self.summary_data["improvements_made"])}

### Next Week Priorities
"""
        
        for priority in self.summary_data["next_week_priorities"]:
            summary += f"- {priority}\n"
        
        return summary
    
    def generate_technical_summary(self) -> str:
        """Generate technical summary for engineering team."""
        releases = self.summary_data["releases_deployed"]
        performance = self.summary_data["performance_metrics"]
        
        summary = f"""
## Week {self.week_number} Technical Summary

### Deployments
"""
        
        for release in releases:
            summary += f"""
- **{release["version"]}**: {release["overall_status"]}
  - Pipeline: {release["pipeline_url"]}
  - Compliance Score: {release["compliance_score"]:.1f}%
  - Security: {release["security_status"]}
  - Risk Control: {release["risk_control_status"]}
"""
        
        summary += f"""
### Performance Metrics
- **Average Response Time**: {performance.get("avg_response_time_ms", 0):.1f}ms
- **P95 Response Time**: {performance.get("p95_response_time_ms", 0):.1f}ms
- **Error Rate**: {performance.get("error_rate", 0):.2f}%
- **Throughput**: {performance.get("throughput", 0)} req/s
- **Availability**: {performance.get("availability", 0):.1f}%
"""
        
        if performance.get("resource_utilization"):
            summary += f"""
### Resource Utilization
"""
            for resource, utilization in performance["resource_utilization"].items():
                summary += f"- **{resource}**: {utilization:.1f}%\n"
        
        summary += f"""
### Security Scan Results
- **Critical**: {self.summary_data["security_findings"]["critical_vulnerabilities"]}
- **High**: {self.summary_data["security_findings"]["high_vulnerabilities"]}
- **Medium**: {self.summary_data["security_findings"]["medium_vulnerabilities"]}
- **Coverage**: {self.summary_data["security_findings"]["security_scan_coverage"]:.1f}%

### Incidents Resolved
"""
        
        for incident in self.summary_data["incidents_resolved"]:
            summary += f"- **{incident.get('title', 'Unknown')}**: {incident.get('resolution', 'Unknown')}\n"
        
        return summary
    
    def generate_risk_summary(self) -> str:
        """Generate risk summary for risk management team."""
        summary = f"""
## Week {self.week_number} Risk Summary

### Risk Assessment
- **Overall Risk Score**: {self._calculate_weekly_risk_score():.1f}%
- **System Mode**: {self._get_current_mode()}
- **Valid Assertions**: {self._get_valid_assertions()}/20
- **Priority Violations**: {self._get_priority_violations()}
- **Mode Transitions**: {self._get_mode_transitions()}
- **Rollbacks**: {self._get_rollbacks()}

### Risk Control Validation
"""
        
        releases = self.summary_data["releases_deployed"]
        for release in releases:
            summary += f"""
- **{release["version"]}**: {release["risk_control_status"]}
"""
        
        summary += f"""
### Risk Trends
"""
        
        risk_trends = self.summary_data["security_findings"].get("security_trends", {})
        for trend, value in risk_trends.items():
            summary += f"- **{trend}**: {value}\n"
        
        summary += f"""
### Risk Mitigation
"""
        
        improvements = self.summary_data["improvements_made"]
        for improvement in improvements:
            if improvement.get("category") == "risk":
                summary += f"- **{improvement.get('title', 'Unknown')}**: {improvement.get('description', 'Unknown')}\n"
        
        return summary
    
    def generate_compliance_summary(self) -> str:
        """Generate compliance summary for compliance team."""
        summary = f"""
## Week {self.week_number} Compliance Summary

### SOX Compliance Status
- **Overall Status**: {"COMPLIANT" if self._is_sox_compliant() else "NON_COMPLIANT"}
- **Audit Trail Integrity**: {"INTACT" if self._is_audit_trail_intact() else "COMPROMISED"}
- **Data Retention**: {"COMPLIANT" if self._is_data_retention_compliant() else "NON_COMPLIANT"}
- **Access Control**: {"COMPLIANT" if self._is_access_control_compliant() else "NON_COMPLIANT"}

### Regulatory Reporting
- **FINRA**: {"COMPLIANT" if self._is_finra_compliant() else "NON_COMPLIANT"}
- **SEC**: {"COMPLIANT" if self._is_sec_compliant() else "NON_COMPLIANT"}
- **Internal Audit**: {"COMPLETED" if self._is_internal_audit_complete() else "PENDING"}

### Release Compliance
"""
        
        releases = self.summary_data["releases_deployed"]
        for release in releases:
            summary += f"""
- **{release["version"]}**: {release["compliance_status"]} (Score: {release["compliance_score"]:.1f}%)
"""
        
        summary += f"""
### Compliance Actions
"""
        
        improvements = self.summary_data["improvements_made"]
        for improvement in improvements:
            if improvement.get("category") == "compliance":
                summary += f"- **{improvement.get('title', 'Unknown')}**: {improvement.get('description', 'Unknown')}\n"
        
        return summary
    
    def generate_operations_summary(self) -> str:
        """Generate operations summary for operations team."""
        summary = f"""
## Week {self.week_number} Operations Summary

### System Health
- **Availability**: {self.summary_data["performance_metrics"].get("availability", 0):.1f}%
- **System Mode**: {self._get_current_mode()}
- **Active Alerts**: {self._get_active_alerts()}
- **Resource Utilization**: {self._get_avg_resource_utilization():.1f}%

### Deployments
"""
        
        releases = self.summary_data["releases_deployed"]
        for release in releases:
            summary += f"""
- **{release["version"]}**: {release["overall_status"]} at {release["timestamp"]}
"""
        
        summary += f"""
### Incidents
"""
        
        incidents = self.summary_data["incidents_resolved"]
        for incident in incidents:
            summary += f"""
- **{incident.get('title', 'Unknown')}**: {incident.get('severity', 'Unknown')} - {incident.get('resolution', 'Unknown')}
"""
        
        summary += f"""
### Maintenance Activities
"""
        
        improvements = self.summary_data["improvements_made"]
        for improvement in improvements:
            if improvement.get("category") == "operations":
                summary += f"- **{improvement.get('title', 'Unknown')}**: {improvement.get('description', 'Unknown')}\n"
        
        return summary
    
    def _get_current_mode(self) -> str:
        """Get current system mode."""
        # This would be fetched from the actual system
        return "SIGHTED_DEGRADED"  # Placeholder
    
    def _calculate_weekly_risk_score(self) -> float:
        """Calculate weekly risk score."""
        # This would be calculated from actual metrics
        return 85.0  # Placeholder
    
    def _get_valid_assertions(self) -> int:
        """Get count of valid assertions."""
        # This would be fetched from the actual system
        return 18  # Placeholder
    
    def _get_priority_violations(self) -> int:
        """Get count of priority violations."""
        # This would be fetched from the actual system
        return 3  # Placeholder
    
    def _get_mode_transitions(self) -> int:
        """Get count of mode transitions."""
        # This would be fetched from the actual system
        return 2  # Placeholder
    
    def _get_rollbacks(self) -> int:
        """Get count of rollbacks."""
        # This would be fetched from the actual system
        return 0  # Placeholder
    
    def _is_sox_compliant(self) -> bool:
        """Check SOX compliance."""
        # This would be checked from actual compliance data
        return True  # Placeholder
    
    def _is_audit_trail_intact(self) -> bool:
        """Check audit trail integrity."""
        # This would be checked from actual audit data
        return True  # Placeholder
    
    def _is_data_retention_compliant(self) -> bool:
        """Check data retention compliance."""
        # This would be checked from actual retention data
        return True  # Placeholder
    
    def _is_access_control_compliant(self) -> bool:
        """Check access control compliance."""
        # This would be checked from actual access control data
        return True  # Placeholder
    
    def _is_finra_compliant(self) -> bool:
        """Check FINRA compliance."""
        # This would be checked from actual compliance data
        return True  # Placeholder
    
    def _is_sec_compliant(self) -> bool:
        """Check SEC compliance."""
        # This would be checked from actual compliance data
        return True  # Placeholder
    
    def _is_internal_audit_complete(self) -> bool:
        """Check if internal audit is complete."""
        # This would be checked from actual audit data
        return True  # Placeholder
    
    def _get_active_alerts(self) -> int:
        """Get count of active alerts."""
        # This would be fetched from actual alert data
        return 2  # Placeholder
    
    def _get_avg_resource_utilization(self) -> float:
        """Get average resource utilization."""
        # This would be calculated from actual resource data
        return 65.0  # Placeholder
    
    def add_drill_annotation(self, annotation: str, author: str = "system"):
        """Add war-game drill annotation."""
        self.summary_data["human_annotations"]["drill_annotations"].append({
            "text": annotation,
            "author": author,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def add_change_annotation(self, annotation: str, author: str = "system"):
        """Add change/deployment annotation."""
        self.summary_data["human_annotations"]["change_annotations"].append({
            "text": annotation,
            "author": author,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def add_learning_annotation(self, annotation: str, author: str = "system"):
        """Add learning/insight annotation."""
        self.summary_data["human_annotations"]["learning_annotations"].append({
            "text": annotation,
            "author": author,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def add_milestone_annotation(self, annotation: str, author: str = "system"):
        """Add milestone annotation."""
        self.summary_data["human_annotations"]["milestone_annotations"].append({
            "text": annotation,
            "author": author,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def generate_learning_narrative(self) -> str:
        """Generate learning narrative from annotations."""
        narrative = f"""
## Week {self.week_number} Learning Narrative

### Key Insights
"""
        
        for annotation in self.summary_data["human_annotations"]["learning_annotations"]:
            narrative += f"- **{annotation['author']}**: {annotation['text']}\n"
        
        narrative += f"""
### Drill Performance Notes
"""
        
        for annotation in self.summary_data["human_annotations"]["drill_annotations"]:
            narrative += f"- **{annotation['author']}**: {annotation['text']}\n"
        
        narrative += f"""
### Change Impact
"""
        
        for annotation in self.summary_data["human_annotations"]["change_annotations"]:
            narrative += f"- **{annotation['author']}**: {annotation['text']}\n"
        
        narrative += f"""
### Milestones Achieved
"""
        
        for annotation in self.summary_data["human_annotations"]["milestone_annotations"]:
            narrative += f"- **{annotation['author']}**: {annotation['text']}\n"
        
        return narrative
    
    def add_next_week_priorities(self, priorities: List[str]):
        """Add next week priorities."""
        self.summary_data["next_week_priorities"] = priorities
    
    def generate_weekly_summary(self) -> Dict[str, Any]:
        """Generate complete weekly summary."""
        self.summary_data["executive_summary"] = self.generate_executive_summary()
        self.summary_data["technical_summary"] = self.generate_technical_summary()
        self.summary_data["risk_summary"] = self.generate_risk_summary()
        self.summary_data["compliance_summary"] = self.generate_compliance_summary()
        self.summary_data["operations_summary"] = self.generate_operations_summary()
        
        self.summary_data["summary_timestamp"] = datetime.utcnow().isoformat()
        self.summary_data["learning_narrative"] = self.generate_learning_narrative()
        
        return self.summary_data
    
    def generate_html_summary(self) -> str:
        """Generate HTML weekly summary."""
        summary = self.generate_weekly_summary()
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MERID Week {self.week_number} Summary - Season 1</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
            color: #333;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #eee;
        }}
        .section {{
            margin-bottom: 30px;
        }}
        .section h2 {{
            color: #333;
            border-bottom: 2px solid #007bff;
            padding-bottom: 10px;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }}
        .metric-label {{
            font-weight: 500;
            color: #666;
        }}
        .metric-value {{
            font-weight: bold;
            color: #333;
        }}
        .status-passed {{
            color: #28a745;
        }}
        .status-failed {{
            color: #dc3545;
        }}
        .status-warning {{
            color: #ffc107;
        }}
        .pre {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            overflow-x: auto;
            font-family: monospace;
            font-size: 12px;
        }}
        .download-links {{
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }}
        .download-links a {{
            display: inline-block;
            margin: 0 10px;
            padding: 10px 20px;
            background: #007bff;
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>MERID Week {self.week_number} Summary</h1>
            <p>Season 1 • {self.week_start.strftime('%B %d, %Y')} - {self.week_end.strftime('%B %d, %Y')}</p>
            <p>Summary ID: {self.summary_data['week_metadata']['summary_id']}</p>
        </div>
        
        <div class="section">
            <h2>Section A: Change Summary</h2>
            <div class="metric">
                <span class="metric-label">Total Releases:</span>
                <span class="metric-value">{self.summary_data['change_summary']['total_releases']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Features Deployed:</span>
                <span class="metric-value">{len(self.summary_data['change_summary']['features_deployed'])}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Risk Control Changes:</span>
                <span class="metric-value">{len(self.summary_data['change_summary']['risk_control_changes'])}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Security Enhancements:</span>
                <span class="metric-value">{len(self.summary_data['change_summary']['security_enhancements'])}</span>
            </div>
        </div>
        
        <div class="section">
            <h2>Section B: Testing & Risk Lane Evidence</h2>
            <div class="metric">
                <span class="metric-label">Unit Tests:</span>
                <span class="metric-value">{self.summary_data['testing_evidence']['unit_tests']['passed']}/{self.summary_data['testing_evidence']['unit_tests']['total']} ({self.summary_data['testing_evidence']['unit_tests']['coverage']:.1f}% coverage)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Integration Tests:</span>
                <span class="metric-value">{self.summary_data['testing_evidence']['integration_tests']['passed']}/{self.summary_data['testing_evidence']['integration_tests']['total']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Security Scans:</span>
                <span class="metric-value">{self.summary_data['testing_evidence']['security_scans']['critical']} critical, {self.summary_data['testing_evidence']['security_scans']['high']} high</span>
            </div>
            <div class="metric">
                <span class="metric-label">Compliance Validations:</span>
                <span class="metric-value">{self.summary_data['testing_evidence']['compliance_validations']['passed']}/{self.summary_data['testing_evidence']['compliance_validations']['total']}</span>
            </div>
        </div>
        
        <div class="section">
            <h2>Section C: Security & Compliance</h2>
            <div class="metric">
                <span class="metric-label">Audit Findings:</span>
                <span class="metric-value">{len(self.summary_data['security_compliance']['audit_findings'])}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Policy Violations:</span>
                <span class="metric-value">{len(self.summary_data['security_compliance']['policy_violations'])}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Remediation Actions:</span>
                <span class="metric-value">{len(self.summary_data['security_compliance']['remediation_actions'])}</span>
            </div>
        </div>
        
        <div class="section">
            <h2>Section D: Operational Metrics</h2>
            <div class="metric">
                <span class="metric-label">Incidents:</span>
                <span class="metric-value">{self.summary_data['operational_metrics']['incidents']['total']} total ({self.summary_data['operational_metrics']['incidents']['critical']} critical)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Rollbacks:</span>
                <span class="metric-value">{self.summary_data['operational_metrics']['rollbacks']['total']}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Uptime:</span>
                <span class="metric-value">{self.summary_data['operational_metrics']['slo_performance']['uptime']:.2f}%</span>
            </div>
            <div class="metric">
                <span class="metric-label">Priority Violations:</span>
                <span class="metric-value">{self.summary_data['operational_metrics']['priority_violations']['total']}</span>
            </div>
        </div>
        
        <div class="section">
            <h2>Section E: Regulatory Notes</h2>
            <div class="metric">
                <span class="metric-label">SEC References:</span>
                <span class="metric-value">{len(self.summary_data['regulatory_notes']['sec_references'])}</span>
            </div>
            <div class="metric">
                <span class="metric-label">FINRA Compliance:</span>
                <span class="metric-value">{'Compliant' if self.summary_data['regulatory_notes']['finra_compliance'].get('compliant', False) else 'Non-Compliant'}</span>
            </div>
            <div class="metric">
                <span class="metric-label">SOX Controls:</span>
                <span class="metric-value">{'Compliant' if self.summary_data['regulatory_notes']['sox_controls'].get('compliant', False) else 'Non-Compliant'}</span>
            </div>
        </div>
        
        <div class="section">
            <h2>Mode Promotion Readiness (SIGHTED_LIVE)</h2>
            <div class="metric">
                <span class="metric-label">Readiness Score:</span>
                <span class="metric-value">{self.summary_data['mode_promotion_readiness']['readiness_score']:.1f}%</span>
            </div>
            <div class="metric">
                <span class="metric-label">Assertion Density:</span>
                <span class="metric-value">{self.summary_data['mode_promotion_readiness']['assertion_density']['current']}/{self.summary_data['mode_promotion_readiness']['assertion_density']['target']} ({self.summary_data['mode_promotion_readiness']['assertion_density']['status']})</span>
            </div>
            <div class="metric">
                <span class="metric-label">Shadow Trading PnL:</span>
                <span class="metric-value">${self.summary_data['mode_promotion_readiness']['shadow_trading_pnl']['current']:,.2f} (${self.summary_data['mode_promotion_readiness']['shadow_trading_pnl']['target']:,.2f} target, {self.summary_data['mode_promotion_readiness']['shadow_trading_pnl']['drawdown']:.2%} drawdown)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Incident Rate:</span>
                <span class="metric-value">{self.summary_data['mode_promotion_readiness']['incident_rate']['current']:.2f}/week ({self.summary_data['mode_promotion_readiness']['incident_rate']['target']:.2f} target)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Evidence Accumulated:</span>
                <span class="metric-value">{self.summary_data['mode_promotion_readiness']['evidence_accumulated']['weeks_stable']} weeks stable</span>
            </div>
        </div>
        
        <div class="section">
            <h2>War Game Drill Results</h2>
            <div class="metric">
                <span class="metric-label">Overall Performance:</span>
                <span class="metric-value">{self.summary_data['war_game_drills']['overall_performance']['score']:.1f}% (Grade: {self.summary_data['war_game_drills']['overall_performance']['grade']})</span>
            </div>
            <div class="metric">
                <span class="metric-label">Drills Conducted:</span>
                <span class="metric-value">{len(self.summary_data['war_game_drills']['drills_conducted'])}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Avg Response Time:</span>
                <span class="metric-value">{self.summary_data['war_game_drills']['response_time_metrics']['avg_response_time']:.1f}s (target: {self.summary_data['war_game_drills']['response_time_metrics']['target_response_time']:.1f}s)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Runbook Adherence:</span>
                <span class="metric-value">{self.summary_data['war_game_drills']['runbook_adherence']['score']:.1f}%</span>
            </div>
        </div>
        
        <div class="section">
            <h2>Executive Summary</h2>
            <pre class="pre">{summary['executive_summary']}</pre>
        </div>
        
        <div class="section">
            <h2>Technical Summary</h2>
            <pre class="pre">{summary['technical_summary']}</pre>
        </div>
        
        <div class="section">
            <h2>Risk Summary</h2>
            <pre class="pre">{summary['risk_summary']}</pre>
        </div>
        
        <div class="section">
            <h2>Compliance Summary</h2>
            <pre class="pre">{summary['compliance_summary']}</pre>
        </div>
        
        <div class="section">
            <h2>Operations Summary</h2>
            <pre class="pre">{summary['operations_summary']}</pre>
        </div>
        
        <div class="download-links">
            <a href="week-{self.week_number}-summary.json" download>Download JSON Summary</a>
            <a href="week-{self.week_number}-summary.html" download>Download HTML Report</a>
        </div>
    </div>
</body>
</html>
        """
        return html


def main():
    """Main entry point for weekly dossier summary generation."""
    parser = argparse.ArgumentParser(description='Generate MERID weekly dossier summary')
    parser.add_argument('--week', type=int, required=True, help='Week number')
    parser.add_argument('--year', type=int, default=datetime.now().year, help='Year')
    parser.add_argument('--output', default='week-summary.html', help='Output filename')
    parser.add_argument('--dossiers-dir', default='release-dossiers', help='Directory containing release dossiers')
    
    args = parser.parse_args()
    
    # Create weekly summary generator
    generator = WeeklyDossierSummary(args.week, args.year)
    
    # Load release dossiers from the week
    import glob
    dossier_files = glob.glob(os.path.join(args.dossiers_dir, f"*-{args.year}-W{args.week-1}-*.json"))
    
    for dossier_file in dossier_files:
        try:
            with open(dossier_file, 'r') as f:
                dossier_data = json.load(f)
            generator.add_release_dossier(dossier_data)
        except Exception as e:
            print(f"Error loading dossier {dossier_file}: {e}")
    
    # Add mock data for demonstration
    generator.add_security_findings({
        "critical_vulnerabilities": 0,
        "high_vulnerabilities": 2,
        "medium_vulnerabilities": 5,
        "secrets_found": 0,
        "security_scan_coverage": 95.0,
        "remediation_actions": ["Updated dependencies", "Fixed configuration issues"],
        "security_trends": {"vulnerabilities_trend": "decreasing", "scan_coverage_trend": "increasing"}
    })
    
    generator.add_performance_metrics({
        "avg_response_time_ms": 45.2,
        "p95_response_time_ms": 78.5,
        "error_rate": 0.02,
        "throughput": 1250,
        "availability": 99.9,
        "resource_utilization": {"cpu": 65.0, "memory": 45.0, "disk": 30.0},
        "performance_trends": {"latency_trend": "stable", "throughput_trend": "increasing"}
    })
    
    generator.add_incidents_resolved([
        {
            "title": "Priority violation spike",
            "severity": "MEDIUM",
            "resolution": "Adjusted rate limits and blocked malicious actor"
        },
        {
            "title": "Feed latency issue",
            "severity": "LOW",
            "resolution": "Restarted feed service"
        }
    ])
    
    generator.add_improvements_made([
        {
            "category": "risk",
            "title": "Enhanced priority violation detection",
            "description": "Added real-time violation monitoring and alerting"
        },
        {
            "category": "operations",
            "title": "Automated backup procedures",
            "description": "Implemented automated daily backup of configuration and audit logs"
        },
        {
            "category": "compliance",
            "title": "Audit trail validation",
            "description": "Enhanced audit trail integrity validation"
        }
    ])
    
    generator.add_milestone_annotation("Crossed 1000 assertion threshold", "ops-team")
    generator.add_milestone_annotation("First major feed outage handled cleanly", "ops-team")
    generator.add_change_annotation("Assertion set v2 deployed", "dev-team")
    generator.add_learning_annotation("Runbook gap identified in priority violation handling", "security-team")
    generator.add_drill_annotation("Best performance on mode rollback drill", "ops-team")
    
    generator.add_next_week_priorities([
        "Complete shadow trade integration testing",
        "Enhance red-team test coverage",
        "Implement automated compliance reporting",
        "Optimize performance monitoring"
    ])
    
    # Generate and save summary
    summary = generator.generate_weekly_summary()
    
    # Save HTML summary
    html_content = generator.generate_html_summary()
    with open(args.output, 'w') as f:
        f.write(html_content)
    
    # Save JSON summary
    json_filename = args.output.replace('.html', '.json')
    with open(json_filename, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"Week {args.week} summary generated: {args.output}")
    print(f"JSON summary saved: {json_filename}")
    print(f"Week {args.week} risk score: {generator._calculate_weekly_risk_score():.1f}%")
    print(f"Week {args.week} releases: {len(generator.summary_data['releases_deployed'])}")


if __name__ == "__main__":
    main()
